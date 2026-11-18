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
import time
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, StringConstraints

from superset.utils import json

RUN_AUDIENCE = "nxtbi-copilot"
APPROVAL_AUDIENCE = "nxtbi-dashboard-approval"
RUN_TTL = 240
APPROVAL_TTL = 900
MAX_BODY_BYTES = 128 * 1024

ShortText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]
ResourceId = Annotated[int, Field(gt=0, le=2**31 - 1)]
WireId = Annotated[str, StringConstraints(pattern=r"^[\w-]{1,80}$")]


class Contract(BaseModel):
    """Reject coercion and unknown fields at the tool boundary."""

    model_config = ConfigDict(strict=True, extra="forbid")


class AggregateFilter(Contract):
    """An equality constraint on one registered dataset column."""

    column: ShortText
    value: ShortText | bool | int | Annotated[float, Field(allow_inf_nan=False)]


class ProposalWidget(Contract):
    """A widget bound solely to an existing metric and dataset column."""

    type: Literal["metric-tile", "ag-grid-table", "echarts"]
    dataset_id: ResourceId = Field(alias="datasetId")
    metric: ShortText
    dimension: ShortText | None = None
    title: ShortText | None = None
    chart_style: Literal["bar", "line"] | None = Field(default=None, alias="chartStyle")
    filter: AggregateFilter | None = None

    @model_validator(mode="after")
    def validate_dimension(self) -> ProposalWidget:
        """A category chart needs an existing grouping column."""
        if self.type == "echarts" and self.dimension is None:
            raise ValueError("A chart requires a grouping column.")
        if self.type != "echarts" and self.chart_style is not None:
            raise ValueError("Chart style is only available on charts.")
        return self


class DashboardProposal(Contract):
    """A draft layout that can be generated or edited before approval."""

    title: ShortText
    widgets: list[ProposalWidget] = Field(min_length=1, max_length=8)


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
    url: str = Field(pattern=r"^/dashboard/v2/[1-9][0-9]{0,9}/$")

    @model_validator(mode="after")
    def validate_dashboard_url(self) -> CopilotHistoryDashboard:
        """Keep the saved dashboard link tied to the matching ID."""
        if self.url != f"/dashboard/v2/{self.id}/":
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


def make_document(
    proposal: DashboardProposal,
    percentages: dict[tuple[int, str], int] | None = None,
) -> dict[str, Any]:
    """Compile the allowed widget choices through the Dashboard V2 document format."""
    children: list[str] = []
    nodes: dict[str, Any] = {
        "root": {"type": "grid", "layout": {"columns": 24}, "children": children}
    }
    kpi_count = sum(widget.type == "metric-tile" for widget in proposal.widgets)
    kpi_span = 24 // max(2, min(kpi_count, 4))
    for index, widget in enumerate(proposal.widgets, 1):
        node_id = f"widget_{index}"
        children.append(node_id)
        props: dict[str, Any] = {
            "dataBinding": {
                "datasetId": widget.dataset_id,
                "metrics": [widget.metric],
                "dimensions": (
                    [widget.dimension]
                    if widget.dimension and widget.type != "metric-tile"
                    else []
                ),
                "rowLimit": 100,
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
            props["label"] = widget.title or widget.metric
            precision = (percentages or {}).get((widget.dataset_id, widget.metric))
            if precision is not None:
                props.update(percentage=True, decimals=precision)
        if widget.type == "ag-grid-table" and widget.title:
            props["label"] = widget.title
        is_trend = widget.chart_style == "line"
        if widget.type == "echarts":
            axis_binding = {"source": "dimension", "alias": widget.dimension}
            if is_trend:
                props["dataBinding"]["orderByDimension"] = True
                axis_binding["format"] = "date"
            props["crossFilter"] = not is_trend
            props["echartsOptions"] = {
                "animation": False,
                "grid": {"left": 64, "right": 24, "bottom": 40, "top": 48},
                "tooltip": {"trigger": "axis", "renderMode": "richText"},
                "xAxis": {
                    "type": "category",
                    "axisLabel": {"hideOverlap": True},
                    "data": {"$bind": axis_binding},
                },
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": widget.chart_style or "bar",
                        "data": {"$bind": {"source": "metric", "alias": widget.metric}},
                    }
                ],
            }
            if widget.title:
                props["echartsOptions"]["title"] = {"text": widget.title}
        nodes[node_id] = {
            "type": widget.type,
            "layout": {
                "colSpan": kpi_span
                if widget.type == "metric-tile"
                else 24
                if is_trend
                else 12,
                "rowSpan": 4 if widget.type == "metric-tile" else 9,
            },
            "props": props,
        }
    return {"version": 1, "root": "root", "nodes": nodes}
