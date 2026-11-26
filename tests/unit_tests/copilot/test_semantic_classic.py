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

"""Verify semantic Copilot save validation and native chart bindings."""

from unittest.mock import create_autospec, Mock
from uuid import uuid4

import pytest

from superset.copilot import semantic_classic
from superset.semantic_layers.models import SemanticView

CAPTIONS = semantic_classic.SemanticClassicCaptions(
    locale="ar",
    dashboard={"en": "Property overview", "ar": "نظرة عامة على العقارات"},
    kpi={"en": "Transactions", "ar": "المعاملات"},
    breakdown={"en": "Transactions by property type", "ar": "المعاملات حسب نوع العقار"},
)


def test_semantic_classic_save_preserves_the_view_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Save localized native charts at the approved metric and grouping."""
    view = create_autospec(SemanticView, instance=True)
    view.id = 19
    view.implementation.selection_identity_version = "lab-selection-v1"
    view.get_compatible_metrics.return_value = ["transaction_count"]
    view.get_compatible_dimensions.return_value = ["property_type"]
    monkeypatch.setattr(
        semantic_classic, "security_manager", Mock(can_access=Mock(return_value=True))
    )
    save = Mock(return_value=(11, True))
    monkeypatch.setattr(semantic_classic, "save_classic_dashboard", save)
    approval_uuid = uuid4()

    assert semantic_classic.create_semantic_classic_dashboard(
        view, "transaction_count", CAPTIONS, approval_uuid
    ) == (11, True)

    view.raise_for_access.assert_called_once_with()
    kwargs = save.call_args.kwargs
    assert kwargs["approval_uuid"] == approval_uuid
    assert kwargs["title"] == "نظرة عامة على العقارات"
    assert kwargs["title_translations"] == CAPTIONS.dashboard
    assert kwargs["content_locale"] == "ar"
    kpi, breakdown = kwargs["chart_specs"]
    assert [chart.datasource_id for chart in (kpi, breakdown)] == [19, 19]
    assert [chart.datasource_type for chart in (kpi, breakdown)] == [
        "semantic_view",
        "semantic_view",
    ]
    assert kpi.form_data == {
        "datasource": "19__semantic_view",
        "viz_type": "big_number_total",
        "metric": "transaction_count",
        "time_range": "No filter",
        "adhoc_filters": [],
        "row_limit": 100,
        "semantic_selection_version": "lab-selection-v1",
    }
    assert breakdown.form_data == {
        "datasource": "19__semantic_view",
        "viz_type": "table",
        "query_mode": "aggregate",
        "metrics": ["transaction_count"],
        "groupby": ["property_type"],
        "column_config": {
            "property_type": {"customColumnName": "نوع العقار"},
            "transaction_count": {"customColumnName": "المعاملات"},
        },
        "time_range": "No filter",
        "adhoc_filters": [],
        "row_limit": 100,
        "semantic_selection_version": "lab-selection-v1",
    }
    assert kpi.title == "المعاملات"
    assert kpi.title_translations == CAPTIONS.kpi
    assert breakdown.title_translations == CAPTIONS.breakdown


def test_semantic_classic_save_rechecks_metric_compatibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refuse a selected metric if its approved grouping is unavailable."""
    view = create_autospec(SemanticView, instance=True)
    view.get_compatible_metrics.return_value = ["transaction_count"]
    view.get_compatible_dimensions.return_value = ["sale_date"]
    monkeypatch.setattr(
        semantic_classic, "security_manager", Mock(can_access=Mock(return_value=True))
    )
    save = Mock()
    monkeypatch.setattr(semantic_classic, "save_classic_dashboard", save)

    with pytest.raises(ValueError, match="compatible"):
        semantic_classic.create_semantic_classic_dashboard(
            view, "transaction_count", CAPTIONS, uuid4()
        )

    save.assert_not_called()
