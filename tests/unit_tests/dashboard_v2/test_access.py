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
"""Object-level read access to a v2 dashboard's document.

A v2 dashboard has no member charts, so the classic "published and no member
charts" fallback of ``raise_for_access`` would admit every authenticated user;
these tests cover the rule that looks at the datasets the document binds."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture
from sqlalchemy.orm.session import Session

from superset import security_manager
from superset.dashboard_v2 import access
from superset.utils import json
from tests.unit_tests.dashboard_v2.conftest import make_document

BASE = "/api/v1/dashboard_v2/"


def _bound_document(*dataset_ids: int) -> dict[str, Any]:
    """A document with one chart per dataset id, plus a markdown block."""
    document = make_document("text")
    for dataset_id in dataset_ids:
        name = f"chart_{dataset_id}"
        document["nodes"][name] = {
            "type": "echarts",
            "props": {"dataBinding": {"datasetId": dataset_id}},
        }
        document["nodes"]["root"]["children"].append(name)
    return document


def _caller(
    mocker: MockerFixture,
    *,
    admin: bool = False,
    editor: bool = False,
    viewer: bool = False,
    guest: bool = False,
    datasets: set[int] | None = None,
) -> None:
    """Describe the caller to the security manager."""
    mocker.patch.object(security_manager, "is_admin", return_value=admin)
    mocker.patch.object(security_manager, "is_editor", return_value=editor)
    mocker.patch.object(security_manager, "is_viewer", return_value=viewer)
    mocker.patch.object(security_manager, "is_guest_user", return_value=guest)
    mocker.patch.object(
        security_manager,
        "can_access_datasource",
        side_effect=lambda dataset: dataset.id in (datasets or set()),
    )


def _existing_datasets(mocker: MockerFixture, *dataset_ids: int) -> None:
    """Make the given dataset ids resolve to rows."""
    rows = [MagicMock(id=dataset_id) for dataset_id in dataset_ids]
    query = mocker.patch.object(access.db.session, "query")
    query.return_value.filter.return_value.all.return_value = rows


def _dashboard(viewers: bool = False) -> MagicMock:
    return MagicMock(viewers=[object()] if viewers else [])


def test_bound_dataset_ids_cover_every_binding_shape() -> None:
    stored = {
        "nodes": {
            "root": {"type": "grid", "children": ["a", "b", "c", "d"]},
            "a": {"type": "echarts", "props": {"dataBinding": {"datasetId": 3}}},
            "b": {"type": "filter.select", "props": {"datasetId": 4}},
            "c": {"type": "markdown", "props": {"content": "x"}},
            "d": {"type": "echarts", "props": {"dataBinding": {"datasetId": True}}},
            "e": {"type": "tabs"},
        }
    }

    assert access.bound_dataset_ids(stored) == {3, 4}
    assert access.bound_dataset_ids({"nodes": None}) == set()


@pytest.mark.parametrize(
    "caller",
    [{"admin": True}, {"editor": True}, {"guest": True}],
)
def test_admins_editors_and_guests_named_by_their_token_read_the_document(
    mocker: MockerFixture, caller: dict[str, bool]
) -> None:
    _caller(mocker, **caller)
    query = mocker.patch.object(access.db.session, "query")

    assert access.can_read_document(_dashboard(), _bound_document(7)) is True
    query.assert_not_called()


def test_a_viewer_reads_the_document_without_dataset_access(
    mocker: MockerFixture,
) -> None:
    _caller(mocker, viewer=True)

    assert access.can_read_document(_dashboard(viewers=True), _bound_document(7))


def test_viewer_status_only_counts_when_the_dashboard_has_viewers(
    mocker: MockerFixture,
) -> None:
    _caller(mocker, viewer=True)
    _existing_datasets(mocker, 7)

    assert not access.can_read_document(_dashboard(), _bound_document(7))


def test_anyone_else_needs_access_to_every_bound_dataset(
    mocker: MockerFixture,
) -> None:
    _existing_datasets(mocker, 7, 8)
    document = _bound_document(7, 8)

    _caller(mocker, datasets={7, 8})
    assert access.can_read_document(_dashboard(), document) is True
    _caller(mocker, datasets={7})
    assert access.can_read_document(_dashboard(), document) is False
    _caller(mocker, datasets=set())
    assert access.can_read_document(_dashboard(), document) is False


def test_a_bound_dataset_that_no_longer_exists_counts_as_inaccessible(
    mocker: MockerFixture,
) -> None:
    _caller(mocker, datasets={7, 8})
    _existing_datasets(mocker, 7)

    assert access.can_read_document(_dashboard(), _bound_document(7, 8)) is False


def test_a_document_without_data_widgets_is_for_editors_and_viewers_only(
    mocker: MockerFixture,
) -> None:
    _caller(mocker, datasets={7})
    query = mocker.patch.object(access.db.session, "query")

    assert access.can_read_document(_dashboard(), make_document()) is False
    query.assert_not_called()


# --------------------------------------------------------------------------
# Through the API, against real dataset rows
# --------------------------------------------------------------------------


def _create_with_dataset(client: Any, session: Session) -> tuple[int, int]:
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.core import Database

    SqlaTable.metadata.create_all(session.get_bind())  # pylint: disable=no-member
    database = Database(database_name="db", sqlalchemy_uri="sqlite://")
    dataset = SqlaTable(table_name="orders", database=database)
    session.add_all([database, dataset])
    session.flush()
    response = client.post(
        BASE,
        json={"dashboard_title": "Sales", "document": _bound_document(dataset.id)},
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()["id"], dataset.id


def test_published_document_is_not_disclosed_without_dataset_access(
    client: Any,
    mocker: MockerFixture,
    dashboard_v2_enabled: None,
    editor: None,
    v2_session: Session,
) -> None:
    """The caller passes ``raise_for_access`` (published, no member charts)
    but is neither admin, editor nor viewer and cannot read the dataset."""
    pk, _ = _create_with_dataset(client, v2_session)
    _caller(mocker, datasets=set())

    response = client.get(f"{BASE}{pk}")

    assert response.status_code == 403
    body = json.dumps(response.get_json())
    assert "document" not in body
    assert "datasetId" not in body


def test_published_document_is_served_with_access_to_its_datasets(
    client: Any,
    mocker: MockerFixture,
    dashboard_v2_enabled: None,
    editor: None,
    v2_session: Session,
) -> None:
    pk, dataset_id = _create_with_dataset(client, v2_session)
    _caller(mocker, datasets={dataset_id})

    response = client.get(f"{BASE}{pk}")

    assert response.status_code == 200
    assert f"chart_{dataset_id}" in response.get_json()["result"]["document"]["nodes"]


def test_document_without_data_widgets_is_403_for_a_plain_user(
    client: Any,
    mocker: MockerFixture,
    dashboard_v2_enabled: None,
    editor: None,
    v2_session: Session,
) -> None:
    response = client.post(
        BASE, json={"dashboard_title": "Notes", "document": make_document()}
    )
    pk = response.get_json()["id"]
    _caller(mocker)

    assert client.get(f"{BASE}{pk}").status_code == 403
