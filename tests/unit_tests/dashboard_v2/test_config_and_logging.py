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
"""The declared document limits, their exposure to the frontend, and the
request logger's behaviour on a body too deeply nested to parse."""

from __future__ import annotations

from typing import Any

from pytest_mock import MockerFixture

from superset.dashboard_v2.document import current_limits, DocumentLimits


def test_limits_are_declared_in_config_with_the_documented_defaults(
    app: Any, app_context: None
) -> None:
    assert app.config["DASHBOARD_V2_MAX_NODES"] == 500
    assert app.config["DASHBOARD_V2_MAX_DEPTH"] == 16
    assert app.config["DASHBOARD_V2_MAX_DOCUMENT_BYTES"] == 1024 * 1024
    assert app.config["DASHBOARD_V2_MAX_VALUE_DEPTH"] == 32
    assert current_limits() == DocumentLimits()


def test_the_limits_the_builder_enforces_are_in_the_bootstrap_config(
    app: Any, app_context: None, mocker: MockerFixture
) -> None:
    from superset.views.base import _get_frontend_config_value, FRONTEND_CONF_KEYS

    mocker.patch.dict(
        app.config, {"DASHBOARD_V2_MAX_NODES": 800, "DASHBOARD_V2_MAX_DEPTH": 12}
    )

    assert "DASHBOARD_V2_MAX_NODES" in FRONTEND_CONF_KEYS
    assert "DASHBOARD_V2_MAX_DEPTH" in FRONTEND_CONF_KEYS
    assert _get_frontend_config_value("DASHBOARD_V2_MAX_NODES") == 800
    assert _get_frontend_config_value("DASHBOARD_V2_MAX_DEPTH") == 12


def test_request_logging_survives_a_body_nested_past_the_parser(
    app: Any, mocker: MockerFixture
) -> None:
    """``get_json(silent=True)`` only swallows malformed JSON; the logger
    must not turn a pathologically nested body into a server error."""
    from flask import request

    from superset.utils.log import collect_request_payload

    with app.test_request_context("/api/v1/anything?x=1", method="POST", json={"a": 1}):
        mocker.patch.object(
            type(request._get_current_object()),
            "get_json",
            side_effect=RecursionError("maximum recursion depth exceeded"),
        )

        payload = collect_request_payload()

    assert payload["path"] == "/api/v1/anything"
    assert payload["x"] == "1"
    assert "a" not in payload


def test_request_logging_survives_a_really_deeply_nested_body(app: Any) -> None:
    from superset.utils.log import collect_request_payload

    depth = 200_000
    body = "[" * depth + "]" * depth

    with app.test_request_context(
        "/api/v1/anything", method="POST", data=body, content_type="application/json"
    ):
        payload = collect_request_payload()

    assert payload["path"] == "/api/v1/anything"
    assert set(payload) <= {"path", "url_rule"}


def test_request_logging_ignores_a_json_body_that_is_not_an_object(app: Any) -> None:
    from superset.utils.log import collect_request_payload

    with app.test_request_context("/api/v1/anything", method="POST", json=[1, 2]):
        payload = collect_request_payload()

    assert payload["path"] == "/api/v1/anything"
    assert set(payload) <= {"path", "url_rule"}
