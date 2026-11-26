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
from __future__ import annotations

import re
import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest
from marshmallow import ValidationError
from pytest_mock import MockerFixture
from superset_core.widgets import Widget, WidgetDataNotSupportedError

from superset.commands.chart.exceptions import ChartDataQueryFailedError
from superset.commands.widget.data import (
    resolve_widget,
    WidgetDataCommand,
    WidgetValuesCommand,
)
from superset.commands.widget.exceptions import (
    SavedWidgetForbiddenError,
    SavedWidgetNotFoundError,
    WidgetInvalidError,
)
from superset.commands.widget.saved import (
    CreateSavedWidgetCommand,
    UpdateSavedWidgetCommand,
)
from superset.connectors.sqla.models import SqlaTable, SqlMetric, TableColumn
from superset.exceptions import SupersetSecurityException
from superset.models.core import Database
from superset.widgets.controls import DataBinding
from superset.widgets.data import (
    build_widget_query,
    FilterValidationError,
    props_dataset_id,
    resolved_filters_to_adhoc,
    validate_guest_inline_props,
    widget_dataset_id,
    WidgetContext,
    WidgetDataError,
)
from superset.widgets.registry import registry
from superset.widgets.schemas import WidgetDataPostSchema

DATASET_ID = 17
BAR_PROPS: dict[str, Any] = {
    "dataBinding": {
        "datasetId": DATASET_ID,
        "metrics": ["sum__num"],
        "dimensions": ["state"],
    }
}


def _security(mocker: MockerFixture, *modules: str, guest: bool) -> MagicMock:
    sm = MagicMock()
    sm.is_guest_user.return_value = guest
    for module in modules:
        mocker.patch(f"{module}.security_manager", new=sm)
    return sm


def _datasource() -> MagicMock:
    datasource = MagicMock()
    datasource.column_names = ["state", "gender", "num"]
    datasource.columns = [
        MagicMock(column_name="state", groupby=True),
        MagicMock(column_name="gender", groupby=True),
        MagicMock(column_name="num", groupby=False),
    ]
    datasource.metrics = [MagicMock(metric_name="sum__num")]
    return datasource


def _saved_widget(props: dict[str, Any] | None = None) -> MagicMock:
    widget = MagicMock()
    widget.uuid = uuid.uuid4()
    widget.widget_type = "echarts"
    widget.props_dict = props or BAR_PROPS
    widget.created_by_fk = 2
    return widget


def test_filter_operator_must_be_a_string() -> None:
    """A JSON array in the operator field is a validation error."""
    with pytest.raises(FilterValidationError, match="unsupported operator"):
        resolved_filters_to_adhoc([{"column": "state", "operator": []}], {"state"})


def test_guest_metric_column_name_must_be_a_string() -> None:
    """Malformed column references fail validation before building a query."""
    props = {
        "dataBinding": {
            "metrics": [
                {
                    "expressionType": "SIMPLE",
                    "aggregate": "COUNT",
                    "column": {"column_name": []},
                }
            ]
        }
    }
    with pytest.raises(WidgetDataError, match="Guest metrics"):
        validate_guest_inline_props(props, _datasource())


@pytest.mark.parametrize(
    "props, expected",
    [
        ({"dataBinding": {"datasetId": 7}}, 7),
        ({"datasetId": 3}, 3),
        ({"dataBinding": {"datasetId": "7"}}, None),
        ({"datasetId": True}, None),
        ({}, None),
        (None, None),
    ],
)
def test_props_dataset_id(props: Any, expected: int | None) -> None:
    assert props_dataset_id(props) == expected


@pytest.mark.parametrize(
    "widget_type, props, expected",
    [
        # A filter reads its own datasetId, whatever else the props hold.
        ("filter.select", {"dataBinding": {"datasetId": 1}, "datasetId": 2}, 2),
        ("filter.select", {"dataBinding": {}, "datasetId": 2}, 2),
        ("filter.select", {"dataBinding": {"datasetId": 1}}, None),
        # A data-bound widget reads its binding.
        ("echarts", {"dataBinding": {"datasetId": 1}, "datasetId": 2}, 1),
        ("metric-tile", {"datasetId": 2}, None),
        # A type that reads no data binds none.
        ("markdown", {"content": "x", "datasetId": 2}, None),
        ("filter.bar", {"dataBinding": {"datasetId": 1}}, None),
    ],
)
def test_the_widget_type_decides_which_dataset_a_definition_reads(
    widget_type: str, props: dict[str, Any], expected: int | None
) -> None:
    """
    SECURITY.md row "Gamma" (an author needs access to the dataset a widget
    binds); principal: Gamma author or a custom ``can_grant_guest_token`` role.
    The dataset every check is run against is the one the widget type queries,
    so a stray key cannot point the check at another dataset.
    """
    assert widget_dataset_id(registry.get(widget_type), props) == expected


def test_a_filter_is_authored_against_the_dataset_it_queries(
    mocker: MockerFixture,
) -> None:
    """The check a stray ``dataBinding`` used to move to another dataset."""
    from superset.commands.widget.utils import raise_for_widget_authoring

    sm = _security(mocker, "superset.commands.widget.utils", guest=False)
    get_table = mocker.patch(
        "superset.commands.widget.utils.get_table", return_value=_datasource()
    )
    mocker.patch("superset.commands.widget.utils.raise_for_widget_sql")
    filter_cls = registry.get("filter.select")
    assert filter_cls is not None

    raise_for_widget_authoring(
        filter_cls, {"dataBinding": {"datasetId": 1}, "datasetId": 2, "column": "ssn"}
    )

    get_table.assert_called_once_with(2)
    sm.raise_for_access.assert_called_once_with(datasource=get_table.return_value)


@pytest.mark.parametrize(
    "widget_type, props",
    [
        (
            "filter.select",
            {"dataBinding": {"datasetId": 1}, "datasetId": 2, "column": "state"},
        ),
        ("filter.select", {"dataBinding": {}, "datasetId": 2, "column": "state"}),
        ("echarts", {**BAR_PROPS, "echartsOptions": {}, "datasetId": 99}),
        ("metric-tile", {**BAR_PROPS, "datasetId": DATASET_ID}),
        ("ag-grid-table", {**BAR_PROPS, "datasetId": 99}),
        ("markdown", {"content": "x", "datasetId": 99}),
        ("markdown", {"content": "x", "dataBinding": {"datasetId": 99}}),
        ("filter.bar", {"dataBinding": {"datasetId": 99}}),
    ],
)
def test_props_naming_a_dataset_the_widget_does_not_read_are_refused(
    widget_type: str, props: dict[str, Any]
) -> None:
    from superset.commands.widget.utils import validate_widget_props

    with pytest.raises(WidgetInvalidError) as excinfo:
        validate_widget_props(widget_type, props)
    assert "named in one place only" in str(excinfo.value.errors)


@pytest.mark.parametrize(
    "widget_type, props",
    [
        ("filter.select", {"datasetId": 2, "column": "state", "dataBinding": None}),
        ("echarts", {**BAR_PROPS, "echartsOptions": {}, "datasetId": None}),
        ("markdown", {"content": "x"}),
    ],
)
def test_props_naming_their_dataset_once_are_accepted(
    widget_type: str, props: dict[str, Any]
) -> None:
    from superset.commands.widget.utils import validate_widget_props

    validate_widget_props(widget_type, props)


def test_selector_schema_requires_exactly_one() -> None:
    schema = WidgetDataPostSchema()
    assert schema.load({"id": "x"}) == {"id": "x", "filters": []}
    with pytest.raises(ValidationError):
        schema.load({})
    with pytest.raises(ValidationError):
        schema.load({"id": "x", "widget": {"type": "echarts", "props": {}}})


def test_resolve_inline_for_user(mocker: MockerFixture) -> None:
    _security(mocker, "superset.commands.widget.data", guest=False)
    mocker.patch("superset.commands.widget.data.get_table", return_value=_datasource())
    widget_cls, props, context = resolve_widget(
        {"widget": {"type": "echarts", "props": BAR_PROPS}}
    )
    assert issubclass(widget_cls, Widget)
    assert props is BAR_PROPS
    assert context == WidgetContext(DATASET_ID)


def test_resolve_inline_validates_props_via_registry(mocker: MockerFixture) -> None:
    _security(mocker, "superset.commands.widget.data", guest=False)
    with pytest.raises(WidgetInvalidError) as excinfo:
        resolve_widget({"widget": {"type": "metric-tile", "props": {"decimals": "x"}}})
    assert excinfo.value.errors

    with pytest.raises(WidgetInvalidError):
        resolve_widget({"widget": {"type": "not-a-widget", "props": {}}})


def test_resolve_inline_guest_needs_grant(mocker: MockerFixture) -> None:
    sm = _security(mocker, "superset.commands.widget.data", guest=True)
    sm.guest_widget_grants_dataset.return_value = False
    with pytest.raises(SavedWidgetForbiddenError):
        resolve_widget({"widget": {"type": "echarts", "props": BAR_PROPS}})


def test_resolve_inline_guest_is_hardened(mocker: MockerFixture) -> None:
    sm = _security(mocker, "superset.commands.widget.data", guest=True)
    sm.guest_widget_grants_dataset.return_value = True
    mocker.patch("superset.commands.widget.data.get_table", return_value=_datasource())
    resolve_widget({"widget": {"type": "echarts", "props": BAR_PROPS}})

    sql_metric = {
        "dataBinding": {
            "datasetId": DATASET_ID,
            "metrics": [{"expressionType": "SQL", "sqlExpression": "SUM(num)"}],
        }
    }
    with pytest.raises(WidgetDataError):
        resolve_widget({"widget": {"type": "echarts", "props": sql_metric}})


def test_resolve_saved_widget(mocker: MockerFixture) -> None:
    _security(
        mocker,
        "superset.commands.widget.utils",
        "superset.commands.widget.data",
        guest=False,
    )
    saved = _saved_widget()
    mocker.patch(
        "superset.commands.widget.utils.SavedWidgetDAO.find_by_uuid",
        return_value=saved,
    )
    _, props, context = resolve_widget({"id": str(saved.uuid)})
    assert props == BAR_PROPS
    assert context == WidgetContext(DATASET_ID, str(saved.uuid))
    assert not context.inline


@pytest.mark.parametrize("granted", [True, False])
def test_saved_query_requires_a_guest_dataset_grant(
    mocker: MockerFixture, granted: bool
) -> None:
    """Verify the token binding before handing a saved definition to the widget."""
    saved = _saved_widget()
    mocker.patch("superset.commands.widget.data.load_saved_widget", return_value=saved)
    sm = _security(mocker, "superset.commands.widget.data", guest=True)
    sm.guest_widget_grants_dataset.return_value = granted
    context = WidgetContext(DATASET_ID, str(saved.uuid))
    if granted:
        assert resolve_widget({"id": str(saved.uuid)})[2] == context
    else:
        with pytest.raises(SavedWidgetForbiddenError):
            resolve_widget({"id": str(saved.uuid)})
    sm.guest_widget_grants_dataset.assert_called_once_with(context)


def test_resolve_saved_widget_guest_must_be_named(mocker: MockerFixture) -> None:
    sm = _security(mocker, "superset.commands.widget.utils", guest=True)
    sm.guest_token_names_widget.return_value = False
    mocker.patch(
        "superset.commands.widget.utils.SavedWidgetDAO.find_by_uuid",
        return_value=_saved_widget(),
    )
    with pytest.raises(SavedWidgetForbiddenError):
        resolve_widget({"id": "whatever"})


def test_resolve_unknown_saved_widget(mocker: MockerFixture) -> None:
    mocker.patch(
        "superset.commands.widget.utils.SavedWidgetDAO.find_by_uuid",
        return_value=None,
    )
    with pytest.raises(SavedWidgetNotFoundError):
        resolve_widget({"id": "missing"})


@pytest.mark.parametrize(
    "error, expected",
    [
        (WidgetDataNotSupportedError("markdown"), WidgetInvalidError),
        (WidgetDataError("no binding"), WidgetInvalidError),
        # A column the dataset does not have surfaces as a failed query, not as
        # a validation error: still the caller's mistake, so 400 not 500.
        (
            ChartDataQueryFailedError("Columns missing in dataset: ['gender']"),
            WidgetInvalidError,
        ),
        (SupersetSecurityException(MagicMock()), SavedWidgetForbiddenError),
    ],
)
def test_data_command_maps_errors(
    mocker: MockerFixture, error: Exception, expected: type[Exception]
) -> None:
    widget_cls = MagicMock()
    widget_cls.fetch_data.side_effect = error
    mocker.patch(
        "superset.commands.widget.data.resolve_widget",
        return_value=(widget_cls, BAR_PROPS, WidgetContext(DATASET_ID)),
    )
    with pytest.raises(expected):
        WidgetDataCommand({"id": "x"}, []).run()


def test_data_and_values_commands_dispatch(mocker: MockerFixture) -> None:
    widget_cls = MagicMock()
    widget_cls.fetch_data.return_value = {"columns": ["state"], "rows": []}
    widget_cls.fetch_values.return_value = ["boy", "girl"]
    context = WidgetContext(DATASET_ID)
    mocker.patch(
        "superset.commands.widget.data.resolve_widget",
        return_value=(widget_cls, BAR_PROPS, context),
    )
    filters = [{"column": "state", "operator": "IN", "value": ["CA"]}]

    assert WidgetDataCommand({"id": "x"}, filters).run()["columns"] == ["state"]
    widget_cls.fetch_data.assert_called_once_with(BAR_PROPS, filters, context)
    assert WidgetValuesCommand({"id": "x"}).run() == ["boy", "girl"]

    with pytest.raises(WidgetInvalidError):
        WidgetDataCommand({"id": "x"}, "not-a-list").run()


@pytest.mark.parametrize(
    ("overrides", "expected_order"),
    [
        ({}, [("sum__num", False), ("state", True)]),
        ({"orderByDimension": True}, [("state", True)]),
        ({"orderByMetric": False}, None),
        ({"dimensions": []}, None),
    ],
)
def test_ranked_query_round_trips_binding_and_applies_order_with_limit(
    overrides: dict[str, Any], expected_order: list[tuple[str, bool]] | None
) -> None:
    binding = {
        **BAR_PROPS["dataBinding"],
        "orderByMetric": True,
        "rowLimit": 12,
        **overrides,
    }
    stored = DataBinding.model_validate(binding).model_dump(
        by_alias=True, exclude_unset=True
    )
    assert stored == binding

    _, query, _ = build_widget_query({"dataBinding": stored}, [])
    assert query.get("orderby") == expected_order
    assert query["row_limit"] == 12


def test_ranked_query_does_not_use_an_adhoc_metric_as_an_ordering_key() -> None:
    adhoc = {
        "expressionType": "SIMPLE",
        "aggregate": "SUM",
        "column": {"column_name": "num"},
    }
    _, query, _ = build_widget_query(
        {
            "dataBinding": {
                **BAR_PROPS["dataBinding"],
                "metrics": [adhoc, "sum__num"],
                "orderByMetric": True,
            }
        },
        [],
    )
    assert query["metrics"] == [adhoc, "sum__num"]
    assert "orderby" not in query


def test_ranked_query_compiles_metric_order_before_limit() -> None:
    _, query, _ = build_widget_query(
        {
            "dataBinding": {
                **BAR_PROPS["dataBinding"],
                "orderByMetric": True,
                "rowLimit": 12,
            }
        },
        [],
    )
    table = SqlaTable(
        database=Database(database_name="db", sqlalchemy_uri="sqlite://"),
        table_name="observations",
        columns=[
            TableColumn(column_name="state", type="TEXT"),
            TableColumn(column_name="num", type="INTEGER"),
        ],
        metrics=[SqlMetric(metric_name="sum__num", expression="SUM(num)")],
    )
    statement = table.get_sqla_query(
        columns=query["columns"],
        metrics=query["metrics"],
        filter=query["filters"],
        extras=query["extras"],
        orderby=query["orderby"],
        row_limit=query["row_limit"],
        is_timeseries=False,
    ).sqla_query
    with table.database.get_sqla_engine() as engine:
        sql = str(
            statement.compile(
                dialect=engine.dialect, compile_kwargs={"literal_binds": True}
            )
        )
    assert re.search(
        r"ORDER BY [^\n]+ DESC, [^\n]*state ASC\s+LIMIT 12\b", sql, re.IGNORECASE
    )


def test_guest_inline_props_accept_safe_shapes() -> None:
    validate_guest_inline_props(
        {
            "dataBinding": {
                "datasetId": DATASET_ID,
                "metrics": [
                    "sum__num",
                    {
                        "expressionType": "SIMPLE",
                        "aggregate": "sum",
                        "column": {"column_name": "num"},
                    },
                ],
                "dimensions": ["gender"],
                "filters": [
                    {
                        "expressionType": "SIMPLE",
                        "subject": "state",
                        "operator": "==",
                        "comparator": "CA",
                        "clause": "WHERE",
                    }
                ],
            }
        },
        _datasource(),
    )
    validate_guest_inline_props(
        {"datasetId": DATASET_ID, "column": "gender"}, _datasource()
    )


@pytest.mark.parametrize(
    "props",
    [
        {"dataBinding": {"metrics": ["not_a_metric"]}},
        {
            "dataBinding": {
                "metrics": [
                    {
                        "expressionType": "SIMPLE",
                        "aggregate": "SUM",
                        "column": {"column_name": "num"},
                        "sqlExpression": "1; DROP TABLE x",
                    }
                ]
            }
        },
        {
            "dataBinding": {
                "metrics": [
                    {
                        "expressionType": "SIMPLE",
                        "aggregate": "PERCENTILE",
                        "column": {"column_name": "num"},
                    }
                ]
            }
        },
        {"dataBinding": {"metrics": ["sum__num"], "dimensions": ["num"]}},
        {
            "dataBinding": {
                "metrics": ["sum__num"],
                "filters": [{"expressionType": "SQL", "sqlExpression": "1=1"}],
            }
        },
        {
            "dataBinding": {
                "metrics": ["sum__num"],
                "filters": [{"expressionType": "SIMPLE", "subject": "secret"}],
            }
        },
        {"datasetId": DATASET_ID, "column": "secret"},
    ],
)
def test_guest_inline_props_reject_unsafe_shapes(props: dict[str, Any]) -> None:
    with pytest.raises(WidgetDataError):
        validate_guest_inline_props(props, _datasource())


def test_create_rejects_guests_and_invalid_props(mocker: MockerFixture) -> None:
    _security(mocker, "superset.commands.widget.saved", guest=True)
    with pytest.raises(SavedWidgetForbiddenError):
        CreateSavedWidgetCommand(
            {"widget_type": "echarts", "props": BAR_PROPS}
        ).validate()

    _security(mocker, "superset.commands.widget.saved", guest=False)
    # The author's dataset entitlement has its own tests
    # (tests/unit_tests/security/test_widget_data_access.py).
    authoring = mocker.patch(
        "superset.commands.widget.saved.raise_for_widget_authoring"
    )
    with pytest.raises(WidgetInvalidError):
        CreateSavedWidgetCommand(
            {"widget_type": "metric-tile", "props": {"decimals": "x"}}
        ).validate()
    authoring.assert_not_called()
    CreateSavedWidgetCommand({"widget_type": "echarts", "props": BAR_PROPS}).validate()
    authoring.assert_called_once_with(registry.get("echarts"), BAR_PROPS)


def test_update_requires_owner_or_admin(mocker: MockerFixture) -> None:
    sm = _security(mocker, "superset.commands.widget.utils", guest=False)
    sm.is_admin.return_value = False
    mocker.patch(
        "superset.commands.widget.saved.SavedWidgetDAO.find_by_uuid",
        return_value=_saved_widget(),
    )
    user_id = mocker.patch("superset.commands.widget.utils.get_user_id", return_value=1)
    with pytest.raises(SavedWidgetForbiddenError):
        UpdateSavedWidgetCommand("x", {"title": "t"}).validate()

    user_id.return_value = 2
    UpdateSavedWidgetCommand("x", {"title": "t"}).validate()

    user_id.return_value = 1
    sm.is_admin.return_value = True
    UpdateSavedWidgetCommand("x", {"title": "t"}).validate()


def test_semantic_widget_checks_view_access_before_authoring(
    mocker: MockerFixture,
) -> None:
    """A saved semantic binding is validated against an authorized view."""
    from superset.commands.widget.utils import raise_for_widget_authoring

    view_id = uuid.uuid4()
    props = {"dataBinding": {"semanticViewId": str(view_id), "metrics": ["sales"]}}
    widget_cls = registry.get("metric-tile")
    assert widget_cls is not None
    resolver = mocker.patch(
        "superset.commands.widget.utils.resolve_widget_semantic_view"
    )
    validate = mocker.patch(
        "superset.commands.widget.utils.validate_widget_semantic_members"
    )

    raise_for_widget_authoring(widget_cls, props)
    resolver.assert_called_once_with(view_id)
    validate.assert_called_once_with(resolver.return_value, props)

    resolver.side_effect = SupersetSecurityException(MagicMock())
    validate.reset_mock()
    with pytest.raises(SavedWidgetForbiddenError):
        raise_for_widget_authoring(widget_cls, props)
    validate.assert_not_called()


def test_saved_semantic_widget_requires_view_access_even_for_creator(
    mocker: MockerFixture,
) -> None:
    """Losing access to a semantic view denies reading its saved definition."""
    from superset.commands.widget.utils import raise_for_widget_read

    view_id = uuid.uuid4()
    saved = _saved_widget(
        {"dataBinding": {"semanticViewId": str(view_id), "metrics": ["sales"]}}
    )
    saved.widget_type = "metric-tile"
    sm = _security(mocker, "superset.commands.widget.utils", guest=False)
    sm.is_admin.return_value = False
    mocker.patch("superset.commands.widget.utils.get_user_id", return_value=2)
    resolver = mocker.patch(
        "superset.commands.widget.utils.resolve_widget_semantic_view",
        side_effect=SupersetSecurityException(MagicMock()),
    )

    with pytest.raises(SavedWidgetForbiddenError):
        raise_for_widget_read(saved)
    resolver.assert_called_once_with(view_id)


def test_inline_semantic_widget_checks_view_before_dispatch(
    mocker: MockerFixture,
) -> None:
    """Dispatch has a server-resolved semantic binding for signed-in users."""
    view_id = uuid.uuid4()
    props = {"dataBinding": {"semanticViewId": str(view_id), "metrics": ["sales"]}}
    sm = _security(mocker, "superset.commands.widget.data", guest=False)
    resolver = mocker.patch(
        "superset.commands.widget.data.resolve_widget_semantic_view"
    )
    selector = {"widget": {"type": "metric-tile", "props": props}}

    assert resolve_widget(selector)[2].semantic_view_id == view_id
    resolver.assert_called_once_with(view_id)
    resolver.reset_mock()

    sm.is_guest_user.return_value = True
    with pytest.raises(SavedWidgetForbiddenError):
        resolve_widget(selector)
    resolver.assert_not_called()


def test_semantic_widget_list_withholds_binding_when_view_access_is_revoked(
    mocker: MockerFixture,
) -> None:
    """A listed owner record can survive revocation without defining a query."""
    from superset.commands.widget.utils import serialize_saved_widget

    view_id = uuid.uuid4()
    props = {"dataBinding": {"semanticViewId": str(view_id), "metrics": ["sales"]}}
    saved = _saved_widget(props)
    saved.widget_type = "metric-tile"
    _security(mocker, "superset.commands.widget.utils", guest=False)
    resolver = mocker.patch(
        "superset.commands.widget.utils.resolve_widget_semantic_view",
        side_effect=SupersetSecurityException(MagicMock()),
    )

    listed = serialize_saved_widget(saved)

    assert listed["uuid"] == str(saved.uuid)
    assert listed["props"] == {}
    assert saved.props_dict == props
    resolver.assert_called_once_with(view_id)


def test_named_guest_cannot_dispatch_saved_semantic_widget(
    mocker: MockerFixture,
) -> None:
    """A saved widget token cannot authorize its current semantic source."""
    saved = _saved_widget(
        {"dataBinding": {"semanticViewId": str(uuid.uuid4()), "metrics": ["sales"]}}
    )
    saved.widget_type = "metric-tile"
    mocker.patch("superset.commands.widget.data.load_saved_widget", return_value=saved)
    sm = _security(mocker, "superset.commands.widget.data", guest=True)
    sm.guest_widget_grants_dataset.return_value = True
    resolver = mocker.patch(
        "superset.commands.widget.data.resolve_widget_semantic_view"
    )

    with pytest.raises(SavedWidgetForbiddenError):
        resolve_widget({"id": str(saved.uuid)})
    resolver.assert_not_called()
