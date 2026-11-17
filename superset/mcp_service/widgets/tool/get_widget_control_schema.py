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
"""MCP tool: get_widget_control_schema"""

import logging

from fastmcp import Context
from superset_core.mcp.decorators import tool, ToolAnnotations

from superset.extensions import event_logger
from superset.mcp_service.privacy import (
    requires_data_model_metadata_access,
    user_can_view_data_model_metadata,
)
from superset.mcp_service.widgets.schemas import (
    GetWidgetControlSchemaRequest,
    WidgetControlSchema,
    WidgetToolError,
)
from superset.mcp_service.widgets.utils import (
    data_model_metadata_denied_error,
    resolve_widget,
    unknown_widget_type_error,
    widgets_disabled_error,
)
from superset.widgets.schema_tools import (
    get_subtrees,
    prune_to_minimal_viable,
    SchemaPathError,
)

logger = logging.getLogger(__name__)

ENRICHMENT_WARNING = (
    "Could not shape the dynamic branches from control_values; "
    "returning the default schema."
)


def _get_widget_control_schema_impl(
    request: GetWidgetControlSchemaRequest,
) -> WidgetControlSchema | WidgetToolError:
    """Pure logic: the minimum-viable root schema, or the requested subtrees.

    ``control_values`` only shape x-dynamic branches (which datasets and
    columns a picker offers); nothing in them is executed as a query.
    """
    if (disabled := widgets_disabled_error()) is not None:
        return disabled
    # The schema's pickers enumerate dataset names and columns. The decorator
    # hides the tool from roles that may not see those; this enforces it for
    # direct calls.
    if not user_can_view_data_model_metadata():
        return data_model_metadata_denied_error()

    widget = resolve_widget(request.widget_type)
    if widget is None:
        return unknown_widget_type_error(request.widget_type)

    warning: str | None = None
    try:
        schema = widget.get_control_schema(request.control_values, request.series)
    except Exception:  # pylint: disable=broad-except
        # Same degradation as the REST endpoint: malformed dynamic values
        # yield the base schema rather than a failure.
        logger.exception(
            "Error enriching control schema for widget type %s", request.widget_type
        )
        warning = ENRICHMENT_WARNING
        schema = widget.get_control_schema(None, None)

    if not request.paths:
        return WidgetControlSchema(
            widget_type=request.widget_type,
            control_schema=prune_to_minimal_viable(schema),
            warning=warning,
        )
    try:
        subtrees = get_subtrees(schema, request.paths)
    except SchemaPathError as ex:
        return WidgetToolError.create(
            f"{ex} Call this tool without paths first, then drill into the "
            "x-path values of its x-collapsed nodes.",
            "ValidationError",
        )
    return WidgetControlSchema(
        widget_type=request.widget_type, subtrees=subtrees, warning=warning
    )


@tool(
    tags=["discovery"],
    class_permission_name="Chart",
    annotations=ToolAnnotations(
        title="Get widget control schema",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=False,
    ),
)
@requires_data_model_metadata_access
async def get_widget_control_schema(
    request: GetWidgetControlSchemaRequest, ctx: Context
) -> WidgetControlSchema | WidgetToolError:
    """Describe a Dashboard V2 widget type: its control JSON Schema
    (progressive disclosure).

    Without ``paths``, ``control_schema`` holds the minimum-viable root: every
    mandatory field expanded, cheap optional leaves inline, and optional
    nested branches as markers carrying ``x-collapsed: true`` and an
    ``x-path``. The mandatory fields alone are enough for a valid widget.

    With ``paths`` (each an ``x-path`` from a marker), ``subtrees`` holds one
    self-contained JSON Schema per path. Expand a branch only when the task
    needs that optional capability.

    A marker flagged ``x-dynamic: true`` depends on the current props: pass
    them as ``control_values`` (and known ``series`` values) to get its
    enriched shape. The values only shape the schema; no query is run.

    Example:
    ```json
    {"widget_type": "metric-tile", "paths": ["dataBinding"]}
    ```
    """
    await ctx.info(
        "Describing widget type: widget_type=%s, paths=%s"
        % (request.widget_type, request.paths)
    )
    with event_logger.log_context(action="mcp.get_widget_control_schema"):
        result = _get_widget_control_schema_impl(request)
    if isinstance(result, WidgetToolError):
        await ctx.warning("Widget schema lookup failed: %s" % (result.error_type,))
    return result
