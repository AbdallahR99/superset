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
"""
Server-side rules for the free-form JSON a widget definition may carry.

An ECharts ``option`` and AG Grid ``columnDefs`` are written by one principal
and drawn in the browser of another: a different Superset user, or a visitor of
a page that embeds the widget. Both libraries have settings that reach the DOM
as HTML or are compiled into code, so a stored definition is only accepted
when it is declarative. The rules reject instead of rewriting: every write path
(the validate route, saved widgets, Dashboard V2 documents) runs the control
model, and a rejected document is never stored, so what is stored is clean for
any renderer, including ones that do no sanitizing of their own.

The approach is an allowlist wherever the vocabulary is small enough to list
(top-level option components, toolbox features, column settings) and, below
that, a type rule: only JSON scalars, with strings that carry no markup, no
script URL and, where a library would treat them as a template or expression,
no function source.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Shared string rules
# ---------------------------------------------------------------------------

MAX_STRING_LENGTH = 20000

# The start of an element, closing tag, comment, doctype or processing
# instruction. ``a < b`` is not markup; ``<b>``, ``</b>`` and ``<!--`` are.
_MARKUP = re.compile(r"<[A-Za-z!/?]")
# Matched after dropping what a URL parser ignores inside a scheme.
_SCRIPT_SCHEME = re.compile(r"^(?:javascript|vbscript|data|livescript):", re.IGNORECASE)
_URL_NOISE = re.compile(r"[\x00-\x20\x7f]")
_SAFE_LINK = re.compile(r"^(?:https?:|mailto:|/|#|\.{0,2}/|[^:]*$)", re.IGNORECASE)
_FUNCTION_SOURCE = re.compile(
    r"^\s*(?:async\s+)?function\b|=>|^\s*\(?\s*function\b|\bnew\s+Function\b"
)


def string_problem(value: str) -> str | None:
    """Why a string may not be stored in a widget definition, if it may not."""
    if len(value) > MAX_STRING_LENGTH:
        return f"is longer than {MAX_STRING_LENGTH} characters"
    if _MARKUP.search(value):
        return "contains HTML markup"
    if _SCRIPT_SCHEME.match(_URL_NOISE.sub("", value)):
        return "is a script or data URL"
    return None


# ---------------------------------------------------------------------------
# ECharts option
# ---------------------------------------------------------------------------

MAX_OPTION_DEPTH = 32
MAX_OPTION_NODES = 20000

# Top-level components that only paint onto the chart's canvas.
ECHARTS_OPTION_KEYS = frozenset(
    {
        "angleAxis",
        "animation",
        "animationDelay",
        "animationDelayUpdate",
        "animationDuration",
        "animationDurationUpdate",
        "animationEasing",
        "animationEasingUpdate",
        "animationThreshold",
        "aria",
        "axisPointer",
        "backgroundColor",
        "blendMode",
        "calendar",
        "color",
        "darkMode",
        "dataZoom",
        "dataset",
        "grid",
        "hoverLayerThreshold",
        "legend",
        "parallel",
        "parallelAxis",
        "polar",
        "radar",
        "radiusAxis",
        "series",
        "singleAxis",
        "stateAnimation",
        "textStyle",
        "title",
        "toolbox",
        "tooltip",
        "useUTC",
        "visualMap",
        "xAxis",
        "yAxis",
    }
)

# Built-in toolbox features that render nothing but canvas. ``dataView`` opens
# an HTML panel built from authored strings, and a custom ``my*`` feature only
# exists to run a handler.
ECHARTS_TOOLBOX_FEATURES = frozenset(
    {"dataZoom", "magicType", "restore", "saveAsImage"}
)

# Settings that exist to reach the DOM or to run code, wherever they sit.
ECHARTS_FORBIDDEN_KEYS = frozenset(
    {
        "appendTo",
        "appendToBody",
        "className",
        "dataView",
        "extraCssText",
        "graphic",
        "renderItem",
    }
)

_DOM_EVENTS = frozenset(
    {
        "animationend",
        "animationstart",
        "blur",
        "change",
        "click",
        "contextmenu",
        "dblclick",
        "drag",
        "dragend",
        "dragenter",
        "dragleave",
        "dragover",
        "dragstart",
        "drop",
        "error",
        "focus",
        "input",
        "keydown",
        "keypress",
        "keyup",
        "load",
        "mousedown",
        "mouseenter",
        "mouseleave",
        "mousemove",
        "mouseout",
        "mouseover",
        "mouseup",
        "mousewheel",
        "pointerdown",
        "pointermove",
        "pointerup",
        "submit",
        "touchend",
        "touchmove",
        "touchstart",
        "transitionend",
        "wheel",
    }
)

_LINK_KEYS = frozenset({"link", "sublink"})
# ``axisPointer.link`` shares the name but not the meaning: it is a list of
# axis references (``{"xAxisIndex": "all"}``) that move their pointers
# together, and nothing opens it as a URL.
_AXIS_LINK_PARENT = "axisPointer"


def _is_event_handler(key: str) -> bool:
    lowered = key.lower()
    return lowered.startswith("on") and lowered[2:] in _DOM_EVENTS


def _is_formatter(key: str) -> bool:
    return key == "formatter" or key.endswith("Formatter")


def _echarts_key_problem(key: Any, path: str, depth: int) -> str | None:
    if not isinstance(key, str):
        return f"{path} has a key that is not a string"
    if depth == 0 and key not in ECHARTS_OPTION_KEYS:
        return f"{path}.{key} is not an allowed ECharts option component"
    if key in ECHARTS_FORBIDDEN_KEYS or _is_event_handler(key):
        return f"{path}.{key} is not allowed: it renders HTML or runs code"
    return None


def _is_axis_link(key: str, parent: str | None) -> bool:
    return key == "link" and parent == _AXIS_LINK_PARENT


def _axis_link_problem(value: Any, path: str) -> str | None:
    """
    An ``axisPointer.link`` is a list of axis-reference objects (or one such
    object). Their contents are checked by the walk like any other JSON; the
    shape is fixed here so that a string, which a component reading ``link``
    as a URL would open, cannot sit under this exemption.
    """
    groups = value if isinstance(value, list) else [value]
    if not all(isinstance(group, dict) for group in groups):
        return f"{path} must be a list of axis references"
    return None


def echarts_formatter_problem(value: Any, path: str) -> str | None:
    """Validate a text template or the per-unit templates of a time axis."""
    templates = value.values() if isinstance(value, dict) else [value]
    if not all(isinstance(template, str) for template in templates):
        return f"{path} must be a text template"
    if any(_FUNCTION_SOURCE.search(template) for template in templates):
        return f"{path} must be a text template, not a function"
    return None


def _echarts_value_problem(
    key: str, value: Any, path: str, parent: str | None = None
) -> str | None:
    """
    Rules that depend on the key a value sits under, and for ``link`` on the
    component that holds it (``parent``, the nearest enclosing key).
    """
    if _is_formatter(key):
        return echarts_formatter_problem(value, path)
    if _is_axis_link(key, parent):
        return _axis_link_problem(value, path)
    if key in _LINK_KEYS and (
        not isinstance(value, str) or not _SAFE_LINK.match(_URL_NOISE.sub("", value))
    ):
        return f"{path} must be an http(s), mailto or relative link"
    if key == "feature":
        # Only a toolbox has features; the rule holds wherever one is nested.
        if not isinstance(value, dict):
            return f"{path} must be an object"
        for feature in value:
            if feature not in ECHARTS_TOOLBOX_FEATURES:
                return f"{path}.{feature} is not an allowed toolbox feature"
    return None


def _echarts_scalar_problem(value: Any, path: str) -> str | None:
    """Why a leaf of the option is not an acceptable JSON scalar, if it is not."""
    if isinstance(value, str):
        problem = string_problem(value)
        return f"{path} {problem}" if problem else None
    if value is None or isinstance(value, (bool, int, float)):
        return None
    return f"{path} is not a JSON value"


def echarts_option_problem(option: Any, root: str = "echartsOptions") -> str | None:
    """
    Describe the first reason an authored ECharts option may not be stored, or
    return ``None`` when it is declarative.

    Accepted: the canvas-only top-level components of ``ECHARTS_OPTION_KEYS``;
    below them any JSON, as long as no key is one that renders HTML or runs
    code (``graphic``, ``dataView``, ``renderItem``, ``extraCssText``, DOM
    event handlers such as ``onclick``), a ``toolbox`` only names built-in
    canvas features, a ``formatter`` is a text template rather than function
    source, ``link`` / ``sublink`` are ordinary links (``axisPointer.link``,
    a list of axis references and not a URL, is the exception), and no string holds
    markup or a script URL (which rules out HTML tooltips and HTML rich text).
    The walk is iterative and bounded in depth and size.

    :param option: The ``echartsOptions`` value of a widget definition
    :param root: The name the option is reported under in messages
    :returns: A message naming the offending path, or ``None``
    """
    if not isinstance(option, dict):
        return f"{root} must be an object"
    seen = 0
    # Each entry also carries the nearest enclosing key, which a list passes
    # on to its items, so a rule can tell which component a value belongs to.
    stack: list[tuple[Any, str, int, str | None]] = [(option, root, 0, None)]
    while stack:
        value, path, depth, parent = stack.pop()
        seen += 1
        if seen > MAX_OPTION_NODES:
            return f"{root} holds more than {MAX_OPTION_NODES} values"
        if not isinstance(value, (dict, list)):
            if problem := _echarts_scalar_problem(value, path):
                return problem
            continue
        if depth >= MAX_OPTION_DEPTH:
            return f"{root} is nested deeper than {MAX_OPTION_DEPTH} levels"
        if isinstance(value, list):
            stack.extend(
                (item, f"{path}[{index}]", depth + 1, parent)
                for index, item in enumerate(value)
            )
            continue
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if problem := (
                _echarts_key_problem(key, path, depth)
                or _echarts_value_problem(key, child, child_path, parent)
            ):
                return problem
            stack.append((child, child_path, depth + 1, key))
    return None


# ---------------------------------------------------------------------------
# AG Grid column definitions
# ---------------------------------------------------------------------------

MAX_COLUMN_DEFS = 500
MAX_COLUMN_TEXT_LENGTH = 500

# The declarative column settings, by the JSON type each must have. AG Grid
# compiles strings in settings such as ``valueGetter``, ``valueFormatter``,
# ``cellRenderer`` and ``cellClassRules`` into functions or mounts them as
# components, so nothing outside this list is accepted. Kept in step with the
# renderer's own list (``AgGridTableWidget`` in the widgets package).
AG_GRID_COLUMN_SETTINGS: dict[str, type] = {
    "field": str,
    "colId": str,
    "headerName": str,
    "headerTooltip": str,
    "type": str,
    "cellDataType": str,
    "valueFormat": str,
    "sort": str,
    "pinned": str,
    "width": float,
    "minWidth": float,
    "maxWidth": float,
    "flex": float,
    "sortIndex": float,
    "hide": bool,
    "sortable": bool,
    "resizable": bool,
    "filter": bool,
    "wrapText": bool,
    "autoHeight": bool,
    "wrapHeaderText": bool,
    "autoHeaderHeight": bool,
    "suppressMovable": bool,
    "lockPosition": bool,
}

# Settings that name something accept only the built-in names. A ``type`` or
# ``cellDataType`` of any other name refers to a definition registered on the
# grid (``columnTypes`` / ``dataTypeDefinitions``), which a stored widget has
# no way to supply; the renderer keeps the same names and drops the rest.
_COLUMN_ENUMS: dict[str, frozenset[str]] = {
    "type": frozenset({"numericColumn", "rightAligned"}),
    "cellDataType": frozenset(
        {"text", "number", "boolean", "date", "dateString", "object"}
    ),
    "valueFormat": frozenset({"date"}),
    "sort": frozenset({"asc", "desc"}),
    "pinned": frozenset({"left", "right"}),
}


def _column_setting_problem(key: str, value: Any, path: str) -> str | None:
    expected = AG_GRID_COLUMN_SETTINGS[key]
    if expected is bool:
        return None if isinstance(value, bool) else f"{path} must be true or false"
    if expected is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{path} must be a number"
        return None if 0 <= value <= 100000 else f"{path} is out of range"
    if not isinstance(value, str):
        return f"{path} must be text"
    if len(value) > MAX_COLUMN_TEXT_LENGTH:
        return f"{path} is longer than {MAX_COLUMN_TEXT_LENGTH} characters"
    if problem := string_problem(value):
        return f"{path} {problem}"
    if key in _COLUMN_ENUMS and value not in _COLUMN_ENUMS[key]:
        return f"{path} must be one of {sorted(_COLUMN_ENUMS[key])}"
    return None


def column_defs_problem(column_defs: Any, root: str = "columnDefs") -> str | None:
    """
    Describe the first reason authored AG Grid column definitions may not be
    stored, or return ``None`` when every one is declarative.

    Each definition is a flat object whose keys all come from
    ``AG_GRID_COLUMN_SETTINGS`` with the listed type. Renderers, value
    getters and formatters, class rules, tooltips built from expressions and
    every other setting AG Grid would execute or mount are not on the list
    and are therefore rejected by name.
    ``valueFormat`` names a built-in display format implemented by the widget.

    :param column_defs: The ``columnDefs`` value of a widget definition
    :param root: The name the list is reported under in messages
    :returns: A message naming the offending path, or ``None``
    """
    if not isinstance(column_defs, list):
        return f"{root} must be an array"
    if len(column_defs) > MAX_COLUMN_DEFS:
        return f"{root} holds more than {MAX_COLUMN_DEFS} columns"
    for index, column in enumerate(column_defs):
        path = f"{root}[{index}]"
        if not isinstance(column, dict):
            return f"{path} must be an object"
        for key, value in column.items():
            if key not in AG_GRID_COLUMN_SETTINGS:
                return f"{path}.{key} is not an allowed column setting"
            if problem := _column_setting_problem(key, value, f"{path}.{key}"):
                return problem
    return None
