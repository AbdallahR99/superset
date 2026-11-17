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
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest
from marshmallow import ValidationError
from pytest_mock import MockerFixture

from superset.exceptions import SupersetSecurityException
from superset.extensions import appbuilder
from superset.security.guest_token import (
    GuestToken,
    GuestTokenResourceType,
    GuestUser,
)
from superset.security.manager import (
    query_context_modified,
    SupersetSecurityManager,
    widget_context_grants_data_access,
)
from superset.widgets.data import WidgetContext

DATASET_ID = 17
WIDGET_UUID = str(uuid.uuid4())


def _guest(
    resources: list[dict[str, Any]], datasets: list[int] | None = None
) -> GuestUser:
    token: GuestToken = {
        "user": {},
        "resources": resources,  # type: ignore[typeddict-item]
        "rls_rules": [],
        "iat": 0,
        "exp": 9999999999,
    }
    if datasets is not None:
        token["datasets"] = datasets
    return GuestUser(token=token, roles=[])


def _widget_resource(
    widget_uuid: str = WIDGET_UUID, dataset_id: int | None = DATASET_ID
) -> dict[str, Any]:
    """A ``widget`` resource as minting records it: bound to a dataset."""
    return {
        "type": GuestTokenResourceType.WIDGET,
        "id": widget_uuid,
        "dataset_id": dataset_id,
    }


def _dataset_resource(dataset_id: int | str = DATASET_ID) -> dict[str, Any]:
    """The explicit grant for inline definitions against one dataset."""
    return {"type": GuestTokenResourceType.DATASET, "id": str(dataset_id)}


def _saved(dataset_id: int = DATASET_ID) -> WidgetContext:
    return WidgetContext(dataset_id, WIDGET_UUID)


def _inline(dataset_id: int = DATASET_ID) -> WidgetContext:
    return WidgetContext(dataset_id)


def _datasource(dataset_id: int = DATASET_ID) -> MagicMock:
    datasource = MagicMock()
    datasource.id = dataset_id
    datasource.type = "table"
    datasource.perm = f"[db].[table](id:{dataset_id})"
    return datasource


def _query_context(
    context: WidgetContext | Any,
    datasource: MagicMock,
    form_data: dict[str, Any] | None = None,
) -> MagicMock:
    query_context = MagicMock()
    query_context.slice_ = None
    query_context.form_data = form_data or {}
    query_context.datasource = datasource
    query_context.widget_context = context
    return query_context


@pytest.fixture
def sm(app_context: None) -> SupersetSecurityManager:
    return SupersetSecurityManager(appbuilder)


def _as_guest(
    mocker: MockerFixture, sm: SupersetSecurityManager, guest: GuestUser
) -> None:
    mocker.patch.object(sm, "is_guest_user", return_value=True)
    mocker.patch.object(sm, "get_current_guest_user_if_guest", return_value=guest)
    mocker.patch.object(sm, "can_access", return_value=False)
    mocker.patch.object(sm, "can_access_schema", return_value=False)
    mocker.patch.object(sm, "is_editor", return_value=False)


def _as_minter(mocker: MockerFixture, sm: SupersetSecurityManager) -> MagicMock:
    """
    A signed-in minting principal entitled to read the saved widget. Returns
    the widget read rule's spy; the rule itself is tested in
    ``tests/unit_tests/security/test_widget_data_access.py``.
    """
    mocker.patch.object(sm, "is_guest_user", return_value=False)
    return mocker.patch("superset.commands.widget.utils.raise_for_widget_read")


def test_widget_context_inline_flag() -> None:
    assert _inline().inline
    assert not _saved().inline


def test_saved_widget_grant_requires_named_resource(
    mocker: MockerFixture, sm: SupersetSecurityManager
) -> None:
    _as_guest(mocker, sm, _guest([_widget_resource(str(uuid.uuid4()))]))
    assert not sm.guest_widget_grants_datasource(_saved(), _datasource())

    _as_guest(mocker, sm, _guest([_widget_resource(WIDGET_UUID.upper())]))
    assert sm.guest_widget_grants_datasource(_saved(), _datasource())


def test_saved_widget_grant_ignores_datasets_claim(
    mocker: MockerFixture, sm: SupersetSecurityManager
) -> None:
    _as_guest(mocker, sm, _guest([], datasets=[DATASET_ID]))
    assert not sm.guest_widget_grants_datasource(_saved(), _datasource())


def test_inline_grant_requires_a_dataset_resource(
    mocker: MockerFixture, sm: SupersetSecurityManager
) -> None:
    _as_guest(mocker, sm, _guest([_widget_resource()]))
    assert not sm.guest_widget_grants_datasource(_inline(), _datasource())

    _as_guest(mocker, sm, _guest([_dataset_resource(99)]))
    assert not sm.guest_widget_grants_datasource(_inline(), _datasource())

    _as_guest(mocker, sm, _guest([_dataset_resource()]))
    assert sm.guest_widget_grants_datasource(_inline(), _datasource())


def test_datasets_claim_is_never_an_inline_grant(
    mocker: MockerFixture, sm: SupersetSecurityManager
) -> None:
    """
    SECURITY.md row "Embedded guest token"; principal: a guest holding an
    ordinary dashboard-scoped token. ``datasets`` is an allowlist that narrows
    the token, so it must not let the guest query the dataset inline.
    """
    dashboard = {"type": GuestTokenResourceType.DASHBOARD, "id": str(uuid.uuid4())}
    for resources in ([], [dashboard], [_widget_resource()]):
        _as_guest(mocker, sm, _guest(resources, datasets=[DATASET_ID]))
        assert not sm.guest_widget_grants_dataset(_inline())
        assert not sm.guest_widget_grants_datasource(_inline(), _datasource())
        with pytest.raises(SupersetSecurityException):
            sm.raise_for_access(query_context=_query_context(_inline(), _datasource()))


@pytest.mark.parametrize(
    "resource_id",
    ["017", " 17", "17 ", "+17", "1e1", "17.0", "", "abc", None, True, 17.0, [17]],
)
def test_dataset_resource_id_must_be_a_plain_integer(
    mocker: MockerFixture, sm: SupersetSecurityManager, resource_id: Any
) -> None:
    resource = {"type": GuestTokenResourceType.DATASET, "id": resource_id}
    _as_guest(mocker, sm, _guest([resource]))
    assert not sm.guest_widget_grants_datasource(_inline(), _datasource())
    assert not sm.guest_widget_grants_datasource(_inline(1), _datasource(1))


def test_dataset_allowlist_still_narrows_an_inline_grant(
    mocker: MockerFixture, sm: SupersetSecurityManager
) -> None:
    _as_guest(mocker, sm, _guest([_dataset_resource()], datasets=[99]))
    assert not sm.guest_widget_grants_dataset(_inline())
    with pytest.raises(SupersetSecurityException):
        sm.raise_for_access(query_context=_query_context(_inline(), _datasource()))

    _as_guest(mocker, sm, _guest([_dataset_resource()], datasets=[DATASET_ID]))
    assert sm.guest_widget_grants_dataset(_inline())
    sm.raise_for_access(query_context=_query_context(_inline(), _datasource()))


def test_grant_requires_matching_dataset(
    mocker: MockerFixture, sm: SupersetSecurityManager
) -> None:
    _as_guest(
        mocker,
        sm,
        _guest([_widget_resource(), _dataset_resource()], datasets=[DATASET_ID, 99]),
    )
    assert not sm.guest_widget_grants_datasource(_saved(), _datasource(99))
    assert not sm.guest_widget_grants_datasource(_inline(), _datasource(99))


def test_widget_grant_is_bound_to_the_dataset_recorded_at_mint(
    mocker: MockerFixture, sm: SupersetSecurityManager
) -> None:
    """
    A widget-scoped token was checked against one dataset. Once the saved
    widget binds another one, the token no longer grants its data.
    """
    _as_guest(mocker, sm, _guest([_widget_resource(dataset_id=DATASET_ID)]))
    assert sm.guest_widget_grants_datasource(_saved(), _datasource())

    rebound = _saved(dataset_id=99)
    assert not sm.guest_widget_grants_dataset(rebound)
    assert not sm.guest_widget_grants_datasource(rebound, _datasource(99))
    with pytest.raises(SupersetSecurityException):
        sm.raise_for_access(query_context=_query_context(rebound, _datasource(99)))
    # The definition stays readable; only the data grant lapses.
    assert sm.guest_token_names_widget(WIDGET_UUID)


@pytest.mark.parametrize(
    "resource",
    [
        {"type": GuestTokenResourceType.WIDGET, "id": WIDGET_UUID},
        {"type": GuestTokenResourceType.WIDGET, "id": WIDGET_UUID, "dataset_id": None},
        {"type": GuestTokenResourceType.WIDGET, "id": WIDGET_UUID, "dataset_id": "17"},
        {"type": GuestTokenResourceType.WIDGET, "id": WIDGET_UUID, "dataset_id": True},
    ],
)
def test_widget_resource_without_a_recorded_dataset_grants_no_data(
    mocker: MockerFixture, sm: SupersetSecurityManager, resource: dict[str, Any]
) -> None:
    _as_guest(mocker, sm, _guest([resource]))
    assert not sm.guest_widget_grants_datasource(_saved(), _datasource())
    assert not sm.guest_widget_grants_datasource(_saved(1), _datasource(1))


def test_grant_is_guest_only(
    mocker: MockerFixture, sm: SupersetSecurityManager
) -> None:
    mocker.patch.object(sm, "is_guest_user", return_value=False)
    assert not sm.guest_widget_grants_datasource(_saved(), _datasource())


def test_server_built_context_is_not_a_modified_payload() -> None:
    assert not query_context_modified(_query_context(_saved(), _datasource()))


def test_raise_for_access_allows_saved_widget_context(
    mocker: MockerFixture, sm: SupersetSecurityManager
) -> None:
    _as_guest(mocker, sm, _guest([_widget_resource()]))
    sm.raise_for_access(query_context=_query_context(_saved(), _datasource()))


def test_raise_for_access_allows_inline_context_with_dataset_resource(
    mocker: MockerFixture, sm: SupersetSecurityManager
) -> None:
    _as_guest(mocker, sm, _guest([_dataset_resource()]))
    sm.raise_for_access(query_context=_query_context(_inline(), _datasource()))


def test_raise_for_access_rejects_inline_without_claim(
    mocker: MockerFixture, sm: SupersetSecurityManager
) -> None:
    _as_guest(mocker, sm, _guest([_widget_resource()]))
    with pytest.raises(SupersetSecurityException):
        sm.raise_for_access(query_context=_query_context(_inline(), _datasource()))


def test_raise_for_access_rejects_forged_form_data(
    mocker: MockerFixture, sm: SupersetSecurityManager
) -> None:
    _as_guest(mocker, sm, _guest([_widget_resource(), _dataset_resource()]))
    forged = _query_context(
        None,
        _datasource(),
        form_data={"widget_context": {"dataset_id": DATASET_ID, "saved": WIDGET_UUID}},
    )
    with pytest.raises(SupersetSecurityException):
        sm.raise_for_access(query_context=forged)


def test_raise_for_access_rejects_duck_typed_marker(
    mocker: MockerFixture, sm: SupersetSecurityManager
) -> None:
    _as_guest(mocker, sm, _guest([_dataset_resource()]))
    fake = MagicMock(dataset_id=DATASET_ID, saved_widget_uuid=None)

    assert not widget_context_grants_data_access(
        sm, _query_context(fake, _datasource()), _datasource()
    )
    with pytest.raises(SupersetSecurityException):
        sm.raise_for_access(query_context=_query_context(fake, _datasource()))


def test_raise_for_access_respects_dataset_allowlist(
    mocker: MockerFixture, sm: SupersetSecurityManager
) -> None:
    _as_guest(mocker, sm, _guest([_widget_resource()], datasets=[99]))
    with pytest.raises(SupersetSecurityException):
        sm.raise_for_access(query_context=_query_context(_saved(), _datasource()))


def test_validate_guest_token_resources_requires_saved_widget(
    mocker: MockerFixture, sm: SupersetSecurityManager
) -> None:
    find_by_uuid = mocker.patch(
        "superset.daos.saved_widget.SavedWidgetDAO.find_by_uuid", return_value=None
    )
    readable = _as_minter(mocker, sm)
    resources: Any = [{"type": "widget", "id": WIDGET_UUID}]
    with pytest.raises(ValidationError):
        sm.validate_guest_token_resources(resources)

    # A widget type that queries no data grants no data: the token records
    # that it is bound to no dataset. The minter must still be a reader of
    # the widget, since the token hands a guest its definition.
    note = MagicMock(widget_type="markdown", props_dict={"content": "# hi"})
    find_by_uuid.return_value = note
    sm.validate_guest_token_resources(resources)
    readable.assert_called_once_with(note)
    assert resources == [{"type": "widget", "id": WIDGET_UUID, "dataset_id": None}]
    sm.validate_guest_token_resources([])


@pytest.mark.parametrize(
    "widget_type, props",
    [
        ("echarts", {"echartsOptions": {}}),
        ("metric-tile", {"dataBinding": {"datasetId": "17", "metrics": ["m"]}}),
        ("filter.select", {"column": "state"}),
        ("extensions.gone.away.chart", {"dataBinding": {"datasetId": 17}}),
    ],
)
def test_minting_rejects_a_data_widget_without_a_dataset(
    mocker: MockerFixture,
    sm: SupersetSecurityManager,
    widget_type: str,
    props: dict[str, Any],
) -> None:
    """
    A widget type that queries data must bind a dataset the minter can be
    checked against; an unknown type cannot be reasoned about at all.
    """
    mocker.patch(
        "superset.daos.saved_widget.SavedWidgetDAO.find_by_uuid",
        return_value=MagicMock(widget_type=widget_type, props_dict=props),
    )
    _as_minter(mocker, sm)
    mocker.patch.object(sm, "can_access_datasource", return_value=True)
    mocker.patch(
        "superset.daos.datasource.DatasourceDAO.get_datasource",
        return_value=_datasource(),
    )
    resources: Any = [{"type": "widget", "id": WIDGET_UUID}]
    if widget_type.startswith("extensions."):
        with pytest.raises(ValidationError, match="unknown widget type"):
            sm.validate_guest_token_resources(resources)
    else:
        with pytest.raises(ValidationError, match="binds no dataset"):
            sm.validate_guest_token_resources(resources)
    assert "dataset_id" not in resources[0]


def test_minting_records_the_widgets_dataset_and_ignores_a_sent_one(
    mocker: MockerFixture, sm: SupersetSecurityManager
) -> None:
    mocker.patch(
        "superset.daos.saved_widget.SavedWidgetDAO.find_by_uuid",
        return_value=MagicMock(
            widget_type="echarts",
            props_dict={"dataBinding": {"datasetId": DATASET_ID, "metrics": ["m"]}},
        ),
    )
    get_datasource = mocker.patch(
        "superset.daos.datasource.DatasourceDAO.get_datasource",
        return_value=_datasource(),
    )
    _as_minter(mocker, sm)
    mocker.patch.object(sm, "can_access_datasource", return_value=True)
    resources: Any = [{"type": "widget", "id": WIDGET_UUID, "dataset_id": 99}]

    sm.validate_guest_token_resources(resources)

    assert resources[0]["dataset_id"] == DATASET_ID
    assert get_datasource.call_args.args[1] == DATASET_ID
