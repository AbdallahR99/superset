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
"""Command-level behaviour of Dashboard v2 saves that the HTTP tests cannot
reach: the compare-and-swap write, saves that lose a race after their own
checks passed, database-level aborts and the idempotent create."""

from __future__ import annotations

import uuid
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture
from sqlalchemy import event
from sqlalchemy.dialects import mysql, postgresql, sqlite
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.orm.session import Session

from superset.commands.dashboard_v2.exceptions import (
    DashboardV2ConflictError,
    DashboardV2InvalidError,
    DashboardV2NotFoundError,
    DashboardV2SaveFailedError,
)
from superset.commands.dashboard_v2.save import (
    CreateDashboardV2Command,
    normalize_and_validate,
    UpdateDashboardV2Command,
)
from superset.daos.dashboard import DashboardDAO
from superset.dashboard_v2 import storage
from superset.dashboard_v2.document import with_revision, write_stored_document
from superset.utils import json
from superset.utils.core import override_user
from superset.versioning.changes.state import compute_records_from_state
from superset.versioning.diff import ChangeRecord
from superset.versioning.unit_of_work import INITIAL_STATES_KEY
from tests.unit_tests.dashboard_v2.conftest import make_document, stored_document

SAVE = "superset.commands.dashboard_v2.save"


def _create(title: str = "Sales", **extra: Any) -> int:
    result = CreateDashboardV2Command(
        {"dashboard_title": title, "document": make_document(), **extra}
    ).run()
    return result["id"]


def _raw_json_metadata(session: Session, pk: int) -> str:
    from superset.models.dashboard import Dashboard

    session.expire_all()
    dashboard = session.get(Dashboard, pk)
    assert dashboard is not None
    return cast(str, dashboard.json_metadata)


def _write_behind_the_session(session: Session, pk: int, json_metadata: str) -> None:
    """Change the row the way another connection would: past the ORM."""
    from superset.models.dashboard import Dashboard

    table = Dashboard.__table__
    session.execute(
        table.update().where(table.c.id == pk).values(json_metadata=json_metadata)
    )
    session.commit()


def _user(user_id: int) -> Any:
    """Run a block as the user with this id."""
    return override_user(MagicMock(id=user_id, is_anonymous=False))


def _dbapi_error(original: Exception) -> OperationalError:
    return OperationalError("UPDATE dashboards", {}, original)


def test_create_stores_revision_one_and_runs_the_asset_hook(
    app: Any, mocker: MockerFixture, editor: None, v2_session: Session
) -> None:
    hook = MagicMock()
    mocker.patch.dict(app.config, {"AFTER_ASSET_CREATE": hook})

    pk = _create()

    assert stored_document(v2_session, pk)["revision"] == 1
    hook.assert_called_once()
    created, asset_type = hook.call_args.args
    assert (created.id, asset_type) == (pk, "dashboard")


def test_create_and_update_answer_with_what_their_transaction_stored(
    mocker: MockerFixture, editor: None, v2_session: Session
) -> None:
    """The response is built by the saving command itself; nothing is read
    back afterwards, so a later writer's revision can never be reported."""
    reread = mocker.patch(
        "superset.commands.dashboard_v2.get.load_v2_dashboard",
        side_effect=AssertionError("the saved dashboard must not be re-read"),
    )
    command = CreateDashboardV2Command(
        {"dashboard_title": "Sales", "document": make_document()}
    )

    created = command.run()
    updated = UpdateDashboardV2Command(
        created["id"], {"document": make_document("x"), "dashboard_title": "New"}, 1
    ).run()

    assert command.created is True
    assert (created["revision"], updated["revision"]) == (1, 2)
    assert set(updated["document"]["nodes"]) == {"root", "x"}
    assert "revision" not in updated["document"]
    assert updated["dashboard_title"] == "New"
    assert stored_document(v2_session, created["id"])["revision"] == 2
    reread.assert_not_called()


def test_update_writes_with_a_compare_and_swap(
    mocker: MockerFixture, editor: None, v2_session: Session
) -> None:
    """The write only matches while ``json_metadata`` still holds the value
    the revision was read from, on every supported database."""
    pk = _create()
    before = _raw_json_metadata(v2_session, pk)
    execute = mocker.spy(v2_session, "execute")

    UpdateDashboardV2Command(pk, {"document": make_document("x")}, 1).run()

    swaps = [
        call.args[0]
        for call in execute.call_args_list
        if getattr(call.args[0], "is_update", False)
    ]
    assert len(swaps) == 1
    assert swaps[0].compile().params["json_metadata_1"] == before
    for dialect in (postgresql.dialect(), mysql.dialect(), sqlite.dialect()):
        sql = " ".join(str(swaps[0].compile(dialect=dialect)).split())
        assert sql.startswith("UPDATE dashboards SET json_metadata=")
        assert "WHERE dashboards.id = " in sql
        assert "AND dashboards.json_metadata = " in sql


def test_the_locking_read_is_a_plain_read_on_sqlite(
    mocker: MockerFixture, editor: None, v2_session: Session
) -> None:
    pk = _create()
    execute = mocker.spy(v2_session, "execute")

    storage.read_current_json_metadata(pk)

    statement = execute.call_args.args[0]
    assert (
        str(statement.compile(dialect=postgresql.dialect()))
        .rstrip()
        .endswith("FOR UPDATE")
    )
    assert "FOR UPDATE" not in str(statement.compile(dialect=sqlite.dialect()))


def test_compare_and_swap_only_writes_over_the_expected_value(
    editor: None, v2_session: Session
) -> None:
    pk = _create()
    before = _raw_json_metadata(v2_session, pk)

    assert storage.compare_and_swap_json_metadata(pk, "something else", "{}") is False
    assert _raw_json_metadata(v2_session, pk) == before
    assert storage.compare_and_swap_json_metadata(pk, before, "{}") is True
    assert _raw_json_metadata(v2_session, pk) == "{}"


def test_save_that_loses_the_race_after_validation_is_rejected(
    mocker: MockerFixture, editor: None, v2_session: Session
) -> None:
    """Both saves read revision 1. The other one commits revision 2 before
    this one writes; there is no row lock to stop that (as on SQLite), so the
    compare-and-swap is what refuses the overwrite."""
    pk = _create()
    read_by_both = _raw_json_metadata(v2_session, pk)
    winner = write_stored_document(
        json.dumps({}),
        with_revision(normalize_and_validate(make_document("winner")), 2),
    )
    command = UpdateDashboardV2Command(pk, {"document": make_document("loser")}, 1)
    command.validate()
    _write_behind_the_session(v2_session, pk, winner)
    mocker.patch.object(command, "validate")
    mocker.patch(f"{SAVE}.read_current_json_metadata", return_value=read_by_both)

    with pytest.raises(DashboardV2ConflictError) as excinfo:
        command.run()

    assert excinfo.value.status == 409
    assert _raw_json_metadata(v2_session, pk) == winner


def test_conflict_reports_the_revision_the_winner_stored(
    editor: None, v2_session: Session
) -> None:
    pk = _create()
    command = UpdateDashboardV2Command(pk, {"document": make_document("loser")}, 1)
    command.validate()
    winner = write_stored_document(
        json.dumps({}),
        with_revision(normalize_and_validate(make_document("winner")), 2),
    )
    _write_behind_the_session(v2_session, pk, winner)
    command.validate = lambda: None  # type: ignore[method-assign]

    with pytest.raises(DashboardV2ConflictError) as excinfo:
        command.run()

    assert excinfo.value.current_revision == 2
    assert set(stored_document(v2_session, pk)["nodes"]) == {"root", "winner"}


def test_swap_lost_to_a_writer_of_another_key_is_retried_and_keeps_that_key(
    mocker: MockerFixture, editor: None, v2_session: Session
) -> None:
    """A classic update changed ``color_scheme`` between this save's read and
    its write. The revision is unchanged, so the save goes through on the
    fresh value instead of overwriting the other writer or failing."""
    pk = _create()
    stale = _raw_json_metadata(v2_session, pk)
    fresh = json.dumps({**json.loads(stale), "color_scheme": "supersetColors"})
    _write_behind_the_session(v2_session, pk, fresh)
    mocker.patch(f"{SAVE}.read_current_json_metadata", side_effect=[stale, fresh])

    result = UpdateDashboardV2Command(pk, {"document": make_document("x")}, 1).run()

    stored = json.loads(_raw_json_metadata(v2_session, pk))
    assert result["revision"] == 2
    assert stored["color_scheme"] == "supersetColors"
    assert set(stored["v2_document"]["nodes"]) == {"root", "x"}


def test_history_uses_the_metadata_replaced_by_the_successful_swap(
    mocker: MockerFixture, editor: None, v2_session: Session
) -> None:
    """A retried widget edit records its old value without claiming another edit."""
    pk = _create()
    stale = _raw_json_metadata(v2_session, pk)
    fresh = json.dumps({**json.loads(stale), "color_scheme": "supersetColors"})
    _write_behind_the_session(v2_session, pk, fresh)
    mocker.patch(f"{SAVE}.read_current_json_metadata", side_effect=[stale, fresh])
    mocker.patch(f"{SAVE}.capture_for_write", return_value=True)
    records: list[ChangeRecord] = []

    def capture(session: Session, *_args: Any) -> None:
        state = session.info.get(INITIAL_STATES_KEY, {}).get(("dashboard", pk))
        if state is not None:
            records.extend(compute_records_from_state(*state))

    event.listen(v2_session, "before_flush", capture, once=True)
    document = make_document()
    document["nodes"]["node_1"]["props"]["content"] = "Reviewed"
    UpdateDashboardV2Command(pk, {"document": document}, 1).run()

    content_changes = [
        (record.from_value, record.to_value)
        for record in records
        if record.path[-1:] == ["content"]
    ]
    assert content_changes == [("# node_1", "Reviewed")]
    assert all(record.path[-1:] != ["color_scheme"] for record in records)


def test_save_is_refused_when_the_document_vanished(
    mocker: MockerFixture, editor: None, v2_session: Session
) -> None:
    pk = _create()
    mocker.patch(f"{SAVE}.read_current_json_metadata", return_value=None)

    with pytest.raises(DashboardV2NotFoundError):
        UpdateDashboardV2Command(pk, {"document": make_document()}, 1).run()


class _PgError(Exception):
    def __init__(self, pgcode: str) -> None:
        super().__init__(pgcode)
        self.pgcode = pgcode


@pytest.mark.parametrize(
    "error",
    [
        _dbapi_error(_PgError("40001")),
        _dbapi_error(_PgError("40P01")),
        _dbapi_error(_PgError("55P03")),
        _dbapi_error(Exception(1213, "Deadlock found when trying to get lock")),
        _dbapi_error(Exception(1205, "Lock wait timeout exceeded")),
        _dbapi_error(Exception("database is locked")),
        StaleDataError("UPDATE statement on table 'dashboards' expected 1 row"),
    ],
)
def test_database_aborts_caused_by_concurrency_are_conflicts(
    mocker: MockerFixture, editor: None, v2_session: Session, error: Exception
) -> None:
    """Serialization failures, deadlocks, lock timeouts and a busy SQLite are
    answered as a conflict carrying the stored revision, not as a failure."""
    pk = _create()
    mocker.patch(f"{SAVE}.compare_and_swap_json_metadata", side_effect=error)

    with pytest.raises(DashboardV2ConflictError) as excinfo:
        UpdateDashboardV2Command(pk, {"document": make_document("x")}, 1).run()

    assert excinfo.value.current_revision == 1
    assert set(stored_document(v2_session, pk)["nodes"]) == {"root", "node_1"}


def test_a_failed_commit_caused_by_concurrency_is_a_conflict(
    mocker: MockerFixture, editor: None, v2_session: Session
) -> None:
    pk = _create()
    mocker.patch.object(
        v2_session, "commit", side_effect=_dbapi_error(_PgError("40001"))
    )

    with pytest.raises(DashboardV2ConflictError):
        UpdateDashboardV2Command(pk, {"document": make_document("x")}, 1).run()


def test_other_database_errors_stay_failures(
    mocker: MockerFixture, editor: None, v2_session: Session
) -> None:
    pk = _create()
    mocker.patch(
        f"{SAVE}.compare_and_swap_json_metadata",
        side_effect=_dbapi_error(Exception("disk I/O error")),
    )

    with pytest.raises(DashboardV2SaveFailedError):
        UpdateDashboardV2Command(pk, {"document": make_document("x")}, 1).run()


def test_unknown_widget_type_is_rejected_by_the_command(
    editor: None, v2_session: Session
) -> None:
    document = make_document()
    document["nodes"]["node_1"]["type"] = "not-registered"

    with pytest.raises(DashboardV2InvalidError, match="unknown type"):
        normalize_and_validate(document)


# --------------------------------------------------------------------------
# Idempotent create
# --------------------------------------------------------------------------


def test_create_uses_the_client_uuid(
    mocker: MockerFixture, editor: None, v2_session: Session
) -> None:
    key = uuid.uuid4()

    result = CreateDashboardV2Command(
        {"dashboard_title": "Sales", "document": make_document(), "uuid": key}
    ).run()

    assert result["uuid"] == str(key)


def test_repeating_a_create_returns_the_dashboard_already_created(
    mocker: MockerFixture, editor: None, v2_session: Session
) -> None:
    key = uuid.uuid4()
    first = CreateDashboardV2Command(
        {"dashboard_title": "Sales", "document": make_document(), "uuid": key}
    )
    repeat = CreateDashboardV2Command(
        {"dashboard_title": "Sales", "document": make_document(), "uuid": key}
    )

    with _user(7):
        created = first.run()
        UpdateDashboardV2Command(
            created["id"], {"document": make_document("x")}, 1
        ).run()
        again = repeat.run()

    assert (first.created, repeat.created) == (True, False)
    assert again["id"] == created["id"]
    # The stored state, not the body that was sent again.
    assert again["revision"] == 2
    assert set(again["document"]["nodes"]) == {"root", "x"}


def test_a_uuid_of_someone_elses_dashboard_is_refused(
    mocker: MockerFixture, editor: None, v2_session: Session
) -> None:
    key = uuid.uuid4()
    with _user(7):
        _create(uuid=key)

    with _user(8), pytest.raises(DashboardV2InvalidError, match="uuid already exists"):
        _create(uuid=key)


def test_an_anonymous_repeat_is_refused(
    mocker: MockerFixture, editor: None, v2_session: Session
) -> None:
    key = uuid.uuid4()
    _create(uuid=key)

    with pytest.raises(DashboardV2InvalidError, match="uuid already exists"):
        _create(uuid=key)


def test_a_uuid_of_a_classic_dashboard_is_refused(
    mocker: MockerFixture, editor: None, v2_session: Session
) -> None:
    from superset.models.dashboard import Dashboard

    key = uuid.uuid4()
    with _user(7):
        v2_session.add(
            Dashboard(dashboard_title="Classic", uuid=key, json_metadata="{}")
        )
        v2_session.flush()

        with pytest.raises(DashboardV2InvalidError, match="uuid already exists"):
            _create(uuid=key)


def test_a_uuid_of_a_dashboard_in_the_trash_is_refused(
    mocker: MockerFixture, editor: None, v2_session: Session
) -> None:
    """A soft-deleted dashboard still holds its uuid. Even its own creator
    gets a validation error rather than the unique constraint's failure."""
    from superset.models.dashboard import Dashboard

    key = uuid.uuid4()
    with _user(7):
        pk = _create(uuid=key)
        dashboard = v2_session.get(Dashboard, pk)
        assert dashboard is not None
        dashboard.soft_delete()
        v2_session.flush()
        v2_session.expire_all()
        # The row is invisible to an ordinary lookup.
        assert v2_session.query(Dashboard).filter(Dashboard.uuid == key).count() == 0
        create = mocker.spy(DashboardDAO, "create")

        with pytest.raises(DashboardV2InvalidError, match="uuid already exists"):
            _create(uuid=key)

    create.assert_not_called()


def test_create_losing_a_race_on_its_uuid_returns_the_winners_dashboard(
    mocker: MockerFixture, editor: None, v2_session: Session
) -> None:
    """Both creates found the uuid free; the loser fails on the unique
    constraint and answers with the dashboard the winner stored."""
    key = uuid.uuid4()
    loser = CreateDashboardV2Command(
        {"dashboard_title": "Sales", "document": make_document(), "uuid": key}
    )
    with _user(7):
        winner = _create(uuid=key)
        found = loser._find_existing()
        mocker.patch.object(loser, "_find_existing", side_effect=[None, found])
        mocker.patch(
            f"{SAVE}.DashboardDAO.create",
            side_effect=IntegrityError("INSERT", {}, Exception("UNIQUE constraint")),
        )

        result = loser.run()

    assert loser.created is False
    assert result["id"] == winner
