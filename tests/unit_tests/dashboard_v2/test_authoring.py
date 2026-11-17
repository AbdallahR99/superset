# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""The authoring rule on a Dashboard v2 document save: an editor may only add
data definitions (a dataset binding, SQL) they would be allowed to store as a
saved widget, while definitions the document already holds stay saveable."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture
from sqlalchemy.orm.session import Session

from superset import security_manager
from superset.commands.dashboard_v2.exceptions import DashboardV2InvalidError
from superset.commands.dashboard_v2.save import (
    CreateDashboardV2Command,
    raise_for_document_authoring,
    UpdateDashboardV2Command,
)
from superset.commands.widget.exceptions import (
    SavedWidgetForbiddenError,
    WidgetSqlForbiddenError,
)
from superset.errors import ErrorLevel, SupersetError, SupersetErrorType
from superset.exceptions import SupersetSecurityException
from superset.widgets.data import WidgetDatasetMissingError
from tests.unit_tests.dashboard_v2.conftest import make_document, stored_document

SAVE = "superset.commands.dashboard_v2.save"
BASE = "/api/v1/dashboard_v2/"
FORBIDDEN = "You don't have access to the dataset this widget reads."


def _chart(dataset_id: int = 7, **props: Any) -> dict[str, Any]:
    return {
        "type": "echarts",
        "props": {"dataBinding": {"datasetId": dataset_id}, **props},
    }


def _create(document: dict[str, Any]) -> int:
    return CreateDashboardV2Command(
        {"dashboard_title": "Sales", "document": document}
    ).run()["id"]


def _update(pk: int, document: dict[str, Any], base_revision: int = 1) -> Any:
    return UpdateDashboardV2Command(pk, {"document": document}, base_revision).run()


@pytest.fixture
def rule(mocker: MockerFixture) -> MagicMock:
    """The saved-widget authoring rule, allowing everything until told not to."""
    return mocker.patch(f"{SAVE}.raise_for_widget_authoring", return_value=None)


def test_create_refuses_a_binding_the_author_may_not_store_and_names_the_node(
    rule: MagicMock, editor: None, v2_session: Session
) -> None:
    from superset.models.dashboard import Dashboard

    rule.side_effect = SavedWidgetForbiddenError()

    with pytest.raises(DashboardV2InvalidError) as refused:
        _create(make_document("text", "chart", chart=_chart()))

    assert refused.value.status == 422
    assert refused.value.errors == {
        "chart": [{"loc": ["dataBinding"], "message": FORBIDDEN}]
    }
    assert v2_session.query(Dashboard).count() == 0


def test_the_rule_is_asked_with_the_widget_type_and_the_props(
    rule: MagicMock, editor: None, v2_session: Session
) -> None:
    from superset.widgets.registry import registry

    _create(make_document("text", "chart", chart=_chart(title="Revenue")))

    rule.assert_called_once_with(
        registry.get("echarts"), {"dataBinding": {"datasetId": 7}, "title": "Revenue"}
    )


def test_untouched_definitions_stay_saveable_by_an_editor_without_dataset_access(
    rule: MagicMock, editor: None, v2_session: Session
) -> None:
    """Restyling, moving and duplicating a stored definition, and editing the
    nodes around it, never asks the rule: nothing new reaches the dataset."""
    pk = _create(make_document("text", "chart", chart=_chart()))
    rule.reset_mock()
    rule.side_effect = SavedWidgetForbiddenError()
    document = make_document(
        "chart_copy",
        "chart",
        "new_text",
        chart={**_chart(title="Renamed"), "layout": {"x": 4, "w": 12}},
        chart_copy=_chart(),
    )

    updated = _update(pk, document)

    assert updated["revision"] == 2
    rule.assert_not_called()
    assert set(stored_document(v2_session, pk)["nodes"]) == {
        "root",
        "chart",
        "chart_copy",
        "new_text",
    }


@pytest.mark.parametrize(
    "changed",
    [
        pytest.param(_chart(8), id="another_dataset"),
        pytest.param(
            {
                "type": "echarts",
                "props": {
                    "dataBinding": {
                        "datasetId": 7,
                        "metrics": [
                            {"expressionType": "SQL", "sqlExpression": "SUM(pay)"}
                        ],
                    }
                },
            },
            id="sql_added",
        ),
        pytest.param(
            {"type": "ag-grid-table", "props": {"dataBinding": {"datasetId": 7}}},
            id="another_widget_type",
        ),
    ],
)
def test_update_refuses_a_changed_definition_and_keeps_the_stored_document(
    rule: MagicMock, editor: None, v2_session: Session, changed: dict[str, Any]
) -> None:
    pk = _create(make_document("text", "chart", chart=_chart()))
    rule.side_effect = WidgetSqlForbiddenError("no SQL for you")

    with pytest.raises(DashboardV2InvalidError) as refused:
        _update(pk, make_document("text", "chart", chart=changed))

    assert refused.value.errors == {
        "chart": [{"loc": ["dataBinding"], "message": "no SQL for you"}]
    }
    stored = stored_document(v2_session, pk)
    assert stored["revision"] == 1
    assert stored["nodes"]["chart"] == _chart()


def test_every_refused_node_is_named(rule: MagicMock) -> None:
    rule.side_effect = SavedWidgetForbiddenError()
    document = make_document("a", "b", "text", a=_chart(1), b=_chart(2))

    with pytest.raises(DashboardV2InvalidError) as refused:
        raise_for_document_authoring(document, None)

    assert set(refused.value.errors) == {"a", "b"}


def test_nodes_that_bind_no_dataset_are_not_checked(rule: MagicMock) -> None:
    document = make_document(
        "text",
        "empty_chart",
        "tabs",
        empty_chart={"type": "echarts", "props": {"dataBinding": {}}},
        tabs={"type": "tabs", "children": []},
    )

    raise_for_document_authoring(document, None)

    rule.assert_not_called()


def test_the_real_rule_refuses_a_dataset_the_author_cannot_read(
    mocker: MockerFixture, editor: None, v2_session: Session
) -> None:
    """Not mocked at the seam: ``raise_for_widget_authoring`` itself turns the
    security manager's refusal into the node error."""
    mocker.patch("superset.commands.widget.utils.get_table", return_value=MagicMock())
    mocker.patch.object(security_manager, "is_admin", return_value=False)
    mocker.patch.object(
        security_manager,
        "raise_for_access",
        side_effect=SupersetSecurityException(
            SupersetError(
                message="denied",
                error_type=SupersetErrorType.DATASOURCE_SECURITY_ACCESS_ERROR,
                level=ErrorLevel.ERROR,
            )
        ),
    )

    with pytest.raises(DashboardV2InvalidError) as refused:
        _create(make_document("chart", chart=_chart()))

    assert refused.value.errors == {
        "chart": [{"loc": ["dataBinding"], "message": FORBIDDEN}]
    }


def test_a_new_binding_to_a_dataset_that_does_not_exist_is_refused(
    mocker: MockerFixture, editor: None, v2_session: Session
) -> None:
    mocker.patch(
        "superset.commands.widget.utils.get_table",
        side_effect=WidgetDatasetMissingError("The dataset does not exist."),
    )

    with pytest.raises(DashboardV2InvalidError) as refused:
        _create(make_document("chart", chart=_chart()))

    assert refused.value.errors == {
        "chart": [{"loc": ["dataBinding"], "message": "The dataset does not exist."}]
    }


def test_the_api_answers_a_refused_definition_with_422_and_per_node_errors(
    rule: MagicMock,
    client: Any,
    dashboard_v2_enabled: None,
    editor: None,
    v2_session: Session,
) -> None:
    created = client.post(
        BASE, json={"dashboard_title": "Sales", "document": make_document("text")}
    )
    assert created.status_code == 201, created.get_json()
    pk = created.get_json()["id"]
    rule.side_effect = SavedWidgetForbiddenError()

    response = client.put(
        f"{BASE}{pk}",
        json={
            "document": make_document("text", "chart", chart=_chart()),
            "base_revision": 1,
        },
    )

    assert response.status_code == 422
    assert response.get_json()["errors"] == {
        "chart": [{"loc": ["dataBinding"], "message": FORBIDDEN}]
    }
    assert stored_document(v2_session, pk)["revision"] == 1
