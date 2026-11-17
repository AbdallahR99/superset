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
"""MCP tool: list_saved_widgets"""

import logging

from fastmcp import Context
from superset_core.mcp.decorators import tool, ToolAnnotations

from superset.extensions import event_logger
from superset.mcp_service.privacy import user_can_view_data_model_metadata
from superset.mcp_service.widgets.schemas import (
    ListSavedWidgetsRequest,
    SavedWidgetList,
    WidgetToolError,
)
from superset.mcp_service.widgets.utils import (
    serialize_saved_widget,
    widget_tool_error,
    widgets_disabled_error,
)

logger = logging.getLogger(__name__)


def _list_saved_widgets_impl(
    request: ListSavedWidgetsRequest,
) -> SavedWidgetList | WidgetToolError:
    """Pure logic: one page of the saved widgets the caller may list.

    Which widgets are visible is decided by ``ListSavedWidgetsCommand``, the
    command behind ``GET /api/v1/widget/``.
    """
    if (disabled := widgets_disabled_error()) is not None:
        return disabled
    # pylint: disable=import-outside-toplevel
    from superset.commands.widget.saved import ListSavedWidgetsCommand

    # The tool's pages are 1-based, the command's 0-based.
    command = ListSavedWidgetsCommand(
        page=request.page - 1, page_size=request.page_size
    )
    try:
        widgets = command.run()
    except Exception as ex:  # pylint: disable=broad-except
        return widget_tool_error(ex)

    include_metadata = user_can_view_data_model_metadata()
    items = [
        serialize_saved_widget(widget, include_data_model_metadata=include_metadata)
        for widget in widgets
    ]
    return SavedWidgetList(
        widgets=items,
        count=len(items),
        total_count=command.count,
        page=request.page,
        page_size=request.page_size,
    )


@tool(
    tags=["discovery"],
    class_permission_name="Chart",
    annotations=ToolAnnotations(
        title="List saved widgets",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=False,
    ),
)
async def list_saved_widgets(
    request: ListSavedWidgetsRequest | None = None,
    ctx: Context | None = None,
) -> SavedWidgetList | WidgetToolError:
    """List your saved widgets and those bound to datasets you can read.

    Admins see all saved widgets.

    Returns each widget's ``uuid``, ``widget_type``, ``title``, ``props`` and
    ``dataset_id``. Use ``get_widget_data`` with a ``uuid`` to fetch its rows.

    Example:
    ```json
    {"page": 1, "page_size": 25}
    ```
    """
    if ctx is None:
        raise RuntimeError("FastMCP context is required for list_saved_widgets")
    request = request or ListSavedWidgetsRequest()
    await ctx.info(
        "Listing saved widgets: page=%s, page_size=%s"
        % (request.page, request.page_size)
    )
    with event_logger.log_context(action="mcp.list_saved_widgets"):
        result = _list_saved_widgets_impl(request)
    if isinstance(result, WidgetToolError):
        await ctx.warning("Saved widget listing failed: %s" % (result.error_type,))
    return result
