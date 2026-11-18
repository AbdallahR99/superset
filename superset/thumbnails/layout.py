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
"""Create data-free dashboard card illustrations from saved layout geometry."""

from __future__ import annotations

from base64 import b64encode
from typing import Any

from superset.dashboard_v2.document import load_stored_document
from superset.utils import json


def _span(value: Any, maximum: int) -> int:
    """Clamp a persisted grid span to the drawable grid."""
    return min(maximum, max(1, value)) if type(value) is int else maximum


def _rows(nodes: dict[str, Any], v2: bool) -> list[list[tuple[int, str]]]:
    """Read the visible first tab and at most four rows, ignoring widget contents."""
    rows: list[list[tuple[int, str]]] = []
    seen: set[str] = set()
    pending = ["root" if v2 else "ROOT_ID"]
    root = nodes.get("root")
    grid = root.get("layout") if isinstance(root, dict) else None
    columns = _span(grid.get("columns", 24), 48) if isinstance(grid, dict) else 12
    used = columns
    while pending and len(seen) < 500:
        key = pending.pop()
        if key in seen:
            continue
        seen.add(key)
        node = nodes.get(key)
        if not isinstance(node, dict):
            continue
        kind = node.get("type")
        children = node.get("children")
        if isinstance(children, list) and (children or v2):
            if kind == "ROW":
                used = columns
            if kind == "TABS":
                children = children[:1]
            pending.extend(
                child for child in reversed(children[:500]) if isinstance(child, str)
            )
            continue
        if not isinstance(kind, str) or (not v2 and kind not in {"CHART", "MARKDOWN"}):
            continue
        meta = node.get("layout" if v2 else "meta")
        width = (
            _span(meta.get("colSpan" if v2 else "width"), columns)
            if isinstance(meta, dict)
            else columns
        )
        if used + width > columns:
            if len(rows) == 4:
                break
            rows.append([])
            used = 0
        used += width
        rows[-1].append((round(240 * width / columns), kind))
    return rows


def layout_thumbnail(
    metadata: str | None, positions: str | None, dashboard_id: int
) -> str:
    """Return a decorative image containing only trusted shapes and numeric spans."""
    document = load_stored_document(metadata)
    try:
        nodes = document["nodes"] if document else json.loads(positions or "{}")
    except (ValueError, TypeError):
        nodes = {}
    rows = _rows(nodes, document is not None) if isinstance(nodes, dict) else []
    accent = ("#227582", "#42689c", "#63569b", "#287963")[dashboard_id % 4]
    shapes = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="264" height="148" '
        'viewBox="0 0 264 148">',
        '<rect width="264" height="148" fill="#edf2f6"/>',
        f'<rect x="12" y="10" width="42" height="4" rx="2" fill="{accent}"/>',
    ]
    for index, row in enumerate(rows):
        x = 12
        height = min(52, 114 // len(rows))
        y = 23 + index * height
        for width, kind in row:
            shapes.append(
                f'<rect x="{x}" y="{y}" width="{max(1, width - 3)}" '
                f'height="{height - 3}" '
                'rx="3" fill="white" stroke="#cbd7df"/>'
            )
            if width >= 20:
                left, top = x + 5, y + 6
                right, bottom = x + width - 9, y + height - 9
                if kind in {"CHART", "echarts"}:
                    # Empty chart axes indicate a plot without inventing observations.
                    shapes.append(
                        f'<path d="M{left} {top}V{bottom}H{right}" fill="none" '
                        f'stroke="{accent}" stroke-width="2"/>'
                    )
                else:
                    marks = 3 if kind in {"ag-grid-table", "MARKDOWN"} else 1
                    for line in range(marks):
                        shapes.append(
                            f'<rect x="{left}" y="{top + line * 5}" '
                            f'width="{max(3, (width - 10) * 2 // 3)}" '
                            f'height="2" rx="1" fill="{accent}"/>'
                        )
            x += width
    shapes.append("</svg>")
    encoded = b64encode("".join(shapes).encode()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"
