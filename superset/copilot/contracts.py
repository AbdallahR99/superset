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

"""Bounded contracts for the NxtBI Copilot gateway."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import time
from dataclasses import dataclass, field
from itertools import groupby
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, StringConstraints

from superset.utils import json
from superset.widgets.safety import MAX_COLUMN_TEXT_LENGTH, string_problem

RUN_AUDIENCE = "nxtbi-copilot"
APPROVAL_AUDIENCE = "nxtbi-dashboard-approval"
RUN_TTL = 240
APPROVAL_TTL = 900
MAX_BODY_BYTES = 128 * 1024
RANKED_CATEGORY_LIMIT = 12

ShortText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]
SummaryText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)
]
ResourceId = Annotated[int, Field(gt=0, le=2**31 - 1)]
ContentLocale = Literal["en", "ar"]
TitleTranslations = dict[ContentLocale, ShortText]
WireId = Annotated[str, StringConstraints(pattern=r"^[\w-]{1,80}$")]


class Contract(BaseModel):
    """Reject coercion and unknown fields at the tool boundary."""

    model_config = ConfigDict(strict=True, extra="forbid")


class AggregateFilter(Contract):
    """An equality constraint on one registered dataset column."""

    column: ShortText
    value: ShortText | bool | int | Annotated[float, Field(allow_inf_nan=False)]


class ProposalWidget(Contract):
    """A widget bound solely to named dataset metrics and columns."""

    type: Literal["metric-tile", "ag-grid-table", "echarts"]
    dataset_id: ResourceId = Field(alias="datasetId")
    metric: ShortText | None = None
    dimension: ShortText | None = None
    metrics: list[ShortText] | None = Field(default=None, min_length=1, max_length=6)
    dimensions: list[ShortText] | None = Field(default=None, max_length=4)
    title: ShortText | None = None
    title_translations: TitleTranslations = Field(
        default_factory=dict, alias="titleTranslations"
    )
    chart_style: Literal["bar", "line", "ranked-bar"] | None = Field(
        default=None, alias="chartStyle"
    )
    filter: AggregateFilter | None = None

    @model_validator(mode="after")
    def validate_bindings(self) -> ProposalWidget:
        """Allow exactly one binding form and keep compound bindings table-only."""
        if self.model_fields_set & {"metrics", "dimensions"}:
            if self.type != "ag-grid-table":
                raise ValueError("Only tables accept compound bindings.")
            if self.model_fields_set & {"metric", "dimension"}:
                raise ValueError("Choose either scalar or compound table bindings.")
            if self.metrics is None or self.dimensions is None:
                raise ValueError("A compound table requires both binding arrays.")
            names = [*self.metrics, *self.dimensions]
            if len(names) != len(set(names)):
                raise ValueError("Choose distinct metrics and dimensions.")
        elif self.metric is None:
            raise ValueError("Choose a metric.")
        if self.type == "echarts" and self.dimension is None:
            raise ValueError("A chart requires a grouping column.")
        if self.type != "echarts" and self.chart_style is not None:
            raise ValueError("Chart style is only available on charts.")
        return self

    @property
    def metric_names(self) -> list[str]:
        """Return selected saved metric names in proposal order."""
        if self.metrics is not None:
            return self.metrics
        return [self.metric] if self.metric else []

    @property
    def dimension_names(self) -> list[str]:
        """Return selected grouping column names in proposal order."""
        if self.dimensions is not None:
            return self.dimensions
        return [self.dimension] if self.dimension else []


class DashboardProposal(Contract):
    """A draft layout that can be generated or edited before approval."""

    title: ShortText
    widgets: list[ProposalWidget] = Field(min_length=1, max_length=8)
    summary: SummaryText | None = None
    title_translations: TitleTranslations = Field(
        default_factory=dict, alias="titleTranslations"
    )
    content_locale: ContentLocale | None = Field(default=None, alias="contentLocale")
    dashboard_type: Literal["v1", "v2"] = Field(default="v2", alias="dashboardType")

    @model_validator(mode="after")
    def validate_dashboard_type(self) -> DashboardProposal:
        """Restrict the extended proposal fields to Dashboard V2."""
        if self.dashboard_type == "v1" and (
            self.summary is not None
            or any(
                widget.metrics is not None or widget.chart_style == "ranked-bar"
                for widget in self.widgets
            )
        ):
            raise ValueError(
                "Compound tables, summaries and ranked charts require Dashboard V2."
            )
        return self


class DashboardApproval(DashboardProposal):
    """An explicit approval sent by the authenticated host."""

    approval_token: str = Field(alias="approvalToken", min_length=10, max_length=2048)


class ToolRequest(Contract):
    """A single call within the agent gateway's supported surface."""

    name: Literal[
        "list_datasets",
        "get_dataset",
        "profile_dataset",
        "aggregate_dataset",
        "list_dashboards",
        "get_dashboard",
        "list_charts",
        "get_chart",
        "get_saved_widget",
        "propose_dashboard",
    ]
    arguments: dict[str, Any]


class ListArguments(Contract):
    """Search published metadata using a bounded query."""

    query: ShortText | None = None


class GetArguments(Contract):
    """Select one object by its numeric Superset identity."""

    id: ResourceId


class ProfileArguments(GetArguments):
    """Count visible rows and profile at most three named columns."""

    columns: list[ShortText] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def unique_columns(self) -> ProfileArguments:
        """Reject ambiguous repeated profile columns."""
        if len(self.columns) != len(set(self.columns)):
            raise ValueError("Choose distinct profile columns.")
        return self


class AggregateArguments(GetArguments):
    """Summarize a registered metric, optionally grouped and filtered."""

    metric: ShortText
    dimension: ShortText | None = None
    filter: AggregateFilter | None = None


class SavedWidgetArguments(Contract):
    """Select a saved widget by its public UUID."""

    id: str = Field(min_length=36, max_length=36)


class RunIdentity(BaseModel):
    """The fields of an AG-UI input used to scope a server capability."""

    model_config = ConfigDict(strict=True)
    thread_id: WireId = Field(alias="threadId")
    run_id: WireId = Field(alias="runId")


class CopilotHistoryMessage(Contract):
    """One visible chat message, without tool or activity payloads."""

    id: WireId
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=24_000)


class CopilotHistoryDashboard(Contract):
    """A same-site link returned after dashboard approval."""

    id: ResourceId
    url: str = Field(pattern=r"^/dashboard/(?:v2/)?[1-9][0-9]{0,9}/$")

    @model_validator(mode="after")
    def validate_dashboard_url(self) -> CopilotHistoryDashboard:
        """Keep the saved dashboard link tied to the matching ID."""
        if self.url not in (f"/dashboard/{self.id}/", f"/dashboard/v2/{self.id}/"):
            raise ValueError("Dashboard URL must match the dashboard ID.")
        return self


class CopilotConversation(Contract):
    """A transcript snapshot containing only content shown in the chat."""

    thread_id: WireId = Field(alias="threadId")
    messages: list[CopilotHistoryMessage] = Field(min_length=1, max_length=32)
    updated_at: str = Field(
        alias="updatedAt",
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$",
    )
    saved_dashboard: CopilotHistoryDashboard | None = Field(
        default=None, alias="savedDashboard"
    )


def _base64(data: bytes) -> str:
    """Encode unpadded URL-safe Base64."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _mac(secret: str, payload: str) -> str:
    """Return the capability signature over the encoded payload."""
    return _base64(
        hmac.new(
            secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256
        ).digest()
    )


def sign_claims(secret: str, claims: dict[str, Any]) -> str:
    """Sign a private server-to-server or dashboard approval capability."""
    if len(secret) < 32:
        raise ValueError("Copilot signing material is missing or too short.")
    payload = _base64(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    return f"{payload}.{_mac(secret, payload)}"


def verify_claims(
    secret: str,
    token: str,
    audience: str,
    max_ttl: int,
    *,
    now: int | None = None,
) -> dict[str, Any]:
    """Authenticate a capability for exactly one audience and a bounded lifetime."""
    if len(secret) < 32 or len(token) > 2048 or not token.isascii():
        raise ValueError("Invalid Copilot capability.")
    try:
        payload, signature = token.split(".")
        if not hmac.compare_digest(_mac(secret, payload), signature):
            raise ValueError
        claims = json.loads(
            base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        )
    except (ValueError, UnicodeError, binascii.Error) as err:
        raise ValueError("Invalid Copilot capability.") from err
    timestamp = int(time.time()) if now is None else now
    if (
        not isinstance(claims, dict)
        or type(claims.get("exp")) is not int
        or not timestamp < claims["exp"] <= timestamp + max_ttl
        or claims.get("aud") != audience
        or not isinstance(claims.get("sub"), str)
    ):
        raise ValueError("Invalid Copilot capability.")
    return claims


def percent_precision(d3format: str | None) -> int | None:
    """Return the supported decimal count for a percentage metric format."""
    if d3format == "%":
        return 0
    if d3format and d3format.startswith(".") and d3format.endswith("%"):
        precision = d3format[1:-1]
        if len(precision) == 1 and precision in "0123456789":
            return int(precision)
    return None


@dataclass
class ProposalMetadata:
    """Saved display metadata gathered from the authorized dataset references."""

    metric_formats: dict[tuple[int, str], str] = field(default_factory=dict)
    metric_labels: dict[tuple[int, str], str] = field(default_factory=dict)
    dimension_labels: dict[tuple[int, str], str] = field(default_factory=dict)
    temporal_dimensions: set[tuple[int, str]] = field(default_factory=set)


def _tile_display(
    widget: ProposalWidget, metric: str, metadata: ProposalMetadata
) -> dict[str, Any]:
    """Use the saved metric label and supported fixed or percentage precision."""
    key = (widget.dataset_id, metric)
    props: dict[str, Any] = {
        "label": widget.title or metadata.metric_labels.get(key, metric)
    }
    d3format = metadata.metric_formats.get(key)
    if (precision := percent_precision(d3format)) is not None:
        props.update(percentage=True, decimals=precision)
    elif fixed := re.fullmatch(r",?\.([0-9]|10)f", d3format or ""):
        props["decimals"] = int(fixed[1])
    return props


def _table_header(name: str, label: str | None) -> str:
    """Use a saved label within native column bounds, or keep the field name."""
    header = (label or name)[:MAX_COLUMN_TEXT_LENGTH]
    return name if string_problem(header) else header


def _table_columns(
    widget: ProposalWidget, metadata: ProposalMetadata
) -> list[dict[str, Any]]:
    """Define grouped columns first and format only saved temporal dimensions."""
    columns: list[dict[str, Any]] = []
    header_layout = {"wrapHeaderText": True, "autoHeaderHeight": True}
    for name in widget.dimension_names:
        key = (widget.dataset_id, name)
        column: dict[str, Any] = {
            "field": name,
            "headerName": _table_header(name, metadata.dimension_labels.get(key)),
            "minWidth": 160,
            "flex": 2,
            "wrapText": True,
            "autoHeight": True,
            **header_layout,
        }
        if key in metadata.temporal_dimensions:
            column["valueFormat"] = "date"
        columns.append(column)
    return columns + [
        {
            "field": name,
            "headerName": _table_header(
                name, metadata.metric_labels.get((widget.dataset_id, name))
            ),
            "minWidth": 132,
            "flex": 1,
            **header_layout,
        }
        for name in widget.metric_names
    ]


def _theme_value(token: str) -> dict[str, dict[str, str]]:
    """Bind a native chart option to a Superset theme token."""
    return {"$bind": {"source": "theme", "token": token}}


def _chart_value_axis(
    label: str, d3format: str | None, is_trend: bool
) -> dict[str, Any]:
    """Describe the value scale using safe, supported saved format details."""
    axis_label: dict[str, Any] = {
        "fontSize": 11,
        "color": _theme_value("colorTextSecondary"),
    }
    axis: dict[str, Any] = {
        "type": "value",
        "name": label,
        "nameLocation": "middle",
        "nameGap": 54 if is_trend else 32,
        "nameTextStyle": {"width": 170, "overflow": "break"},
        "axisLabel": axis_label,
        "splitLine": {"lineStyle": {"color": _theme_value("colorBorderSecondary")}},
    }
    if fixed := re.fullmatch(r"(\$)?,?\.([0-9]|10)f", d3format or ""):
        axis["minInterval"] = 10 ** -int(fixed[2])
        if fixed[1]:
            axis_label["formatter"] = "${value}"
    elif d3format in {"d", ",d"}:
        axis["minInterval"] = 1
    return axis


def _chart_display(
    widget: ProposalWidget, metadata: ProposalMetadata
) -> dict[str, Any]:
    """Compile a legacy bar, ranked category comparison or chronological native line."""
    is_trend = widget.chart_style == "line"
    metric = widget.metric_names[0]
    axis_binding = {"source": "dimension", "alias": widget.dimension}
    metric_binding = {"$bind": {"source": "metric", "alias": metric}}
    if widget.chart_style in {None, "bar"}:
        return {
            "crossFilter": True,
            "echartsOptions": {
                "animation": False,
                "grid": {"left": 64, "right": 24, "bottom": 40, "top": 48},
                "tooltip": {"trigger": "axis", "renderMode": "richText"},
                "xAxis": {
                    "type": "category",
                    "axisLabel": {"hideOverlap": True},
                    "data": {"$bind": axis_binding},
                },
                "yAxis": {"type": "value"},
                "series": [{"type": "bar", "data": metric_binding}],
                **({"title": {"text": widget.title}} if widget.title else {}),
            },
        }
    key = (widget.dataset_id, metric)
    label = _table_header(metric, metadata.metric_labels.get(key))
    category_label: dict[str, Any] = {
        "color": _theme_value("colorTextSecondary"),
        "fontSize": 11,
        "hideOverlap": True,
    }
    category_axis: dict[str, Any] = {
        "type": "category",
        "axisLabel": category_label,
        "data": {"$bind": axis_binding},
    }
    series: dict[str, Any] = {
        "type": "line" if is_trend else "bar",
        "name": label,
        "data": metric_binding,
    }
    if is_trend:
        axis_binding["format"] = "date"
        series.update(
            smooth=False,
            connectNulls=False,
            showSymbol=True,
            symbol="circle",
            symbolSize=7,
            lineStyle={"width": 2.5},
        )
    else:
        category_axis["inverse"] = True
        category_label.update(width=148, overflow="break")
        series.update(barMaxWidth=24, realtimeSort=True)
    value_axis = _chart_value_axis(label, metadata.metric_formats.get(key), is_trend)
    options: dict[str, Any] = {
        "animation": False,
        "aria": {"enabled": True},
        "color": [_theme_value("colorPrimary")],
        "grid": {
            "left": 14,
            "right": 14,
            "top": 16,
            "bottom": 14,
            "outerBoundsMode": "same",
            "outerBoundsContain": "all",
        },
        "legend": {"show": False},
        "tooltip": {
            "trigger": "axis",
            "renderMode": "richText",
            "confine": True,
            "axisPointer": {"type": "line" if is_trend else "shadow"},
        },
        "xAxis": category_axis if is_trend else value_axis,
        "yAxis": value_axis if is_trend else category_axis,
        "series": [series],
    }
    if widget.title:
        options["title"] = {"text": widget.title}
    return {"crossFilter": not is_trend, "echartsOptions": options}


def _dashboard_layout(proposal: DashboardProposal) -> tuple[list[str], dict[str, int]]:
    """Keep proposal order, insert the summary, and pair adjacent charts."""
    children: list[str] = []
    chart_spans: dict[str, int] = {}
    pending_summary = ["summary"] if proposal.summary else []
    groups = groupby(
        enumerate(proposal.widgets, 1), key=lambda item: item[1].type == "echarts"
    )
    for is_chart, widgets in groups:
        node_ids = [f"widget_{index}" for index, _ in widgets]
        if is_chart:
            children.extend(pending_summary)
            pending_summary = []
            chart_spans.update(dict.fromkeys(node_ids, 12))
            if len(node_ids) % 2:
                chart_spans[node_ids[-1]] = 24
        children.extend(node_ids)
    return children + pending_summary, chart_spans


def make_document(
    proposal: DashboardProposal,
    metadata: ProposalMetadata | None = None,
) -> dict[str, Any]:
    """Compile the allowed widget choices through the Dashboard V2 document format."""
    metadata = metadata or ProposalMetadata()
    children, chart_spans = _dashboard_layout(proposal)
    nodes: dict[str, Any] = {
        "root": {"type": "grid", "layout": {"columns": 24}, "children": children}
    }
    kpi_count = sum(widget.type == "metric-tile" for widget in proposal.widgets)
    kpi_span = 24 // max(2, min(kpi_count, 4))
    for index, widget in enumerate(proposal.widgets, 1):
        node_id = f"widget_{index}"
        dimensions = widget.dimension_names if widget.type != "metric-tile" else []
        metric_names = widget.metric_names
        is_trend = widget.chart_style == "line"
        is_chart = widget.type == "echarts"
        is_ranked = widget.chart_style == "ranked-bar"
        props: dict[str, Any] = {
            "dataBinding": {
                "datasetId": widget.dataset_id,
                "metrics": metric_names,
                "dimensions": dimensions,
                "rowLimit": RANKED_CATEGORY_LIMIT if is_ranked else 100,
                **({"orderByMetric": True} if is_ranked else {}),
            }
        }
        if widget.filter:
            props["dataBinding"]["filters"] = [
                {
                    "expressionType": "SIMPLE",
                    "clause": "WHERE",
                    "subject": widget.filter.column,
                    "operator": "==",
                    "comparator": widget.filter.value,
                }
            ]
        if widget.type == "metric-tile":
            props.update(_tile_display(widget, metric_names[0], metadata))
        if widget.type == "ag-grid-table" and widget.title:
            props["label"] = widget.title
        compound_table = widget.metrics is not None
        if compound_table:
            props["columnDefs"] = _table_columns(widget, metadata)
        if (compound_table and dimensions) or is_trend:
            props["dataBinding"]["orderByDimension"] = True
        if is_chart:
            props.update(_chart_display(widget, metadata))
        nodes[node_id] = {
            "type": widget.type,
            "layout": {
                "colSpan": kpi_span
                if widget.type == "metric-tile"
                else chart_spans.get(node_id, 24 if compound_table else 12),
                "rowSpan": 4 if widget.type == "metric-tile" else 11 if is_chart else 9,
            },
            "props": props,
        }
    if proposal.summary:
        nodes["summary"] = {
            "type": "markdown",
            "layout": {"colSpan": 24, "rowSpan": 4},
            "props": {"content": proposal.summary},
        }
    if proposal.content_locale:
        nodes["root"]["props"] = {
            "nxtbiLocalization": {
                "sourceLocale": proposal.content_locale,
                "title": {
                    "source": proposal.title,
                    "translations": proposal.title_translations,
                },
                "widgets": {
                    f"widget_{index}": {
                        "source": widget.title,
                        "translations": widget.title_translations,
                    }
                    for index, widget in enumerate(proposal.widgets, 1)
                    if widget.title and widget.title_translations
                },
            }
        }
    return {"version": 1, "root": "root", "nodes": nodes}
