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
"""Exercise the lab's SQLite executor through the Superset SDK query contract."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from importlib import import_module
from pathlib import Path
from types import ModuleType

import pyarrow as pa
import pytest
from superset_core.semantic_layers.errors import (
    SemanticQueryErrorCode,
    SemanticQueryRejectedError,
)
from superset_core.semantic_layers.types import (
    Filter,
    Grains,
    GroupLimit,
    Operator,
    OrderDirection,
    OrFilter,
    PredicateType,
    SemanticQuery,
)
from superset_core.semantic_layers.view import SemanticView

pytest_plugins: list[str] = ["superset_core.semantic_layers.testing"]


@pytest.fixture
def market(
    monkeypatch: pytest.MonkeyPatch, semantic_layer_registration: None
) -> tuple[ModuleType, SemanticView]:
    """Load the extension without initializing a Superset host."""
    source = (
        Path(__file__).resolve().parents[1] / "property_market" / "dist/backend/src"
    )
    monkeypatch.syspath_prepend(str(source))
    model = import_module("nxtbi_property_market.model")
    provider = import_module("nxtbi_property_market")
    return model, provider.PropertyTransactionsView("lab")


def test_approved_metrics_use_their_definitions(
    market: tuple[ModuleType, SemanticView],
) -> None:
    """Keep sales, properties, transaction average, and area weighting distinct."""
    model, view = market
    table = view.get_table(
        SemanticQuery(
            [
                model.METRICS["transaction_count"],
                model.METRICS["average_transaction_price"],
                model.METRICS["weighted_price_per_sqm"],
                model.METRICS["distinct_property_count"],
            ],
            [],
        )
    ).results

    assert table.schema == pa.schema(
        [
            ("transaction_count", pa.int64()),
            ("average_transaction_price", pa.float64()),
            ("weighted_price_per_sqm", pa.float64()),
            ("distinct_property_count", pa.int64()),
        ]
    )
    assert table.to_pylist() == [
        {
            "transaction_count": 6,
            "average_transaction_price": 400_000.0,
            "weighted_price_per_sqm": pytest.approx(2_280_000 / 610),
            "distinct_property_count": 4,
        }
    ]


def test_district_grouping_uses_the_composite_key(
    market: tuple[ModuleType, SemanticView],
) -> None:
    """Keep other-scope properties out of totals and retain missing districts."""
    model, view = market
    count = model.METRICS["transaction_count"]
    average = model.METRICS["average_transaction_price"]
    district = model.DIMENSIONS["district"]
    query = SemanticQuery(
        [count, average], [district], order=[(average, OrderDirection.DESC)]
    )

    assert view.get_table(query).results.to_pylist() == [
        {
            "district": "Downtown",
            "transaction_count": 2,
            "average_transaction_price": 570_000.0,
        },
        {
            "district": "Marina",
            "transaction_count": 2,
            "average_transaction_price": 330_000.0,
        },
        {
            "district": None,
            "transaction_count": 2,
            "average_transaction_price": 300_000.0,
        },
    ]


def test_null_selection_combines_with_date_cutoff(
    market: tuple[ModuleType, SemanticView],
) -> None:
    """Honor both branches of a mixed NULL filter and its outer date constraint."""
    model, view = market
    district = model.DIMENSIONS["district"]
    sale_date = model.DIMENSIONS["sale_date"]
    count = model.METRICS["transaction_count"]
    weighted = model.METRICS["weighted_price_per_sqm"]
    members = OrFilter(
        frozenset(
            {
                Filter(PredicateType.WHERE, district, Operator.IN, ("Marina",)),
                Filter(PredicateType.WHERE, district, Operator.IS_NULL, None),
            }
        )
    )
    query = SemanticQuery([count, weighted], [district], filters={members})

    assert {
        row["district"]: row["transaction_count"]
        for row in view.get_table(query).results.to_pylist()
    } == {"Marina": 2, None: 2}

    cutoff = Filter(
        PredicateType.WHERE, sale_date, Operator.GREATER_THAN_OR_EQUAL, date(2026, 2, 1)
    )
    scoped = replace(query, filters={members, cutoff})
    assert view.get_table(scoped).results.to_pylist() == [
        {"district": None, "transaction_count": 2, "weighted_price_per_sqm": 6000.0},
    ]


@pytest.mark.parametrize(
    ("date_name", "expected"),
    [("sale_date", 0), ("registration_date", 1)],
)
def test_date_roles_have_independent_coverage(
    market: tuple[ModuleType, SemanticView], date_name: str, expected: int
) -> None:
    """The April registration does not turn into an April sale."""
    model, view = market
    field = model.DIMENSIONS[date_name]
    count = model.METRICS["transaction_count"]
    cutoff = Filter(
        PredicateType.WHERE, field, Operator.GREATER_THAN_OR_EQUAL, date(2026, 4, 1)
    )

    table = view.get_table(SemanticQuery([count], [], filters={cutoff})).results
    assert table.to_pylist() == [{"transaction_count": expected}]


@pytest.mark.parametrize(
    ("date_name", "expected"),
    [("sale_date", [1, 2, 2]), ("registration_date", [1, 2, 2, 1])],
)
def test_monthly_grouping_keeps_raw_filter_grain(
    market: tuple[ModuleType, SemanticView], date_name: str, expected: list[int]
) -> None:
    """Group complete months after filtering the selected raw date role."""
    model, view = market
    raw_date = model.DIMENSIONS[date_name]
    month = next(
        member
        for member in view.get_dimensions()
        if member.name == date_name and member.grain == Grains.MONTH
    )
    count = model.METRICS["transaction_count"]
    cutoff = Filter(
        PredicateType.WHERE, raw_date, Operator.GREATER_THAN_OR_EQUAL, date(2026, 1, 6)
    )
    query = SemanticQuery(
        [count], [month], filters={cutoff}, order=[(month, OrderDirection.ASC)]
    )

    table = view.get_table(query).results
    assert table.schema == pa.schema(
        [(date_name, pa.date32()), ("transaction_count", pa.int64())]
    )
    assert table[date_name].to_pylist() == [
        date(2026, index, 1) for index in range(1, len(expected) + 1)
    ]
    assert table["transaction_count"].to_pylist() == expected


def test_value_suggestions_return_the_complete_matching_domain(
    market: tuple[ModuleType, SemanticView],
) -> None:
    """Keep the stable Arrow column name and apply value search."""
    model, view = market
    district = model.DIMENSIONS["district"]
    full_table = view.get_values(district).results
    assert full_table.schema == pa.schema([("district", pa.string())])
    assert set(full_table["district"].to_pylist()) == {"Downtown", "Marina", None}

    search = Filter(PredicateType.WHERE, district, Operator.LIKE, "Mar%")
    filtered = view.get_values(district, {search}).results
    assert filtered.to_pylist() == [{"district": "Marina"}]


def test_order_and_exact_counts_honor_the_requested_window(
    market: tuple[ModuleType, SemanticView],
) -> None:
    """Sort the complete grouping before applying a page limit."""
    model, view = market
    average = model.METRICS["average_transaction_price"]
    district = model.DIMENSIONS["district"]
    query = SemanticQuery([average], [district], order=[(average, OrderDirection.DESC)])

    limited = replace(query, limit=1)
    assert view.get_table(limited).results.to_pylist() == [
        {"district": "Downtown", "average_transaction_price": 570_000.0}
    ]
    assert view.get_row_count(limited).results.to_pylist() == [{"rowcount": 1}]
    assert view.get_row_count(query).results.to_pylist() == [{"rowcount": 3}]


@pytest.mark.parametrize(
    ("operator", "expected"),
    [(Operator.IN, 0), (Operator.NOT_IN, 6)],
)
def test_empty_membership_filters_include_nulls_only_for_not_in(
    market: tuple[ModuleType, SemanticView], operator: Operator, expected: int
) -> None:
    """Apply empty IN and NOT IN before aggregation using SDK predicate semantics."""
    model, view = market
    district = model.DIMENSIONS["district"]
    count = model.METRICS["transaction_count"]
    membership = Filter(PredicateType.WHERE, district, operator, ())
    query = SemanticQuery([count], [], filters={membership})

    assert view.get_table(query).results.to_pylist() == [
        {"transaction_count": expected}
    ]


def test_table_and_count_refuse_unsupported_group_limits(
    market: tuple[ModuleType, SemanticView],
) -> None:
    """Reject unsupported ranking instead of returning a broader query."""
    model, view = market
    district = model.DIMENSIONS["district"]
    average = model.METRICS["average_transaction_price"]
    query = SemanticQuery(
        [average],
        [district],
        group_limit=GroupLimit([district], top=1, metric=average),
    )

    for execute in (view.get_table, view.get_row_count):
        with pytest.raises(SemanticQueryRejectedError) as error:
            execute(query)
        assert error.value.code == SemanticQueryErrorCode.UNSUPPORTED_QUERY


def test_table_and_count_refuse_unsupported_row_offsets(
    market: tuple[ModuleType, SemanticView],
) -> None:
    """Reject paging that the provider does not advertise."""
    model, view = market
    query = SemanticQuery(
        [model.METRICS["transaction_count"]], [model.DIMENSIONS["district"]], offset=1
    )

    for execute in (view.get_table, view.get_row_count):
        with pytest.raises(SemanticQueryRejectedError) as error:
            execute(query)
        assert error.value.code == SemanticQueryErrorCode.UNSUPPORTED_OFFSET
