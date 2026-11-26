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

import pytest

from superset.copilot.classic import classic_chart_form_data
from superset.copilot.contracts import ProposalWidget
from superset.copilot.localization import localized_caption
from superset.dashboard_v2.document import V2_DOCUMENT_KEY
from superset.models.dashboard import Dashboard
from superset.utils import json


@pytest.mark.parametrize(
    ("widget_type", "style", "viz_type", "dimension_key"),
    [
        ("metric-tile", None, "big_number_total", None),
        ("ag-grid-table", None, "table", "groupby"),
        ("echarts", "bar", "echarts_timeseries_bar", "x_axis"),
        ("echarts", "line", "echarts_timeseries_line", "x_axis"),
    ],
)
def test_classic_chart_keeps_scoped_saved_measure(
    widget_type: str, style: str | None, viz_type: str, dimension_key: str | None
) -> None:
    draft = ProposalWidget.model_validate(
        {
            "type": widget_type,
            "datasetId": 4,
            "metric": "saved_measure",
            "dimension": "event_date" if dimension_key else None,
            "chartStyle": style,
            "filter": {"column": "snapshot_date", "value": "2026-01-01"},
        }
    )
    form_data = classic_chart_form_data(draft, 2)

    assert form_data["viz_type"] == viz_type
    assert form_data["datasource"] == "4__table"
    if widget_type == "metric-tile":
        assert form_data["metric"] == "saved_measure"
        assert form_data["y_axis_format"] == ".2%"
    else:
        assert form_data["metrics"] == ["saved_measure"]
    if dimension_key:
        expected = ["event_date"] if dimension_key == "groupby" else "event_date"
        assert form_data[dimension_key] == expected
    if style == "line":
        assert form_data["orderby"] == [["event_date", True]]
    else:
        assert "orderby" not in form_data
    predicate = form_data["adhoc_filters"][0]
    assert predicate["expressionType"] == "SIMPLE"
    assert predicate["subject"] == "snapshot_date"
    assert predicate["operator"] == "=="
    assert predicate["comparator"] == "2026-01-01"
    assert form_data["time_range"] == "No filter"


def test_classic_localization_uses_viewer_locale_and_current_source() -> None:
    metadata = {
        "nxtbi_localization": {
            "sourceLocale": "en",
            "title": {"source": "Sales", "translations": {"ar": "المبيعات"}},
            "widgets": {
                "18": {"source": "Revenue", "translations": {"ar": "الإيرادات"}}
            },
        }
    }
    assert localized_caption(metadata, "Sales", "ar_AE") == "المبيعات"
    assert localized_caption(metadata, "Revenue", "ar-AE", 18) == "الإيرادات"
    assert localized_caption(metadata, "Sales", "fr") is None
    assert localized_caption(metadata, "Revised sales", "ar") is None
    assert localized_caption(metadata, "Revenue", "ar", 19) is None


def test_v2_dashboard_card_displays_approved_translation_until_source_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("superset.models.dashboard.get_locale", lambda: "ar_AE")
    monkeypatch.setattr(
        "superset.models.dashboard.translate", lambda title, **_context: title
    )
    dashboard = Dashboard(
        dashboard_title="Sales",
        json_metadata=json.dumps(
            {
                V2_DOCUMENT_KEY: {
                    "version": 1,
                    "nodes": {
                        "root": {
                            "type": "grid",
                            "children": [],
                            "props": {
                                "nxtbiLocalization": {
                                    "sourceLocale": "en",
                                    "title": {
                                        "source": "Sales",
                                        "translations": {"ar": "المبيعات"},
                                    },
                                }
                            },
                        }
                    },
                }
            }
        ),
    )

    assert dashboard.localized_title == "المبيعات"
    assert dashboard.dashboard_title == "Sales"
    dashboard.dashboard_title = "Revised sales"
    assert dashboard.localized_title == "Revised sales"
