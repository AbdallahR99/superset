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
Server-side data execution for widgets.

A widget's data is always produced by ``Widget.fetch_data`` /
``Widget.fetch_values`` on its registered type, from props the server holds (a
saved widget) or has validated (an inline spec). ``DataBindingWidget`` is the
implementation every built-in query-bound widget shares: the query is rebuilt
from ``props.dataBinding``, client filters are only structured column
comparisons ANDed on, and the ``QueryContext`` carries the ``WidgetContext`` so
``raise_for_access`` can authorize a guest on it.

Who may put SQL into a widget definition
----------------------------------------
The rule is the one Explore applies to an ad-hoc SQL metric or filter of a
classic chart: a signed-in principal who can read the dataset through its own
grants (``raise_for_access(datasource=...)``) may write SQL expressions against
it. The expression runs through the dataset's normal ad-hoc pipeline (the same
sanitizing, ``ALLOW_ADHOC_SUBQUERY`` and template processing), so the builder
is exactly as permissive as ``/api/v1/chart/data`` for the same role. An
embedded guest can never send SQL: an inline definition from a guest must be
buildable from names alone (see ``find_sql_in_props``). SQL stored in a saved
widget is its author's, checked when it was saved, and is served to a guest
unchanged, the way a chart's SQL metric is on an embedded dashboard.

Row level security for guests
-----------------------------
A guest is not the widget's author. The rows a guest reads are narrowed by the
``rls`` rules of its token plus the RLS rules that apply to the guest role
(``GUEST_ROLE_NAME``), never by the author's own role rules. Minting therefore
refuses a ``widget`` or ``dataset`` resource on an RLS-protected dataset unless
the token carries a rule covering it, and refuses one from a minting principal
whose own rows of that dataset are narrowed by RLS (see
``SupersetSecurityManager._raise_for_guest_token_widget_rls``). A deployment
that decides the row scope of its tokens some other way turns the guard off
with ``GUEST_TOKEN_WIDGET_RLS_GUARD = False``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from flask import current_app
from superset_core.widgets import Widget

from superset.commands.chart.data.get_data_command import ChartDataCommand
from superset.common.chart_data import ChartDataResultFormat, ChartDataResultType
from superset.common.query_context_factory import QueryContextFactory
from superset.daos.datasource import DatasourceDAO
from superset.daos.exceptions import DatasourceNotFound
from superset.exceptions import SupersetSecurityException
from superset.utils.core import (
    apply_max_row_limit,
    DatasourceType,
    split_adhoc_filters_into_base_filters,
)

if TYPE_CHECKING:
    from superset.connectors.sqla.models import BaseDatasource

DEFAULT_ROW_LIMIT = 1000

FILTER_OPERATORS = frozenset(
    {"EQUALS", "NOT_EQUALS", "IN", "NOT_IN", "RANGE", "TIME_RANGE"}
)

GUEST_AGGREGATES = frozenset({"AVG", "COUNT", "COUNT_DISTINCT", "MAX", "MIN", "SUM"})

# Comparison operators a SIMPLE authored filter may carry when its author is
# not allowed to write SQL. None of them is rendered from caller-supplied text.
SIMPLE_FILTER_OPERATORS = frozenset(
    {
        "==",
        "!=",
        ">",
        "<",
        ">=",
        "<=",
        "IN",
        "NOT IN",
        "LIKE",
        "NOT LIKE",
        "ILIKE",
        "NOT ILIKE",
        "IS NULL",
        "IS NOT NULL",
        "IS TRUE",
        "IS FALSE",
        "TEMPORAL_RANGE",
    }
)

# Keys that carry SQL text somewhere in the query pipeline. A definition whose
# author may not write SQL must not contain them at any depth of its binding.
SQL_BEARING_KEYS = frozenset(
    {"sqlExpression", "sql", "where", "having", "extras", "expression"}
)

JINJA_MARKERS = ("{{", "{%", "{#")

# A column reference that cannot be anything but a name: the query layer
# compiles a dimension that is not a column of the dataset as raw SQL, so a
# string outside this shape is SQL when the dataset is not at hand to say
# otherwise.
_PLAIN_IDENTIFIER = re.compile(r"[^\W\d]\w*")

# Upper bound on the rows a guest's inline definition may ask for.
GUEST_INLINE_ROW_LIMIT = 10000


class WidgetDataError(ValueError):
    """The props cannot be executed (no binding, missing dataset, ...)."""


class WidgetDatasetMissingError(WidgetDataError):
    """The dataset the props bind does not exist, for example after deletion."""


class WidgetSqlNotAllowedError(WidgetDataError):
    """The props carry SQL or template code their author may not write."""


class FilterValidationError(ValueError):
    """A client-supplied filter is malformed or targets an unknown column."""


@dataclass(frozen=True)
class WidgetContext:
    """
    What a widget data request is served for: the dataset its props read and,
    for a saved widget, its uuid. Built only server-side, never from a request
    payload, so authorization can trust it.
    """

    dataset_id: int | None
    saved_widget_uuid: str | None = None

    @property
    def inline(self) -> bool:
        return self.saved_widget_uuid is None


def widget_queries_data(widget_cls: type[Widget]) -> bool:
    """
    Whether a widget type reads data on the server at all, that is whether it
    implements ``fetch_data`` or ``fetch_values`` itself.
    """
    return any(
        getattr(getattr(widget_cls, name), "__func__", None)
        is not getattr(Widget, name).__func__
        for name in ("fetch_data", "fetch_values")
    )


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def props_dataset_id(props: Any) -> int | None:
    """
    The dataset props read when their widget type is not known:
    ``dataBinding.datasetId`` or ``datasetId``.

    Every check that has the widget type goes through ``widget_dataset_id``
    instead, which asks the type. This guess is only for a definition whose
    type is not registered, and for a type that reads data without declaring
    where its dataset lives.
    """
    if not isinstance(props, dict):
        return None
    binding = props.get("dataBinding")
    if isinstance(binding, dict):
        return _int_or_none(binding.get("datasetId"))
    return _int_or_none(props.get("datasetId"))


def widget_dataset_id(widget_cls: type[Widget] | None, props: Any) -> int | None:
    """
    The dataset a definition of ``widget_cls`` reads.

    The widget type is the authority: a type that declares
    ``bound_dataset_id(props)`` (every built-in that reads data does, with the
    same lookup its ``fetch_data`` / ``fetch_values`` uses) is asked, a type
    that reads no data binds none whatever its props hold, and only an
    unregistered type or one that reads data without declaring its dataset
    falls back to ``props_dataset_id``. Authoring, minting and read checks all
    resolve the dataset here, so they are run against the dataset the widget
    queries.

    :param widget_cls: The registered widget type, when there is one
    :param props: The widget definition
    :returns: The dataset id, or ``None`` when the definition binds none
    """
    if not isinstance(props, dict):
        return None
    if widget_cls is None:
        return props_dataset_id(props)
    resolver = getattr(widget_cls, "bound_dataset_id", None)
    if callable(resolver):
        return _int_or_none(resolver(props))
    if not widget_queries_data(widget_cls):
        return None
    return props_dataset_id(props)


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _simple_filter(column: str, operator: str, comparator: Any) -> dict[str, Any]:
    return {
        "expressionType": "SIMPLE",
        "clause": "WHERE",
        "subject": column,
        "operator": operator,
        "comparator": comparator,
    }


def _to_adhoc(
    column: str, operator: str, value: Any, index: int
) -> list[dict[str, Any]]:
    if operator in ("EQUALS", "NOT_EQUALS"):
        if value is None or not _is_scalar(value):
            raise FilterValidationError(f"filters[{index}]: value must be a scalar")
        return [_simple_filter(column, "==" if operator == "EQUALS" else "!=", value)]

    if operator in ("IN", "NOT_IN"):
        if not isinstance(value, list) or not all(_is_scalar(item) for item in value):
            raise FilterValidationError(
                f"filters[{index}]: value must be a list of scalars"
            )
        if not value:
            return []
        return [_simple_filter(column, "IN" if operator == "IN" else "NOT IN", value)]

    bounds = ("min", "max") if operator == "RANGE" else ("start", "end")
    if (
        not isinstance(value, dict)
        or set(value) - set(bounds)
        or not all(_is_scalar(item) for item in value.values())
    ):
        raise FilterValidationError(
            f"filters[{index}]: value must be an object with {bounds} scalars"
        )
    lower, upper = value.get(bounds[0]), value.get(bounds[1])
    upper_operator = "<=" if operator == "RANGE" else "<"
    filters = []
    if lower is not None:
        filters.append(_simple_filter(column, ">=", lower))
    if upper is not None:
        filters.append(_simple_filter(column, upper_operator, upper))
    return filters


def resolved_filters_to_adhoc(
    filters: Any, allowed_columns: set[str]
) -> list[dict[str, Any]]:
    """
    Convert client-supplied resolved filters (the dashboard bus vocabulary) to
    SIMPLE adhoc filters. Only structured column comparisons are accepted, so a
    client can narrow a widget's rows but never inject SQL or reshape the query.
    """
    if filters is None:
        return []
    if not isinstance(filters, list):
        raise FilterValidationError("filters must be a list")
    adhoc: list[dict[str, Any]] = []
    for index, resolved in enumerate(filters):
        if not isinstance(resolved, dict):
            raise FilterValidationError(f"filters[{index}] must be an object")
        column = resolved.get("column")
        operator = resolved.get("operator")
        if not isinstance(column, str) or column not in allowed_columns:
            raise FilterValidationError(f"filters[{index}]: unknown column {column!r}")
        if not isinstance(operator, str) or operator not in FILTER_OPERATORS:
            raise FilterValidationError(
                f"filters[{index}]: unsupported operator {operator!r}"
            )
        adhoc.extend(_to_adhoc(column, operator, resolved.get("value"), index))
    return adhoc


def build_widget_query(
    props: dict[str, Any],
    extra_adhoc_filters: list[dict[str, Any]],
) -> tuple[int, dict[str, Any], dict[str, Any]]:
    """
    Build ``(dataset_id, query, form_data)`` from a widget's stored
    ``dataBinding``, mirroring the frontend's ``fetchQueryData``. Authored
    filters come only from the stored props; ``extra_adhoc_filters`` are ANDed on.
    """
    binding = props.get("dataBinding")
    dataset_id = (
        _int_or_none(binding.get("datasetId")) if isinstance(binding, dict) else None
    )
    if not isinstance(binding, dict) or dataset_id is None:
        raise WidgetDataError("This widget has no data binding.")

    metrics = [
        metric for metric in binding.get("metrics") or [] if metric not in (None, "")
    ]
    dimensions = [
        dimension
        for dimension in binding.get("dimensions") or []
        if isinstance(dimension, str) and dimension
    ]
    authored_filters = [
        adhoc
        for adhoc in binding.get("filters") or []
        if isinstance(adhoc, dict) and ("clause" in adhoc or "expressionType" in adhoc)
    ]
    row_limit = _int_or_none(binding.get("rowLimit"))
    if row_limit is None or row_limit < 1:
        row_limit = DEFAULT_ROW_LIMIT

    adhoc_filters = [*authored_filters, *extra_adhoc_filters]
    form_data: dict[str, Any] = {
        "datasource": f"{dataset_id}__table",
        "metrics": metrics,
        "groupby": dimensions,
        "adhoc_filters": adhoc_filters,
        "row_limit": row_limit,
        "result_format": "json",
        "result_type": "full",
    }
    base_filters: dict[str, Any] = {"adhoc_filters": adhoc_filters}
    split_adhoc_filters_into_base_filters(base_filters)
    query = {
        "metrics": metrics,
        "columns": dimensions,
        "filters": base_filters["filters"],
        "extras": {"where": base_filters["where"], "having": base_filters["having"]},
        "row_limit": row_limit,
    }
    return dataset_id, query, form_data


def get_table(dataset_id: int) -> BaseDatasource:
    """
    The SQL dataset a widget reads.

    A widget keeps the id of a dataset that has since been deleted; that is
    reported as ``WidgetDatasetMissingError`` so every caller can answer it as
    a missing object instead of failing.
    """
    try:
        return DatasourceDAO.get_datasource(DatasourceType.TABLE, dataset_id)
    except DatasourceNotFound as ex:
        raise WidgetDatasetMissingError(
            "The dataset this widget reads does not exist."
        ) from ex


def _scan_for_sql(value: Any, path: str) -> str | None:
    """Where ``value`` carries SQL-bearing keys or template code, if anywhere."""
    if isinstance(value, str):
        if any(marker in value for marker in JINJA_MARKERS):
            return f"{path} contains template code"
        return None
    if isinstance(value, dict):
        for key, item in value.items():
            if key in SQL_BEARING_KEYS and item not in (None, "", [], {}):
                return f"{path}.{key} carries SQL"
            if found := _scan_for_sql(item, f"{path}.{key}"):
                return found
        return None
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            if found := _scan_for_sql(item, f"{path}[{index}]"):
                return found
    return None


def _sql_in_metric(metric: Any, path: str) -> str | None:
    if isinstance(metric, str):
        return None
    column = metric.get("column") if isinstance(metric, dict) else None
    if (
        not isinstance(metric, dict)
        or metric.get("expressionType") != "SIMPLE"
        or not isinstance(metric.get("aggregate"), str)
        or not isinstance(column, dict)
        or not isinstance(column.get("column_name", column.get("columnName")), str)
    ):
        return f"{path} is not a saved metric name or a SIMPLE aggregate of a column"
    return None


def _sql_in_filter(adhoc: Any, path: str) -> str | None:
    if (
        not isinstance(adhoc, dict)
        or adhoc.get("expressionType") != "SIMPLE"
        or adhoc.get("clause", "WHERE") != "WHERE"
        or not isinstance(adhoc.get("subject"), str)
        or str(adhoc.get("operator", "")).upper() not in SIMPLE_FILTER_OPERATORS
    ):
        return f"{path} is not a SIMPLE comparison on a column"
    return None


def _not_a_column(value: Any, columns: set[str] | None) -> bool:
    """
    Whether ``value`` may reach the query layer as something other than a
    column of the dataset. With the dataset's columns at hand only one of them
    is a name; without them only a plain identifier is taken for one.
    """
    if not isinstance(value, str):
        return True
    if columns is not None:
        return value not in columns
    return _PLAIN_IDENTIFIER.fullmatch(value) is None


def _sql_in_binding(binding: dict[str, Any], columns: set[str] | None) -> str | None:
    for index, metric in enumerate(binding.get("metrics") or []):
        if found := _sql_in_metric(metric, f"dataBinding.metrics[{index}]"):
            return found
    for index, dimension in enumerate(binding.get("dimensions") or []):
        if _not_a_column(dimension, columns):
            return f"dataBinding.dimensions[{index}] is not a column of the dataset"
    for index, adhoc in enumerate(binding.get("filters") or []):
        if found := _sql_in_filter(adhoc, f"dataBinding.filters[{index}]"):
            return found
    return _scan_for_sql(binding, "dataBinding")


def find_sql_in_props(
    props: Any, datasource: BaseDatasource | None = None
) -> str | None:
    """
    Describe the first place a widget definition carries SQL or template code,
    or return ``None`` when it is SQL-free.

    SQL-free means the query can be built from names alone: metrics are saved
    metric names or SIMPLE aggregates of a named column, dimensions are column
    names, authored filters are SIMPLE ``WHERE`` comparisons on a named column
    with a known operator, and nothing in the binding holds a SQL expression,
    an ``extras.where`` / ``having`` clause or a Jinja marker.

    A dimension is the one place a bare string is SQL: the query layer groups
    by a string that is not a column of the dataset as a raw SQL expression.
    So with ``datasource`` given, a dimension (and the ``column`` of a values
    widget) is a name only when the dataset has that column; without it, only
    when it is a plain identifier, which is the most that can be said from the
    text alone. Pass the datasource whenever the answer decides what a
    principal may store or run.

    :param props: The widget definition
    :param datasource: The dataset the definition reads, when it is known
    :returns: A description of the SQL found, or ``None``
    """
    if not isinstance(props, dict):
        return None
    columns = (
        {str(name) for name in datasource.column_names}
        if datasource is not None
        else None
    )
    binding = props.get("dataBinding")
    if isinstance(binding, dict) and (found := _sql_in_binding(binding, columns)):
        return found
    column = props.get("column")
    if column is not None and (
        _not_a_column(column, columns) or _scan_for_sql(column, "column")
    ):
        return "column is not a column of the dataset"
    return None


def user_may_author_widget_sql(datasource: BaseDatasource | None) -> bool:
    """
    Whether the caller may put SQL expressions into a widget definition.

    The same rule Explore applies to an ad-hoc SQL metric of a classic chart:
    whoever can read the dataset through its own grants may write SQL
    expressions against it, so a Gamma user with dataset access is treated
    here exactly as on ``/api/v1/chart/data``. A guest never may, whatever its
    role grants. A definition that binds no dataset has nothing to run SQL
    against and is left to admins.
    """
    # pylint: disable=import-outside-toplevel
    from superset import security_manager

    if security_manager.is_guest_user():
        return False
    if security_manager.is_admin():
        return True
    return datasource is not None and bool(
        security_manager.can_access_datasource(datasource)
    )


def raise_for_widget_sql(props: Any, datasource: BaseDatasource | None) -> None:
    """Reject a SQL-bearing definition from a caller who may not author SQL."""
    if (
        found := find_sql_in_props(props, datasource)
    ) and not user_may_author_widget_sql(datasource):
        raise WidgetSqlNotAllowedError(
            f"This widget definition is not allowed for you: {found}."
        )


def _require_guest_metric(
    metric: Any, saved_metrics: set[str], columns: set[str]
) -> None:
    if isinstance(metric, str):
        if metric not in saved_metrics:
            raise WidgetDataError(f"Unknown metric {metric!r}.")
        return
    column = metric.get("column") if isinstance(metric, dict) else None
    if (
        not isinstance(metric, dict)
        or metric.get("expressionType") != "SIMPLE"
        or metric.get("sqlExpression")
        or str(metric.get("aggregate", "")).upper() not in GUEST_AGGREGATES
        or not isinstance(column, dict)
        or not isinstance(column.get("column_name"), str)
        or column["column_name"] not in columns
    ):
        raise WidgetDataError(
            "Guest metrics must be saved metrics or simple aggregates of a column."
        )


def validate_guest_inline_props(
    props: dict[str, Any], datasource: BaseDatasource
) -> None:
    """
    Restrict an inline spec a guest sends to what the dataset already exposes:
    saved metrics or simple aggregates, groupable dimensions, and SIMPLE
    filters on existing columns. Nothing that carries SQL gets through.
    """
    columns = set(datasource.column_names)
    groupable = {
        column.column_name
        for column in datasource.columns
        if getattr(column, "groupby", True)
    }
    saved_metrics = {str(metric.metric_name) for metric in datasource.metrics}

    binding = props.get("dataBinding")
    if isinstance(binding, dict):
        for metric in binding.get("metrics") or []:
            _require_guest_metric(metric, saved_metrics, columns)
        for dimension in binding.get("dimensions") or []:
            if not isinstance(dimension, str) or dimension not in groupable:
                raise WidgetDataError(f"Unknown dimension {dimension!r}.")
        for adhoc in binding.get("filters") or []:
            if (
                not isinstance(adhoc, dict)
                or adhoc.get("expressionType") != "SIMPLE"
                or adhoc.get("sqlExpression")
                or not isinstance(adhoc.get("subject"), str)
                or adhoc.get("subject") not in columns
            ):
                raise WidgetDataError(
                    "Guest filters must be simple comparisons on dataset columns."
                )
        row_limit = binding.get("rowLimit")
        if row_limit is not None and (
            _int_or_none(row_limit) is None
            or not 1 <= row_limit <= GUEST_INLINE_ROW_LIMIT
        ):
            raise WidgetDataError(
                f"Guest row limits must be between 1 and {GUEST_INLINE_ROW_LIMIT}."
            )

    column = props.get("column")
    if column is not None and (not isinstance(column, str) or column not in columns):
        raise WidgetDataError(f"Unknown column {column!r}.")

    # Membership alone does not rule out an operator the query layer renders
    # from text or a template marker in a comparator; the structural rule does.
    if found := find_sql_in_props(props, datasource):
        raise WidgetSqlNotAllowedError(
            f"Guest widget definitions cannot carry SQL: {found}."
        )


def raise_for_widget_datasource_access(
    context: Any, datasource: BaseDatasource
) -> None:
    """
    Datasource access for a request that has no ``QueryContext`` of its own
    (column values): a guest is authorized by the widget rule, anyone else by
    the datasource's own permissions.
    """
    # pylint: disable=import-outside-toplevel
    from superset import security_manager

    if security_manager.is_guest_user():
        if not isinstance(
            context, WidgetContext
        ) or not security_manager.guest_widget_grants_datasource(context, datasource):
            raise SupersetSecurityException(
                security_manager.get_datasource_access_error_object(datasource)
            )
        security_manager.raise_for_unsupported_guest_rls(datasource)
        security_manager.raise_for_guest_dataset_allowlist(datasource)
    else:
        security_manager.raise_for_access(datasource=datasource)


def fetch_column_values(dataset_id: int, column: str, context: Any) -> list[Any]:
    """Distinct values of one column, the way the datasource values API serves them."""
    datasource = get_table(dataset_id)
    raise_for_widget_datasource_access(context, datasource)
    row_limit = apply_max_row_limit(current_app.config["FILTER_SELECT_ROW_LIMIT"])
    try:
        return datasource.values_for_column(
            column_name=column,
            limit=row_limit,
            denormalize_column=not datasource.normalize_columns,
        )
    except KeyError as ex:
        raise WidgetDataError(f"Column {column} does not exist") from ex


class DataBindingWidget(Widget):
    """``fetch_data`` for any widget whose props carry a ``dataBinding``."""

    @classmethod
    def bound_dataset_id(cls, props: dict[str, Any]) -> int | None:
        """The dataset the binding queries (see ``widget_dataset_id``)."""
        binding = props.get("dataBinding")
        return (
            _int_or_none(binding.get("datasetId"))
            if isinstance(binding, dict)
            else None
        )

    @classmethod
    def fetch_data(
        cls,
        props: dict[str, Any],
        filters: list[dict[str, Any]],
        context: Any,
    ) -> dict[str, Any]:
        dataset_id = cls.bound_dataset_id(props)
        if dataset_id is None:
            raise WidgetDataError("This widget has no data binding.")
        # Authorization keys on the context, so the dataset queried must be the
        # one the context was resolved for.
        if not isinstance(context, WidgetContext) or context.dataset_id != dataset_id:
            raise WidgetDataError("The widget's dataset does not match its context.")
        datasource = get_table(dataset_id)
        extra_filters = resolved_filters_to_adhoc(filters, set(datasource.column_names))
        _, query, form_data = build_widget_query(props, extra_filters)

        query_context = QueryContextFactory().create(
            datasource={"id": dataset_id, "type": DatasourceType.TABLE.value},
            queries=[query],
            form_data=form_data,
            result_type=ChartDataResultType.FULL,
            result_format=ChartDataResultFormat.JSON,
        )
        query_context.widget_context = context
        command = ChartDataCommand(query_context)
        command.validate()
        result = command.run()
        first = result["queries"][0] if result["queries"] else {}
        return {"columns": first.get("colnames") or [], "rows": first.get("data") or []}
