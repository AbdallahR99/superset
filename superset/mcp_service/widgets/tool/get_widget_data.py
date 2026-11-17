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
"""MCP tool: get_widget_data"""

import logging

from fastmcp import Context
from superset_core.mcp.decorators import tool, ToolAnnotations

from superset.extensions import event_logger
from superset.mcp_service.widgets.schemas import (
    GetWidgetDataRequest,
    WidgetDataResponse,
    WidgetToolError,
)
from superset.mcp_service.widgets.utils import (
    jsonable,
    widget_tool_error,
    widgets_disabled_error,
)

logger = logging.getLogger(__name__)


def _get_widget_data_impl(
    request: GetWidgetDataRequest,
) -> WidgetDataResponse | WidgetToolError:
    """Pure logic: run a saved widget's query through ``WidgetDataCommand``.

    Only the saved-widget selector is ever built here, so the query comes from
    props stored on the server; the command (shared with
    ``POST /api/v1/widget/data``) applies dataset permissions and row-level
    security and accepts the filters only as structured column comparisons.
    """
    if (disabled := widgets_disabled_error()) is not None:
        return disabled
    # pylint: disable=import-outside-toplevel
    from superset.commands.widget.data import WidgetDataCommand

    try:
        result = WidgetDataCommand(
            {"id": request.id},
            [resolved.model_dump() for resolved in request.filters],
        ).run()
    except Exception as ex:  # pylint: disable=broad-except
        return widget_tool_error(ex)

    payload = jsonable(result)
    rows = payload.get("rows") or []
    return WidgetDataResponse(
        columns=payload.get("columns") or [],
        rows=rows,
        row_count=len(rows),
    )


@tool(
    tags=["data"],
    class_permission_name="Chart",
    annotations=ToolAnnotations(
        title="Get widget data",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=False,
    ),
)
async def get_widget_data(
    request: GetWidgetDataRequest, ctx: Context
) -> WidgetDataResponse | WidgetToolError:
    """Run a saved widget's query and return its rows, as the calling user.

    ``id`` is a saved widget uuid (see ``list_saved_widgets``). The query is
    built server-side from the widget's stored props; ``filters`` can only
    narrow it with column comparisons. Dataset permissions and row-level
    security apply. Inline widget definitions and SQL are not accepted.

    Example:
    ```json
    {
        "id": "cedf0501-fa36-4e19-9f84-e9da6d657dcc",
        "filters": [{"column": "state", "operator": "IN", "value": ["CA", "NY"]}]
    }
    ```

    Returns ``columns``, ``rows`` and ``row_count``, or an error with
    ``error_type`` NotFound, Forbidden or ValidationError.
    """
    await ctx.info(
        "Fetching widget data: id=%s, filter_count=%s"
        % (request.id, len(request.filters))
    )
    with event_logger.log_context(action="mcp.get_widget_data.query"):
        result = _get_widget_data_impl(request)
    if isinstance(result, WidgetToolError):
        await ctx.warning("Widget data fetch failed: %s" % (result.error_type,))
    else:
        await ctx.info("Widget data fetched: row_count=%s" % (result.row_count,))
    return result
