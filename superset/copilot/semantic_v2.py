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

"""Create a native Dashboard V2 draft from the approved semantic lab view."""

from typing import Any
from uuid import UUID

from superset.commands.dashboard_v2.save import CreateDashboardV2Command
from superset.copilot.semantic_classic import (
    BREAKDOWN_DIMENSION,
    SemanticClassicCaptions,
)
from superset.semantic_layers.models import SemanticView

_CURRENCY_UNITS = frozenset({"AED", "AED/m²"})


def _make_semantic_document(
    view_uuid: UUID,
    metric_id: str,
    captions: SemanticClassicCaptions,
    *,
    unit: str,
    selection_version: str | None,
) -> dict[str, Any]:
    """Compile stable semantic bindings and approved captions into native widgets."""
    locale = captions.locale
    binding: dict[str, Any] = {
        "semanticViewId": str(view_uuid),
        "metrics": [metric_id],
    }
    if selection_version is not None:
        binding["semanticSelectionVersion"] = selection_version
    kpi = captions.kpi[locale]
    breakdown = captions.breakdown[locale]
    property_type_label = "نوع العقار" if locale == "ar" else "Property type"
    return {
        "version": 1,
        "root": "root",
        "nodes": {
            "root": {
                "type": "grid",
                "layout": {"columns": 24},
                "children": ["metric", "breakdown"],
                "props": {
                    "nxtbiLocalization": {
                        "sourceLocale": locale,
                        "title": {
                            "source": captions.dashboard[locale],
                            "translations": captions.dashboard,
                        },
                        "widgets": {
                            "metric": {"source": kpi, "translations": captions.kpi},
                            "breakdown": {
                                "source": breakdown,
                                "translations": captions.breakdown,
                            },
                        },
                    }
                },
            },
            "metric": {
                "type": "metric-tile",
                "layout": {"colSpan": 8, "rowSpan": 4},
                "props": {
                    "label": kpi,
                    "decimals": 2 if unit in _CURRENCY_UNITS else 0,
                    "suffix": f" {unit}" if unit in _CURRENCY_UNITS else "",
                    "dataBinding": {**binding, "dimensions": [], "rowLimit": 1},
                },
            },
            "breakdown": {
                "type": "ag-grid-table",
                "layout": {"colSpan": 16, "rowSpan": 9},
                "props": {
                    "label": breakdown,
                    "columnDefs": [
                        {
                            "field": BREAKDOWN_DIMENSION,
                            "headerName": property_type_label,
                        },
                        {"field": metric_id, "headerName": kpi},
                    ],
                    "dataBinding": {
                        **binding,
                        "dimensions": [BREAKDOWN_DIMENSION],
                        "rowLimit": 100,
                    },
                },
            },
        },
    }


def create_semantic_v2_dashboard(
    view: SemanticView,
    metric_id: str,
    captions: SemanticClassicCaptions,
    approval_uuid: UUID,
    *,
    unit: str,
    selection_version: str | None,
) -> tuple[int, bool]:
    """Save the approved KPI and breakdown through native V2 authoring."""
    view.raise_for_access()
    if BREAKDOWN_DIMENSION not in view.get_compatible_dimensions([metric_id], []):
        raise ValueError("Choose a compatible metric and property type dimension.")
    command = CreateDashboardV2Command(
        {
            "dashboard_title": captions.dashboard[captions.locale],
            "document": _make_semantic_document(
                view.uuid,
                metric_id,
                captions,
                unit=unit,
                selection_version=selection_version,
            ),
            "uuid": approval_uuid,
        }
    )
    dashboard = command.run()
    return dashboard["id"], command.created
