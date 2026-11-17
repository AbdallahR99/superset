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
"""The Dashboard v2 flag gate against an app with CSRF protection on, which
the other test modules run without: the gate answers before the CSRF check."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_mock import MockerFixture

from superset.dashboard_v2.feature import register_dashboard_v2_gate
from superset.extensions import feature_flag_manager
from tests.unit_tests.dashboard_v2.conftest import make_document

BASE = "/api/v1/dashboard_v2/"
ROUTE_UUID = "0b9d6f0e-3c1a-4d57-9a5e-2f8c1b7d4e60"
CSRF_ON = [{"WTF_CSRF_ENABLED": True}]

UNSAFE_GATED_ROUTES = [
    ("POST", BASE),
    ("PUT", f"{BASE}1"),
    ("POST", "/api/v1/widgets/type/markdown/validate"),
    ("POST", "/api/v1/widget/"),
    ("PUT", f"/api/v1/widget/{ROUTE_UUID}"),
    ("DELETE", f"/api/v1/widget/{ROUTE_UUID}"),
]


@pytest.mark.parametrize("app", CSRF_ON, indirect=True)
@pytest.mark.parametrize("method, path", UNSAFE_GATED_ROUTES)
def test_flag_off_is_404_before_the_csrf_check(
    client: Any, method: str, path: str
) -> None:
    """An anonymous write without a CSRF token to a gated route is a 404, the
    answer of a route that does not exist, not the 400 of the CSRF check."""
    response = client.open(path, method=method, json={})

    assert response.status_code == 404
    assert response.get_json() == {"message": "Not found"}


@pytest.mark.parametrize("app", CSRF_ON, indirect=True)
def test_csrf_protection_still_applies_once_the_flag_is_on(
    client: Any, mocker: MockerFixture
) -> None:
    mocker.patch.dict(feature_flag_manager._feature_flags, {"DASHBOARD_V2": True})

    response = client.post(
        BASE, json={"dashboard_title": "Sales", "document": make_document()}
    )

    assert response.status_code == 400
    assert "CSRF" in response.get_data(as_text=True)


@pytest.mark.parametrize("app", CSRF_ON, indirect=True)
def test_csrf_protection_of_other_routes_is_untouched(client: Any) -> None:
    """The gate only answers for its own blueprints."""
    response = client.post("/api/v1/dashboard/", json={"dashboard_title": "x"})

    assert response.status_code == 400
    assert "CSRF" in response.get_data(as_text=True)


@pytest.mark.parametrize("app", CSRF_ON, indirect=True)
def test_the_gate_is_the_first_before_request_hook(app: Any) -> None:
    hooks = app.before_request_funcs[None]

    assert hooks[0].__name__ == "refuse_disabled_dashboard_v2"
    assert any(hook.__name__ == "csrf_protect" for hook in hooks[1:])


def test_registering_the_gate_puts_it_ahead_of_existing_hooks() -> None:
    from flask import Flask

    flask_app = Flask(__name__)

    @flask_app.before_request
    def earlier() -> None:
        return None

    register_dashboard_v2_gate(flask_app, ())

    names = [hook.__name__ for hook in flask_app.before_request_funcs[None]]
    assert names == ["refuse_disabled_dashboard_v2", "earlier"]
