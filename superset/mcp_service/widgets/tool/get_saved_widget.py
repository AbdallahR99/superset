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
"""MCP tool: get_saved_widget"""

import logging

from fastmcp import Context
from superset_core.mcp.decorators import tool, ToolAnnotations

from superset.extensions import event_logger
from superset.mcp_service.privacy import user_can_view_data_model_metadata
from superset.mcp_service.widgets.schemas import (
    GetSavedWidgetRequest,
    SavedWidgetInfo,
    WidgetToolError,
)
from superset.mcp_service.widgets.utils import (
    serialize_saved_widget,
    widget_tool_error,
    widgets_disabled_error,
)

logger = logging.getLogger(__name__)


def _get_saved_widget_impl(
    request: GetSavedWidgetRequest,
) -> SavedWidgetInfo | WidgetToolError:
    """Pure logic: one saved widget, read through ``GetSavedWidgetCommand``.

    The command is the one behind ``GET /api/v1/widget/<uuid>``, so the same
    read rule applies.
    """
    if (disabled := widgets_disabled_error()) is not None:
        return disabled
    # pylint: disable=import-outside-toplevel
    from superset.commands.widget.saved import GetSavedWidgetCommand

    try:
        widget = GetSavedWidgetCommand(request.id).run()
    except Exception as ex:  # pylint: disable=broad-except
        return widget_tool_error(ex)

    return serialize_saved_widget(
        widget, include_data_model_metadata=user_can_view_data_model_metadata()
    )


@tool(
    tags=["discovery"],
    class_permission_name="Chart",
    annotations=ToolAnnotations(
        title="Get saved widget",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=False,
    ),
)
async def get_saved_widget(
    request: GetSavedWidgetRequest, ctx: Context
) -> SavedWidgetInfo | WidgetToolError:
    """Get a saved widget's definition: its type, title, props and dataset.

    Example:
    ```json
    {"id": "cedf0501-fa36-4e19-9f84-e9da6d657dcc"}
    ```

    Returns ``uuid``, ``widget_type``, ``title``, ``props``, ``dataset_id``
    and ``changed_on``, or an error with ``error_type`` NotFound or Forbidden.
    Use ``get_widget_data`` with the same ``id`` to fetch its rows.
    """
    await ctx.info("Retrieving saved widget: id=%s" % (request.id,))
    with event_logger.log_context(action="mcp.get_saved_widget"):
        result = _get_saved_widget_impl(request)
    if isinstance(result, WidgetToolError):
        await ctx.warning("Saved widget lookup failed: %s" % (result.error_type,))
    return result
