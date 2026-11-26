# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""Build a scoped default dashboard from registered CSV dataset metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .contracts import DashboardDraft, WidgetDraft

_CATEGORY = re.compile(
    r"(?:^|_)(?:status|state|stage|category|type|region|area|city|country|zone|"
    r"channel|method|priority|sector|segment|department|class|tier)(?:_|$)"
)
_PRIVATE_FIELD = re.compile(
    r"(?:^|_)(?:id|key|reference|ref|uuid|code|person|personal|surname|"
    r"contact|email|phone|address|username|password|passport|ssn|comment|notes)(?:_|$)"
)


@dataclass(frozen=True)
class UploadFields:
    """Saved measures and bounded candidate dimensions for a selected file."""

    metric: str
    metric_label: str
    count_available: bool
    temporal: str | None
    categories: tuple[str, ...]

    @property
    def profile_columns(self) -> list[str]:
        """Return no more than three registered columns for evidence."""
        return ([self.temporal] if self.temporal else []) + list(self.categories)


def _names(metadata: dict[str, object], key: str) -> list[str]:
    """Read distinct names that fit the dashboard tool contracts."""
    values = metadata.get(key)
    if not isinstance(values, list):
        return []
    return list(
        dict.fromkeys(
            name for name in values if isinstance(name, str) and 0 < len(name) <= 160
        )
    )


def select_fields(
    metadata: object, dataset_id: int, requested_metric: str | None
) -> UploadFields:
    """Choose useful saved measures and conventional categories, never row IDs."""
    if (
        not isinstance(metadata, dict)
        or type(metadata.get("id")) is not int
        or metadata["id"] != dataset_id
    ):
        raise ValueError("The imported dataset is unavailable to the signed-in user.")
    metrics = _names(metadata, "metrics")
    if not metrics or (requested_metric and requested_metric not in metrics):
        raise ValueError("Choose a saved metric from the imported dataset.")
    if requested_metric:
        metric = requested_metric
    else:
        fallback = next((name for name in metrics if name != "count"), metrics[0])
        metric = next((name for name in metrics if name.startswith("sum_")), fallback)
    label = metric.replace("_", " ").capitalize()
    if isinstance(details := metadata.get("metric_details"), list):
        for detail in details:
            if (
                isinstance(detail, dict)
                and detail.get("metric_name") == metric
                and isinstance(verbose := detail.get("verbose_name"), str)
                and verbose.strip()
            ):
                label = verbose.strip()
                break

    groupable = _names(metadata, "groupable_columns")
    temporal_columns = _names(metadata, "temporal_columns")
    temporal = next((name for name in temporal_columns if name in groupable), None)
    categories = tuple(
        name
        for name in groupable
        if name not in temporal_columns
        and name != metric
        and _CATEGORY.search(name.lower())
        and not _PRIVATE_FIELD.search(name.lower())
    )[: (2 if temporal else 3)]
    return UploadFields(metric, label, "count" in metrics, temporal, categories)


def select_dimensions(
    profile: object, dataset_id: int, candidates: UploadFields
) -> tuple[str | None, str | None]:
    """Find a populated category and a date series that fits the widget row cap."""
    if (
        not isinstance(profile, dict)
        or profile.get("dataset_id") != dataset_id
        or type(count := profile.get("row_count")) is not int
        or count < 1
        or not isinstance(columns := profile.get("columns"), list)
    ):
        raise ValueError("The imported dataset has no verified rows to chart.")
    counts = {
        entry["column_name"]: entry["distinct_count"]
        for entry in columns
        if isinstance(entry, dict)
        and isinstance(entry.get("column_name"), str)
        and type(entry.get("distinct_count")) is int
    }
    category = next(
        (name for name in candidates.categories if 2 <= counts.get(name, 0) <= 10),
        None,
    )
    temporal = candidates.temporal
    # Dashboard V2's proposal compiler fetches up to 100 grouped rows.
    if not temporal or not 2 <= counts.get(temporal, 0) <= 100:
        temporal = None
    return category, temporal


def supported_aggregate(
    total: object, dataset_id: int, metric: str, *, dimension: str | None = None
) -> bool:
    """Check the scope and numeric observations returned by the chart gateway."""
    if (
        not isinstance(total, dict)
        or (total.get("dataset_id"), total.get("metric"), total.get("dimension"))
        != (dataset_id, metric, dimension)
        or not isinstance(rows := total.get("rows"), list)
    ):
        return False
    if dimension:
        groups = {
            row["group"]
            for row in rows
            if isinstance(row, dict)
            and type(row.get("group")) in (str, int, float, bool)
            and type(row.get("value")) in (int, float)
        }
        return len(groups) >= 2
    return (
        len(rows) == 1
        and isinstance(rows[0], dict)
        and type(rows[0].get("value")) in (int, float)
    )


def make_draft(
    title: str,
    dataset_id: int,
    fields: UploadFields,
    category: str | None,
    temporal: str | None,
    locale: Literal["ar", "en"],
) -> DashboardDraft:
    """Compose full-file charts with existing widgets and separate save approval."""
    records = "السجلات" if locale == "ar" else "Records"
    labeling = fields.metric_label if fields.metric != "count" else records
    widgets = [
        WidgetDraft(
            type="metric-tile",
            datasetId=dataset_id,
            metric=fields.metric,
            title=labeling[:160],
        )
    ]
    if fields.count_available and fields.metric != "count":
        widgets.append(
            WidgetDraft(
                type="metric-tile", datasetId=dataset_id, metric="count", title=records
            )
        )
    if temporal:
        widgets.append(
            WidgetDraft(
                type="echarts",
                datasetId=dataset_id,
                metric=fields.metric,
                dimension=temporal,
                chartStyle="line",
                title=f"{labeling} {'عبر الزمن' if locale == 'ar' else 'over time'}"[
                    :160
                ],
            )
        )
    if category:
        by = "حسب" if locale == "ar" else "by"
        category_label = category.replace("_", " ")
        widgets.append(
            WidgetDraft(
                type="echarts",
                datasetId=dataset_id,
                metric=fields.metric,
                dimension=category,
                chartStyle="bar",
                title=f"{labeling} {by} {category_label}"[:160],
            )
        )
    return DashboardDraft(title=title, widgets=widgets)
