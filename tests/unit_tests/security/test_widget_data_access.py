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


def _widget_resource(
    widget_uuid: str, dataset_id: int | None = DATASET_ID
) -> dict[str, Any]:
    """A ``widget`` resource as minting records it: bound to a dataset."""
    return {
        "type": GuestTokenResourceType.WIDGET,
        "id": widget_uuid,
        "dataset_id": dataset_id,
    }


def _dataset_resource(dataset_id: int = DATASET_ID) -> dict[str, Any]:
    """The explicit grant for inline definitions against one dataset."""
    return {"type": GuestTokenResourceType.DATASET, "id": str(dataset_id)}


def _dashboard_resource() -> dict[str, Any]:
    return {"type": GuestTokenResourceType.DASHBOARD, "id": str(uuid.uuid4())}


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
    _as_guest(mocker, _guest([_dataset_resource()]))
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


def test_guest_inline_widget_needs_a_dataset_resource(
    mocker: MockerFixture, app_context: None
) -> None:
    _patch_tables(mocker)
    inline = {"widget": {"type": "echarts", "props": SAFE_PROPS}}

    # A widget resource alone is not an inline grant, even for its own dataset.
    _as_guest(mocker, _guest([_widget_resource(WIDGET_A)]))
    with pytest.raises(SavedWidgetForbiddenError):
        resolve_widget(inline)

    # The grant is for another dataset.
    _as_guest(mocker, _guest([_dataset_resource(OTHER_DATASET_ID)]))
    with pytest.raises(SavedWidgetForbiddenError):
        resolve_widget(inline)

    # A malformed resource grants nothing.
    for bad_id in (DATASET_ID + 0.0, f"0{DATASET_ID}", [DATASET_ID], None):
        _as_guest(
            mocker,
            _guest([{"type": GuestTokenResourceType.DATASET, "id": bad_id}]),
        )
        with pytest.raises(SavedWidgetForbiddenError):
            resolve_widget(inline)

    _as_guest(mocker, _guest([_dataset_resource()]))
    _, props, context = resolve_widget(inline)
    assert props == SAFE_PROPS
    assert context == WidgetContext(DATASET_ID)


@pytest.mark.parametrize("endpoint", ["data", "values"])
@pytest.mark.parametrize(
    "resources",
    [
        pytest.param([], id="no-resources"),
        pytest.param(["dashboard"], id="dashboard-only"),
        pytest.param(["dashboard", "widget"], id="dashboard-and-saved-widget"),
    ],
)
def test_dashboard_token_with_datasets_cannot_run_an_inline_definition(
    mocker: MockerFixture, app_context: None, resources: list[str], endpoint: str
) -> None:
    """
    SECURITY.md row "Embedded guest token" (in-scope bullet "An embedded guest
    token authorizes actions outside the dashboard it was issued for");
    principal: a guest holding an ordinary dashboard-scoped token.

    ``datasets: [17]`` only narrows that token. It must not let the guest
    read arbitrary columns of dataset 17 through an inline widget definition:
    the request is refused with 403 before any query or value lookup runs.
    """
    from superset.commands.widget.data import WidgetValuesCommand

    token_resources = [
        _dashboard_resource() if kind == "dashboard" else _widget_resource(WIDGET_A)
        for kind in resources
    ]
    _as_guest(mocker, _guest(token_resources, datasets=[DATASET_ID]))
    datasource = _datasource()
    _patch_tables(mocker, datasource)
    fetch_data = mocker.patch("superset.widgets.data.DataBindingWidget.fetch_data")

    if endpoint == "data":
        selector = {
            "widget": {
                "type": "ag-grid-table",
                "props": {
                    "dataBinding": {
                        "datasetId": DATASET_ID,
                        "metrics": ["sum__num"],
                        "dimensions": ["state", "gender"],
                        "rowLimit": 10000,
                    }
                },
            }
        }
        command: Any = WidgetDataCommand(selector, [])
    else:
        selector = {
            "widget": {
                "type": "filter.select",
                "props": {"datasetId": DATASET_ID, "column": "state"},
            }
        }
        command = WidgetValuesCommand(selector)

    with pytest.raises(SavedWidgetForbiddenError) as excinfo:
        command.run()
    assert excinfo.value.status == 403
    fetch_data.assert_not_called()
    datasource.values_for_column.assert_not_called()
    # The lower layers agree, so no other entry point turns the claim into a
    # grant either.
    assert not security_manager.guest_widget_grants_dataset(WidgetContext(DATASET_ID))
    with pytest.raises(SupersetSecurityException):
        fetch_column_values(DATASET_ID, "state", WidgetContext(DATASET_ID))


def test_guest_saved_widget_pointed_at_another_dataset_is_denied(
    mocker: MockerFixture, app_context: None
) -> None:
    """
    SECURITY.md row "Embedded guest token"; principal: a guest whose token was
    minted for widget A while it read dataset 17. After the author points the
    widget at dataset 99 the token grants neither its data nor its values.
    """
    from superset.commands.widget.data import WidgetValuesCommand

    _as_guest(mocker, _guest([_widget_resource(WIDGET_A, DATASET_ID)]))
    rebound = _saved_widget(
        WIDGET_A,
        props={"dataBinding": {"datasetId": OTHER_DATASET_ID, "metrics": ["sum__num"]}},
    )
    filter_widget = _saved_widget(
        WIDGET_B, props={"datasetId": OTHER_DATASET_ID, "column": "state"}
    )
    filter_widget.widget_type = "filter.select"
    _patch_saved(mocker, rebound, filter_widget)
    datasource = _datasource(OTHER_DATASET_ID)
    _patch_tables(mocker, datasource)
    # The query context the widget builds, checked by the real access rule.
    query_context = _query_context(None, datasource)
    query_context.raise_for_access.side_effect = lambda: (
        security_manager.raise_for_access(query_context=query_context)
    )
    mocker.patch(
        "superset.widgets.data.QueryContextFactory"
    ).return_value.create.return_value = query_context
    run = mocker.patch(
        "superset.commands.chart.data.get_data_command.ChartDataCommand.run"
    )

    with pytest.raises(SavedWidgetForbiddenError):
        WidgetDataCommand({"id": WIDGET_A}, []).run()
    run.assert_not_called()

    _as_guest(mocker, _guest([_widget_resource(WIDGET_B, DATASET_ID)]))
    with pytest.raises(SavedWidgetForbiddenError):
        WidgetValuesCommand({"id": WIDGET_B}).run()
    datasource.values_for_column.assert_not_called()

    # A token minted after the change is bound to the new dataset.
    _as_guest(mocker, _guest([_widget_resource(WIDGET_B, OTHER_DATASET_ID)]))
    datasource.values_for_column.return_value = ["CA"]
    mocker.patch.object(security_manager, "raise_for_unsupported_guest_rls")
    assert WidgetValuesCommand({"id": WIDGET_B}).run() == ["CA"]


def test_guest_inline_widget_without_a_dataset_is_denied(
    mocker: MockerFixture, app_context: None
) -> None:
    """Default deny: nothing to check the definition against, so no access."""
    _as_guest(mocker, _guest([_dataset_resource()]))

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


@pytest.mark.parametrize(
    "dimension",
    [
        "CASE WHEN ssn LIKE 'a%' THEN 1 ELSE 0 END",
        "(SELECT max(ssn) FROM people)",
        "state || ssn",
        "lower(state)",
        "state, ssn",
        "state -- x",
        "",
        "1",
    ],
)
def test_a_dimension_that_is_not_a_name_is_sql(dimension: str) -> None:
    """
    SECURITY.md row "Embedded guest token" ("a guest can never send SQL
    expressions") and the SQL authoring rule of the Gamma row; principal: any
    caller whose right to author SQL is decided by ``raise_for_widget_sql``.
    The query layer groups by a string that is not a dataset column as raw
    SQL, so such a string is never SQL-free, with or without the dataset.
    """
    props = _binding(dimensions=[dimension])

    assert find_sql_in_props(props) is not None
    assert find_sql_in_props(props, _datasource()) is not None
    assert find_sql_in_props({"datasetId": DATASET_ID, "column": dimension})
    assert find_sql_in_props(
        {"datasetId": DATASET_ID, "column": dimension}, _datasource()
    )


def test_a_dimension_is_a_name_only_when_the_dataset_has_that_column() -> None:
    """
    An identifier the dataset does not list is compiled as SQL all the same
    (a physical column the dataset leaves out, for one), so with the dataset
    at hand its own columns are the only names.
    """
    datasource = _datasource()
    datasource.column_names = ["state", "gender", "num", "order count"]

    assert find_sql_in_props(_binding(dimensions=["ssn"])) is None
    assert find_sql_in_props(_binding(dimensions=["ssn"]), datasource) is not None
    assert find_sql_in_props({"column": "ssn"}, datasource) is not None
    # A real column is a name whatever characters it is spelled with.
    assert find_sql_in_props(_binding(dimensions=["order count"]), datasource) is None
    assert find_sql_in_props(SAFE_PROPS, datasource) is None
    assert find_sql_in_props({"column": "state"}, datasource) is None


def test_inline_expression_dimension_needs_the_callers_dataset_access(
    mocker: MockerFixture, app_context: None
) -> None:
    """
    The inline path decides SQL authoring against the dataset's columns: an
    expression passed off as a dimension is refused for a principal without
    access to the dataset and allowed, as in Explore, for one with it.
    """
    props = _binding(dimensions=["CASE WHEN ssn LIKE 'a%' THEN 1 ELSE 0 END"])
    datasource = _datasource()
    _patch_tables(mocker, datasource)

    _as_user(mocker, datasource_access=False)
    mocker.patch.object(security_manager, "can_access_datasource", return_value=False)
    with pytest.raises(WidgetSqlNotAllowedError, match="dimensions"):
        resolve_widget({"widget": {"type": "echarts", "props": props}})

    mocker.patch.object(security_manager, "can_access_datasource", return_value=True)
    resolve_widget({"widget": {"type": "echarts", "props": props}})

    _as_guest(mocker, _guest([_dataset_resource()]))
    with pytest.raises(WidgetDataError):
        resolve_widget({"widget": {"type": "echarts", "props": props}})


@pytest.mark.parametrize("name", sorted(SQL_BEARING_PROPS))
def test_sql_bearing_inline_definition_is_allowed_for_gamma_with_dataset_access(
    mocker: MockerFixture, app_context: None, name: str
) -> None:
    """
    SECURITY.md row "Gamma" (read data: only granted datasets). Explore lets a
    Gamma user with access to a dataset add an ad-hoc SQL metric or filter to a
    chart on it; the V2 builder applies the same rule, no stricter.
    """
    raise_for_access = _as_user(mocker)
    datasource = _datasource()
    _patch_tables(mocker, datasource)
    props = SQL_BEARING_PROPS[name]

    _, resolved, context = resolve_widget(
        {"widget": {"type": "echarts", "props": props}}
    )

    assert resolved == props
    assert context == WidgetContext(DATASET_ID)
    raise_for_access.assert_called_with(datasource=datasource)


@pytest.mark.parametrize("name", sorted(SQL_BEARING_PROPS))
def test_sql_bearing_inline_definition_is_rejected_without_dataset_access(
    mocker: MockerFixture, app_context: None, name: str
) -> None:
    """Gamma without a grant on the dataset: no SQL against it, as in Explore."""
    _as_user(mocker, datasource_access=False)
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
    _as_guest(mocker, _guest([_dataset_resource()]))
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
    _as_guest(mocker, _guest([_dataset_resource()]))
    mocker.patch.object(security_manager, "can_access", return_value=True)
    mocker.patch.object(security_manager, "is_admin", return_value=True)
    mocker.patch.object(security_manager, "is_editor", return_value=True)

    assert not user_may_author_widget_sql(_datasource())


@pytest.mark.parametrize(
    "grants, allowed",
    [
        ({"admin": True, "datasource_access": False}, True),
        ({"datasource_access": True}, True),
        # SQL Lab or editorship elsewhere is not access to this dataset.
        ({"sql_lab": True, "datasource_access": False}, False),
        ({"datasource_access": False}, False),
    ],
)
def test_sql_authoring_follows_dataset_access(
    mocker: MockerFixture,
    app_context: None,
    grants: dict[str, bool],
    allowed: bool,
) -> None:
    """
    The SQL-authoring rule is dataset access, the rule classic charts use for
    ad-hoc SQL metrics; admins always may.
    """
    _as_user(mocker, **grants)
    _patch_tables(mocker)
    selector = {"widget": {"type": "echarts", "props": SQL_BEARING_PROPS["sql_metric"]}}

    assert user_may_author_widget_sql(_datasource()) is allowed
    if allowed:
        _, props, _ = resolve_widget(selector)
        assert props == SQL_BEARING_PROPS["sql_metric"]
    else:
        with pytest.raises(WidgetSqlNotAllowedError):
            resolve_widget(selector)


def test_guest_inline_definition_is_checked_against_the_dataset(
    mocker: MockerFixture, app_context: None
) -> None:
    _as_guest(mocker, _guest([_dataset_resource()]))
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


def test_gamma_saves_a_sql_bearing_widget_only_on_a_dataset_it_can_read(
    mocker: MockerFixture, app_context: None
) -> None:
    own = _saved_widget(WIDGET_A, created_by_fk=1)
    _patch_saved(mocker, own)
    _patch_tables(mocker)

    _as_user(mocker)
    CreateSavedWidgetCommand(
        {"widget_type": "echarts", "props": SQL_BEARING_PROPS["sql_metric"]}
    ).validate()
    UpdateSavedWidgetCommand(
        WIDGET_A, {"props": SQL_BEARING_PROPS["sql_where_filter"]}
    ).validate()
    CreateSavedWidgetCommand({"widget_type": "echarts", "props": SAFE_PROPS}).validate()

    _as_user(mocker, datasource_access=False)
    with pytest.raises(SavedWidgetForbiddenError):
        CreateSavedWidgetCommand(
            {"widget_type": "echarts", "props": SQL_BEARING_PROPS["sql_metric"]}
        ).validate()
    with pytest.raises(SavedWidgetForbiddenError):
        UpdateSavedWidgetCommand(
            WIDGET_A, {"props": SQL_BEARING_PROPS["sql_where_filter"]}
        ).validate()


def test_guest_cannot_save_a_widget_at_all(
    mocker: MockerFixture, app_context: None
) -> None:
    _as_guest(mocker, _guest([_dataset_resource()]))
    _patch_tables(mocker)

    for props in (SAFE_PROPS, SQL_BEARING_PROPS["sql_metric"]):
        with pytest.raises(SavedWidgetForbiddenError):
            CreateSavedWidgetCommand(
                {"widget_type": "echarts", "props": props}
            ).validate()


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
        {"type": "datasets", "id": DATASET_ID},
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
    # The widget's creator, so that the dataset check is the one that decides.
    _as_user(mocker, user_id=2)
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


@pytest.mark.parametrize(
    "widget_type, props",
    [("markdown", {"content": "private notes"}), ("filter.bar", {})],
)
def test_minting_requires_the_minter_to_be_a_reader_of_the_widget(
    mocker: MockerFixture,
    app_context: None,
    widget_type: str,
    props: dict[str, Any],
) -> None:
    """
    SECURITY.md row "Embedded guest token" ("Every grant is checked against
    the minting principal"); principal: a custom role holding only
    ``can_grant_guest_token``. A widget that binds no dataset is readable by
    its creator and admins only, and a token for it hands a guest that
    definition, so only they may mint one.
    """
    note = _saved_widget(WIDGET_A, props=props, created_by_fk=2)
    note.widget_type = widget_type
    _patch_saved(mocker, note)
    resources: Any = [{"type": GuestTokenResourceType.WIDGET, "id": WIDGET_A}]

    _as_user(mocker, user_id=1)
    with pytest.raises(SavedWidgetGuestTokenDeniedError) as excinfo:
        security_manager.validate_guest_token_resources(resources)
    assert isinstance(excinfo.value, EmbeddedDashboardAccessDeniedError)
    assert "dataset_id" not in resources[0]

    for user_id, admin in ((2, False), (1, True)):
        _as_user(mocker, user_id=user_id, admin=admin)
        granted: Any = [{"type": GuestTokenResourceType.WIDGET, "id": WIDGET_A}]
        security_manager.validate_guest_token_resources(granted)
        assert granted[0]["dataset_id"] is None


def test_minting_a_dataset_bound_widget_applies_the_widget_read_rule(
    mocker: MockerFixture, app_context: None
) -> None:
    """
    The minter of a widget that binds a dataset passes the same read rule as
    any reader: someone who is neither its creator nor an admin must be able
    to read the dataset through ``raise_for_access``.
    """
    _patch_saved(mocker, _saved_widget(WIDGET_A, created_by_fk=2))
    datasource = _datasource()
    mocker.patch(
        "superset.daos.datasource.DatasourceDAO.get_datasource",
        return_value=datasource,
    )
    mocker.patch.object(security_manager, "can_access_datasource", return_value=True)
    resources: Any = [{"type": GuestTokenResourceType.WIDGET, "id": WIDGET_A}]

    raise_for_access = _as_user(mocker, user_id=1, datasource_access=False)
    with pytest.raises(SavedWidgetGuestTokenDeniedError):
        security_manager.validate_guest_token_resources(resources)
    raise_for_access.assert_called_once_with(datasource=datasource)

    _as_user(mocker, user_id=1, datasource_access=True)
    security_manager.validate_guest_token_resources(resources)
    assert resources[0]["dataset_id"] == DATASET_ID


def test_a_guest_cannot_mint_a_widget_resource(
    mocker: MockerFixture, app_context: None
) -> None:
    """A token naming a widget is not an entitlement to grant it onwards."""
    _patch_saved(mocker, _saved_widget(WIDGET_A, props={"content": "x"}))
    _as_guest(mocker, _guest([_widget_resource(WIDGET_A, None)]))

    with pytest.raises(SavedWidgetGuestTokenDeniedError):
        security_manager.validate_guest_token_resources(
            [{"type": GuestTokenResourceType.WIDGET, "id": WIDGET_A}]
        )


def test_minting_a_filter_checks_the_dataset_the_filter_queries(
    mocker: MockerFixture, app_context: None
) -> None:
    """
    A stored filter whose props also carry a ``dataBinding`` for another
    dataset is minted against its own ``datasetId``, the one it queries.
    """
    props = {
        "dataBinding": {"datasetId": OTHER_DATASET_ID},
        "datasetId": DATASET_ID,
        "column": "state",
    }
    widget = _saved_widget(WIDGET_A, props=props)
    widget.widget_type = "filter.select"
    _patch_saved(mocker, widget)
    _as_user(mocker, admin=True)
    get_datasource = mocker.patch(
        "superset.daos.datasource.DatasourceDAO.get_datasource",
        return_value=_datasource(),
    )
    mocker.patch.object(security_manager, "can_access_datasource", return_value=True)
    resources: Any = [{"type": GuestTokenResourceType.WIDGET, "id": WIDGET_A}]

    security_manager.validate_guest_token_resources(resources)

    assert resources[0]["dataset_id"] == DATASET_ID
    assert get_datasource.call_args.args[1] == DATASET_ID


def test_minting_still_checks_dashboards_listed_next_to_widgets(
    mocker: MockerFixture, app_context: None
) -> None:
    """
    The minter's dashboard entitlement check runs for every dashboard
    resource, whatever other resource types the token lists.
    """
    note = _saved_widget(WIDGET_A, props={"content": "x"})
    note.widget_type = "markdown"
    _patch_saved(mocker, note)
    _as_user(mocker, user_id=2)
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


def test_minting_a_dataset_resource_requires_the_minters_dataset_access(
    mocker: MockerFixture, app_context: None
) -> None:
    """
    SECURITY.md row "Embedded guest token"; principal: a custom role holding
    only ``can_grant_guest_token``. The inline grant is validated with
    ``can_access_datasource`` for the minting user.
    """
    from superset.daos.exceptions import DatasourceNotFound

    datasource = _datasource()
    get_datasource = mocker.patch(
        "superset.daos.datasource.DatasourceDAO.get_datasource",
        return_value=datasource,
    )
    can_access = mocker.patch.object(
        security_manager, "can_access_datasource", return_value=False
    )
    resources: Any = [{"type": "dataset", "id": str(DATASET_ID)}]

    with pytest.raises(SavedWidgetGuestTokenDeniedError):
        security_manager.validate_guest_token_resources(resources)
    can_access.assert_called_once_with(datasource)

    can_access.return_value = True
    security_manager.validate_guest_token_resources(resources)
    assert resources == [{"type": "dataset", "id": str(DATASET_ID)}]

    get_datasource.side_effect = DatasourceNotFound()
    with pytest.raises(ValidationError):
        security_manager.validate_guest_token_resources(resources)

    for bad_id in ("0", "-1", "1.5", "seven", "", "017", None):
        with pytest.raises(ValidationError):
            security_manager.validate_guest_token_resources(
                [{"type": "dataset", "id": bad_id}]  # type: ignore[list-item]
            )


def test_minting_does_not_treat_the_datasets_claim_as_a_grant(
    mocker: MockerFixture, app_context: None
) -> None:
    """
    The claim stays what it was before widgets existed: an allowlist. Minting
    neither checks it as a grant nor turns it into one, with the widget APIs
    on or off, and the token it produces cannot run an inline definition.
    """
    get_datasource = mocker.patch(
        "superset.daos.datasource.DatasourceDAO.get_datasource"
    )
    mocker.patch.object(security_manager, "can_access_datasource", return_value=False)

    for enabled in (False, True):
        mocker.patch("superset.is_feature_enabled", return_value=enabled)
        resources: Any = []
        security_manager.validate_guest_token_resources(
            resources, datasets=[DATASET_ID]
        )
        assert resources == []
    get_datasource.assert_not_called()

    _as_guest(mocker, _guest([], datasets=[DATASET_ID]))
    assert not security_manager.guest_widget_grants_dataset(WidgetContext(DATASET_ID))


def test_guest_token_schema_drops_a_client_sent_widget_binding() -> None:
    """Only the server records the dataset a widget resource is bound to."""
    from superset.security.api import guest_token_create_schema

    body = guest_token_create_schema.load(
        {
            "user": {"username": "guest"},
            "resources": [
                {"type": "widget", "id": WIDGET_A, "dataset_id": OTHER_DATASET_ID},
                {"type": "dataset", "id": str(DATASET_ID)},
            ],
            "rls": [],
        }
    )

    assert body["resources"] == [
        {"type": "widget", "id": WIDGET_A},
        {"type": "dataset", "id": str(DATASET_ID)},
    ]
    with pytest.raises(ValidationError):
        guest_token_create_schema.load(
            {"resources": [{"type": "datasets", "id": "1"}], "rls": []}
        )


# --------------------------------------------------------------------------
# Minting: row level security for widget and dataset grants
# --------------------------------------------------------------------------


def _mint(
    mocker: MockerFixture,
    resources: list[dict[str, Any]],
    rls: list[dict[str, Any]],
    *,
    protected: bool,
    hook: Any = None,
    guard: bool | None = None,
    admin: bool = True,
    minter_rules: dict[int, list[Any]] | None = None,
    underlying: list[MagicMock] | Exception | None = None,
) -> dict[str, Any]:
    """
    Mint a token for already-validated resources and decode its claims.

    :param protected: Whether the dataset carries RLS rules at all
    :param hook: The deployment's ``GUEST_TOKEN_VALIDATOR_HOOK``
    :param guard: ``GUEST_TOKEN_WIDGET_RLS_GUARD``, left unset when ``None``
    :param admin: Whether the minting principal is an admin
    :param minter_rules: The RLS rules that apply to the minter, by dataset id
    :param underlying: The datasets a virtual dataset reads, or the failure
        to work them out
    """
    datasource = _datasource()
    datasource.row_level_security_filters = [MagicMock()] if protected else []
    mocker.patch(
        "superset.daos.datasource.DatasourceDAO.get_datasource",
        return_value=datasource,
    )
    from flask import current_app

    config: dict[str, Any] = {"GUEST_TOKEN_VALIDATOR_HOOK": hook}
    if guard is not None:
        config["GUEST_TOKEN_WIDGET_RLS_GUARD"] = guard
    mocker.patch.dict(current_app.config, config)
    mocker.patch.object(security_manager, "is_admin", return_value=admin)
    mocker.patch.object(
        security_manager,
        "get_rls_filters",
        side_effect=lambda table: (minter_rules or {}).get(table.id, []),
    )
    mocker.patch.object(
        security_manager,
        "_guest_token_underlying_datasets",
        side_effect=underlying if isinstance(underlying, Exception) else None,
        return_value=[] if isinstance(underlying, Exception) else underlying or [],
    )
    token = security_manager.create_guest_access_token(
        {"username": "guest"},
        resources,  # type: ignore[arg-type]
        rls,  # type: ignore[arg-type]
    )
    return security_manager.parse_jwt_guest_token(token)


@pytest.mark.parametrize(
    "resource",
    [
        {"type": "widget", "id": WIDGET_A, "dataset_id": DATASET_ID},
        {"type": "dataset", "id": str(DATASET_ID)},
    ],
)
def test_minting_requires_an_rls_rule_for_an_rls_protected_dataset(
    mocker: MockerFixture, app_context: None, resource: dict[str, Any]
) -> None:
    """
    SECURITY.md row "Embedded guest token" and in-scope bullet
    "row-level-security rule bypass"; principal: a guest of a widget whose
    author is limited by role RLS. A guest is filtered by the token's rules
    and the guest role's rules only, so a token without a covering rule would
    show more than the author sees and is refused.
    """
    with pytest.raises(ValidationError, match="row level security"):
        _mint(mocker, [resource], [], protected=True)
    # A rule for another dataset covers nothing.
    with pytest.raises(ValidationError, match="row level security"):
        _mint(
            mocker,
            [resource],
            [{"dataset": OTHER_DATASET_ID, "clause": "1 = 1"}],
            protected=True,
        )

    scoped = _mint(
        mocker,
        [resource],
        [{"dataset": DATASET_ID, "clause": "org = 'a'"}],
        protected=True,
    )
    assert scoped["rls_rules"] == [{"dataset": DATASET_ID, "clause": "org = 'a'"}]
    assert scoped["resources"] == [resource]
    _mint(mocker, [resource], [{"clause": "org = 'a'"}], protected=True)

    # No RLS on the dataset: nothing to preserve.
    _mint(mocker, [resource], [], protected=False)
    # A rule with no clause filters nothing and covers nothing.
    for empty in ({"clause": ""}, {"dataset": DATASET_ID, "clause": "  "}):
        with pytest.raises(ValidationError, match="row level security"):
            _mint(mocker, [resource], [empty], protected=True)


RLS_RESOURCES = [
    {"type": "widget", "id": WIDGET_A, "dataset_id": DATASET_ID},
    {"type": "dataset", "id": str(DATASET_ID)},
]


@pytest.mark.parametrize("resource", RLS_RESOURCES)
def test_a_validator_hook_does_not_switch_the_rls_guard_off(
    mocker: MockerFixture, app_context: None, resource: dict[str, Any]
) -> None:
    """
    SECURITY.md row "Embedded guest token"; principal: a custom role holding
    ``can_grant_guest_token`` in a deployment whose
    ``GUEST_TOKEN_VALIDATOR_HOOK`` was written for dashboard tokens. The hook
    being installed says nothing about widget and dataset resources, so the
    guard stays on until the deployment turns it off by name.
    """

    def hook(body: dict[str, Any]) -> bool:
        return True

    with pytest.raises(ValidationError, match="row level security"):
        _mint(mocker, [resource], [], protected=True, hook=hook)
    with pytest.raises(ValidationError, match="row level security"):
        _mint(mocker, [resource], [], protected=True, hook=hook, guard=True)

    _mint(mocker, [resource], [], protected=True, hook=hook, guard=False)
    _mint(mocker, [resource], [], protected=True, guard=False)


@pytest.mark.parametrize("resource", RLS_RESOURCES)
def test_a_minter_restricted_by_rls_cannot_choose_a_guests_row_scope(
    mocker: MockerFixture, app_context: None, resource: dict[str, Any]
) -> None:
    """
    SECURITY.md row "Embedded guest token" and in-scope bullet
    "row-level-security rule bypass"; principal: a custom role holding
    ``can_grant_guest_token`` and access to the dataset under a role RLS
    rule. The token's rules are the minter's own words, so a vacuous one
    (``1 = 1``) would hand a guest the rows the minter's role cannot see.
    """
    restricted = {DATASET_ID: [MagicMock(clause="tenant = 'acme'")]}
    for rls in (
        [{"dataset": DATASET_ID, "clause": "1 = 1"}],
        [{"clause": "1 = 1"}],
        [{"dataset": DATASET_ID, "clause": "tenant = 'acme'"}],
    ):
        with pytest.raises(ValidationError, match="restricted for you"):
            _mint(
                mocker,
                [resource],
                rls,
                protected=True,
                admin=False,
                minter_rules=restricted,
            )

    # An admin reads every row and so may choose any scope, as may a
    # principal no rule applies to.
    rule = [{"dataset": DATASET_ID, "clause": "1 = 1"}]
    _mint(mocker, [resource], rule, protected=True, minter_rules=restricted)
    _mint(mocker, [resource], rule, protected=True, admin=False)
    # The deployment that decides row scope itself opts out of both rules.
    _mint(
        mocker,
        [resource],
        [],
        protected=True,
        admin=False,
        minter_rules=restricted,
        guard=False,
    )


@pytest.mark.parametrize("resource", RLS_RESOURCES)
def test_rls_on_the_tables_a_virtual_dataset_reads_counts(
    mocker: MockerFixture, app_context: None, resource: dict[str, Any]
) -> None:
    """
    SECURITY.md in-scope bullet "row-level-security rule bypass"; principal:
    a custom ``can_grant_guest_token`` role granting a virtual dataset whose
    own row carries no rule while the physical table it selects from does.
    """
    physical = _datasource(OTHER_DATASET_ID)
    physical.row_level_security_filters = [MagicMock()]

    with pytest.raises(ValidationError, match=f"Dataset {OTHER_DATASET_ID} is prot"):
        _mint(mocker, [resource], [], protected=False, underlying=[physical])
    # A rule on an unrelated dataset covers neither.
    with pytest.raises(ValidationError, match="row level security"):
        _mint(
            mocker,
            [resource],
            [{"dataset": 5, "clause": "org = 'a'"}],
            protected=False,
            underlying=[physical],
        )
    for covering in (
        {"clause": "org = 'a'"},
        {"dataset": OTHER_DATASET_ID, "clause": "org = 'a'"},
        {"dataset": DATASET_ID, "clause": "org = 'a'"},
    ):
        _mint(mocker, [resource], [covering], protected=False, underlying=[physical])

    # The minter's own restriction on the physical table counts as well.
    with pytest.raises(ValidationError, match="restricted for you"):
        _mint(
            mocker,
            [resource],
            [{"clause": "1 = 1"}],
            protected=False,
            underlying=[physical],
            admin=False,
            minter_rules={OTHER_DATASET_ID: [MagicMock()]},
        )


@pytest.mark.parametrize("resource", RLS_RESOURCES)
def test_a_virtual_dataset_whose_tables_are_unknown_is_treated_as_protected(
    mocker: MockerFixture, app_context: None, resource: dict[str, Any]
) -> None:
    unparsable = ValueError("cannot parse")

    with pytest.raises(ValidationError, match="could not be determined"):
        _mint(mocker, [resource], [], protected=False, underlying=unparsable)
    with pytest.raises(ValidationError, match="could not be determined"):
        _mint(
            mocker,
            [resource],
            [{"clause": "org = 'a'"}],
            protected=False,
            underlying=unparsable,
            admin=False,
        )
    # An admin's rule for every dataset needs nothing known about the tables.
    _mint(
        mocker,
        [resource],
        [{"clause": "org = 'a'"}],
        protected=False,
        underlying=unparsable,
    )


def test_the_datasets_behind_a_virtual_dataset_are_resolved_from_its_sql(
    session: Session,
) -> None:
    """
    The lookup the mint guard relies on: the registered datasets a virtual
    dataset selects from, without the virtual dataset itself, and nothing for
    a physical one.
    """
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.core import Database

    SqlaTable.metadata.create_all(session.get_bind())
    database = Database(database_name="virtual_rls_db", sqlalchemy_uri="sqlite://")
    orders = SqlaTable(table_name="orders", database=database)
    people = SqlaTable(table_name="people", database=database)
    unrelated = SqlaTable(table_name="unrelated", database=database)
    virtual = SqlaTable(
        table_name="order_people",
        database=database,
        sql="SELECT o.id, p.name FROM orders o JOIN people p ON p.id = o.person_id",
    )
    session.add_all([orders, people, unrelated, virtual])
    session.flush()

    found = security_manager._guest_token_underlying_datasets(virtual)

    assert {dataset.id for dataset in found} == {orders.id, people.id}
    assert security_manager._guest_token_underlying_datasets(orders) == []


def test_minting_a_dashboard_token_is_not_subject_to_the_widget_rls_rule(
    mocker: MockerFixture, app_context: None
) -> None:
    from superset.daos.datasource import DatasourceDAO

    claims = _mint(mocker, [_dashboard_resource()], [], protected=True)

    assert "datasets" not in claims
    # Dashboard resources never reach the widget rule's dataset lookup.
    DatasourceDAO.get_datasource.assert_not_called()  # type: ignore[attr-defined]


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
    _as_guest(mocker, _guest([_dataset_resource()]))
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
