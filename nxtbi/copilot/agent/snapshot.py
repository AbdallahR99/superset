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


"""Build a snapshot proposal after checking user-scoped evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .captions import arabic_label, titles
from .contracts import DashboardDraft, DatasetFilter, WidgetDraft


def validate_fields(
    metadata: Any,
    dataset_id: int,
    temporal: str,
    headline: str,
    kpis: list[str],
    breakdowns: list[str],
) -> dict[str, str]:
    """Require saved measures and verified groupable fields and return KPI labels."""
    if not isinstance(metadata, dict) or metadata.get("id") != dataset_id:
        raise ValueError("Dataset metadata is unavailable.")
    if any(
        temporal not in metadata.get(key, [])
        for key in ("temporal_columns", "filterable_columns", "groupable_columns")
    ):
        raise ValueError("Choose a groupable, filterable temporal column.")
    metrics = set(metadata.get("metrics", []))
    if {headline, *kpis} - metrics or len(set(kpis)) != len(kpis):
        raise ValueError(
            "Choose distinct saved KPI metric names and a saved headline metric."
        )
    categories = set(metadata.get("groupable_columns", [])) - set(
        metadata.get("temporal_columns", [])
    )
    if set(breakdowns) - categories or len(set(breakdowns)) != len(breakdowns):
        raise ValueError("Choose distinct groupable categorical breakdowns.")
    return {
        entry["metric_name"]: entry["verbose_name"]
        for entry in metadata.get("metric_details", [])
        if entry.get("metric_name") and entry.get("verbose_name")
    }


def latest_date(profile: Any, dataset_id: int, temporal: str) -> str:
    """Read the latest observed date reported for the selected temporal field."""
    if (
        isinstance(profile, dict)
        and profile.get("dataset_id") == dataset_id
        and profile.get("row_count", 0) > 0
    ):
        for col in profile.get("columns", []):
            if col.get("column_name") == temporal and isinstance(
                latest := col.get("latest"), str
            ):
                datetime.fromisoformat(latest)
                return latest
    raise ValueError(
        "No observed snapshot date was available for this temporal column."
    )


def require_measures(
    total: Any, groups: Any, dataset_id: int, metric: str, dimension: str
) -> None:
    """Reject a missing headline or a comparison with fewer than two categories."""
    for result, expected in ((total, None), (groups, dimension)):
        if not isinstance(result, dict) or (
            result.get("dataset_id"),
            result.get("metric"),
            result.get("dimension"),
        ) != (dataset_id, metric, expected):
            raise ValueError("Scoped saved metric evidence is unavailable.")
    if not total.get("rows") or type(total["rows"][0].get("value")) not in (float, int):
        raise ValueError("The latest snapshot has no headline value.")
    observed = {
        r.get("group")
        for r in groups.get("rows", [])
        if r.get("group") is not None and type(r.get("value")) in (float, int)
    }
    if len(observed) < 2:
        raise ValueError("Choose a breakdown with at least two populated categories.")


def make_draft(
    title: str,
    dataset_id: int,
    temporal: str,
    headline: str,
    kpis: list[str],
    breakdowns: list[str],
    latest: str,
    labels: dict[str, str],
) -> DashboardDraft:
    """Compose an unfiltered temporal line and snapshot-scoped tiles and comparisons."""
    scope = DatasetFilter(column=temporal, value=latest)

    def label(metric: str) -> str:
        return labels.get(metric, metric.replace("_", " ").capitalize())

    def scoped_title(text: str) -> str:
        return f"{text[: 150 - len(latest)]} · {latest}"

    widgets = [
        WidgetDraft(
            type="metric-tile",
            datasetId=dataset_id,
            metric=metric,
            filter=scope,
            title=scoped_title(label(metric)),
            title_translations=titles(
                scoped_title(label(metric)), scoped_title(arabic_label(label(metric)))
            ),
        )
        for metric in kpis
    ]
    widgets.append(
        WidgetDraft(
            type="echarts",
            datasetId=dataset_id,
            dimension=temporal,
            metric=headline,
            chartStyle="line",
            title=f"{label(headline)} over time"[:160],
            title_translations=titles(
                f"{label(headline)} over time",
                f"{arabic_label(label(headline))} عبر الزمن",
            ),
        )
    )
    for i, field in enumerate(breakdowns):
        display_name = field.removesuffix("_en").removesuffix("_ar").replace("_", " ")
        widgets.append(
            WidgetDraft(
                type="echarts" if i == 0 else "ag-grid-table",
                datasetId=dataset_id,
                dimension=field,
                metric=headline,
                filter=scope,
                title=scoped_title(f"{label(headline)} by {display_name}"),
                title_translations=titles(
                    scoped_title(f"{label(headline)} by {display_name}"),
                    scoped_title(
                        f"{arabic_label(label(headline))} حسب "
                        f"{arabic_label(display_name)}"
                    ),
                ),
            )
        )
    return DashboardDraft(title=title, widgets=widgets)
