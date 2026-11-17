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
reach: the row lock and a save that loses a race after its own checks passed."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm.session import Session

from superset.commands.dashboard_v2.exceptions import (
    DashboardV2ConflictError,
    DashboardV2InvalidError,
    DashboardV2NotFoundError,
)
from superset.commands.dashboard_v2.save import (
    CreateDashboardV2Command,
    normalize_and_validate,
    UpdateDashboardV2Command,
)
from superset.dashboard_v2.document import with_revision, write_stored_document
from superset.utils import json
from tests.unit_tests.dashboard_v2.conftest import make_document, stored_document


def _create(title: str = "Sales") -> int:
    dashboard = CreateDashboardV2Command(
        {"dashboard_title": title, "document": make_document()}
    ).run()
    return dashboard.id


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


def test_update_reads_the_revision_under_a_row_lock(
    mocker: MockerFixture, editor: None, v2_session: Session
) -> None:
    """The authoritative revision check reads ``json_metadata`` with
    ``SELECT ... FOR UPDATE``, so concurrent saves are serialized on databases
    that support row locks."""
    pk = _create()
    execute = mocker.spy(v2_session, "execute")

    UpdateDashboardV2Command(pk, {"document": make_document("x")}, 1).run()

    locking = [
        call.args[0]
        for call in execute.call_args_list
        if getattr(call.args[0], "_for_update_arg", None) is not None
    ]
    assert len(locking) == 1
    sql = str(locking[0].compile(dialect=postgresql.dialect()))
    assert "dashboards.json_metadata" in sql
    assert sql.rstrip().endswith("FOR UPDATE")


def test_save_that_loses_the_race_after_validation_is_rejected(
    mocker: MockerFixture, editor: None, v2_session: Session
) -> None:
    """Both saves pass the first revision check against revision 1; by the
    time this one holds the row lock the other has committed revision 2. The
    locked read sees it and the save is refused instead of overwriting."""
    pk = _create()
    winner = write_stored_document(
        json.dumps({}),
        with_revision(normalize_and_validate(make_document("winner")), 2),
    )
    mocker.patch.object(
        UpdateDashboardV2Command, "_lock_json_metadata", return_value=winner
    )

    with pytest.raises(DashboardV2ConflictError) as excinfo:
        UpdateDashboardV2Command(pk, {"document": make_document("loser")}, 1).run()

    assert excinfo.value.current_revision == 2
    assert excinfo.value.status == 409
    assert set(stored_document(v2_session, pk)["nodes"]) == {"root", "node_1"}


def test_save_is_refused_when_the_document_vanished_under_the_lock(
    mocker: MockerFixture, editor: None, v2_session: Session
) -> None:
    pk = _create()
    mocker.patch.object(
        UpdateDashboardV2Command, "_lock_json_metadata", return_value=None
    )

    with pytest.raises(DashboardV2NotFoundError):
        UpdateDashboardV2Command(pk, {"document": make_document()}, 1).run()


def test_unknown_widget_type_is_rejected_by_the_command(
    editor: None, v2_session: Session
) -> None:
    document = make_document()
    document["nodes"]["node_1"]["type"] = "not-registered"

    with pytest.raises(DashboardV2InvalidError, match="unknown type"):
        normalize_and_validate(document)
