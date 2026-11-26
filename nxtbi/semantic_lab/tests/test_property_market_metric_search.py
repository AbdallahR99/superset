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

"""Verify grounded bilingual metric lookup on the property-market catalogue."""

from __future__ import annotations

from typing import Literal

import pytest

pytest_plugins: list[str] = ["superset_core.semantic_layers.testing"]


@pytest.mark.parametrize(
    ("phrase", "locale"),
    [
        ("average property price", "en"),
        ("  AVERAGE   PROPERTY PRICE?  ", "en"),
        ("متوسط سعر العقار", "ar"),
        ("مُتَوَسِّط سِعْر العَـقَار؟", "ar"),
    ],
)
def test_ambiguous_metric_surfaces_both_localized_definitions(
    semantic_layer_registration: None, phrase: str, locale: Literal["en", "ar"]
) -> None:
    """Report the measures that share an everyday phrase for clarification."""
    from nxtbi_property_market.metric_search import resolve_metric
    from nxtbi_property_market.model import METRIC_CATALOG

    result = resolve_metric(phrase, locale)

    assert result.status == "ambiguous"
    assert {candidate.metric_id for candidate in result.candidates} == {
        "average_transaction_price",
        "weighted_price_per_sqm",
    }
    assert {candidate.unit for candidate in result.candidates} == {"AED", "AED/m²"}
    for candidate in result.candidates:
        text = METRIC_CATALOG[candidate.metric_id]
        assert candidate.label == (text.label_ar if locale == "ar" else text.label_en)
        assert candidate.definition == (
            text.definition_ar if locale == "ar" else text.definition_en
        )


@pytest.mark.parametrize(
    ("locale", "metric_id"),
    [("en", "average_transaction_price"), ("ar", "weighted_price_per_sqm")],
)
def test_explicit_metric_labels_select_one_definition(
    semantic_layer_registration: None, locale: Literal["en", "ar"], metric_id: str
) -> None:
    """Explicit bilingual catalogue labels resolve to stable metric identifiers."""
    from nxtbi_property_market.metric_search import resolve_metric
    from nxtbi_property_market.model import METRIC_CATALOG

    text = METRIC_CATALOG[metric_id]
    result = resolve_metric(text.label_ar if locale == "ar" else text.label_en, locale)

    assert result.status == "matched"
    assert tuple(candidate.metric_id for candidate in result.candidates) == (metric_id,)


@pytest.mark.parametrize("phrase", ["", "price", "median price", "average property"])
def test_unknown_phrase_preserves_an_empty_candidate_set(
    semantic_layer_registration: None, phrase: str
) -> None:
    """Unknown or incomplete phrases never invent a metric."""
    from nxtbi_property_market.metric_search import resolve_metric

    result = resolve_metric(phrase, "en")

    assert result.status == "unmatched"
    assert result.candidates == ()
