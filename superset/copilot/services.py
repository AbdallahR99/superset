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
import time
from collections.abc import Mapping
from typing import Any

import jwt
from flask import current_app

from superset import db, security_manager
from superset.commands.dashboard_v2.save import (
    normalize_and_validate,
    raise_for_document_authoring,
)
from superset.connectors.sqla.models import SqlaTable
from superset.copilot.contracts import (
    DashboardProposal,
    GetArguments,
    ListArguments,
    make_document,
    ToolRequest,
)
from superset.mcp_service.privacy import user_can_view_data_model_metadata
from superset.utils import json


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
            item["groupable_columns"] = [
                row[name][:256]
                for row in value[collection][:50]
                if isinstance(row, dict)
                and isinstance(row.get(name), str)
                and row.get("groupby") is True
            ]
    return item


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
            request["column_fields"] = ["column_name", "groupby"]
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
        rows = payload.get(collection)
        if not isinstance(rows, list):
            raise CopilotToolError(
                "The Superset MCP service returned invalid metadata."
            )
        return {"items": [_public_metadata(row, fields) for row in rows[:12]]}
    item = _public_metadata(payload, fields)
    if not item.get("id"):
        raise CopilotAccessError("The metadata is unavailable to the current user.")
    return item


def validate_dashboard_proposal(proposal: DashboardProposal) -> dict[str, Any]:
    """Resolve existing data references and invoke the normal V2 authoring guard."""
    if not security_manager.can_access("can_write", "Dashboard"):
        raise CopilotAccessError("The current user cannot create dashboards.")
    if not user_can_view_data_model_metadata():
        raise CopilotAccessError("The requested dataset metadata is unavailable.")
    datasets: dict[int, SqlaTable] = {}
    for widget in proposal.widgets:
        if widget.dataset_id not in datasets:
            dataset = db.session.get(SqlaTable, widget.dataset_id)
            if dataset is None or dataset.deleted_at is not None:
                raise CopilotAccessError("The requested dataset is unavailable.")
            dataset.raise_for_access()
            datasets[widget.dataset_id] = dataset
        dataset = datasets[widget.dataset_id]
        if widget.metric not in {metric.metric_name for metric in dataset.metrics}:
            raise ValueError("Choose an existing dataset metric.")
        if widget.dimension and widget.dimension not in {
            column.column_name for column in dataset.columns if column.groupby
        }:
            raise ValueError("Choose a groupable dataset column.")
    document = normalize_and_validate(make_document(proposal))
    raise_for_document_authoring(document, None)
    return document
