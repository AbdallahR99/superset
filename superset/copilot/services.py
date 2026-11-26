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

"""Scoped access to Superset MCP and Dashboard V2 authoring."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import jwt
from flask import current_app

from superset import db, security_manager
from superset.charts.schemas import ChartDataQueryContextSchema
from superset.commands.chart.data.get_data_command import ChartDataCommand
from superset.commands.dashboard_v2.save import (
    normalize_and_validate,
    raise_for_document_authoring,
)
from superset.common.query_context_factory import QueryContextFactory
from superset.connectors.sqla.models import SqlaTable
from superset.copilot.contracts import (
    AggregateArguments,
    DashboardProposal,
    GetArguments,
    ListArguments,
    make_document,
    percent_precision,
    ProfileArguments,
    ProposalWidget,
    ToolRequest,
)
from superset.mcp_service.privacy import user_can_view_data_model_metadata
from superset.utils import json
from superset.widgets.data import build_widget_query, resolved_filters_to_adhoc


class CopilotAccessError(ValueError):
    """Requested metadata or dashboard authoring is unavailable to this user."""


class CopilotToolError(RuntimeError):
    """The configured MCP service could not complete a scoped read."""


_READ_TOOLS = {
    "list_datasets": ("list_datasets", "datasets", ("id", "table_name", "description")),
    "get_dataset": (
        "get_dataset_info",
        None,
        ("id", "table_name", "description", "columns", "metrics"),
    ),
    "list_dashboards": (
        "list_dashboards",
        "dashboards",
        ("id", "dashboard_title", "description"),
    ),
    "get_dashboard": (
        "get_dashboard_info",
        None,
        ("id", "dashboard_title", "description"),
    ),
    "list_charts": (
        "list_charts",
        "charts",
        ("id", "slice_name", "description", "viz_type"),
    ),
    "get_chart": (
        "get_chart_info",
        None,
        ("id", "slice_name", "description", "viz_type"),
    ),
}


def delegated_mcp_token(
    username: str, config: Mapping[str, Any], *, now: int | None = None
) -> str:
    """Mint a short-lived token for the initiating Superset principal."""
    secret = config.get("MCP_JWT_SECRET")
    issuer = config.get("MCP_JWT_ISSUER")
    audience = config.get("MCP_JWT_AUDIENCE")
    if (
        not isinstance(secret, str)
        or len(secret) < 32
        or not isinstance(issuer, str)
        or not isinstance(audience, str)
        or config.get("MCP_JWT_ALGORITHM") != "HS256"
        or not config.get("MCP_AUTH_ENABLED")
    ):
        raise CopilotToolError("The Copilot requires authenticated MCP delegation.")
    timestamp = int(time.time()) if now is None else now
    return jwt.encode(
        {
            "sub": username,
            "preferred_username": username,
            "iss": issuer,
            "aud": audience,
            "iat": timestamp,
            "exp": timestamp + 30,
            "client_id": "nxtbi-copilot",
            "scope": "superset:read",
        },
        secret,
        algorithm="HS256",
    )


async def _call_mcp(
    url: str, token: str, tool: str, request: dict[str, Any]
) -> dict[str, Any]:
    """Discover and invoke only the exact configured MCP read tool."""
    from fastmcp import Client

    async with asyncio.timeout(14), Client(url, auth=token, timeout=10) as client:
        tools = await client.list_tools(max_pages=5)
        if not any(item.name == tool for item in tools):
            raise CopilotAccessError("This tool is unavailable to the current user.")
        result = await client.call_tool(
            tool, {"request": request}, raise_on_error=False
        )
        if result.is_error:
            raise CopilotAccessError("The metadata is unavailable to the current user.")
        payload = result.structured_content
        if payload is None and len(result.content) == 1:
            payload = json.loads(getattr(result.content[0], "text", "null"))
    if isinstance(payload, dict) and isinstance(payload.get("result"), dict):
        payload = payload["result"]
    if not isinstance(payload, dict) or payload.get("error"):
        raise CopilotAccessError("The metadata is unavailable to the current user.")
    return payload


def _public_metadata(value: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    """Project away raw SQL, chart config and other unused tool response fields."""
    if not isinstance(value, dict):
        return {}
    item = {
        name: value[name][:480] if isinstance(value[name], str) else value[name]
        for name in fields
        if name in value and type(value[name]) in (int, str)
    }
    for collection, name in (("columns", "column_name"), ("metrics", "metric_name")):
        if collection not in fields or not isinstance(value.get(collection), list):
            continue
        item[collection] = [
            row[name][:256]
            for row in value[collection][:50]
            if isinstance(row, dict) and isinstance(row.get(name), str)
        ]
        if collection == "columns":
            for flag, key in (
                ("groupby", "groupable_columns"),
                ("filterable", "filterable_columns"),
                ("is_dttm", "temporal_columns"),
            ):
                item[key] = [
                    row[name][:256]
                    for row in value[collection][:50]
                    if isinstance(row, dict)
                    and isinstance(row.get(name), str)
                    and row.get(flag) is True
                ]
        else:
            item["metric_details"] = [
                {
                    key: row[key][:256]
                    for key in (
                        "metric_name",
                        "verbose_name",
                        "description",
                        "d3format",
                    )
                    if isinstance(row.get(key), str) and row[key]
                }
                for row in value[collection][:50]
                if isinstance(row, dict) and isinstance(row.get(name), str)
            ]
    return item


def _public_page(
    payload: dict[str, Any], collection: str, fields: tuple[str, ...]
) -> dict[str, Any]:
    """Preserve only authorized metadata and validated pagination facts."""
    rows = payload.get(collection)
    if not isinstance(rows, list):
        raise CopilotToolError("The Superset MCP service returned invalid metadata.")
    result: dict[str, Any] = {
        "items": [_public_metadata(row, fields) for row in rows[:12]]
    }
    if type(total_count := payload.get("total_count")) is int and total_count >= 0:
        result["total_count"] = total_count
    if type(has_next := payload.get("has_next")) is bool:
        result["has_next"] = has_next
    return result


def read_metadata(user: Any, call: ToolRequest) -> dict[str, Any]:
    """Dispatch a scoped MCP read for the actor already validated by the gateway."""
    name, collection, fields = _READ_TOOLS[call.name]
    selected = list(fields)
    if collection:
        arguments = ListArguments.model_validate(call.arguments)
        request: dict[str, Any] = {"page_size": 12, "select_columns": selected}
        if arguments.query:
            request["search"] = arguments.query
    else:
        resource_id = GetArguments.model_validate(call.arguments).id
        request = {"identifier": resource_id}
        if name == "get_dataset_info":
            request["select_columns"] = selected
            request["column_fields"] = [
                "column_name",
                "groupby",
                "filterable",
                "is_dttm",
            ]
    url = current_app.config.get("NXTBI_COPILOT_MCP_URL")
    if not url:
        raise CopilotToolError("The Copilot MCP endpoint is not configured.")
    token = delegated_mcp_token(user.username, current_app.config)
    try:
        payload = asyncio.run(_call_mcp(url, token, name, request))
    except CopilotAccessError:
        raise
    except Exception as error:
        # Do not expose client library exceptions which can include the bearer.
        raise CopilotToolError("The Superset MCP service did not respond.") from error
    if collection:
        return _public_page(payload, collection, fields)
    item = _public_metadata(payload, fields)
    if not item.get("id"):
        raise CopilotAccessError("The metadata is unavailable to the current user.")
    return item


def _evidence_dataset(dataset_id: int) -> SqlaTable:
    """Authorize both metadata inspection and chart-data execution as the actor."""
    if not (
        user_can_view_data_model_metadata()
        and security_manager.can_access("can_read", "Dataset")
        and security_manager.can_access("can_read", "Chart")
    ):
        raise CopilotAccessError("Dataset evidence is unavailable.")
    dataset = db.session.get(SqlaTable, dataset_id)
    if dataset is None or dataset.deleted_at is not None:
        raise CopilotAccessError("Dataset evidence is unavailable.")
    dataset.raise_for_access()
    return dataset


def _evidence_rows(
    binding: dict[str, Any], filters: list[dict[str, Any]], *, ordered: bool = False
) -> list[dict[str, Any]]:
    """Execute one widget query under the active user's chart-data access and RLS."""
    dataset_id, query, form = build_widget_query({"dataBinding": binding}, filters)
    if ordered:
        query["orderby"] = [[binding["metrics"][0], False]]
    schema = ChartDataQueryContextSchema()
    schema.query_context_factory = QueryContextFactory(
        authorize_semantic_before_metadata=True
    )
    context = schema.load(
        {
            "datasource": {"id": dataset_id, "type": "table"},
            "queries": [query],
            "form_data": form,
            "result_format": "json",
            "result_type": "results",
        }
    )
    command = ChartDataCommand(context)
    command.validate()
    data = command.run()["queries"][0].get("data")
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        raise CopilotToolError("The aggregate result is unavailable.")
    return data


def _temporal_bound(value: object) -> str | None:
    """Serialize a database temporal aggregate as an ISO date or timestamp."""
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and len(value) <= 64:
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            try:
                return datetime.fromisoformat(value).isoformat()
            except ValueError:
                pass
    raise CopilotToolError("The temporal aggregate is unavailable.")


def _aggregate_count(row: dict[str, Any], key: str) -> int:
    """Accept only a measured count, including a genuine zero."""
    value = row.get(key)
    if type(value) is not int or value < 0:
        raise CopilotToolError("The aggregate counts are unavailable.")
    return value


def profile_dataset(args: ProfileArguments) -> dict[str, Any]:
    """Measure visible counts and temporal bounds in one aggregate query."""
    dataset = _evidence_dataset(args.id)
    columns = {column.column_name: column for column in dataset.columns}
    if set(args.columns) - columns.keys():
        raise ValueError("Choose existing dataset columns.")
    metrics: list[dict[str, Any]] = [
        {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "row_count"}
    ]
    for i, name in enumerate(args.columns):
        aggregates = [("COUNT", "present"), ("COUNT_DISTINCT", "distinct")]
        if columns[name].is_dttm:
            aggregates.extend([("MIN", "earliest"), ("MAX", "latest")])
        for aggregate, prefix in aggregates:
            metrics.append(
                {
                    "expressionType": "SIMPLE",
                    "aggregate": aggregate,
                    "column": {"column_name": name},
                    "label": f"{prefix}_{i}",
                }
            )
    rows = _evidence_rows({"datasetId": args.id, "metrics": metrics, "rowLimit": 1}, [])
    if len(rows) != 1:
        raise CopilotToolError("The aggregate counts are unavailable.")
    row = rows[0]
    total = _aggregate_count(row, "row_count")
    profiles = []
    for i, name in enumerate(args.columns):
        present = _aggregate_count(row, f"present_{i}")
        profile: dict[str, str | int | None] = {
            "column_name": name,
            "non_null_count": present,
            "null_count": total - present,
            "distinct_count": _aggregate_count(row, f"distinct_{i}"),
        }
        if columns[name].is_dttm:
            for bound in ("earliest", "latest"):
                if f"{bound}_{i}" not in row:
                    raise CopilotToolError("The temporal aggregate is unavailable.")
                profile[bound] = _temporal_bound(row[f"{bound}_{i}"])
        profiles.append(profile)
    return {"dataset_id": args.id, "row_count": total, "columns": profiles}


def _metric_number(value: object) -> int | float | None:
    """Normalize a chart metric to a finite JSON number while preserving nulls."""
    if value is None:
        return None
    if isinstance(value, Decimal) and value.is_finite():
        value = float(value)
    if type(value) is int or (type(value) is float and math.isfinite(value)):
        return value
    raise CopilotToolError("The requested metric did not return a numeric value.")


def aggregate_dataset(args: AggregateArguments) -> dict[str, Any]:
    """Read a saved metric with at most ten groups and one equality predicate."""
    dataset = _evidence_dataset(args.id)
    if args.metric not in {m.metric_name for m in dataset.metrics}:
        raise ValueError("Choose an existing metric.")
    if args.dimension and args.dimension not in {
        col.column_name for col in dataset.columns if col.groupby
    }:
        raise ValueError("Choose a groupable dataset column.")
    if args.dimension == args.metric:
        raise ValueError("Choose a dimension with a distinct result label.")
    filters = []
    if args.filter:
        filters = resolved_filters_to_adhoc(
            [{**args.filter.model_dump(), "operator": "EQUALS"}],
            {col.column_name for col in dataset.columns if col.filterable},
        )
    rows = _evidence_rows(
        {
            "datasetId": args.id,
            "metrics": [args.metric],
            "dimensions": [args.dimension] if args.dimension else [],
            "rowLimit": 11 if args.dimension else 1,
        },
        filters,
        ordered=bool(args.dimension),
    )
    result = []
    for row in rows[:10]:
        if args.metric not in row or (args.dimension and args.dimension not in row):
            raise CopilotToolError("The aggregate fields are unavailable.")
        value = _metric_number(row[args.metric])
        group = row.get(args.dimension) if args.dimension else None
        if isinstance(group, date):
            group = group.isoformat()
        if group is not None and (
            type(group) not in (bool, int, float, str)
            or (isinstance(group, str) and len(group) > 256)
            or (isinstance(group, float) and not math.isfinite(group))
        ):
            raise CopilotToolError("The group label cannot be displayed.")
        result.append({"group": group, "value": value})
    return {
        "dataset_id": args.id,
        "metric": args.metric,
        "dimension": args.dimension,
        "rows": result,
        "truncated": len(rows) > 10,
    }


def _validate_widget_columns(widget: ProposalWidget, dataset: SqlaTable) -> None:
    """Validate each analytical use against the registered dataset column flags."""
    if widget.dimension and widget.dimension not in {
        column.column_name for column in dataset.columns if column.groupby
    }:
        raise ValueError("Choose a groupable dataset column.")
    if widget.filter and widget.filter.column not in {
        column.column_name for column in dataset.columns if column.filterable
    }:
        raise ValueError("Choose a filterable dataset column.")
    if widget.chart_style == "line" and widget.dimension not in {
        column.column_name for column in dataset.columns if column.is_dttm
    }:
        raise ValueError("Choose a temporal dataset column for a line chart.")


def validate_proposal_references(
    proposal: DashboardProposal,
) -> dict[tuple[int, str], int]:
    """Verify persisted dataset references and return saved percentage precision."""
    if not security_manager.can_access("can_write", "Dashboard"):
        raise CopilotAccessError("The current user cannot create dashboards.")
    if proposal.dashboard_type == "v1" and not security_manager.can_access(
        "can_write", "Chart"
    ):
        raise CopilotAccessError("The current user cannot create charts.")
    if not user_can_view_data_model_metadata():
        raise CopilotAccessError("The requested dataset metadata is unavailable.")
    datasets: dict[int, SqlaTable] = {}
    percentages: dict[tuple[int, str], int] = {}
    for widget in proposal.widgets:
        if proposal.dashboard_type == "v1" and len(widget.title or "") > 250:
            raise ValueError("Classic chart titles must be at most 250 characters.")
        if widget.dataset_id not in datasets:
            dataset = db.session.get(SqlaTable, widget.dataset_id)
            if dataset is None or dataset.deleted_at is not None:
                raise CopilotAccessError("The requested dataset is unavailable.")
            dataset.raise_for_access()
            datasets[widget.dataset_id] = dataset
        dataset = datasets[widget.dataset_id]
        metric = next(
            (item for item in dataset.metrics if item.metric_name == widget.metric),
            None,
        )
        if metric is None:
            raise ValueError("Choose an existing dataset metric.")
        if (
            widget.type == "metric-tile"
            and (precision := percent_precision(metric.d3format)) is not None
        ):
            percentages[(widget.dataset_id, widget.metric)] = precision
        _validate_widget_columns(widget, dataset)
    return percentages


def validate_dashboard_proposal(proposal: DashboardProposal) -> dict[str, Any]:
    """Compile validated references and invoke the normal V2 authoring guard."""
    percentages = validate_proposal_references(proposal)
    document = normalize_and_validate(make_document(proposal, percentages))
    raise_for_document_authoring(document, None)
    return document
