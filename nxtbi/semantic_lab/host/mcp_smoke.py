# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Verify the registered lab view through the native in-process MCP tools."""

from __future__ import annotations

import argparse
import asyncio
import math
import os
from typing import TypeVar

from fastmcp import Client
from pydantic import BaseModel

from superset.mcp_service.semantic_layer.schemas import (
    CompatibleDimensionsResponse,
    GetTableResponse,
    MetricList,
    SemanticViewPage,
)
from superset.utils import json

PROVIDER = "extensions.nxtbi.property-market-lab.market"
VIEW = "property_transactions"
EXPECTED_METRICS = {
    "average_transaction_price": 400000.0,
    "weighted_price_per_sqm": 2280000 / 610,
    "transaction_count": 6,
    "distinct_property_count": 4,
}
DIMENSIONS = {"district", "property_type", "sale_date", "registration_date"}

Response = TypeVar("Response", bound=BaseModel)


async def _call(
    client: Client,
    name: str,
    request: dict[str, object],
    schema: type[Response],
) -> Response:
    """Check and decode the normal MCP tool response."""
    result = await client.call_tool(name, {"request": request}, raise_on_error=False)
    if result.is_error:
        raise RuntimeError(f"MCP tool call failed: {name}")

    payload: object = result.structured_content
    if payload is None and len(result.content) == 1:
        payload = json.loads(getattr(result.content[0], "text", "null"))
    if isinstance(payload, dict) and isinstance(payload.get("result"), dict):
        payload = payload["result"]
    if not isinstance(payload, dict):
        raise RuntimeError(f"Invalid MCP response: {name}")
    if payload.get("success") is False or payload.get("error"):
        raise RuntimeError(
            f"MCP returned {payload.get('error_type', 'an error')}: {name}"
        )
    return schema.model_validate(payload)


def _verify_totals(table: GetTableResponse, view_id: int) -> None:
    """Check the native query against independently calculated fixture totals."""
    if table.source != "external" or table.view_id != view_id or len(table.data) != 1:
        raise RuntimeError("The native semantic query must return one aggregate row.")
    row = table.data[0]
    for name, expected in EXPECTED_METRICS.items():
        value = row.get(name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isclose(value, expected, rel_tol=1e-9)
        ):
            raise RuntimeError(f"Unexpected aggregate for {name}.")


async def verify(username: str) -> None:
    """Discover an accessible view, inspect its members, and check its totals."""
    from superset.mcp_service import flask_singleton
    from superset.mcp_service.app import mcp

    app = flask_singleton.app
    if "/semantic-lab-extension" not in app.config.get("LOCAL_EXTENSIONS", ()):
        raise RuntimeError(
            "The isolated property-market lab configuration is required."
        )
    if app.config.get("MCP_AUTH_ENABLED"):
        raise RuntimeError(
            "Use the authenticated transport for an MCP auth deployment."
        )
    if app.config.get("MCP_DATASET_ROLE_ALLOWLIST") is not None:
        raise RuntimeError("External semantic views require standard MCP routing.")

    # The FastMCP Client object below uses its in-memory transport. This process
    # serves no port, and the configured user still passes native RBAC and DAO checks.
    app.config["MCP_DEV_USERNAME"] = username
    async with Client(mcp) as client:
        views = await _call(
            client, "list_semantic_views", {"search": VIEW}, SemanticViewPage
        )
        matching_ids = [
            item.source.id
            for item in views.sources
            if item.provider == PROVIDER and item.name == VIEW
        ]
        if len(matching_ids) != 1:
            raise RuntimeError(
                "Expected exactly one registered property_transactions view."
            )
        view_id = matching_ids[0]

        metrics = await _call(client, "list_metrics", {"view_id": view_id}, MetricList)
        selected = {
            item.name: item
            for item in metrics.metrics
            if item.source == "external" and item.view_id == view_id
        }
        if metrics.incomplete or not EXPECTED_METRICS.keys() <= selected.keys():
            raise RuntimeError("The external metric catalog is incomplete.")

        compatible = await _call(
            client,
            "get_compatible_dimensions",
            {"view_id": view_id, "selected_metrics": list(EXPECTED_METRICS)},
            CompatibleDimensionsResponse,
        )
        dimensions = {dimension.name for dimension in compatible.compatible_dimensions}
        if compatible.source != "external" or not DIMENSIONS <= dimensions:
            raise RuntimeError(
                "The external metric selection lost compatible dimensions."
            )

        versions = {
            selected[name].semantic_selection_version for name in EXPECTED_METRICS
        }
        if len(versions) != 1:
            raise RuntimeError("Catalog metrics reported different selection versions.")
        request: dict[str, object] = {
            "view_id": view_id,
            "metrics": list(EXPECTED_METRICS),
            "row_limit": 1,
            "use_cache": False,
        }
        if (version := versions.pop()) is not None:
            request["semantic_selection_version"] = version

        table = await _call(client, "get_table", request, GetTableResponse)
        _verify_totals(table, view_id)

    print(
        "PASS native in-process MCP: registered view, four metrics, compatible "
        "dimensions, and correct transaction, property, and price aggregates",
        flush=True,
    )


def main() -> None:
    """Select the existing disposable Superset lab principal."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default=os.environ.get("NXTBI_SEMANTIC_LAB_USER"))
    args = parser.parse_args()
    if not args.username:
        parser.error("--username or NXTBI_SEMANTIC_LAB_USER is required.")
    asyncio.run(verify(args.username))


if __name__ == "__main__":
    main()
