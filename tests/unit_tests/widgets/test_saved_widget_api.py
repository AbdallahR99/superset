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
"""
The HTTP contract of the widget routes: every error is a JSON body with a
``message`` (and ``errors[].message`` for validation problems), the list is
paged, and a widget whose dataset was deleted is answered as a missing object
rather than a server error.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from superset.commands.exceptions import CommandException
from superset.commands.widget.exceptions import (
    SavedWidgetForbiddenError,
    SavedWidgetNotFoundError,
    WidgetDatasetNotFoundError,
    WidgetInvalidError,
    WidgetSqlForbiddenError,
)
from superset.daos.exceptions import DatasourceNotFound
from superset.utils import json

pytestmark = pytest.mark.parametrize(
    "app", [{"FEATURE_FLAGS": {"DASHBOARD_V2": True}}], indirect=True
)

# Fixed, because it appears in parametrized test ids.
WIDGET_UUID = "3f0e6f0e-0d5a-4f55-9d0b-3f6f4a2b9c11"
DATASET_ID = 17
PROPS: dict[str, Any] = {
    "dataBinding": {"datasetId": DATASET_ID, "metrics": ["sum__num"]}
}


def _post(client: Any, url: str, body: Any, method: str = "POST") -> Any:
    return client.open(
        url, method=method, data=json.dumps(body), content_type="application/json"
    )


def _assert_message(response: Any, status: int) -> dict[str, Any]:
    """The body is JSON and names the problem in a non-empty string."""
    assert response.status_code == status
    assert response.content_type.startswith("application/json")
    body = response.get_json()
    assert isinstance(body["message"], str)
    assert body["message"]
    return body


def _saved_widget(
    props: dict[str, Any] | None = None,
    widget_type: str = "echarts",
    created_by_fk: int = 1,
) -> MagicMock:
    widget = MagicMock()
    widget.uuid = uuid.UUID(WIDGET_UUID)
    widget.widget_type = widget_type
    widget.title = "Sales"
    widget.props_dict = PROPS if props is None else props
    widget.dataset_id = DATASET_ID
    widget.created_by_fk = created_by_fk
    widget.changed_on = datetime(2026, 1, 1, 10, 0, 0)
    return widget


# --------------------------------------------------------------------------
# Error bodies
# --------------------------------------------------------------------------

BAD_BODIES: list[tuple[str, str, Any]] = [
    ("POST", "/api/v1/widget/", {}),
    ("POST", "/api/v1/widget/", {"widget_type": "echarts", "props": "nope"}),
    ("POST", "/api/v1/widget/", {"widget_type": "echarts", "props": {}, "x": 1}),
    ("PUT", f"/api/v1/widget/{WIDGET_UUID}", {"props": 3}),
    ("POST", "/api/v1/widget/data", {}),
    ("POST", "/api/v1/widget/data", {"id": "a", "widget": {"type": "x", "props": {}}}),
    ("POST", "/api/v1/widget/data", {"widget": {"props": {}}}),
    ("POST", "/api/v1/widget/data", {"id": "a", "filters": "state"}),
    ("POST", "/api/v1/widget/values", {"widget": {"type": 5}}),
    ("POST", "/api/v1/widgets/type/echarts/control-schema", {"paths": "a"}),
    ("POST", "/api/v1/widgets/type/echarts/control-schema", {"series": [1]}),
]


@pytest.mark.parametrize("method, url, body", BAD_BODIES)
def test_malformed_request_is_400_with_a_message(
    client: Any, full_api_access: None, method: str, url: str, body: Any
) -> None:
    payload = _assert_message(_post(client, url, body, method), 400)

    if "errors" in payload:
        assert all(isinstance(error["message"], str) for error in payload["errors"])
        assert all(isinstance(error["loc"], list) for error in payload["errors"])


def test_schema_error_names_the_field(client: Any, full_api_access: None) -> None:
    payload = _assert_message(
        _post(client, "/api/v1/widget/data", {"widget": {"props": {}}}), 400
    )

    assert payload["message"].startswith("widget.type: ")
    assert payload["errors"][0]["loc"] == ["widget", "type"]


@pytest.mark.parametrize(
    "error, status",
    [
        (WidgetInvalidError("filters must be a list"), 400),
        (SavedWidgetForbiddenError(), 403),
        (WidgetSqlForbiddenError("no SQL for you"), 403),
        (SavedWidgetNotFoundError(WIDGET_UUID), 404),
        (
            WidgetDatasetNotFoundError("The dataset this widget reads does not exist."),
            404,
        ),
    ],
)
@pytest.mark.parametrize(
    "method, url, command",
    [
        ("GET", "/api/v1/widget/", "ListSavedWidgetsCommand"),
        ("POST", "/api/v1/widget/", "CreateSavedWidgetCommand"),
        ("GET", f"/api/v1/widget/{WIDGET_UUID}", "GetSavedWidgetCommand"),
        ("PUT", f"/api/v1/widget/{WIDGET_UUID}", "UpdateSavedWidgetCommand"),
        ("DELETE", f"/api/v1/widget/{WIDGET_UUID}", "DeleteSavedWidgetCommand"),
        ("POST", "/api/v1/widget/data", "WidgetDataCommand"),
        ("POST", "/api/v1/widget/values", "WidgetValuesCommand"),
    ],
)
def test_command_errors_are_json_messages(
    client: Any,
    full_api_access: None,
    mocker: MockerFixture,
    method: str,
    url: str,
    command: str,
    error: CommandException,
    status: int,
) -> None:
    mocker.patch(f"superset.widgets.api.{command}").return_value.run.side_effect = error
    body: dict[str, Any] = {"widget_type": "echarts", "props": PROPS}
    if url.endswith(("data", "values")):
        body = {"id": WIDGET_UUID}
    elif method == "PUT":
        body = {"title": "t"}

    _assert_message(_post(client, url, body, method), status)


@pytest.mark.parametrize("status", [409, 422])
def test_any_command_status_keeps_the_message_body(
    client: Any, full_api_access: None, mocker: MockerFixture, status: int
) -> None:
    """A command that answers 409 or 422 is serialized the same way."""

    class Refused(CommandException):
        message = "refused"

    error = Refused()
    error.status = status
    mocker.patch(
        "superset.widgets.api.UpdateSavedWidgetCommand"
    ).return_value.run.side_effect = error

    payload = _assert_message(
        _post(client, f"/api/v1/widget/{WIDGET_UUID}", {"title": "t"}, "PUT"), status
    )
    assert payload["message"] == "refused"


def test_invalid_props_carry_errors_with_messages(
    client: Any, full_api_access: None
) -> None:
    payload = _assert_message(
        _post(
            client,
            "/api/v1/widget/data",
            {
                "widget": {
                    "type": "echarts",
                    "props": {
                        "dataBinding": {"datasetId": 1, "metrics": ["m"]},
                        "echartsOptions": {
                            "tooltip": {"formatter": "<img src=x onerror=alert(1)>"}
                        },
                    },
                }
            },
        ),
        400,
    )

    assert payload["errors"][0]["loc"] == ["echartsOptions"]
    assert "HTML markup" in payload["errors"][0]["message"]


def test_unauthenticated_calls_are_401_with_a_message(client: Any) -> None:
    for method, url in (
        ("GET", "/api/v1/widget/"),
        ("GET", f"/api/v1/widget/{WIDGET_UUID}"),
        ("POST", "/api/v1/widget/data"),
        ("POST", "/api/v1/widget/values"),
        ("GET", "/api/v1/widgets/types"),
    ):
        _assert_message(_post(client, url, {"id": WIDGET_UUID}, method), 401)


def test_unknown_widget_and_type_are_404_with_a_message(
    client: Any, full_api_access: None, mocker: MockerFixture
) -> None:
    mocker.patch(
        "superset.daos.saved_widget.SavedWidgetDAO.find_by_uuid", return_value=None
    )

    for method, url, body in (
        ("GET", f"/api/v1/widget/{WIDGET_UUID}", {}),
        ("GET", "/api/v1/widget/not-a-uuid", {}),
        ("PUT", f"/api/v1/widget/{WIDGET_UUID}", {"title": "t"}),
        ("DELETE", f"/api/v1/widget/{WIDGET_UUID}", {}),
        ("POST", "/api/v1/widget/data", {"id": WIDGET_UUID}),
        ("POST", "/api/v1/widget/values", {"id": WIDGET_UUID}),
        ("GET", "/api/v1/widgets/type/nope/control-schema", {}),
        ("POST", "/api/v1/widgets/type/nope/validate", {}),
    ):
        _assert_message(_post(client, url, body, method), 404)


# --------------------------------------------------------------------------
# List
# --------------------------------------------------------------------------


def test_list_is_paged(
    client: Any, full_api_access: None, mocker: MockerFixture
) -> None:
    command = mocker.patch("superset.widgets.api.ListSavedWidgetsCommand")
    command.return_value.run.return_value = [_saved_widget()]
    command.return_value.count = 41

    response = client.get("/api/v1/widget/?page=2&page_size=10")

    assert response.status_code == 200
    body = response.get_json()
    assert (body["count"], body["page"], body["page_size"]) == (41, 2, 10)
    assert [row["uuid"] for row in body["result"]] == [WIDGET_UUID]
    command.assert_called_once_with(2, 10)

    client.get("/api/v1/widget/")
    command.assert_called_with(0, 25)


@pytest.mark.parametrize(
    "query",
    ["page=-1", "page=x", "page=1.5", "page_size=0", "page_size=101", "page_size=1e2"],
)
def test_list_rejects_bad_paging(
    client: Any, full_api_access: None, query: str
) -> None:
    find = MagicMock()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("superset.daos.saved_widget.SavedWidgetDAO.find_readable", find)
        _assert_message(client.get(f"/api/v1/widget/?{query}"), 400)
    find.assert_not_called()


# --------------------------------------------------------------------------
# A widget whose dataset was deleted
# --------------------------------------------------------------------------


def _as_owner(mocker: MockerFixture, admin: bool = False) -> None:
    from superset import security_manager

    mocker.patch.object(security_manager, "is_guest_user", return_value=False)
    mocker.patch.object(security_manager, "is_admin", return_value=admin)
    mocker.patch("superset.commands.widget.utils.get_user_id", return_value=1)


def test_deleted_dataset_is_answered_without_a_server_error(
    client: Any, full_api_access: None, mocker: MockerFixture
) -> None:
    """
    ``saved_widgets.dataset_id`` is not a foreign key, so a widget outlives
    its dataset. Every route still answers with a JSON message: the definition
    stays readable for its owner, its data and values are 404, re-saving the
    dangling binding is 400, and another user gets the ordinary 403.
    """
    mocker.patch(
        "superset.daos.datasource.DatasourceDAO.get_datasource",
        side_effect=DatasourceNotFound(),
    )
    chart = _saved_widget()
    mocker.patch(
        "superset.daos.saved_widget.SavedWidgetDAO.find_by_uuid", return_value=chart
    )
    update = mocker.patch("superset.daos.saved_widget.SavedWidgetDAO.update")
    _as_owner(mocker)

    read = client.get(f"/api/v1/widget/{WIDGET_UUID}")
    assert read.status_code == 200
    assert read.get_json()["result"]["dataset_id"] == DATASET_ID

    data = _assert_message(
        _post(client, "/api/v1/widget/data", {"id": WIDGET_UUID}), 404
    )
    assert "dataset" in data["message"]
    inline = {"widget": {"type": "echarts", "props": PROPS}}
    _assert_message(_post(client, "/api/v1/widget/data", inline), 404)

    _assert_message(
        _post(client, f"/api/v1/widget/{WIDGET_UUID}", {"props": PROPS}, "PUT"), 400
    )
    update.assert_not_called()
    _assert_message(
        _post(client, "/api/v1/widget/", {"widget_type": "echarts", "props": PROPS}),
        400,
    )

    chart.widget_type = "filter.select"
    chart.props_dict = {"datasetId": DATASET_ID, "column": "state"}
    _assert_message(_post(client, "/api/v1/widget/values", {"id": WIDGET_UUID}), 404)

    # Someone else: not the owner, and no dataset left to derive access from.
    chart.created_by_fk = 2
    _assert_message(client.get(f"/api/v1/widget/{WIDGET_UUID}"), 403)
    _assert_message(_post(client, "/api/v1/widget/data", {"id": WIDGET_UUID}), 403)


def test_minting_for_a_widget_whose_dataset_was_deleted_is_a_validation_error(
    mocker: MockerFixture,
) -> None:
    from marshmallow import ValidationError

    from superset import security_manager

    mocker.patch(
        "superset.daos.datasource.DatasourceDAO.get_datasource",
        side_effect=DatasourceNotFound(),
    )
    mocker.patch(
        "superset.daos.saved_widget.SavedWidgetDAO.find_by_uuid",
        return_value=_saved_widget(),
    )
    # An admin minter: the widget read rule lets it through, so the missing
    # dataset is what the request fails on.
    mocker.patch.object(security_manager, "is_guest_user", return_value=False)
    mocker.patch.object(security_manager, "is_admin", return_value=True)

    with pytest.raises(ValidationError, match="does not exist"):
        security_manager.validate_guest_token_resources(
            [{"type": "widget", "id": WIDGET_UUID}]  # type: ignore[list-item]
        )
