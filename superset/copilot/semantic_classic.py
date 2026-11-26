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

"""Create a native Classic dashboard from the authorized semantic lab view."""

from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from superset import security_manager
from superset.copilot.classic import ClassicChartSpec, save_classic_dashboard
from superset.copilot.contracts import ContentLocale, TitleTranslations
from superset.copilot.services import CopilotAccessError
from superset.semantic_layers.models import SemanticView

BREAKDOWN_DIMENSION = "property_type"
_BREAKDOWN_LABELS: TitleTranslations = {"en": "Property type", "ar": "نوع العقار"}


@dataclass(frozen=True)
class SemanticClassicCaptions:
    """Approved English and Arabic titles for a semantic dashboard and its charts."""

    locale: ContentLocale
    dashboard: TitleTranslations
    kpi: TitleTranslations
    breakdown: TitleTranslations


def create_semantic_classic_dashboard(
    view: SemanticView,
    metric_id: str,
    captions: SemanticClassicCaptions,
    approval_uuid: UUID,
) -> tuple[int, bool]:
    """Revalidate approved members and save a semantic KPI and breakdown together."""
    if not all(
        security_manager.can_access("can_write", resource)
        for resource in ("Dashboard", "Chart")
    ):
        raise CopilotAccessError("The current user cannot create this dashboard.")
    view.raise_for_access()
    if metric_id not in view.get_compatible_metrics(
        [], []
    ) or BREAKDOWN_DIMENSION not in view.get_compatible_dimensions([metric_id], []):
        raise ValueError("Choose a compatible metric and property type dimension.")

    view_id = cast(int, view.id)
    form_data: dict[str, Any] = {
        "datasource": f"{view_id}__semantic_view",
        "row_limit": 100,
        "time_range": "No filter",
        "adhoc_filters": [],
    }
    if version := view.implementation.selection_identity_version:
        form_data["semantic_selection_version"] = version

    return save_classic_dashboard(
        approval_uuid=approval_uuid,
        title=captions.dashboard[captions.locale],
        title_translations=captions.dashboard,
        content_locale=captions.locale,
        chart_specs=[
            ClassicChartSpec(
                datasource_id=view_id,
                datasource_type="semantic_view",
                title=captions.kpi[captions.locale],
                form_data={
                    **form_data,
                    "viz_type": "big_number_total",
                    "metric": metric_id,
                },
                title_translations=captions.kpi,
            ),
            ClassicChartSpec(
                datasource_id=view_id,
                datasource_type="semantic_view",
                title=captions.breakdown[captions.locale],
                form_data={
                    **form_data,
                    "viz_type": "table",
                    "query_mode": "aggregate",
                    "metrics": [metric_id],
                    "groupby": [BREAKDOWN_DIMENSION],
                    "column_config": {
                        BREAKDOWN_DIMENSION: {
                            "customColumnName": _BREAKDOWN_LABELS[captions.locale],
                        },
                        metric_id: {"customColumnName": captions.kpi[captions.locale]},
                    },
                },
                title_translations=captions.breakdown,
            ),
        ],
    )
