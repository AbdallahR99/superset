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
Shared fixtures for the Dashboard v2 tests.

The built-in widgets are registered before any test module is collected (the
``@widget`` decorator is a stub until the injection runs), and the
``DASHBOARD_V2`` flag — off by default — is switched on per test by the
``dashboard_v2_enabled`` fixture.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from flask import g, has_app_context, has_request_context
from pytest_mock import MockerFixture
from sqlalchemy.orm.session import Session

from superset import security_manager
from superset.core.api.core_api_injection import inject_widget_implementations
from superset.extensions import feature_flag_manager
from superset.utils import json

inject_widget_implementations()


def make_document(*children: str, **extra_nodes: dict[str, Any]) -> dict[str, Any]:
    """A valid document: a root grid holding one markdown block per child."""
    names = children or ("node_1",)
    nodes: dict[str, Any] = {
        "root": {"type": "grid", "layout": {"columns": 24}, "children": list(names)},
    }
    for name in names:
        nodes[name] = {"type": "markdown", "props": {"content": f"# {name}"}}
    nodes.update(extra_nodes)
    return {"version": 1, "nodes": nodes}


@pytest.fixture
def dashboard_v2_enabled(mocker: MockerFixture, app_context: None) -> None:
    """Switch the ``DASHBOARD_V2`` feature flag on for one test."""
    mocker.patch.dict(feature_flag_manager._feature_flags, {"DASHBOARD_V2": True})


@pytest.fixture
def editor(mocker: MockerFixture, full_api_access: None) -> None:
    """A caller that passes every route, read and editorship check."""
    mocker.patch.object(security_manager, "is_admin", return_value=True)

    original_can_access = security_manager.can_access

    def can_access(permission_name: str, view_name: str) -> bool:
        # Direct command tests use a mocked editor without a Flask request user.
        if (
            (permission_name, view_name) == ("can_write", "Dashboard")
            and has_app_context()
            and not has_request_context()
            and not hasattr(g, "user")
        ):
            return True
        return original_can_access(permission_name, view_name)

    mocker.patch.object(security_manager, "can_access", side_effect=can_access)
    mocker.patch.object(security_manager, "raise_for_access", return_value=None)
    mocker.patch.object(security_manager, "raise_for_editorship", return_value=None)
    mocker.patch.object(security_manager, "is_guest_user", return_value=False)


@pytest.fixture
def v2_session(session: Session, mocker: MockerFixture) -> Iterator[Session]:
    """An in-memory metadata database with the dashboard tables created."""
    from superset.models.dashboard import Dashboard
    from superset.models.embedded_dashboard import EmbeddedDashboard  # noqa: F401

    Dashboard.metadata.create_all(session.get_bind())  # pylint: disable=no-member

    def no_subjects(properties: dict[str, Any], *args: Any, **kwargs: Any) -> None:
        properties["editors"] = []

    mocker.patch(
        "superset.commands.dashboard_v2.save.populate_subjects",
        side_effect=no_subjects,
    )
    yield session
    session.rollback()


def stored_document(session: Session, dashboard_id: int) -> dict[str, Any]:
    """The v2 document as it sits in the dashboard row."""
    from superset.models.dashboard import Dashboard

    session.expire_all()
    dashboard = session.get(Dashboard, dashboard_id)
    assert dashboard is not None
    return json.loads(dashboard.json_metadata)["v2_document"]
