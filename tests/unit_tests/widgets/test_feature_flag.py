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
The widget REST APIs are part of Dashboard V2: with ``DASHBOARD_V2`` off (the
default) every route answers 404, to signed-in and anonymous callers alike.
"""

from __future__ import annotations

from typing import Any

import pytest
from pytest_mock import MockerFixture

from superset.utils import json

ROUTES: list[tuple[str, str]] = [
    ("GET", "/api/v1/widgets/types"),
    ("GET", "/api/v1/widgets/type/metric-tile/control-schema"),
    ("POST", "/api/v1/widgets/type/metric-tile/control-schema"),
    ("POST", "/api/v1/widgets/type/metric-tile/validate"),
    ("GET", "/api/v1/widget/"),
    ("POST", "/api/v1/widget/"),
    ("GET", "/api/v1/widget/3f0e6f0e-0d5a-4f55-9d0b-3f6f4a2b9c11"),
    ("PUT", "/api/v1/widget/3f0e6f0e-0d5a-4f55-9d0b-3f6f4a2b9c11"),
    ("DELETE", "/api/v1/widget/3f0e6f0e-0d5a-4f55-9d0b-3f6f4a2b9c11"),
    ("POST", "/api/v1/widget/data"),
    ("POST", "/api/v1/widget/values"),
]


def _call(client: Any, method: str, url: str) -> Any:
    return client.open(
        url, method=method, data=json.dumps({}), content_type="application/json"
    )


@pytest.mark.parametrize("method, url", ROUTES)
def test_widget_routes_are_404_when_flag_is_off(
    client: Any, full_api_access: None, method: str, url: str
) -> None:
    assert _call(client, method, url).status_code == 404


@pytest.mark.parametrize("method, url", ROUTES)
def test_widget_routes_are_404_for_anonymous_when_flag_is_off(
    client: Any, method: str, url: str
) -> None:
    # 404 rather than 401: a disabled deployment does not reveal the routes.
    assert _call(client, method, url).status_code == 404


@pytest.mark.parametrize("method, url", ROUTES)
def test_disabled_widget_routes_answer_with_a_json_message(
    client: Any, method: str, url: str
) -> None:
    response = _call(client, method, url)

    assert response.content_type.startswith("application/json")
    assert isinstance(response.get_json()["message"], str)


def test_there_is_one_gate_and_one_flag_resolver(
    app: Any, mocker: MockerFixture
) -> None:
    """
    The widget routes carry no gate of their own: the app-level Dashboard V2
    gate covers both widget views and resolves the flag through
    ``superset.widgets.feature``, the module the MCP tools and the Dashboard V2
    API import the flag name and resolver from.
    """
    from superset.dashboard_v2 import feature as dashboard_v2_feature
    from superset.widgets import feature
    from superset.widgets.api import SavedWidgetRestApi, WidgetControlsRestApi

    assert feature.DASHBOARD_V2_FLAG == "DASHBOARD_V2"
    assert (
        dashboard_v2_feature.is_dashboard_v2_enabled is feature.is_dashboard_v2_enabled
    )
    assert not hasattr(feature, "requires_dashboard_v2")

    blueprints = set(app.blueprints)
    assert {SavedWidgetRestApi.__name__, WidgetControlsRestApi.__name__} <= blueprints

    # The resolver is the only thing consulted, once per gated request.
    is_enabled = mocker.patch("superset.is_feature_enabled", return_value=False)
    with app.test_client() as client:
        assert client.get("/api/v1/widgets/types").status_code == 404
        assert client.get("/api/v1/widget/").status_code == 404
    assert [call.args for call in is_enabled.call_args_list] == [
        (feature.DASHBOARD_V2_FLAG,)
    ] * 2

    is_enabled.return_value = True
    assert feature.is_dashboard_v2_enabled() is True
    with app.test_client() as client:
        # Past the gate: the route exists and asks for authentication.
        assert client.get("/api/v1/widgets/types").status_code == 401
