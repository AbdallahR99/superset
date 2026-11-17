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
"""MCP tool: list_widget_types"""

import logging

from fastmcp import Context
from superset_core.mcp.decorators import tool, ToolAnnotations

from superset.extensions import event_logger
from superset.mcp_service.widgets.schemas import (
    WidgetToolError,
    WidgetTypeInfo,
    WidgetTypeList,
)
from superset.mcp_service.widgets.utils import registry, widgets_disabled_error

logger = logging.getLogger(__name__)


def _list_widget_types_impl() -> WidgetTypeList | WidgetToolError:
    """Pure logic: the registered schema-driven widget types."""
    if (disabled := widgets_disabled_error()) is not None:
        return disabled
    widget_types = [
        WidgetTypeInfo(
            id=cls.widget_type,
            name=cls.name,
            description=cls.description or "",
        )
        for cls in sorted(registry.values(), key=lambda cls: cls.widget_type)
    ]
    return WidgetTypeList(widget_types=widget_types, count=len(widget_types))


@tool(
    tags=["discovery"],
    class_permission_name="Chart",
    annotations=ToolAnnotations(
        title="List dashboard widget types",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=False,
    ),
)
async def list_widget_types(ctx: Context) -> WidgetTypeList | WidgetToolError:
    """List the Dashboard V2 widget types that have a schema-driven control
    panel.

    Takes no parameters. Pick a type's ``id``, then call
    ``get_widget_control_schema`` for its minimum-viable control schema.
    Returns each type's id, human name and description.
    """
    await ctx.info("Listing widget types")
    with event_logger.log_context(action="mcp.list_widget_types"):
        result = _list_widget_types_impl()
    if isinstance(result, WidgetToolError):
        await ctx.warning("Widget type listing failed: %s" % (result.error_type,))
    return result
