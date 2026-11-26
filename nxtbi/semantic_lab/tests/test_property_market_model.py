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

"""Verify the approved property fixture independently of provider execution."""

import sqlite3
from contextlib import closing

import pytest

pytestmark = pytest.mark.usefixtures("semantic_layer_registration")


def test_fixture_preserves_transaction_grain_and_scope() -> None:
    """A reused property ID cannot fan out or attribute a row to another scope."""
    from nxtbi_property_market.model import (
        MARKET_SELECT_SQL,
        PROPERTY_ROWS,
        SCHEMA_SQL,
        TRANSACTION_ROWS,
    )

    with closing(sqlite3.connect(":memory:")) as db:
        db.executescript(SCHEMA_SQL)
        db.executemany("INSERT INTO properties VALUES (?, ?, ?, ?)", PROPERTY_ROWS)
        db.executemany(
            "INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?)", TRANSACTION_ROWS
        )
        db.execute(
            "INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("foreign", "comparison", "P001", "2026-01-05", "2026-01-10", 99, 1),
        )
        values = db.execute(MARKET_SELECT_SQL).fetchall()

    assert len(values) == 6
    assert sum(row[4] for row in values) == 2_400_000
    assert sum(row[0] == "Marina" for row in values) == 2
    assert sum(row[0] is None for row in values) == 2
    assert sum(row[1] == "Unknown" for row in values) == 1
    assert len({row[6] for row in values}) == 4


def test_metric_metadata_keeps_the_two_price_definitions_separate() -> None:
    """Both languages expose the intended ambiguity and distinct approved units."""
    from nxtbi_property_market.model import METRIC_CATALOG, METRICS, MODEL_VERSION

    average = METRIC_CATALOG["average_transaction_price"]
    weighted = METRIC_CATALOG["weighted_price_per_sqm"]
    assert "average property price" in average.aliases_en
    assert "average property price" in weighted.aliases_en
    assert "متوسط سعر العقار" in average.aliases_ar
    assert "متوسط سعر العقار" in weighted.aliases_ar
    assert (average.unit, weighted.unit) == ("AED", "AED/m²")
    assert average.definition_en != weighted.definition_en
    assert average.definition_ar != weighted.definition_ar
    assert set(METRIC_CATALOG) == set(METRICS)
    assert METRICS["average_transaction_price"].metadata["model_version"] == (
        MODEL_VERSION
    )
