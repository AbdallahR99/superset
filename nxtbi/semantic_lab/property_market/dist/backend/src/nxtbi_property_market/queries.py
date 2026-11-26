# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Execute typed semantic queries against a disposable synthetic market fixture."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from contextlib import closing
from datetime import date, datetime, time, timezone

import pyarrow as pa
from superset_core.semantic_layers.errors import (
    SemanticQueryErrorCode,
    SemanticQueryRejectedError,
)
from superset_core.semantic_layers.types import (
    Dimension,
    Filter,
    FilterExpression,
    FilterValues,
    Grains,
    Metric,
    Operator,
    OrderDirection,
    OrFilter,
    PredicateType,
    SemanticQuery,
    SemanticRequest,
    SemanticResult,
)

from .model import (
    DIMENSIONS,
    MARKET_SELECT_SQL,
    METRICS,
    PROPERTY_COLUMNS,
    PROPERTY_ROWS,
    SCHEMA_SQL,
    TIME_DIMENSIONS,
    TRANSACTION_COLUMNS,
    TRANSACTION_ROWS,
)

SqlValue = str | int | float | None
_MEMBERS = {member.id: member for member in (*DIMENSIONS.values(), *TIME_DIMENSIONS)}
_FROM = f"FROM ({MARKET_SELECT_SQL}) AS market"
_COMPARISON = frozenset(
    {
        Operator.EQUALS,
        Operator.NOT_EQUALS,
        Operator.GREATER_THAN,
        Operator.GREATER_THAN_OR_EQUAL,
        Operator.LESS_THAN,
        Operator.LESS_THAN_OR_EQUAL,
    }
)
_PATTERN = frozenset(
    {Operator.LIKE, Operator.NOT_LIKE, Operator.ILIKE, Operator.NOT_ILIKE}
)
_GLOB_TRANSLATION = str.maketrans(
    {"%": "*", "_": "?", "*": "[*]", "?": "[?]", "[": "[[]"}
)


def _dimension_sql(dimension: Dimension) -> str:
    """Resolve a catalog dimension and any declared calendar grain."""
    if _MEMBERS.get(dimension.id) != dimension:
        raise SemanticQueryRejectedError(SemanticQueryErrorCode.INVALID_QUERY)
    name = _MEMBERS[dimension.id].name
    if dimension.grain == Grains.MONTH:
        return f"date({name}, 'start of month')"
    return name


def _metric_sql(metric: Metric) -> str:
    """Return only expressions defined by the approved model."""
    if METRICS.get(metric.id) != metric:
        raise SemanticQueryRejectedError(SemanticQueryErrorCode.INVALID_QUERY)
    return METRICS[metric.id].definition


def _bind_value(dimension: Dimension, value: FilterValues) -> str:
    """Bind an ISO date or a text value without inserting it into SQL."""
    error = SemanticQueryRejectedError(SemanticQueryErrorCode.INVALID_FILTER)
    if not pa.types.is_date(dimension.type):
        if isinstance(value, str):
            return value
        raise error
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            raise error from None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        # Stored facts are dates. A midnight bound is equal to its date;
        # within-day timestamps sort after that date with ISO text comparisons.
        return (
            value.date().isoformat()
            if value.time() == time.min
            else value.isoformat(sep=" ")
        )
    if isinstance(value, date):
        return value.isoformat()
    raise error


def _pattern_sql(
    column: str, operator: Operator, value: FilterValues
) -> tuple[str, tuple[str, ...]]:
    """Render SQL LIKE wildcards with deterministic SQLite GLOB matching."""
    if not isinstance(value, str):
        raise SemanticQueryRejectedError(SemanticQueryErrorCode.INVALID_FILTER)
    if operator in {Operator.ILIKE, Operator.NOT_ILIKE}:
        column = f"casefold({column})"
        value = value.casefold()
    glob_operator = (
        "NOT GLOB" if operator in {Operator.NOT_LIKE, Operator.NOT_ILIKE} else "GLOB"
    )
    return f"{column} {glob_operator} ?", (value.translate(_GLOB_TRANSLATION),)


def _membership_sql(
    column: Dimension, expression: str, leaf: Filter
) -> tuple[str, tuple[str, ...]]:
    """Bind membership values and preserve SQL behavior on an empty list."""
    if not isinstance(leaf.value, (tuple, frozenset)):
        raise SemanticQueryRejectedError(SemanticQueryErrorCode.INVALID_FILTER)
    values = tuple(sorted(_bind_value(column, value) for value in leaf.value))
    if not values:
        return ("0" if leaf.operator == Operator.IN else "1"), ()
    placeholders = ", ".join("?" for _ in values)
    return f"{expression} {leaf.operator.value} ({placeholders})", values


def _leaf_sql(leaf: Filter) -> tuple[str, tuple[str, ...]]:
    """Render one approved WHERE comparison with SQL NULL semantics."""
    column = leaf.column
    if leaf.type != PredicateType.WHERE or not isinstance(column, Dimension):
        raise SemanticQueryRejectedError(SemanticQueryErrorCode.INVALID_FILTER)
    if _MEMBERS.get(column.id) != column:
        raise SemanticQueryRejectedError(SemanticQueryErrorCode.INVALID_FILTER)
    expression = _dimension_sql(column)
    operator = leaf.operator
    if operator in {Operator.IS_NULL, Operator.IS_NOT_NULL}:
        if leaf.value is not None:
            raise SemanticQueryRejectedError(SemanticQueryErrorCode.INVALID_FILTER)
        return f"{expression} {operator.value}", ()
    if operator in {Operator.IN, Operator.NOT_IN}:
        return _membership_sql(column, expression, leaf)
    if not isinstance(leaf.value, (tuple, frozenset)):
        if operator in _PATTERN:
            return _pattern_sql(expression, operator, leaf.value)
        if operator in _COMPARISON:
            return f"{expression} {operator.value} ?", (
                _bind_value(column, leaf.value),
            )
    raise SemanticQueryRejectedError(SemanticQueryErrorCode.INVALID_FILTER)


def _where_sql(
    filters: Iterable[FilterExpression] | None,
) -> tuple[str, tuple[str, ...]]:
    """Apply every filter with stable ordering and preserve grouped OR leaves."""
    clauses: list[tuple[str, tuple[str, ...]]] = []
    for expression in filters or ():
        if isinstance(expression, OrFilter):
            leaves = sorted(_leaf_sql(leaf) for leaf in expression.filters)
            group_sql = " OR ".join(sql for sql, _ in leaves)
            operands = tuple(value for _, values in leaves for value in values)
            clauses.append((f"({group_sql})", operands))
        else:
            clauses.append(_leaf_sql(expression))
    clauses.sort()
    if not clauses:
        return "", ()
    return (
        " WHERE " + " AND ".join(sql for sql, _ in clauses),
        tuple(value for _, values in clauses for value in values),
    )


def _order_sql(query: SemanticQuery) -> str:
    """Apply explicit ordering and break ties by stable grouping keys."""
    dimensions = {dimension.name: dimension for dimension in query.dimensions}
    clauses: list[str] = []
    ordered_names: set[str] = set()
    for member, direction in query.order or ():
        if direction not in (OrderDirection.ASC, OrderDirection.DESC):
            raise SemanticQueryRejectedError(SemanticQueryErrorCode.INVALID_QUERY)
        if isinstance(member, Metric):
            expression = _metric_sql(member)
        elif isinstance(member, Dimension) and dimensions.get(member.name) == member:
            expression = _dimension_sql(member)
        else:
            raise SemanticQueryRejectedError(SemanticQueryErrorCode.UNSUPPORTED_QUERY)
        clauses.append(f"{expression} {direction.value}")
        ordered_names.add(member.name)
    if not clauses:
        # Match the host default when called directly through the provider SDK.
        temporal = next(
            (d for d in dimensions.values() if pa.types.is_date(d.type)), None
        )
        if temporal is not None:
            clauses.append(f"{_dimension_sql(temporal)} ASC")
            ordered_names.add(temporal.name)
    clauses.extend(
        f"{_dimension_sql(dimension)} ASC"
        for name, dimension in dimensions.items()
        if name not in ordered_names
    )
    return " ORDER BY " + ", ".join(clauses) if clauses else ""


def _query_sql(
    query: SemanticQuery, *, include_order: bool
) -> tuple[str, tuple[SqlValue, ...]]:
    """Compile only catalog projections and reject unsupported query shapes."""
    if query.group_limit is not None:
        raise SemanticQueryRejectedError(SemanticQueryErrorCode.UNSUPPORTED_QUERY)
    if query.offset not in (None, 0):
        raise SemanticQueryRejectedError(SemanticQueryErrorCode.UNSUPPORTED_OFFSET)
    limit = query.limit
    if limit is not None and (type(limit) is not int or not 0 <= limit < 2**63):
        raise SemanticQueryRejectedError(SemanticQueryErrorCode.INVALID_QUERY)
    dimensions = [_dimension_sql(dimension) for dimension in query.dimensions]
    metrics = [_metric_sql(metric) for metric in query.metrics]
    members = [*query.dimensions, *query.metrics]
    if not members or len({member.name for member in members}) != len(members):
        raise SemanticQueryRejectedError(SemanticQueryErrorCode.INVALID_QUERY)
    projections = [
        f"{expression} AS {member.name}"
        for expression, member in zip([*dimensions, *metrics], members, strict=True)
    ]
    where, params = _where_sql(query.filters)
    sql = f"SELECT {', '.join(projections)} {_FROM}{where}"
    if dimensions:
        sql += " GROUP BY " + ", ".join(dimensions)
    if include_order:
        sql += _order_sql(query)
    if limit is not None:
        return sql + " LIMIT ?", (*params, limit)
    return sql, params


def _casefold(value: str | None) -> str | None:
    """Preserve SQL NULL when comparing case-insensitive Unicode patterns."""
    return value.casefold() if value is not None else None


def _rows(sql: str, params: Sequence[SqlValue]) -> list[tuple[SqlValue, ...]]:
    """Load the synthetic fixture and query it through a per-call read-only session."""
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.create_function("casefold", 1, _casefold, deterministic=True)
        connection.executescript(SCHEMA_SQL)
        properties = ", ".join("?" for _ in PROPERTY_COLUMNS)
        transactions = ", ".join("?" for _ in TRANSACTION_COLUMNS)
        # Column names come from the fixture schema. Values remain bound parameters.
        property_insert = (
            f"INSERT INTO properties ({', '.join(PROPERTY_COLUMNS)}) "  # noqa: S608
            f"VALUES ({properties})"
        )
        transaction_insert = (
            f"INSERT INTO transactions ({', '.join(TRANSACTION_COLUMNS)}) "  # noqa: S608
            f"VALUES ({transactions})"
        )
        connection.executemany(property_insert, PROPERTY_ROWS)
        connection.executemany(transaction_insert, TRANSACTION_ROWS)
        connection.execute("PRAGMA query_only = ON")
        return connection.execute(sql, params).fetchall()


def _result(
    sql: str,
    params: Sequence[SqlValue],
    fields: Sequence[tuple[str, pa.DataType]],
) -> SemanticResult:
    """Convert SQLite values to the declared Arrow types with stable column names."""
    rows = _rows(sql, params)
    arrays: list[pa.Array] = []
    for index, (_, data_type) in enumerate(fields):
        values = [row[index] for row in rows]
        if pa.types.is_date(data_type):
            arrays.append(
                pa.array(
                    [
                        date.fromisoformat(value) if isinstance(value, str) else value
                        for value in values
                    ],
                    type=data_type,
                )
            )
        else:
            arrays.append(pa.array(values, type=data_type))
    return SemanticResult(
        # Show provider-owned definitions and placeholders, with no bound values.
        requests=[SemanticRequest("sql", sql)],
        results=pa.Table.from_arrays(arrays, schema=pa.schema(fields)),
    )


def get_table(query: SemanticQuery) -> SemanticResult:
    """Return the selected measures and dimensions in their requested order."""
    sql, params = _query_sql(query, include_order=True)
    return _result(
        sql,
        params,
        [(member.name, member.type) for member in (*query.dimensions, *query.metrics)],
    )


def get_values(
    dimension: Dimension, filters: set[Filter] | None = None
) -> SemanticResult:
    """Return the complete set of distinct values under all filters."""
    expression = _dimension_sql(dimension)
    where, params = _where_sql(filters)
    sql = f"SELECT DISTINCT {expression} {_FROM}{where} ORDER BY {expression} ASC"
    return _result(sql, params, [(dimension.name, dimension.type)])


def get_row_count(query: SemanticQuery) -> SemanticResult:
    """Return the exact number of grouped rows in the requested result window."""
    sql, params = _query_sql(query, include_order=False)
    # The subquery contains approved expressions and bound placeholders.
    return _result(
        f"SELECT COUNT(*) FROM ({sql}) AS result_window",  # noqa: S608
        params,
        [("rowcount", pa.int64())],
    )
