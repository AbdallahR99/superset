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
"""Schemas for the widget MCP tools.

Every request model forbids unknown fields, so a caller cannot smuggle an
inline widget definition (and with it a SQL expression) into a tool that only
reads saved widgets.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_SAVED_WIDGET_PAGE_SIZE = 100
DEFAULT_SAVED_WIDGET_PAGE_SIZE = 25


class WidgetTypeInfo(BaseModel):
    """A registered widget type."""

    id: str = Field(..., description="Widget type id, e.g. 'metric-tile'.")
    name: str = Field(..., description="Human-readable name.")
    description: str = Field("", description="What the widget shows.")


class WidgetTypeList(BaseModel):
    """Every registered widget type."""

    widget_types: list[WidgetTypeInfo] = Field(default_factory=list)
    count: int = Field(0, description="Number of widget types.")


class GetWidgetControlSchemaRequest(BaseModel):
    """Request schema for get_widget_control_schema."""

    model_config = ConfigDict(extra="forbid")

    widget_type: str = Field(..., description="Widget type id from list_widget_types.")
    paths: list[str] = Field(
        default_factory=list,
        description=(
            "x-path values of collapsed branches to expand. Empty returns the "
            "minimum-viable root schema."
        ),
    )
    control_values: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Current widget props, used only to shape x-dynamic branches. "
            "They are never executed as a query."
        ),
    )
    series: list[str] | None = Field(
        default=None,
        description="Known distinct dimension values, for x-dynamic branches.",
    )


class WidgetControlSchema(BaseModel):
    """A widget type's control schema, whole (pruned) or as requested subtrees."""

    widget_type: str = Field(..., description="Widget type id.")
    control_schema: dict[str, Any] | None = Field(
        default=None,
        description="Minimum-viable root JSON Schema; set when no paths were given.",
    )
    subtrees: dict[str, dict[str, Any]] | None = Field(
        default=None,
        description="One JSON Schema per requested path; set when paths were given.",
    )
    warning: str | None = Field(
        default=None,
        description="Set when dynamic branches could not be shaped from the values.",
    )


class ResolvedFilter(BaseModel):
    """A structured narrowing ANDed onto the widget's own query."""

    model_config = ConfigDict(extra="forbid")

    column: str = Field(..., description="Column on the widget's dataset.")
    operator: Literal["EQUALS", "NOT_EQUALS", "IN", "NOT_IN", "RANGE", "TIME_RANGE"]
    value: Any = Field(
        default=None,
        description=(
            "Scalar for EQUALS/NOT_EQUALS, list for IN/NOT_IN, {min, max} for "
            "RANGE, {start, end} for TIME_RANGE."
        ),
    )


class ListSavedWidgetsRequest(BaseModel):
    """Request schema for list_saved_widgets."""

    model_config = ConfigDict(extra="forbid")

    page: int = Field(1, ge=1, description="1-based page number.")
    page_size: int = Field(
        DEFAULT_SAVED_WIDGET_PAGE_SIZE,
        ge=1,
        le=MAX_SAVED_WIDGET_PAGE_SIZE,
        description="Saved widgets per page.",
    )


class GetSavedWidgetRequest(BaseModel):
    """Request schema for get_saved_widget."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Saved widget uuid.")


class GetWidgetDataRequest(BaseModel):
    """Request schema for get_widget_data: a saved widget and optional filters."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Saved widget uuid.")
    filters: list[ResolvedFilter] = Field(
        default_factory=list,
        description="Optional column filters that can only narrow the rows.",
    )


class SavedWidgetInfo(BaseModel):
    """A saved widget's definition."""

    uuid: str
    widget_type: str
    title: str | None = None
    props: dict[str, Any] = Field(
        default_factory=dict,
        description="Widget props; empty when the role may not see dataset details.",
    )
    dataset_id: int | None = None
    changed_on: datetime | None = None


class SavedWidgetList(BaseModel):
    """A page of saved widgets."""

    widgets: list[SavedWidgetInfo] = Field(default_factory=list)
    count: int = Field(0, description="Saved widgets on this page.")
    total_count: int = Field(0, description="Saved widgets the caller can list.")
    page: int = 1
    page_size: int = DEFAULT_SAVED_WIDGET_PAGE_SIZE


class WidgetDataResponse(BaseModel):
    """The rows a widget's query returned."""

    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = Field(0, description="Number of rows returned.")


class WidgetToolError(BaseModel):
    """Structured failure of a widget tool."""

    error: str = Field(..., description="Error message")
    error_type: str = Field(
        ...,
        description=(
            "FeatureDisabled, NotFound, Forbidden, ValidationError, "
            "DataModelMetadataRestricted, CommandError or UnexpectedError"
        ),
    )
    errors: Any = Field(
        default=None, description="Field-level validation errors, when present."
    )
    timestamp: datetime | None = None

    @classmethod
    def create(
        cls, error: str, error_type: str, errors: Any = None
    ) -> "WidgetToolError":
        """Build an error stamped with the current time."""
        return cls(
            error=error,
            error_type=error_type,
            errors=errors,
            timestamp=datetime.now(timezone.utc),
        )
