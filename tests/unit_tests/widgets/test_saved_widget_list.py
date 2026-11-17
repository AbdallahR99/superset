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
The saved-widget list: paged in the database and limited to what the caller
may read (SECURITY.md row "Gamma": only granted datasets, own objects).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture
from sqlalchemy.orm.session import Session

from superset.commands.widget.exceptions import (
    SavedWidgetForbiddenError,
    WidgetInvalidError,
)
from superset.commands.widget.saved import (
    ListSavedWidgetsCommand,
    MAX_LIST_PAGE_SIZE,
)
from superset.daos.saved_widget import SavedWidgetDAO
from superset.models.saved_widget import SavedWidget
from superset.utils import json

ME = 1
SOMEONE_ELSE = 2


@pytest.fixture
def datasets(mocker: MockerFixture, session: Session) -> dict[str, int]:
    """
    Two datasets, of which the caller's grants cover only ``readable``, and a
    dataset id that no longer exists.
    """
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.core import Database

    SqlaTable.metadata.create_all(session.get_bind())
    database = Database(database_name="widget_list_db", sqlalchemy_uri="sqlite://")
    readable = SqlaTable(table_name="readable", database=database)
    secret = SqlaTable(table_name="secret", database=database)
    session.add_all([readable, secret])
    session.flush()

    mocker.patch(
        "superset.views.base.security_manager.can_access_all_datasources",
        return_value=False,
    )
    mocker.patch(
        "superset.views.base.get_dataset_access_filters",
        side_effect=lambda model, *args, **kwargs: model.id == readable.id,
    )
    return {"readable": readable.id, "secret": secret.id, "deleted": 987654}


def _add(
    session: Session,
    title: str,
    created_by_fk: int,
    dataset_id: int | None,
    age_minutes: int,
) -> SavedWidget:
    props: dict[str, Any] = (
        {"content": title}
        if dataset_id is None
        else {"dataBinding": {"datasetId": dataset_id, "metrics": ["count"]}}
    )
    widget = SavedWidget(
        widget_type="markdown" if dataset_id is None else "echarts",
        title=title,
        props=json.dumps(props),
        dataset_id=dataset_id,
        created_by_fk=created_by_fk,
        changed_by_fk=created_by_fk,
        changed_on=datetime(2026, 1, 1) - timedelta(minutes=age_minutes),
    )
    session.add(widget)
    session.flush()
    return widget


def _titles(widgets: list[SavedWidget]) -> list[str]:
    return [str(widget.title) for widget in widgets]


def test_list_holds_only_what_the_caller_may_read(
    session: Session, datasets: dict[str, int]
) -> None:
    _add(session, "mine on secret", ME, datasets["secret"], 1)
    _add(session, "mine note", ME, None, 2)
    _add(session, "theirs on readable", SOMEONE_ELSE, datasets["readable"], 3)
    _add(session, "theirs on secret", SOMEONE_ELSE, datasets["secret"], 4)
    _add(session, "theirs note", SOMEONE_ELSE, None, 5)
    _add(session, "theirs on deleted", SOMEONE_ELSE, datasets["deleted"], 6)
    _add(session, "mine on deleted", ME, datasets["deleted"], 7)

    widgets, count = SavedWidgetDAO.find_readable(
        ME, see_all=False, page=0, page_size=50
    )

    assert _titles(widgets) == [
        "mine on secret",
        "mine note",
        "theirs on readable",
        "mine on deleted",
    ]
    assert count == 4

    everything, total = SavedWidgetDAO.find_readable(
        ME, see_all=True, page=0, page_size=50
    )
    assert total == len(everything) == 7

    assert SavedWidgetDAO.find_readable(None, see_all=False, page=0, page_size=50) == (
        [],
        0,
    )


def test_list_is_paged_in_the_database(
    session: Session, datasets: dict[str, int]
) -> None:
    for index in range(7):
        _add(session, f"mine {index}", ME, datasets["readable"], index)
    # Rows the caller may not read never shift a page.
    for index in range(5):
        _add(session, f"hidden {index}", SOMEONE_ELSE, datasets["secret"], index)

    pages = [
        SavedWidgetDAO.find_readable(ME, see_all=False, page=page, page_size=3)
        for page in range(4)
    ]

    assert [_titles(widgets) for widgets, _ in pages] == [
        ["mine 0", "mine 1", "mine 2"],
        ["mine 3", "mine 4", "mine 5"],
        ["mine 6"],
        [],
    ]
    assert {count for _, count in pages} == {7}


def _security(mocker: MockerFixture, *, guest: bool, admin: bool) -> MagicMock:
    security = MagicMock()
    security.is_guest_user.return_value = guest
    security.is_admin.return_value = admin
    mocker.patch("superset.commands.widget.saved.security_manager", new=security)
    mocker.patch("superset.commands.widget.saved.get_user_id", return_value=ME)
    return security


def test_list_command_passes_the_caller_and_page(mocker: MockerFixture) -> None:
    find = mocker.patch(
        "superset.commands.widget.saved.SavedWidgetDAO.find_readable",
        return_value=(["w"], 9),
    )

    _security(mocker, guest=False, admin=False)
    command = ListSavedWidgetsCommand(2, 10)
    assert command.run() == ["w"]
    assert command.count == 9
    find.assert_called_once_with(ME, see_all=False, page=2, page_size=10)

    _security(mocker, guest=False, admin=True)
    ListSavedWidgetsCommand().run()
    find.assert_called_with(ME, see_all=True, page=0, page_size=MAX_LIST_PAGE_SIZE)


def test_list_command_refuses_guests_and_bad_pages(mocker: MockerFixture) -> None:
    find = mocker.patch("superset.commands.widget.saved.SavedWidgetDAO.find_readable")

    _security(mocker, guest=True, admin=False)
    with pytest.raises(SavedWidgetForbiddenError):
        ListSavedWidgetsCommand().run()

    _security(mocker, guest=False, admin=False)
    bad_pages: list[tuple[Any, Any]] = [
        (-1, 10),
        (0, 0),
        (0, MAX_LIST_PAGE_SIZE + 1),
        (True, 10),
        (0, "10"),
        (1.0, 10),
        (10**9, 10),
    ]
    for page, page_size in bad_pages:
        with pytest.raises(WidgetInvalidError):
            ListSavedWidgetsCommand(page, page_size).run()
    find.assert_not_called()
