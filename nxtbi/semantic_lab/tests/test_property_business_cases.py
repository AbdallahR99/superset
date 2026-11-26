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

"""Verify grouped business results through the native provider's Arrow path."""

from __future__ import annotations

from datetime import date
from importlib import import_module
from pathlib import Path

import pyarrow as pa
import pytest
from superset_core.semantic_layers.types import (
    Filter,
    Grains,
    Metric,
    Operator,
    OrderDirection,
    PredicateType,
    SemanticQuery,
)
from superset_core.semantic_layers.view import SemanticView

pytest_plugins: list[str] = ["superset_core.semantic_layers.testing"]

_MEASURE_FIELDS = (
    ("transaction_count", pa.int64()),
    ("average_transaction_price", pa.float64()),
    ("weighted_price_per_sqm", pa.float64()),
    ("distinct_property_count", pa.int64()),
)

_MonthlyRow = tuple[date, int, float, float | None, int]


@pytest.fixture
def market_view(
    monkeypatch: pytest.MonkeyPatch, semantic_layer_registration: None
) -> SemanticView:
    """Load the real lab view with the SDK's isolated registration fixture."""
    source = (
        Path(__file__).resolve().parents[1] / "property_market" / "dist/backend/src"
    )
    monkeypatch.syspath_prepend(str(source))
    provider = import_module("nxtbi_property_market")
    return provider.PropertyTransactionsView("lab")


@pytest.fixture
def approved_measures(market_view: SemanticView) -> list[Metric]:
    """Select the four approved measures in the expected Arrow column order."""
    metrics = {metric.name: metric for metric in market_view.get_metrics()}
    return [metrics[name] for name, _ in _MEASURE_FIELDS]


@pytest.mark.parametrize(
    ("date_role", "expected"),
    [
        pytest.param(
            "sale_date",
            [
                (date(2026, 1, 1), 2, 330_000.0, 6000.0, 1),
                (date(2026, 2, 1), 2, 690_000.0, 1_380_000 / 380, 2),
                (date(2026, 3, 1), 2, 180_000.0, 2000.0, 2),
            ],
            id="sale-month",
        ),
        pytest.param(
            "registration_date",
            [
                (date(2026, 1, 1), 1, 300_000.0, 6000.0, 1),
                (date(2026, 2, 1), 2, 630_000.0, 3500.0, 2),
                (date(2026, 3, 1), 2, 300_000.0, 6000.0, 2),
                (date(2026, 4, 1), 1, 240_000.0, 2000.0, 1),
            ],
            id="registration-month",
        ),
    ],
)
def test_ordered_months_use_the_selected_date_role_for_every_measure(
    market_view: SemanticView,
    approved_measures: list[Metric],
    date_role: str,
    expected: list[_MonthlyRow],
) -> None:
    """Keep repeat sales, unusable area, and delayed registrations distinct."""
    month = next(
        dimension
        for dimension in market_view.get_dimensions()
        if dimension.name == date_role and dimension.grain == Grains.MONTH
    )
    query = SemanticQuery(
        approved_measures,
        [month],
        order=[(month, OrderDirection.ASC)],
    )

    table = market_view.get_table(query).results

    assert table.schema == pa.schema([(date_role, pa.date32()), *_MEASURE_FIELDS])
    rows = list(zip(*(column.to_pylist() for column in table.columns), strict=True))
    assert rows == expected


def test_property_types_stay_sparse_when_grouped_by_registration_month(
    market_view: SemanticView, approved_measures: list[Metric]
) -> None:
    """Apply the sale cutoff before grouping by registration month and property type."""
    dimensions = {
        (dimension.name, dimension.grain): dimension
        for dimension in market_view.get_dimensions()
    }
    property_type = dimensions["property_type", None]
    sale_date = dimensions["sale_date", None]
    registration_month = dimensions["registration_date", Grains.MONTH]
    sale_cutoff = Filter(
        PredicateType.WHERE, sale_date, Operator.GREATER_THAN_OR_EQUAL, date(2026, 1, 6)
    )
    query = SemanticQuery(
        approved_measures,
        [property_type, registration_month],
        filters={sale_cutoff},
        order=[
            (registration_month, OrderDirection.ASC),
            (property_type, OrderDirection.ASC),
        ],
    )

    table = market_view.get_table(query).results

    assert table.schema == pa.schema(
        [
            ("property_type", pa.string()),
            ("registration_date", pa.date32()),
            *_MEASURE_FIELDS,
        ]
    )
    rows = list(zip(*(column.to_pylist() for column in table.columns), strict=True))
    assert rows == [
        ("Apartment", date(2026, 2, 1), 1, 360_000.0, 6000.0, 1),
        ("Villa", date(2026, 2, 1), 1, 900_000.0, 3000.0, 1),
        ("Apartment", date(2026, 3, 1), 1, 480_000.0, 6000.0, 1),
        ("Unknown", date(2026, 3, 1), 1, 120_000.0, None, 1),
        ("Villa", date(2026, 4, 1), 1, 240_000.0, 2000.0, 1),
    ]
