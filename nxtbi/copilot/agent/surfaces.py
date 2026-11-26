# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Trusted builders for the bounded A2UI 1.0 component catalog."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from typing import Annotated, Literal, TypedDict
from uuid import uuid4

from ag_ui.core import ActivitySnapshotEvent
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .contracts import DatasetFilter, LABEL, POSITIVE_ID

CATALOG_ID = "https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json"
NXTBI_CATALOG_ID = "urn:nxtbi:a2ui:1.0"
WIDGET_CATALOG_ID = "urn:nxtbi:superset-widgets:1.0"
EVIDENCE_GROUP_LIMIT = 5
WIDGET_ID_PATTERN = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
BODY_TEXT = Annotated[str, Field(min_length=1, max_length=1200)]
CELL_TEXT = Annotated[str, Field(max_length=200)]
TABLE_ROW = Annotated[list[CELL_TEXT], Field(min_length=1, max_length=6)]
COMPONENT_ID = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")]
FIELD_NAME = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,39}$")]
FORM_VALUE = Annotated[str, Field(max_length=500)]


class Component(TypedDict, total=False):
    """Fields used by the service's A2UI 1.0 Basic Catalog subset."""

    id: str
    component: str
    text: str
    child: str
    children: list[str]
    label: str
    variant: str
    value: dict[str, str]
    action: dict[str, object]


class FormField(BaseModel):
    """A model-chosen text field without executable validation or code."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,39}$")]
    label: LABEL
    initial_value: CELL_TEXT = ""

    @field_validator("name")
    @classmethod
    def valid_form_name(cls, name: str) -> str:
        """Reserve keys interpreted specially by JavaScript objects."""
        if name in {"constructor", "prototype"}:
            raise ValueError("Reserved form field name")
        return name


class _AllowedProperties(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class FieldBinding(_AllowedProperties):
    """A native A2UI reference to a declared text field."""

    path: Annotated[
        str, Field(alias="@path", pattern=r"^/fields/[A-Za-z][A-Za-z0-9_]{0,39}$")
    ]

    @property
    def name(self) -> str:
        """Return the field key targeted by this binding."""
        return self.path.removeprefix("/fields/")


class SubmitFormAction(_AllowedProperties):
    """Send visible form values as a new user input event."""

    name: Literal["nxtbi.submit-form"]
    context: Annotated[
        dict[FIELD_NAME, FieldBinding], Field(min_length=1, max_length=8)
    ]


class DashboardId(_AllowedProperties):
    """A Superset dashboard identifier for local navigation."""

    dashboard_id: POSITIVE_ID = Field(alias="dashboardId")


class OpenDashboardAction(_AllowedProperties):
    """Open a verified Superset dashboard without mutating it."""

    name: Literal["nxtbi.open-dashboard"]
    context: DashboardId


class ButtonAction(_AllowedProperties):
    """The supported subset of native A2UI event actions."""

    event: Annotated[
        SubmitFormAction | OpenDashboardAction, Field(discriminator="name")
    ]


class TextNode(_AllowedProperties):
    """Basic Catalog text, optionally bound to a declared form value."""

    id: COMPONENT_ID
    component: Literal["Text"]
    text: BODY_TEXT | FieldBinding
    variant: Literal["body", "caption"] | None = None


class CardNode(_AllowedProperties):
    """Basic Catalog container with a single child."""

    id: COMPONENT_ID
    component: Literal["Card"]
    child: COMPONENT_ID


class LayoutNode(_AllowedProperties):
    """Basic Catalog vertical or horizontal group."""

    id: COMPONENT_ID
    component: Literal["Column", "Row"]
    children: Annotated[list[COMPONENT_ID], Field(min_length=1, max_length=12)]


class TextFieldNode(_AllowedProperties):
    """A text input bound to the generated surface's data."""

    id: COMPONENT_ID
    component: Literal["TextField"]
    label: LABEL
    value: FieldBinding
    variant: Literal["shortText", "longText"] = "shortText"


class ButtonNode(_AllowedProperties):
    """A button carrying a permitted local event."""

    id: COMPONENT_ID
    component: Literal["Button"]
    child: COMPONENT_ID
    variant: Literal["primary"] | None = None
    action: ButtonAction


class SavedWidgetNode(_AllowedProperties):
    """Preview one authorized saved widget, without inline widget configuration."""

    id: COMPONENT_ID
    component: Literal["SupersetWidgetPreview"]
    catalog_id: Literal["urn:nxtbi:superset-widgets:1.0"] = Field(
        alias="@catalogId", default=WIDGET_CATALOG_ID
    )
    widget_id: Annotated[str, Field(alias="widgetId", pattern=WIDGET_ID_PATTERN)]

    @field_validator("widget_id")
    @classmethod
    def lower_case_uuid(cls, widget_id: str) -> str:
        """Match the broker's canonical UUID format."""
        return widget_id.lower()


SurfaceNode = Annotated[
    TextNode | CardNode | LayoutNode | TextFieldNode | ButtonNode | SavedWidgetNode,
    Field(discriminator="component"),
]


def _references(node: SurfaceNode) -> list[str]:
    if isinstance(node, (ButtonNode, CardNode)):
        return [node.child]
    if isinstance(node, LayoutNode):
        return node.children
    return []


class SurfaceDraft(_AllowedProperties):
    """A bounded A2UI graph with typed components, values and events."""

    components: Annotated[list[SurfaceNode], Field(min_length=1, max_length=32)]
    fields: Annotated[dict[FIELD_NAME, FORM_VALUE], Field(max_length=8)] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def validate_graph(self) -> SurfaceDraft:
        """Require one connected tree with unique IDs and bounded depth."""
        by_id = {node.id: node for node in self.components}
        if len(by_id) != len(self.components) or "root" not in by_id:
            raise ValueError("Components need unique IDs and one root named root")
        visited: set[str] = set()
        pending = [("root", 0)]
        while pending:
            node_id, depth = pending.pop()
            if depth > 8 or node_id not in by_id or node_id in visited:
                raise ValueError(
                    "Component references need a single tree up to depth 8"
                )
            visited.add(node_id)
            node = by_id[node_id]
            if isinstance(node, ButtonNode) and not isinstance(
                by_id.get(node.child), TextNode
            ):
                raise ValueError("A button label must reference a Text component")
            pending.extend((child, depth + 1) for child in _references(node))
        if len(visited) != len(by_id):
            raise ValueError("Every component must be connected to the root")
        self._validate_bindings()
        return self

    def _validate_bindings(self) -> None:
        if self.fields.keys() & {"constructor", "prototype"}:
            raise ValueError("Reserved form field name")
        shown_fields = {
            node.value.name
            for node in self.components
            if isinstance(node, TextFieldNode)
        }
        for node in self.components:
            if isinstance(node, TextNode) and isinstance(node.text, FieldBinding):
                if node.text.name not in self.fields:
                    raise ValueError("Text binding references an undeclared field")
            if isinstance(node, ButtonNode) and isinstance(
                event := node.action.event, SubmitFormAction
            ):
                if node.id != "submit" or any(
                    name != binding.name or name not in shown_fields
                    for name, binding in event.context.items()
                ):
                    raise ValueError(
                        "A submit button must bind its matching visible fields"
                    )
        if not shown_fields <= self.fields.keys():
            raise ValueError("Input binding references an undeclared field")
        if len(self.dashboard_ids) > 1:
            raise ValueError("A surface may link to at most one dashboard")

    @property
    def dashboard_ids(self) -> set[int]:
        """Return dashboard IDs referenced by navigation buttons."""
        return {
            node.action.event.context.dashboard_id
            for node in self.components
            if isinstance(node, ButtonNode)
            and isinstance(node.action.event, OpenDashboardAction)
        }

    @property
    def saved_widget_ids(self) -> set[str]:
        """Return saved widget IDs that must be checked for browser access."""
        return {
            node.widget_id
            for node in self.components
            if isinstance(node, SavedWidgetNode)
        }


def _surface(
    components: Sequence[Component | dict[str, object]],
    data: dict[str, object] | None = None,
) -> ActivitySnapshotEvent:
    surface_id = f"nxtbi-{uuid4().hex}"
    operations: list[dict[str, object]] = [
        {
            "version": "1.0",
            "createSurface": {"surfaceId": surface_id, "catalogId": CATALOG_ID},
        },
        {
            "version": "1.0",
            "updateComponents": {
                "surfaceId": surface_id,
                "components": list(components),
            },
        },
    ]
    if data is not None:
        operations.append(
            {
                "version": "1.0",
                "updateDataModel": {
                    "surfaceId": surface_id,
                    "path": "/",
                    "value": data,
                },
            }
        )
    return ActivitySnapshotEvent(
        messageId=f"a2ui-surface-{surface_id}",
        activityType="a2ui-surface",
        content={"a2ui_operations": operations},
        replace=True,
    )


def render(draft: SurfaceDraft) -> ActivitySnapshotEvent:
    """Convert a model-authored tree into native A2UI 1.0 operations."""
    return _surface(
        [
            node.model_dump(mode="json", by_alias=True, exclude_none=True)
            for node in draft.components
        ],
        {"fields": draft.fields} if draft.fields else None,
    )


def _frame(title: str, children: list[str]) -> list[Component]:
    return [
        {"id": "root", "component": "Card", "child": "content"},
        {"id": "content", "component": "Column", "children": ["title", *children]},
        {"id": "title", "component": "Text", "text": title},
    ]


def card(title: str, description: str) -> ActivitySnapshotEvent:
    """Render a short, read-only card with plain text."""
    return _surface(
        [
            *_frame(title, ["description"]),
            {"id": "description", "component": "Text", "text": description},
        ]
    )


def _observation(value: object) -> str | None:
    """Display a finite gateway observation without rounding or adding a unit."""
    if type(value) is int or (type(value) is float and math.isfinite(value)):
        return f"{value:,}"
    return None


def _evidence_comparison(
    result: object, metric_label: str, arabic: bool
) -> dict[str, object] | None:
    """Display at most five measured groups in the gateway's result order."""
    if (
        not isinstance(result, dict)
        or not isinstance(dimension := result.get("dimension"), str)
        or not isinstance(rows := result.get("rows"), list)
    ):
        return None
    measured = [
        {
            "group": str(row["group"])
            if row["group"] is not None
            else ("قيمة مفقودة" if arabic else "Missing value"),
            "value": value,
        }
        for row in rows
        if isinstance(row, dict)
        and "group" in row
        and (value := _observation(row.get("value"))) is not None
    ]
    if not measured:
        return None

    shown = min(len(measured), EVIDENCE_GROUP_LIMIT)
    caption = dimension
    if result.get("truncated") is True:
        suffix = (
            f"عرض {shown} مجموعات، وتوجد نتائج أخرى"
            if arabic
            else (f"{shown} groups shown · more available")
        )
        caption = f"{dimension} · {suffix}"
    elif len(measured) > shown:
        suffix = (
            f"عرض {shown} من {len(measured)} مجموعات"
            if arabic
            else (f"{shown} of {len(measured)} groups shown")
        )
        caption = f"{dimension} · {suffix}"
    return {
        "id": "comparison",
        "component": "Table",
        "@catalogId": NXTBI_CATALOG_ID,
        "caption": caption,
        "columns": [
            {"key": "group", "label": "المجموعة" if arabic else "Group"},
            {"key": "value", "label": metric_label},
        ],
        "rows": measured[:shown],
    }


def _evidence_dataset_name(metadata: object, fallback: str) -> str:
    """Read a display name only from a Copilot upload's receipt-like description."""
    if (
        not isinstance(metadata, dict)
        or not isinstance(name := metadata.get("table_name"), str)
        or not name.strip()
    ):
        return fallback
    if re.fullmatch(r"copilot_csv_[0-9a-f]{24}", name) and isinstance(
        description := metadata.get("description"), str
    ):
        if receipt := re.fullmatch(
            r"Uploaded through Copilot from ([^/\\]{1,120}\.csv)\.", description
        ):
            display_name = receipt[1]
            if display_name.isprintable() and display_name[:-4].strip():
                return display_name
    return name.strip()[:160]


def dashboard_evidence(
    metadata: object,
    metric_label: str,
    total: object,
    groups: object,
    *,
    locale: Literal["ar", "en"],
    profile: object = None,
    snapshot_scope: DatasetFilter | None = None,
) -> ActivitySnapshotEvent | None:
    """Present the original draft's verified headline, source, and scope."""
    if (
        not isinstance(total, dict)
        or type(dataset_id := total.get("dataset_id")) is not int
        or not isinstance(rows := total.get("rows"), list)
        or len(rows) != 1
        or not isinstance(rows[0], dict)
        or (value := _observation(rows[0].get("value"))) is None
    ):
        return None

    arabic = locale == "ar"
    dataset_name = _evidence_dataset_name(
        metadata, "مجموعة البيانات" if arabic else "Dataset"
    )
    source = f"{dataset_name} · #{dataset_id}"
    if snapshot_scope:
        label = "لقطة" if arabic else "Snapshot"
        scope = f"{label} · {snapshot_scope.column} = {snapshot_scope.value}"
    else:
        scope = "كل الصفوف المتاحة" if arabic else "All accessible rows"
        count = profile.get("row_count") if isinstance(profile, dict) else None
        if type(count) is int and count >= 0:
            scope = f"{scope} ({count:,})"

    comparison = _evidence_comparison(groups, metric_label, arabic)
    children = (
        ["source", "headline", "comparison"]
        if comparison
        else [
            "source",
            "headline",
        ]
    )
    return _surface(
        [
            *_frame("الأدلة المستخدمة" if arabic else "Evidence used", children),
            {"id": "source", "component": "Text", "text": source, "variant": "caption"},
            {
                "id": "headline",
                "component": "Metric",
                "@catalogId": NXTBI_CATALOG_ID,
                "label": metric_label,
                "value": value,
                "detail": scope,
            },
            *([comparison] if comparison else []),
        ]
    )


def table(
    title: str, headings: list[str], rows: list[list[str]]
) -> ActivitySnapshotEvent:
    """Render a compact table with one Basic Catalog Row per record."""
    if any(len(row) != len(headings) for row in rows):
        raise ValueError("Rows must match the column count")
    records = [headings, *rows]
    components = _frame(title, [f"row-{index}" for index in range(len(records))])
    for row_index, row in enumerate(records):
        cell_ids = [f"cell-{row_index}-{column}" for column in range(len(row))]
        components.append(
            {"id": f"row-{row_index}", "component": "Row", "children": cell_ids}
        )
        components.extend(
            {"id": cell_id, "component": "Text", "text": value}
            for cell_id, value in zip(cell_ids, row, strict=True)
        )
    return _surface(components)


def form(
    title: str, description: str, fields: list[FormField], submit_label: str
) -> ActivitySnapshotEvent:
    """Render a form whose submission becomes an explicit presentation-only action."""
    if len({field.name for field in fields}) != len(fields):
        raise ValueError("Form field names must be unique")
    components = _frame(
        title, ["description", *[f"field-{f.name}" for f in fields], "submit"]
    )
    components.append({"id": "description", "component": "Text", "text": description})
    data: dict[str, str] = {}
    context: dict[str, dict[str, str]] = {}
    for field in fields:
        binding = {"@path": f"/fields/{field.name}"}
        context[field.name] = binding
        data[field.name] = field.initial_value
        components.append(
            {
                "id": f"field-{field.name}",
                "component": "TextField",
                "label": field.label,
                "variant": "shortText",
                "value": binding,
            }
        )
    components.extend(
        [
            {"id": "submit-label", "component": "Text", "text": submit_label},
            {
                "id": "submit",
                "component": "Button",
                "child": "submit-label",
                "variant": "primary",
                "action": {"event": {"name": "nxtbi.submit-form", "context": context}},
            },
        ]
    )
    return _surface(components, {"fields": data})
