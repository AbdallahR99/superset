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
"""The revision of a Dashboard v2 document only ever moves forward.

A version restore reverts ``json_metadata`` as a whole, and that column holds
the document together with the revision guarding concurrent saves. The revert
is driven here through the real restore engine (``restore_version``) with the
version row stubbed, and the saves through the real Dashboard v2 commands."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pytest_mock import MockerFixture
from sqlalchemy.dialects import mysql, postgresql, sqlite
from sqlalchemy.orm.session import Session

from superset.commands.dashboard_v2.exceptions import DashboardV2ConflictError
from superset.commands.dashboard_v2.save import (
    CreateDashboardV2Command,
    store_replaced_json_metadata,
    UpdateDashboardV2Command,
)
from superset.commands.widget.exceptions import SavedWidgetForbiddenError
from superset.dashboard_v2 import storage
from superset.utils import json
from superset.versioning.restore import (
    DashboardDocumentRestoreError,
    restore_version,
)
from tests.unit_tests.dashboard_v2.conftest import make_document, stored_document

SAVE = "superset.commands.dashboard_v2.save"
RESTORE = "superset.versioning.restore"


def _create(*children: str) -> int:
    return CreateDashboardV2Command(
        {"dashboard_title": "Sales", "document": make_document(*children)}
    ).run()["id"]


def _save(pk: int, base_revision: int, *children: str) -> dict[str, Any]:
    return UpdateDashboardV2Command(
        pk, {"document": make_document(*children)}, base_revision
    ).run()


def _raw(session: Session, pk: int) -> str:
    from superset.models.dashboard import Dashboard

    session.expire_all()
    dashboard = session.get(Dashboard, pk)
    assert dashboard is not None
    return dashboard.json_metadata


def _write_behind_the_session(session: Session, pk: int, json_metadata: str) -> None:
    """Change the row the way another connection would: past the ORM."""
    from superset.models.dashboard import Dashboard

    table = Dashboard.__table__
    session.execute(
        table.update().where(table.c.id == pk).values(json_metadata=json_metadata)
    )


def _restore(
    session: Session, pk: int, snapshot: str, behind: str | None = None
) -> None:
    """
    Restore dashboard ``pk`` to a version whose ``json_metadata`` is
    ``snapshot``, the way Continuum's ``revert`` does it: by assigning the
    snapshot's column values to the loaded entity.

    :param behind: A value another writer stores after the entity was loaded
    """
    from superset.models.dashboard import Dashboard

    dashboard = session.get(Dashboard, pk)
    assert dashboard is not None
    if behind is not None:
        _write_behind_the_session(session, pk, behind)
    target = MagicMock()

    def revert(*, relations: list[str]) -> None:
        dashboard.json_metadata = snapshot

    target.revert.side_effect = revert
    with (
        patch(f"{RESTORE}._find_target_version", return_value=target),
        patch(f"{RESTORE}._restore_dashboard_membership", return_value=([], [])),
        patch(f"{RESTORE}._stamp_audit_fields_for_restore"),
    ):
        restore_version(Dashboard, dashboard.uuid, 123, entity=dashboard)
    target.revert.assert_called_once()
    session.commit()


def test_a_save_based_on_a_revision_from_before_a_restore_is_refused(
    editor: None, v2_session: Session
) -> None:
    """Create (1), two saves (3), restore the first version: the restored
    document is stored at revision 4, so a tab that loaded the original
    revision 2 cannot have its save accepted over it."""
    pk = _create("first")
    first_version = _raw(v2_session, pk)
    _save(pk, 1, "second")
    _save(pk, 2, "third")

    _restore(v2_session, pk, first_version)

    restored = stored_document(v2_session, pk)
    assert restored["revision"] == 4
    assert set(restored["nodes"]) == {"root", "first"}
    for stale in (1, 2, 3):
        with pytest.raises(DashboardV2ConflictError) as conflict:
            _save(pk, stale, "from_a_stale_tab")
        assert conflict.value.current_revision == 4
    assert set(stored_document(v2_session, pk)["nodes"]) == {"root", "first"}
    assert _save(pk, 4, "after_reload")["revision"] == 5


def test_a_restore_uses_the_revision_stored_at_the_time_of_the_write(
    editor: None, v2_session: Session
) -> None:
    """A save that lands after the restore loaded the dashboard still counts:
    the restored document goes one past it, not one past the loaded copy."""
    pk = _create("first")
    first_version = _raw(v2_session, pk)
    saved_meanwhile = json.dumps(
        {"v2_document": {**make_document("meanwhile"), "revision": 7}}
    )

    _restore(v2_session, pk, first_version, behind=saved_meanwhile)

    restored = stored_document(v2_session, pk)
    assert restored["revision"] == 8
    assert set(restored["nodes"]) == {"root", "first"}


def test_a_restore_to_a_version_without_a_document_keeps_the_stored_one(
    editor: None, v2_session: Session
) -> None:
    pk = _create("first")
    _save(pk, 1, "second")

    _restore(v2_session, pk, json.dumps({"color_scheme": "from_the_snapshot"}))

    metadata = json.loads(_raw(v2_session, pk))
    assert metadata["color_scheme"] == "from_the_snapshot"
    assert metadata["v2_document"]["revision"] == 2
    assert set(metadata["v2_document"]["nodes"]) == {"root", "second"}
    assert _save(pk, 2, "third")["revision"] == 3


def test_a_restore_is_refused_when_the_snapshots_document_no_longer_validates(
    editor: None, v2_session: Session
) -> None:
    """A widget type that was uninstalled since the snapshot: the restore is
    refused as a whole and nothing is written."""
    pk = _create("first")
    _save(pk, 1, "second")
    before = _raw(v2_session, pk)
    snapshot = json.dumps(
        {
            "v2_document": {
                "version": 1,
                "revision": 1,
                "nodes": {
                    "root": {"type": "grid", "children": ["gone"]},
                    "gone": {"type": "extensions.acme.gone.widget"},
                },
            }
        }
    )

    with pytest.raises(DashboardDocumentRestoreError, match="unknown type"):
        _restore(v2_session, pk, snapshot)
    v2_session.rollback()

    assert _raw(v2_session, pk) == before


def test_a_restore_applies_the_authoring_rule_to_definitions_it_brings_back(
    mocker: MockerFixture, editor: None, v2_session: Session
) -> None:
    pk = _create("first")
    before = _raw(v2_session, pk)
    chart = {"type": "echarts", "props": {"dataBinding": {"datasetId": 7}}}
    snapshot = json.dumps(
        {"v2_document": {**make_document("chart", chart=chart), "revision": 1}}
    )
    mocker.patch(
        f"{SAVE}.raise_for_widget_authoring", side_effect=SavedWidgetForbiddenError()
    )

    with pytest.raises(DashboardDocumentRestoreError, match="widgets: chart"):
        _restore(v2_session, pk, snapshot)
    v2_session.rollback()

    assert _raw(v2_session, pk) == before


def test_a_restore_refuses_a_snapshot_with_a_malformed_document(
    editor: None, v2_session: Session
) -> None:
    pk = _create("first")
    before = _raw(v2_session, pk)
    snapshot = json.dumps({"color_scheme": "old", "v2_document": {"nodes": []}})

    with pytest.raises(
        DashboardDocumentRestoreError, match="document.nodes must be an object"
    ):
        _restore(v2_session, pk, snapshot)
    v2_session.rollback()

    assert _raw(v2_session, pk) == before


def test_a_restore_of_a_classic_dashboard_does_not_create_a_document(
    session: Session,
) -> None:
    from superset.models.dashboard import Dashboard

    Dashboard.metadata.create_all(session.get_bind())  # pylint: disable=no-member
    session.add(
        Dashboard(id=9, dashboard_title="Classic", slices=[], json_metadata="{}")
    )
    session.flush()
    _restore(session, 9, json.dumps({"color_scheme": "old"}))

    assert json.loads(_raw(session, 9)) == {"color_scheme": "old"}


def test_a_restore_keeps_a_document_added_after_reading_classic_metadata(
    mocker: MockerFixture, session: Session
) -> None:
    from superset.models.dashboard import Dashboard

    Dashboard.metadata.create_all(session.get_bind())  # pylint: disable=no-member
    session.add(
        Dashboard(id=9, dashboard_title="Classic", slices=[], json_metadata="{}")
    )
    session.flush()
    stored = {**make_document("imported"), "revision": 1}
    concurrent = json.dumps({"v2_document": stored})
    mocker.patch(f"{SAVE}.read_current_json_metadata", side_effect=["{}", concurrent])

    _restore(
        session, 9, json.dumps({"color_scheme": "from_snapshot"}), behind=concurrent
    )

    assert json.loads(_raw(session, 9)) == {
        "color_scheme": "from_snapshot",
        "v2_document": stored,
    }


def test_replacing_metadata_gives_up_after_losing_every_attempt(
    mocker: MockerFixture, editor: None, v2_session: Session
) -> None:
    pk = _create("first")
    mocker.patch(f"{SAVE}.compare_and_swap_json_metadata", return_value=False)

    with pytest.raises(DashboardV2ConflictError):
        store_replaced_json_metadata(pk, _raw(v2_session, pk))


def test_the_restore_endpoint_answers_a_refused_document_with_422(
    app_context: None,
) -> None:
    from superset.versioning.api_helpers import restore_version_endpoint

    class Command:
        not_found_exc = LookupError
        forbidden_exc = PermissionError
        failed_exc = RuntimeError

        def __init__(self, *_args: object) -> None:
            pass

        def run(self) -> None:
            raise DashboardDocumentRestoreError("the document can't be restored")

    api = MagicMock()
    uuid = "00000000-0000-0000-0000-000000000000"

    restore_version_endpoint(api, MagicMock(), Command, uuid, uuid)

    api.response_422.assert_called_once_with(message="the document can't be restored")


def test_the_swap_compares_bytes_on_mysql() -> None:
    """MySQL and MariaDB compare text by collation (case, accents and
    trailing spaces ignored by default), so the swap compares the UTF-8 bytes
    there; the other databases compare text exactly as it is."""
    expected = '{"a": 1}'

    for dialect_name in ("mysql", "mariadb"):
        condition = storage._unchanged_condition(expected, dialect_name)
        compiled = condition.compile(dialect=mysql.dialect())
        assert str(compiled) == (
            "CAST(CONVERT(dashboards.json_metadata USING utf8mb4) AS BINARY) = "
            "CAST(CONVERT(%s USING utf8mb4) AS BINARY)"
        )
        assert compiled.params == {"expected_json_metadata": expected}
    for dialect_name, dialect in (
        ("postgresql", postgresql.dialect()),
        ("sqlite", sqlite.dialect()),
    ):
        plain = str(
            storage._unchanged_condition(expected, dialect_name).compile(
                dialect=dialect
            )
        )
        assert plain.startswith("dashboards.json_metadata = ")
    assert "IS NULL" in str(storage._unchanged_condition(None, "mysql"))
