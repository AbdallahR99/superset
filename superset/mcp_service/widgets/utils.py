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
"""Shared helpers for the widget MCP tools.

The tools are a thin adapter over ``superset.commands.widget`` (the layer the
REST API calls), so permission checks, row-level security and query building
live in one place. This module only gates on the feature flag, maps command
failures onto the tools' structured error and serializes results.
"""

from __future__ import annotations

import logging
from typing import Any

from superset_core.widgets import Widget

from superset.commands.exceptions import (
    CommandException,
    ForbiddenError,
    ObjectNotFoundError,
)
from superset.commands.widget.exceptions import WidgetInvalidError
from superset.exceptions import SupersetSecurityException
from superset.mcp_service.privacy import (
    DATA_MODEL_METADATA_ERROR_MESSAGE,
    DATA_MODEL_METADATA_ERROR_TYPE,
)
from superset.mcp_service.widgets.schemas import SavedWidgetInfo, WidgetToolError
from superset.utils import json
from superset.widgets.feature import DASHBOARD_V2_FLAG, is_dashboard_v2_enabled
from superset.widgets.registry import registry

logger = logging.getLogger(__name__)

WIDGETS_FEATURE_FLAG = DASHBOARD_V2_FLAG

#: Every tool name this package registers; ``app.py`` removes them from the
#: server when the feature flag is off.
WIDGET_TOOL_NAMES: tuple[str, ...] = (
    "list_widget_types",
    "get_widget_control_schema",
    "list_saved_widgets",
    "get_saved_widget",
    "get_widget_data",
)


def widgets_disabled_error() -> WidgetToolError | None:
    """An error when the widget framework is switched off, else ``None``.

    Uses the gate the widget REST API uses (``superset.widgets.feature``).
    That API answers 404 in this case; a tool call gets the equivalent
    structured error before any command or registry lookup runs.
    """
    if is_dashboard_v2_enabled():
        return None
    return WidgetToolError.create(
        "Widgets are not enabled on this instance.", "FeatureDisabled"
    )


def data_model_metadata_denied_error() -> WidgetToolError:
    """The error for a role that may not inspect dataset details."""
    return WidgetToolError.create(
        DATA_MODEL_METADATA_ERROR_MESSAGE, DATA_MODEL_METADATA_ERROR_TYPE
    )


def widget_tool_error(ex: Exception) -> WidgetToolError:
    """Map a widget command failure onto the tools' structured error.

    Unexpected failures are logged and reported with a fixed message so
    internal details (SQL, stack traces) never reach the caller.
    """
    if isinstance(ex, ObjectNotFoundError):
        return WidgetToolError.create(str(ex.message), "NotFound")
    if isinstance(ex, (ForbiddenError, SupersetSecurityException)):
        return WidgetToolError.create(
            "You don't have access to this widget or its data.", "Forbidden"
        )
    if isinstance(ex, WidgetInvalidError):
        return WidgetToolError.create(str(ex.message), "ValidationError", ex.errors)
    if isinstance(ex, CommandException):
        return WidgetToolError.create(str(ex.message), "CommandError")
    logger.exception("Unexpected error in widget tool")
    return WidgetToolError.create(
        "Unexpected error while handling the widget request.", "UnexpectedError"
    )


def valid_widget_types() -> list[str]:
    """The registered widget type ids, sorted."""
    return sorted(cls.widget_type for cls in registry.values())


def resolve_widget(widget_type: str) -> type[Widget] | None:
    """The registered widget class for a type id, if any."""
    return registry.get(widget_type)


def unknown_widget_type_error(widget_type: str) -> WidgetToolError:
    """Structured error for an unknown widget type, listing the valid ones."""
    return WidgetToolError.create(
        f"Unknown widget type: {widget_type!r}. "
        "Call list_widget_types to see the available types.",
        "NotFound",
        {"valid_widget_types": valid_widget_types()},
    )


def serialize_saved_widget(
    widget: Any, *, include_data_model_metadata: bool
) -> SavedWidgetInfo:
    """Serialize a saved widget, withholding its query definition if required.

    ``props`` name the dataset, its columns and metrics (possibly as SQL
    expressions), so they are dataset details in the sense of
    ``user_can_view_data_model_metadata`` and are dropped for roles that may
    not see those.
    """
    # pylint: disable=import-outside-toplevel
    from superset.commands.widget.utils import (
        serialize_saved_widget as serialize_for_api,
    )

    payload = serialize_for_api(widget)
    if not include_data_model_metadata:
        payload["props"] = {}
        payload["dataset_id"] = None
    return SavedWidgetInfo(**payload)


def jsonable(value: Any) -> Any:
    """Round-trip a query result through JSON.

    Query results can hold datetimes, decimals or numpy values that the tool
    response model cannot carry as-is.
    """
    return json.loads(json.dumps(value))
