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

from .captions import arabic_label, titles
from .contracts import ContentLocale, DashboardDraft, TitleTranslations, WidgetDraft

_CATEGORY = re.compile(
    r"(?:^|_)(?:status|state|stage|category|type|region|area|city|country|zone|"
    r"channel|method|priority|sector|segment|department|class|tier)(?:_|$)"
)
_PRIVATE_FIELD = re.compile(
    r"(?:^|_)(?:id|key|reference|ref|uuid|code|person|personal|surname|"
    r"contact|email|phone|address|username|password|passport|ssn|comment|notes)(?:_|$)"
)
_REGISTERED_METRIC_LIMIT = 3


@dataclass(frozen=True)
class UploadFields:
    """Saved measures and bounded candidate dimensions for a selected dataset."""

    metric: str
    metric_label: str
    count_available: bool
    temporal: str | None
    categories: tuple[str, ...]

    @property
    def profile_columns(self) -> list[str]:
        """Return no more than three registered columns for evidence."""
        return ([self.temporal] if self.temporal else []) + list(self.categories)


class NoSavedMetricsError(ValueError):
    """The authorized dataset has no saved metric the draft can use."""


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
    metadata: object, dataset_id: int, requested_metric: str | None, *, is_upload: bool
) -> list[UploadFields]:
    """Choose saved measures and a shared profile of conventional dimensions."""
    if (
        not isinstance(metadata, dict)
        or type(metadata.get("id")) is not int
        or metadata["id"] != dataset_id
    ):
        raise ValueError("The selected dataset is unavailable to the signed-in user.")
    metrics = _names(metadata, "metrics")
    if not metrics:
        raise NoSavedMetricsError("This dataset has no saved metrics.")
    if requested_metric and requested_metric not in metrics:
        raise ValueError("Choose a saved metric from the selected dataset.")
    authored = [name for name in metrics if name.casefold() != "count"]
    if requested_metric:
        candidates = [requested_metric]
    elif is_upload:
        fallback = authored[0] if authored else metrics[0]
        candidates = [
            next((name for name in metrics if name.startswith("sum_")), fallback)
        ]
    else:
        count = [name for name in metrics if name.casefold() == "count"][:1]
        candidates = authored[: _REGISTERED_METRIC_LIMIT - len(count)] + count

    labels: dict[str, str] = {}
    if isinstance(details := metadata.get("metric_details"), list):
        for detail in details:
            if (
                isinstance(detail, dict)
                and isinstance(name := detail.get("metric_name"), str)
                and name in candidates
                and isinstance(verbose := detail.get("verbose_name"), str)
                and verbose.strip()
            ):
                labels.setdefault(name, verbose.strip())

    groupable = _names(metadata, "groupable_columns")
    temporal_columns = _names(metadata, "temporal_columns")
    temporal = next((name for name in temporal_columns if name in groupable), None)
    categories = tuple(
        name
        for name in groupable
        if name not in temporal_columns
        and (not is_upload or name != candidates[0])
        and _CATEGORY.search(name.lower())
        and not _PRIVATE_FIELD.search(name.lower())
    )[: (2 if temporal else 3)]
    return [
        UploadFields(
            metric,
            labels.get(metric, metric.replace("_", " ").capitalize()),
            is_upload and "count" in metrics,
            temporal,
            categories,
        )
        for metric in candidates
    ]


def registered_titles(metadata: object, dataset_id: int) -> TitleTranslations:
    """Derive stable, readable draft titles from authorized source metadata."""
    name = metadata.get("table_name") if isinstance(metadata, dict) else None
    if isinstance(name, str) and not re.fullmatch(r"copilot_csv_[0-9a-f]{24}", name):
        label = " ".join(name.replace("_", " ").split())[:120].strip()
        if label and label.isprintable():
            label = label[0].upper() + label[1:]
            return titles(f"{label} overview", f"نظرة عامة على {arabic_label(label)}")
    return titles(
        f"Dataset #{dataset_id} overview",
        f"نظرة عامة على مجموعة البيانات #{dataset_id}",
    )


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
        raise ValueError("The selected dataset has no verified rows to chart.")
    counts = {
        entry["column_name"]: entry["distinct_count"]
        for entry in columns
        if isinstance(entry, dict)
        and isinstance(entry.get("column_name"), str)
        and type(entry.get("distinct_count")) is int
    }
    category = next(
        (
            name
            for name in candidates.categories
            if name != candidates.metric and 2 <= counts.get(name, 0) <= 10
        ),
        None,
    )
    temporal = candidates.temporal
    # Dashboard V2's proposal compiler fetches up to 100 grouped rows.
    if (
        not temporal
        or temporal == candidates.metric
        or not 2 <= counts.get(temporal, 0) <= 100
    ):
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
    locale: ContentLocale,
) -> DashboardDraft:
    """Compose charts with existing widgets for separate save approval."""
    label = (
        "Records"
        if fields.count_available and fields.metric == "count"
        else fields.metric_label
    )
    arabic = arabic_label(label)
    widgets = [
        WidgetDraft(
            type="metric-tile",
            datasetId=dataset_id,
            metric=fields.metric,
            title=label[:160],
            title_translations=titles(label, arabic),
        )
    ]
    if fields.count_available and fields.metric != "count":
        widgets.append(
            WidgetDraft(
                type="metric-tile",
                datasetId=dataset_id,
                metric="count",
                title="Records",
                title_translations=titles("Records", "السجلات"),
            )
        )
    if temporal:
        title_variants = titles(f"{label} over time", f"{arabic} عبر الزمن")
        widgets.append(
            WidgetDraft(
                type="echarts",
                datasetId=dataset_id,
                metric=fields.metric,
                dimension=temporal,
                chartStyle="line",
                title=title_variants.en,
                title_translations=title_variants,
            )
        )
    if category:
        dimension_label = category.replace("_", " ")
        title_variants = titles(
            f"{label} by {dimension_label}",
            f"{arabic} حسب {arabic_label(dimension_label)}",
        )
        widgets.append(
            WidgetDraft(
                type="echarts",
                datasetId=dataset_id,
                metric=fields.metric,
                dimension=category,
                chartStyle="bar",
                title=title_variants.en,
                title_translations=title_variants,
            )
        )
    return DashboardDraft(title=title, widgets=widgets, content_locale=locale)
