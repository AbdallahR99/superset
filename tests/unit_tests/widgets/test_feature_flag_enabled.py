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
With ``DASHBOARD_V2`` on, the widget routes exist and keep their own
authentication, and only the two read-only data routes are CSRF-exempt.
"""

from __future__ import annotations

from typing import Any

import pytest
from pytest_mock import MockerFixture

from superset.utils import json

pytestmark = pytest.mark.parametrize(
    "app", [{"FEATURE_FLAGS": {"DASHBOARD_V2": True}}], indirect=True
)


def test_types_route_is_served(client: Any, full_api_access: None) -> None:
    response = client.get("/api/v1/widgets/types")

    assert response.status_code == 200
    assert "echarts" in {item["id"] for item in response.get_json()["result"]}


def test_routes_still_need_authentication(client: Any) -> None:
    assert client.get("/api/v1/widgets/types").status_code == 401
    assert (
        client.post(
            "/api/v1/widget/data",
            data=json.dumps({"id": "x"}),
            content_type="application/json",
        ).status_code
        == 401
    )


def test_only_the_read_only_data_routes_are_csrf_exempt(app: Any) -> None:
    exempt = set(app.config["WTF_CSRF_EXEMPT_LIST"])
    widget_exempt = {name for name in exempt if name.startswith("superset.widgets.")}

    assert widget_exempt == {
        "superset.widgets.api.data",
        "superset.widgets.api.values",
    }

    # The exemption is matched on ``module.name`` of the view function, so the
    # feature gate wrapping each method must keep both intact; otherwise it
    # would silently stop applying (or apply to the wrong view).
    from superset.widgets.api import SavedWidgetRestApi

    for name in ("data", "values", "post", "put", "delete"):
        view = getattr(SavedWidgetRestApi, name)
        assert f"{view.__module__}.{view.__name__}" == f"superset.widgets.api.{name}"


def test_data_route_does_not_write(
    client: Any, full_api_access: None, mocker: MockerFixture
) -> None:
    """
    The CSRF exemption is only safe while the exempt routes are reads: the
    data route hands the selector to the read command and touches no DAO
    write method.
    """
    command = mocker.patch("superset.widgets.api.WidgetDataCommand")
    command.return_value.run.return_value = {"columns": ["a"], "rows": [{"a": 1}]}
    writes = [
        mocker.patch(f"superset.daos.saved_widget.SavedWidgetDAO.{method}")
        for method in ("create", "update", "delete")
    ]

    response = client.post(
        "/api/v1/widget/data",
        data=json.dumps({"id": "abc", "filters": []}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.get_json()["result"] == {"columns": ["a"], "rows": [{"a": 1}]}
    command.assert_called_once_with({"id": "abc"}, [])
    for write in writes:
        write.assert_not_called()


def test_data_route_ignores_a_form_encoded_body(
    client: Any, full_api_access: None
) -> None:
    """
    A cross-site form post (the request a CSRF attack can make without a
    preflight) carries no JSON body, so it never reaches a command.
    """
    response = client.post(
        "/api/v1/widget/data",
        data={"id": "abc"},
        content_type="application/x-www-form-urlencoded",
    )

    assert response.status_code == 400
