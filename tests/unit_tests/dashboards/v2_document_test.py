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
"""The classic dashboard paths and the Dashboard v2 document.

The Dashboard v2 API is the only writer of the document. A classic update
ignores an incoming one and carries the stored one forward, a copy takes the
source's stored document, an import validates it and stamps a fresh revision,
and the classic read never returns it."""

from __future__ import annotations

import copy
from collections.abc import Iterator
from typing import Any

import pytest
from pytest_mock import MockerFixture
from sqlalchemy.orm.session import Session

from superset import security_manager
from superset.commands.exceptions import ImportFailedError
from superset.dashboard_v2 import storage
from superset.utils import json
from tests.integration_tests.fixtures.importexport import dashboard_config
from tests.unit_tests.dashboard_v2.conftest import make_document

V2_ID = 100


def _stored(revision: int, *children: str) -> dict[str, Any]:
    document = make_document(*children)
    return {"version": 1, "revision": revision, "nodes": document["nodes"]}


def _metadata(session: Session, pk: int = V2_ID) -> dict[str, Any]:
    from superset.models.dashboard import Dashboard

    session.flush()
    session.expire_all()
    dashboard = session.get(Dashboard, pk)
    assert dashboard is not None
    return json.loads(dashboard.json_metadata)


@pytest.fixture
def v2_dashboard(session: Session) -> Iterator[Any]:
    """A v2 dashboard at revision 3 with one other metadata key."""
    from superset.models.dashboard import Dashboard

    Dashboard.metadata.create_all(session.get_bind())  # pylint: disable=no-member
    dashboard = Dashboard(
        id=V2_ID,
        dashboard_title="Sales",
        slices=[],
        published=True,
        json_metadata=json.dumps(
            {"color_scheme": "old", "v2_document": _stored(3, "kept")}
        ),
    )
    session.add(dashboard)
    session.flush()
    yield dashboard
    session.rollback()


# --------------------------------------------------------------------------
# Classic update (PUT /api/v1/dashboard/<id>, properties modal)
# --------------------------------------------------------------------------


def test_classic_update_ignores_an_incoming_document(
    session: Session, v2_dashboard: Any
) -> None:
    """The properties modal sends back the metadata it loaded; a document in
    it — stale, tampered with or rolled back — never replaces the stored one."""
    from superset.daos.dashboard import DashboardDAO

    DashboardDAO.set_dash_metadata(
        v2_dashboard,
        {"color_scheme": "new", "v2_document": _stored(1, "attacker")},
    )

    metadata = _metadata(session)
    assert metadata["color_scheme"] == "new"
    assert metadata["v2_document"] == _stored(3, "kept")


def test_classic_update_without_a_document_keeps_the_stored_one(
    session: Session, v2_dashboard: Any
) -> None:
    from superset.daos.dashboard import DashboardDAO

    DashboardDAO.set_dash_metadata(v2_dashboard, {"color_scheme": "new"})

    assert _metadata(session)["v2_document"] == _stored(3, "kept")


def test_classic_update_cannot_roll_back_a_v2_save_made_after_it_loaded(
    session: Session, v2_dashboard: Any
) -> None:
    """The session loaded revision 3; a Dashboard v2 save then stored revision
    4. The classic update writes its own keys around the revision-4 document."""
    from superset.daos.dashboard import DashboardDAO
    from superset.models.dashboard import Dashboard

    table = Dashboard.__table__
    newer = json.dumps({"color_scheme": "old", "v2_document": _stored(4, "newer")})
    session.execute(
        table.update().where(table.c.id == V2_ID).values(json_metadata=newer)
    )
    assert json.loads(v2_dashboard.json_metadata)["v2_document"]["revision"] == 3

    DashboardDAO.set_dash_metadata(
        v2_dashboard, {"color_scheme": "new", "v2_document": _stored(3, "kept")}
    )

    metadata = _metadata(session)
    assert metadata["color_scheme"] == "new"
    assert metadata["v2_document"] == _stored(4, "newer")


def test_classic_update_retries_when_a_v2_save_lands_during_its_write(
    mocker: MockerFixture, session: Session, v2_dashboard: Any
) -> None:
    from superset.daos.dashboard import DashboardDAO
    from superset.models.dashboard import Dashboard

    table = Dashboard.__table__
    stale = v2_dashboard.json_metadata
    newer = json.dumps({"color_scheme": "old", "v2_document": _stored(4, "newer")})
    session.execute(
        table.update().where(table.c.id == V2_ID).values(json_metadata=newer)
    )
    mocker.patch.object(
        storage, "read_current_json_metadata", side_effect=[stale, newer]
    )

    DashboardDAO.set_dash_metadata(v2_dashboard, {"color_scheme": "new"})

    assert _metadata(session)["v2_document"] == _stored(4, "newer")


def test_classic_update_fails_rather_than_overwrite_when_it_keeps_losing(
    mocker: MockerFixture, session: Session, v2_dashboard: Any
) -> None:
    from superset.commands.dashboard.exceptions import DashboardUpdateFailedError
    from superset.daos.dashboard import DashboardDAO

    mocker.patch.object(storage, "compare_and_swap_json_metadata", return_value=False)

    with pytest.raises(DashboardUpdateFailedError):
        DashboardDAO.set_dash_metadata(v2_dashboard, {"color_scheme": "new"})

    assert _metadata(session)["color_scheme"] == "old"


def test_classic_dashboards_are_written_without_extra_queries(
    mocker: MockerFixture, session: Session
) -> None:
    from superset.daos.dashboard import DashboardDAO
    from superset.models.dashboard import Dashboard

    Dashboard.metadata.create_all(session.get_bind())  # pylint: disable=no-member
    dashboard = Dashboard(id=7, dashboard_title="Classic", slices=[])
    session.add(dashboard)
    session.flush()
    read = mocker.spy(storage, "read_current_json_metadata")

    DashboardDAO.set_dash_metadata(
        dashboard, {"color_scheme": "new", "v2_document": _stored(1, "smuggled")}
    )

    metadata = json.loads(dashboard.json_metadata)
    assert metadata["color_scheme"] == "new"
    assert "v2_document" not in metadata
    read.assert_not_called()


def test_json_metadata_schema_accepts_and_does_not_judge_a_document() -> None:
    """A document echoed back by the properties modal must not fail the
    request, whatever it holds: it is ignored further down."""
    from superset.dashboards.schemas import DashboardJSONMetadataSchema

    schema = DashboardJSONMetadataSchema()

    assert schema.validate({"v2_document": _stored(3, "kept")}) == {}
    assert schema.validate({"v2_document": {"nodes": "not even a tree"}}) == {}
    assert schema.validate({"v2_document": None}) == {}


# --------------------------------------------------------------------------
# Classic read
# --------------------------------------------------------------------------


def test_classic_read_does_not_return_the_document() -> None:
    from superset.dashboards.schemas import without_v2_document

    json_metadata = json.dumps({"color_scheme": "x", "v2_document": _stored(3, "a")})

    assert json.loads(without_v2_document(json_metadata)) == {"color_scheme": "x"}
    assert without_v2_document('{"color_scheme": "x"}') == '{"color_scheme": "x"}'
    assert without_v2_document("not json v2_document") == "not json v2_document"
    assert without_v2_document(None) is None


def test_dashboard_get_response_omits_the_document(mocker: MockerFixture) -> None:
    from superset.dashboards.schemas import DashboardGetResponseSchema

    mocker.patch.object(security_manager, "is_guest_user", return_value=False)
    json_metadata = json.dumps({"color_scheme": "x", "v2_document": _stored(3, "a")})

    dumped = DashboardGetResponseSchema().dump(
        {"id": 1, "dashboard_title": "Sales", "json_metadata": json_metadata}
    )

    assert json.loads(dumped["json_metadata"]) == {"color_scheme": "x"}


# --------------------------------------------------------------------------
# Copy ("Save as")
# --------------------------------------------------------------------------


def test_copy_takes_the_sources_stored_document_at_the_initial_revision(
    mocker: MockerFixture, session: Session, v2_dashboard: Any
) -> None:
    from superset.daos.dashboard import DashboardDAO

    mocker.patch.object(security_manager, "is_editor", return_value=True)
    mocker.patch.object(security_manager, "is_admin", return_value=True)

    duplicate = DashboardDAO.copy_dashboard(
        v2_dashboard,
        {
            "dashboard_title": "Sales (copy)",
            "json_metadata": json.dumps(
                {"color_scheme": "old", "v2_document": _stored(9, "from_request")}
            ),
        },
    )

    assert duplicate.id != V2_ID
    assert _metadata(session, duplicate.id)["v2_document"] == _stored(1, "kept")
    assert _metadata(session)["v2_document"] == _stored(3, "kept")


def test_copy_of_a_classic_dashboard_gets_no_document(
    mocker: MockerFixture, session: Session
) -> None:
    from superset.daos.dashboard import DashboardDAO
    from superset.models.dashboard import Dashboard

    Dashboard.metadata.create_all(session.get_bind())  # pylint: disable=no-member
    source = Dashboard(id=8, dashboard_title="Classic", slices=[], json_metadata="{}")
    session.add(source)
    session.flush()
    mocker.patch.object(security_manager, "is_editor", return_value=True)
    mocker.patch.object(security_manager, "is_admin", return_value=True)

    duplicate = DashboardDAO.copy_dashboard(
        source,
        {
            "dashboard_title": "Classic (copy)",
            "json_metadata": json.dumps({"v2_document": _stored(1, "smuggled")}),
        },
    )

    assert "v2_document" not in json.loads(duplicate.json_metadata)


# --------------------------------------------------------------------------
# Import
# --------------------------------------------------------------------------


def _import_config(document: Any) -> dict[str, Any]:
    config = copy.deepcopy(dashboard_config)
    config["metadata"] = {**(config.get("metadata") or {}), "v2_document": document}
    return config


@pytest.fixture
def import_session(session: Session, mocker: MockerFixture) -> Iterator[Session]:
    from superset.models.dashboard import Dashboard

    Dashboard.metadata.create_all(session.get_bind())  # pylint: disable=no-member
    mocker.patch.object(security_manager, "can_access", return_value=True)
    yield session
    session.rollback()


def test_import_validates_the_document_and_starts_at_the_initial_revision(
    import_session: Session,
) -> None:
    from superset.commands.dashboard.importers.v1.utils import import_dashboard

    config = _import_config(_stored(41, "imported"))

    dashboard = import_dashboard(config)

    assert json.loads(dashboard.json_metadata)["v2_document"] == _stored(1, "imported")
    # The caller's config is left as it was.
    assert config["metadata"]["v2_document"]["revision"] == 41


def test_import_over_a_v2_dashboard_moves_past_the_stored_revision(
    import_session: Session,
) -> None:
    from superset.commands.dashboard.importers.v1.utils import import_dashboard
    from superset.models.dashboard import Dashboard

    import_session.add(
        Dashboard(
            dashboard_title="Existing",
            slices=[],
            uuid=dashboard_config["uuid"],
            json_metadata=json.dumps({"v2_document": _stored(5, "old")}),
        )
    )
    import_session.flush()

    dashboard = import_dashboard(_import_config(_stored(2, "new")), overwrite=True)

    assert json.loads(dashboard.json_metadata)["v2_document"] == _stored(6, "new")


@pytest.mark.parametrize(
    ("document", "message"),
    [
        (
            {"nodes": {"root": {"type": "grid", "children": ["ghost"]}}},
            "unknown children",
        ),
        (
            {
                "nodes": {
                    "root": {"type": "grid", "children": ["a"]},
                    "a": {"type": "no-such-widget"},
                }
            },
            "unknown type",
        ),
        (
            {
                "nodes": {
                    "root": {"type": "grid", "children": ["a"]},
                    "a": {"type": "markdown", "props": {"content": 5}},
                }
            },
            "Widget props failed validation",
        ),
    ],
)
def test_import_of_an_invalid_document_fails(
    import_session: Session, document: dict[str, Any], message: str
) -> None:
    from superset.commands.dashboard.importers.v1.utils import import_dashboard
    from superset.models.dashboard import Dashboard

    with pytest.raises(ImportFailedError, match=message):
        import_dashboard(_import_config(document))

    assert import_session.query(Dashboard).count() == 0


def test_import_without_a_document_is_untouched(import_session: Session) -> None:
    from superset.commands.dashboard.importers.v1.utils import import_dashboard

    dashboard = import_dashboard(copy.deepcopy(dashboard_config))

    assert "v2_document" not in json.loads(dashboard.json_metadata or "{}")
