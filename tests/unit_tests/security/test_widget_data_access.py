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
Security properties of the widget data path.

Each test names the principal of the SECURITY.md role and capability matrix it
plays (Embedded guest token, Gamma, sql_lab, Admin) and exercises the real
``SupersetSecurityManager`` and widget commands; only the current user, the
metadata lookups and the permission predicates are substituted.
"""

from __future__ import annotations

import inspect
import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest
from marshmallow import ValidationError
from pytest_mock import MockerFixture
from sqlalchemy.orm.session import Session

from superset import security_manager
from superset.commands.dashboard.embedded.exceptions import (
    EmbeddedDashboardAccessDeniedError,
)
from superset.commands.widget.data import resolve_widget, WidgetDataCommand
from superset.commands.widget.exceptions import (
    SavedWidgetForbiddenError,
    SavedWidgetGuestTokenDeniedError,
    WidgetInvalidError,
    WidgetSqlForbiddenError,
)
from superset.commands.widget.saved import (
    CreateSavedWidgetCommand,
    GetSavedWidgetCommand,
    UpdateSavedWidgetCommand,
)
from superset.exceptions import SupersetSecurityException
from superset.security.guest_token import (
    GuestToken,
    GuestTokenResourceType,
    GuestUser,
)
from superset.widgets.data import (
    DataBindingWidget,
    fetch_column_values,
    find_sql_in_props,
    user_may_author_widget_sql,
    WidgetContext,
    WidgetDataError,
    WidgetSqlNotAllowedError,
)

DATASET_ID = 17
OTHER_DATASET_ID = 99
WIDGET_A = str(uuid.uuid4())
WIDGET_B = str(uuid.uuid4())

SAFE_PROPS: dict[str, Any] = {
    "dataBinding": {
        "datasetId": DATASET_ID,
        "metrics": ["sum__num"],
        "dimensions": ["state"],
    }
}


def _binding(**overrides: Any) -> dict[str, Any]:
    return {
        "dataBinding": {"datasetId": DATASET_ID, "metrics": ["sum__num"], **overrides}
    }


SQL_BEARING_PROPS: dict[str, dict[str, Any]] = {
    "sql_metric": _binding(
        metrics=[{"expressionType": "SQL", "sqlExpression": "SUM(num)"}]
    ),
    "simple_metric_with_sql_expression": _binding(
        metrics=[
            {
                "expressionType": "SIMPLE",
                "aggregate": "SUM",
                "column": {"column_name": "num"},
                "sqlExpression": "(SELECT 1)",
            }
        ]
    ),
    "sql_where_filter": _binding(
        filters=[{"expressionType": "SQL", "clause": "WHERE", "sqlExpression": "1 = 1"}]
    ),
    "sql_having_filter": _binding(
        filters=[
            {"expressionType": "SQL", "clause": "HAVING", "sqlExpression": "1 = 1"}
        ]
    ),
    "adhoc_column_filter_subject": _binding(
        filters=[
            {
                "expressionType": "SIMPLE",
                "clause": "WHERE",
                "subject": {"sqlExpression": "secret || ''", "label": "x"},
                "operator": "==",
                "comparator": "a",
            }
        ]
    ),
    "unknown_filter_operator": _binding(
        filters=[
            {
                "expressionType": "SIMPLE",
                "clause": "WHERE",
                "subject": "state",
                "operator": "LATEST PARTITION",
                "comparator": "a",
            }
        ]
    ),
    "jinja_in_comparator": _binding(
        filters=[
            {
                "expressionType": "SIMPLE",
                "clause": "WHERE",
                "subject": "state",
                "operator": "==",
                "comparator": "{{ current_username() }}",
            }
        ]
    ),
    "jinja_in_metric_label": _binding(
        metrics=[
            {
                "expressionType": "SIMPLE",
                "aggregate": "SUM",
                "column": {"column_name": "num"},
                "label": "{% set x = 1 %}",
            }
        ]
    ),
    "extras_where": _binding(extras={"where": "1 = 1"}),
    "extras_having": _binding(extras={"having": "COUNT(*) > 0"}),
    "raw_where": _binding(where="1 = 1"),
}


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


def _widget_resource(widget_uuid: str) -> dict[str, Any]:
    return {"type": GuestTokenResourceType.WIDGET, "id": widget_uuid}


def _as_guest(mocker: MockerFixture, guest: GuestUser) -> None:
    """Embedded guest token principal: no role grants at all."""
    mocker.patch.object(security_manager, "is_guest_user", return_value=True)
    mocker.patch.object(
        security_manager, "get_current_guest_user_if_guest", return_value=guest
    )
    mocker.patch.object(security_manager, "is_admin", return_value=False)
    mocker.patch.object(security_manager, "can_access", return_value=False)
    mocker.patch.object(security_manager, "can_access_schema", return_value=False)
    mocker.patch.object(security_manager, "is_editor", return_value=False)


def _as_user(
    mocker: MockerFixture,
    *,
    admin: bool = False,
    sql_lab: bool = False,
    editor: bool = False,
    datasource_access: bool = True,
    user_id: int = 1,
) -> MagicMock:
    """
    A signed-in principal. The default is Gamma with a grant on the dataset:
    no SQL Lab, no editorship. Returns the ``raise_for_access`` spy.
    """
    mocker.patch.object(security_manager, "is_guest_user", return_value=False)
    mocker.patch.object(
        security_manager, "get_current_guest_user_if_guest", return_value=None
    )
    mocker.patch.object(security_manager, "is_admin", return_value=admin)
    mocker.patch.object(
        security_manager,
        "can_access",
        side_effect=lambda permission, view: (
            sql_lab and (permission, view) == ("can_execute_sql_query", "SQLLab")
        ),
    )
    mocker.patch.object(security_manager, "is_editor", return_value=editor)
    for module in ("superset.commands.widget.utils",):
        mocker.patch(f"{module}.get_user_id", return_value=user_id)
    return mocker.patch.object(
        security_manager,
        "raise_for_access",
        side_effect=None
        if datasource_access
        else SupersetSecurityException(MagicMock()),
    )


def _datasource(dataset_id: int = DATASET_ID, type_: str = "table") -> MagicMock:
    datasource = MagicMock()
    datasource.id = dataset_id
    datasource.type = type_
    datasource.perm = f"[db].[table](id:{dataset_id})"
    datasource.column_names = ["state", "gender", "num"]
    datasource.columns = [
        MagicMock(column_name="state", groupby=True),
        MagicMock(column_name="gender", groupby=True),
        MagicMock(column_name="num", groupby=False),
    ]
    datasource.metrics = [MagicMock(metric_name="sum__num")]
    return datasource


def _patch_tables(mocker: MockerFixture, datasource: MagicMock | None = None) -> None:
    table = datasource or _datasource()
    for module in (
        "superset.commands.widget.data",
        "superset.commands.widget.utils",
        "superset.widgets.data",
    ):
        mocker.patch(f"{module}.get_table", return_value=table)


def _saved_widget(
    widget_uuid: str,
    props: dict[str, Any] | None = None,
    created_by_fk: int = 2,
) -> MagicMock:
    widget = MagicMock()
    widget.uuid = uuid.UUID(widget_uuid)
    widget.widget_type = "echarts"
    widget.props_dict = SAFE_PROPS if props is None else props
    widget.created_by_fk = created_by_fk
    return widget


def _patch_saved(mocker: MockerFixture, *widgets: MagicMock) -> None:
    by_uuid = {str(widget.uuid): widget for widget in widgets}

    def find(ref: str) -> MagicMock | None:
        return by_uuid.get(str(ref).lower())

    mocker.patch(
        "superset.daos.saved_widget.SavedWidgetDAO.find_by_uuid", side_effect=find
    )


def _query_context(context: Any, datasource: MagicMock) -> MagicMock:
    query_context = MagicMock()
    query_context.slice_ = None
    query_context.form_data = {}
    query_context.datasource = datasource
    query_context.widget_context = context
    return query_context


# --------------------------------------------------------------------------
# Embedded guest token: resource scoping
# --------------------------------------------------------------------------


def test_guest_token_for_widget_a_cannot_load_widget_b(
    mocker: MockerFixture, app_context: None
) -> None:
    _as_guest(mocker, _guest([_widget_resource(WIDGET_A)]))
    _patch_saved(mocker, _saved_widget(WIDGET_A), _saved_widget(WIDGET_B))

    _, _, context = resolve_widget({"id": WIDGET_A})
    assert context == WidgetContext(DATASET_ID, WIDGET_A)

    with pytest.raises(SavedWidgetForbiddenError):
        resolve_widget({"id": WIDGET_B})
    with pytest.raises(SavedWidgetForbiddenError):
        GetSavedWidgetCommand(WIDGET_B).run()
    with pytest.raises(SavedWidgetForbiddenError):
        WidgetDataCommand({"id": WIDGET_B}, []).run()


def test_guest_token_for_widget_a_cannot_query_for_widget_b(
    mocker: MockerFixture, app_context: None
) -> None:
    _as_guest(mocker, _guest([_widget_resource(WIDGET_A)]))

    security_manager.raise_for_access(
        query_context=_query_context(WidgetContext(DATASET_ID, WIDGET_A), _datasource())
    )
    with pytest.raises(SupersetSecurityException):
        security_manager.raise_for_access(
            query_context=_query_context(
                WidgetContext(DATASET_ID, WIDGET_B), _datasource()
            )
        )


def test_widget_token_grants_only_the_widgets_own_dataset(
    mocker: MockerFixture, app_context: None
) -> None:
    """A context resolved for dataset 17 never authorizes a query on dataset 99."""
    _as_guest(mocker, _guest([_widget_resource(WIDGET_A)]))

    with pytest.raises(SupersetSecurityException):
        security_manager.raise_for_access(
            query_context=_query_context(
                WidgetContext(DATASET_ID, WIDGET_A), _datasource(OTHER_DATASET_ID)
            )
        )
    # ... nor a plain datasource check, a dashboard, or an arbitrary dataset.
    with pytest.raises(SupersetSecurityException):
        security_manager.raise_for_access(datasource=_datasource())
    with pytest.raises(SupersetSecurityException):
        security_manager.raise_for_access(
            query_context=_query_context(None, _datasource())
        )


def test_widget_token_does_not_grant_a_dashboard(
    mocker: MockerFixture, app_context: None
) -> None:
    _as_guest(mocker, _guest([_widget_resource(WIDGET_A)]))
    dashboard = MagicMock()
    dashboard.id = WIDGET_A
    dashboard.embedded = [MagicMock(uuid=WIDGET_A)]

    assert not security_manager.has_guest_access(dashboard)


def test_data_binding_widget_refuses_a_context_for_another_dataset(
    mocker: MockerFixture, app_context: None
) -> None:
    """The dataset queried must be the one authorization was resolved for."""
    get_table = mocker.patch("superset.widgets.data.get_table")

    for context in (WidgetContext(OTHER_DATASET_ID, WIDGET_A), None, MagicMock()):
        with pytest.raises(WidgetDataError):
            DataBindingWidget.fetch_data(SAFE_PROPS, [], context)
    get_table.assert_not_called()


# --------------------------------------------------------------------------
# Embedded guest token: the ``datasets`` allowlist
# --------------------------------------------------------------------------


def test_guest_saved_widget_outside_dataset_allowlist_is_denied(
    mocker: MockerFixture, app_context: None
) -> None:
    _as_guest(mocker, _guest([_widget_resource(WIDGET_A)], datasets=[OTHER_DATASET_ID]))
    context = WidgetContext(DATASET_ID, WIDGET_A)

    with pytest.raises(SupersetSecurityException):
        security_manager.raise_for_access(
            query_context=_query_context(context, _datasource())
        )


def test_guest_values_request_outside_dataset_allowlist_is_denied(
    mocker: MockerFixture, app_context: None
) -> None:
    _as_guest(mocker, _guest([_widget_resource(WIDGET_A)], datasets=[OTHER_DATASET_ID]))
    datasource = _datasource()
    _patch_tables(mocker, datasource)

    with pytest.raises(SupersetSecurityException):
        fetch_column_values(DATASET_ID, "state", WidgetContext(DATASET_ID, WIDGET_A))
    datasource.values_for_column.assert_not_called()


def test_guest_values_request_needs_a_server_built_context(
    mocker: MockerFixture, app_context: None
) -> None:
    _as_guest(mocker, _guest([], datasets=[DATASET_ID]))
    datasource = _datasource()
    _patch_tables(mocker, datasource)
    forged = MagicMock(dataset_id=DATASET_ID, saved_widget_uuid=None)

    with pytest.raises(SupersetSecurityException):
        fetch_column_values(DATASET_ID, "state", forged)
    datasource.values_for_column.assert_not_called()


def test_guest_allowlist_never_covers_a_non_table_datasource(
    mocker: MockerFixture, app_context: None
) -> None:
    """The merge kept the datasource-type condition of the allowlist."""
    _as_guest(mocker, _guest([_widget_resource(WIDGET_A)], datasets=[DATASET_ID]))
    semantic_view = _datasource(type_="semantic_view")

    assert not security_manager.guest_widget_grants_datasource(
        WidgetContext(DATASET_ID, WIDGET_A), semantic_view
    )
    with pytest.raises(SupersetSecurityException):
        security_manager.raise_for_guest_dataset_allowlist(semantic_view)


def test_guest_inline_widget_needs_the_dataset_listed(
    mocker: MockerFixture, app_context: None
) -> None:
    _patch_tables(mocker)
    inline = {"widget": {"type": "echarts", "props": SAFE_PROPS}}

    # A widget resource alone is not an inline grant.
    _as_guest(mocker, _guest([_widget_resource(WIDGET_A)]))
    with pytest.raises(SavedWidgetForbiddenError):
        resolve_widget(inline)

    # Another dataset is listed.
    _as_guest(mocker, _guest([], datasets=[OTHER_DATASET_ID]))
    with pytest.raises(SavedWidgetForbiddenError):
        resolve_widget(inline)

    # A malformed claim grants nothing.
    guest = _guest([], datasets=[DATASET_ID])
    guest.guest_token["datasets"] = [str(DATASET_ID), DATASET_ID]  # type: ignore[list-item]
    _as_guest(mocker, guest)
    with pytest.raises(SavedWidgetForbiddenError):
        resolve_widget(inline)

    _as_guest(mocker, _guest([], datasets=[DATASET_ID]))
    _, props, context = resolve_widget(inline)
    assert props == SAFE_PROPS
    assert context == WidgetContext(DATASET_ID)


def test_guest_inline_widget_without_a_dataset_is_denied(
    mocker: MockerFixture, app_context: None
) -> None:
    """Default deny: nothing to check the definition against, so no access."""
    _as_guest(mocker, _guest([], datasets=[DATASET_ID]))

    with pytest.raises(SavedWidgetForbiddenError):
        resolve_widget({"widget": {"type": "markdown", "props": {"content": "hi"}}})


# --------------------------------------------------------------------------
# SQL-bearing inline definitions
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(SQL_BEARING_PROPS))
def test_sql_bearing_definitions_are_detected(name: str) -> None:
    assert find_sql_in_props(SQL_BEARING_PROPS[name]) is not None


def test_sql_free_definitions_are_not_flagged() -> None:
    assert find_sql_in_props(SAFE_PROPS) is None
    assert (
        find_sql_in_props(
            _binding(
                metrics=[
                    "sum__num",
                    {
                        "expressionType": "SIMPLE",
                        "aggregate": "SUM",
                        "column": {"column_name": "num"},
                        "label": "Total",
                    },
                ],
                dimensions=["state"],
                filters=[
                    {
                        "expressionType": "SIMPLE",
                        "clause": "WHERE",
                        "subject": "state",
                        "operator": "IN",
                        "comparator": ["CA", "NY"],
                    }
                ],
                rowLimit=50,
            )
        )
        is None
    )
    assert find_sql_in_props({"datasetId": DATASET_ID, "column": "state"}) is None
    assert find_sql_in_props({"content": "{{ not a query }}"}) is None


@pytest.mark.parametrize("name", sorted(SQL_BEARING_PROPS))
def test_sql_bearing_inline_definition_is_rejected_for_gamma(
    mocker: MockerFixture, app_context: None, name: str
) -> None:
    _as_user(mocker)
    _patch_tables(mocker)
    selector = {"widget": {"type": "echarts", "props": SQL_BEARING_PROPS[name]}}

    with pytest.raises(WidgetSqlNotAllowedError):
        resolve_widget(selector)

    fetch_data = mocker.patch("superset.widgets.data.DataBindingWidget.fetch_data")
    with pytest.raises(WidgetSqlForbiddenError) as excinfo:
        WidgetDataCommand(selector, []).run()
    assert excinfo.value.status == 403
    fetch_data.assert_not_called()


@pytest.mark.parametrize("name", sorted(SQL_BEARING_PROPS))
def test_sql_bearing_inline_definition_is_rejected_for_guests(
    mocker: MockerFixture, app_context: None, name: str
) -> None:
    _as_guest(mocker, _guest([], datasets=[DATASET_ID]))
    _patch_tables(mocker)
    selector = {"widget": {"type": "echarts", "props": SQL_BEARING_PROPS[name]}}

    with pytest.raises(WidgetDataError):
        resolve_widget(selector)

    fetch_data = mocker.patch("superset.widgets.data.DataBindingWidget.fetch_data")
    with pytest.raises((WidgetInvalidError, WidgetSqlForbiddenError)):
        WidgetDataCommand(selector, []).run()
    fetch_data.assert_not_called()


def test_guest_never_authors_sql_whatever_its_roles_grant(
    mocker: MockerFixture, app_context: None
) -> None:
    _as_guest(mocker, _guest([], datasets=[DATASET_ID]))
    mocker.patch.object(security_manager, "can_access", return_value=True)
    mocker.patch.object(security_manager, "is_admin", return_value=True)
    mocker.patch.object(security_manager, "is_editor", return_value=True)

    assert not user_may_author_widget_sql(_datasource())


@pytest.mark.parametrize(
    "grants",
    [{"admin": True}, {"sql_lab": True}, {"editor": True}],
)
def test_sql_bearing_inline_definition_needs_a_sql_capability(
    mocker: MockerFixture, app_context: None, grants: dict[str, bool]
) -> None:
    """
    Admin, the sql_lab role and editors of the dataset already write SQL
    against this data elsewhere, so they may here too.
    """
    _as_user(mocker, **grants)
    _patch_tables(mocker)

    _, props, _ = resolve_widget(
        {"widget": {"type": "echarts", "props": SQL_BEARING_PROPS["sql_metric"]}}
    )
    assert props == SQL_BEARING_PROPS["sql_metric"]


def test_guest_inline_definition_is_checked_against_the_dataset(
    mocker: MockerFixture, app_context: None
) -> None:
    _as_guest(mocker, _guest([], datasets=[DATASET_ID]))
    _patch_tables(mocker)

    for props in (
        _binding(metrics=["not_a_saved_metric"]),
        _binding(dimensions=["num"]),  # not groupable
        _binding(dimensions=["secret"]),
        _binding(rowLimit=10**9),
        _binding(
            filters=[
                {
                    "expressionType": "SIMPLE",
                    "clause": "WHERE",
                    "subject": "secret",
                    "operator": "==",
                    "comparator": 1,
                }
            ]
        ),
    ):
        with pytest.raises(WidgetDataError):
            resolve_widget({"widget": {"type": "echarts", "props": props}})


def test_gamma_cannot_save_a_sql_bearing_widget(
    mocker: MockerFixture, app_context: None
) -> None:
    _as_user(mocker)
    _patch_tables(mocker)

    with pytest.raises(WidgetSqlForbiddenError):
        CreateSavedWidgetCommand(
            {"widget_type": "echarts", "props": SQL_BEARING_PROPS["sql_metric"]}
        ).validate()

    own = _saved_widget(WIDGET_A, created_by_fk=1)
    _patch_saved(mocker, own)
    with pytest.raises(WidgetSqlForbiddenError):
        UpdateSavedWidgetCommand(
            WIDGET_A, {"props": SQL_BEARING_PROPS["sql_where_filter"]}
        ).validate()

    CreateSavedWidgetCommand({"widget_type": "echarts", "props": SAFE_PROPS}).validate()


# --------------------------------------------------------------------------
# Saved widgets: ownership and dataset permission
# --------------------------------------------------------------------------


def test_author_needs_access_to_the_dataset_a_widget_binds(
    mocker: MockerFixture, app_context: None
) -> None:
    raise_for_access = _as_user(mocker, datasource_access=False)
    datasource = _datasource()
    _patch_tables(mocker, datasource)

    with pytest.raises(SavedWidgetForbiddenError):
        CreateSavedWidgetCommand(
            {"widget_type": "echarts", "props": SAFE_PROPS}
        ).validate()
    raise_for_access.assert_called_once_with(datasource=datasource)

    own = _saved_widget(WIDGET_A, created_by_fk=1)
    _patch_saved(mocker, own)
    with pytest.raises(SavedWidgetForbiddenError):
        UpdateSavedWidgetCommand(WIDGET_A, {"props": SAFE_PROPS}).validate()


def test_saved_widget_of_another_owner_without_dataset_access_is_denied(
    mocker: MockerFixture, app_context: None
) -> None:
    raise_for_access = _as_user(mocker, datasource_access=False, user_id=1)
    datasource = _datasource()
    _patch_tables(mocker, datasource)
    _patch_saved(mocker, _saved_widget(WIDGET_A, created_by_fk=2))

    with pytest.raises(SavedWidgetForbiddenError):
        GetSavedWidgetCommand(WIDGET_A).run()
    with pytest.raises(SavedWidgetForbiddenError):
        resolve_widget({"id": WIDGET_A})
    with pytest.raises(SavedWidgetForbiddenError):
        WidgetDataCommand({"id": WIDGET_A}, []).run()
    raise_for_access.assert_called_with(datasource=datasource)


def test_saved_widget_of_another_owner_with_dataset_access_is_readable(
    mocker: MockerFixture, app_context: None
) -> None:
    _as_user(mocker, datasource_access=True, user_id=1)
    _patch_tables(mocker)
    widget = _saved_widget(WIDGET_A, created_by_fk=2)
    _patch_saved(mocker, widget)

    assert GetSavedWidgetCommand(WIDGET_A).run() is widget
    # Reading is not owning.
    with pytest.raises(SavedWidgetForbiddenError):
        UpdateSavedWidgetCommand(WIDGET_A, {"title": "mine"}).validate()


def test_saved_widget_is_readable_by_its_owner_and_admin(
    mocker: MockerFixture, app_context: None
) -> None:
    widget = _saved_widget(WIDGET_A, created_by_fk=1)
    _patch_saved(mocker, widget)
    _patch_tables(mocker)

    _as_user(mocker, datasource_access=False, user_id=1)
    assert GetSavedWidgetCommand(WIDGET_A).run() is widget

    _as_user(mocker, admin=True, datasource_access=False, user_id=5)
    assert GetSavedWidgetCommand(WIDGET_A).run() is widget


def test_saved_widget_without_a_dataset_is_private_to_its_owner(
    mocker: MockerFixture, app_context: None
) -> None:
    _as_user(mocker, datasource_access=True, user_id=1)
    _patch_saved(
        mocker, _saved_widget(WIDGET_A, props={"content": "notes"}, created_by_fk=2)
    )

    with pytest.raises(SavedWidgetForbiddenError):
        GetSavedWidgetCommand(WIDGET_A).run()


def test_signed_in_values_request_goes_through_raise_for_access(
    mocker: MockerFixture, app_context: None
) -> None:
    raise_for_access = _as_user(mocker, datasource_access=False)
    datasource = _datasource()
    _patch_tables(mocker, datasource)

    with pytest.raises(SupersetSecurityException):
        fetch_column_values(DATASET_ID, "state", WidgetContext(DATASET_ID))
    raise_for_access.assert_called_once_with(datasource=datasource)
    datasource.values_for_column.assert_not_called()


# --------------------------------------------------------------------------
# Minting: validate_guest_token_resources
# --------------------------------------------------------------------------


def test_minting_rejects_unknown_resource_types(
    mocker: MockerFixture, app_context: None
) -> None:
    for resource in (
        {"type": "chart", "id": "1"},
        {"type": "dataset", "id": DATASET_ID},
        {"id": WIDGET_A},
    ):
        with pytest.raises(ValidationError):
            security_manager.validate_guest_token_resources([resource])  # type: ignore[list-item]


def test_minting_rejects_a_widget_that_does_not_exist(
    mocker: MockerFixture, app_context: None
) -> None:
    _patch_saved(mocker)

    with pytest.raises(ValidationError):
        security_manager.validate_guest_token_resources(
            [{"type": GuestTokenResourceType.WIDGET, "id": WIDGET_A}]
        )
    with pytest.raises(ValidationError):
        security_manager.validate_guest_token_resources(
            [{"type": GuestTokenResourceType.WIDGET, "id": "not-a-uuid"}]
        )


def test_minting_requires_access_to_the_widgets_dataset(
    mocker: MockerFixture, app_context: None
) -> None:
    """
    A principal holding only ``can_grant_guest_token`` must not hand a guest
    the rows of a dataset it cannot read itself.
    """
    _patch_saved(mocker, _saved_widget(WIDGET_A))
    datasource = _datasource()
    mocker.patch(
        "superset.daos.datasource.DatasourceDAO.get_datasource",
        return_value=datasource,
    )
    can_access = mocker.patch.object(
        security_manager, "can_access_datasource", return_value=False
    )
    resources: Any = [{"type": GuestTokenResourceType.WIDGET, "id": WIDGET_A}]

    with pytest.raises(SavedWidgetGuestTokenDeniedError) as excinfo:
        security_manager.validate_guest_token_resources(resources)
    # The guest token endpoint answers this class with 403.
    assert isinstance(excinfo.value, EmbeddedDashboardAccessDeniedError)
    can_access.assert_called_once_with(datasource)

    can_access.return_value = True
    security_manager.validate_guest_token_resources(resources)


def test_minting_still_checks_dashboards_listed_next_to_widgets(
    mocker: MockerFixture, app_context: None
) -> None:
    """
    The minter's dashboard entitlement check runs for every dashboard
    resource, whatever other resource types the token lists.
    """
    _patch_saved(mocker, _saved_widget(WIDGET_A, props={"content": "x"}))
    dashboard = MagicMock()
    dashboard.embedded = [MagicMock()]
    mocker.patch("superset.models.dashboard.Dashboard.get", return_value=dashboard)
    raise_for_access = mocker.patch.object(
        security_manager,
        "raise_for_access",
        side_effect=SupersetSecurityException(MagicMock()),
    )

    with pytest.raises(EmbeddedDashboardAccessDeniedError):
        security_manager.validate_guest_token_resources(
            [
                {"type": GuestTokenResourceType.WIDGET, "id": WIDGET_A},
                {"type": GuestTokenResourceType.DASHBOARD, "id": 5},
            ]
        )
    raise_for_access.assert_called_once_with(dashboard=dashboard)


def test_minting_checks_inline_datasets_while_widget_apis_are_enabled(
    mocker: MockerFixture, app_context: None
) -> None:
    datasource = _datasource()
    get_datasource = mocker.patch(
        "superset.daos.datasource.DatasourceDAO.get_datasource",
        return_value=datasource,
    )
    can_access = mocker.patch.object(
        security_manager, "can_access_datasource", return_value=False
    )
    flag = mocker.patch("superset.is_feature_enabled", return_value=False)

    # Flag off: the claim only narrows dashboard tokens, as before.
    security_manager.validate_guest_token_resources([], datasets=[DATASET_ID])
    get_datasource.assert_not_called()

    flag.side_effect = lambda name: name == "DASHBOARD_V2"
    with pytest.raises(SavedWidgetGuestTokenDeniedError):
        security_manager.validate_guest_token_resources([], datasets=[DATASET_ID])

    can_access.return_value = True
    security_manager.validate_guest_token_resources([], datasets=[DATASET_ID])


# --------------------------------------------------------------------------
# The widget context cannot be forged from a request
# --------------------------------------------------------------------------


def test_widget_context_is_not_part_of_any_request_schema() -> None:
    from superset.charts.schemas import ChartDataQueryContextSchema
    from superset.common.query_context import QueryContext
    from superset.common.query_context_factory import QueryContextFactory

    assert "widget_context" not in ChartDataQueryContextSchema().fields
    assert (
        "widget_context" not in inspect.signature(QueryContextFactory.create).parameters
    )
    assert QueryContext.widget_context is None


@pytest.mark.parametrize(
    "forged",
    [
        {"dataset_id": DATASET_ID, "saved_widget_uuid": None},
        MagicMock(dataset_id=DATASET_ID, saved_widget_uuid=None),
        (DATASET_ID, None),
        True,
    ],
)
def test_forged_widget_context_grants_nothing(
    mocker: MockerFixture, app_context: None, forged: Any
) -> None:
    _as_guest(mocker, _guest([], datasets=[DATASET_ID]))
    datasource = _datasource()

    query_context = _query_context(forged, datasource)
    query_context.form_data = {
        "widget_context": {"dataset_id": DATASET_ID, "saved_widget_uuid": None}
    }
    with pytest.raises(SupersetSecurityException):
        security_manager.raise_for_access(query_context=query_context)


# --------------------------------------------------------------------------
# Row-level security reaches the SQL a widget runs
# --------------------------------------------------------------------------


def test_widget_query_sql_carries_rls_clauses(
    mocker: MockerFixture, session: Session
) -> None:
    """
    A widget query is the dataset's own query, so the role RLS rules of the
    caller and the RLS rules of a guest token end up in the SQL it runs.
    """
    from superset.commands.chart.data.get_data_command import ChartDataCommand
    from superset.connectors.sqla.models import SqlaTable, SqlMetric, TableColumn
    from superset.models.core import Database

    SqlaTable.metadata.create_all(session.get_bind())
    database = Database(database_name="widget_rls_db", sqlalchemy_uri="sqlite://")
    dataset = SqlaTable(
        table_name="births",
        database=database,
        columns=[
            TableColumn(column_name="state", type="VARCHAR", groupby=True),
            TableColumn(column_name="tenant", type="VARCHAR", groupby=True),
            TableColumn(column_name="num", type="INTEGER"),
        ],
        metrics=[SqlMetric(metric_name="sum__num", expression="SUM(num)")],
    )
    session.add(dataset)
    session.flush()

    role_rule = MagicMock(clause="tenant = 'acme'", group_key=None)
    mocker.patch(
        "superset.connectors.sqla.models.security_manager.get_rls_filters",
        return_value=[role_rule],
    )
    mocker.patch(
        "superset.connectors.sqla.models.security_manager.get_guest_rls_filters",
        return_value=[{"clause": "state <> 'ZZ'"}],
    )
    mocker.patch(
        "superset.connectors.sqla.models.is_feature_enabled",
        side_effect=lambda flag: flag == "EMBEDDED_SUPERSET",
    )
    raise_for_access = mocker.patch.object(security_manager, "raise_for_access")

    def run(self: ChartDataCommand, **kwargs: Any) -> dict[str, Any]:
        query_context = self._query_context
        sql = query_context.datasource.get_query_str(query_context.queries[0].to_dict())
        return {"queries": [{"colnames": ["sql"], "data": [{"sql": sql}]}]}

    mocker.patch.object(ChartDataCommand, "run", run)

    props = {
        "dataBinding": {
            "datasetId": dataset.id,
            "metrics": ["sum__num"],
            "dimensions": ["state"],
        }
    }
    context = WidgetContext(dataset.id, WIDGET_A)
    result = DataBindingWidget.fetch_data(
        props, [{"column": "state", "operator": "IN", "value": ["CA"]}], context
    )
    sql = result["rows"][0]["sql"]

    assert "tenant = 'acme'" in sql
    assert "state <> 'ZZ'" in sql
    assert "births" in sql
    assert "'CA'" in sql

    # The query went through the standard access check, carrying the context
    # the server built.
    raise_for_access.assert_called_once()
    checked = raise_for_access.call_args.kwargs["query_context"]
    assert checked.widget_context == context
    assert checked.datasource.id == dataset.id
