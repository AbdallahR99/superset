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
Helpers for the persisted Dashboard v2 document.

The whole document — every node with its props inline — lives under
``json_metadata["v2_document"]`` of the dashboard row, together with a
monotonically increasing ``revision`` used for optimistic concurrency. A node
with a ``children`` array is a container; every other node is a leaf widget
whose ``type`` names a registered widget type. A block is addressed by its
node id.

Everything a client submits goes through :func:`normalize_document`, which is
iterative (no recursion) and bounded by :class:`DocumentLimits`, so a hostile
document can neither exhaust the interpreter stack nor store an unbounded or
malformed tree.
"""

from __future__ import annotations

# The standard library parser is used on purpose: strict parsing needs its
# ``object_pairs_hook`` and ``parse_constant`` hooks, which the
# ``superset.utils.json`` wrapper does not expose.
import json as stdlib_json  # noqa: TID251
import math
import re
from collections.abc import Collection, Iterator
from dataclasses import dataclass
from typing import Any

from flask import current_app, has_app_context

from superset.utils import json

V2_DOCUMENT_KEY = "v2_document"
DOCUMENT_VERSION = 1
ROOT_ID = "root"
#: The type of the root container; rendered by the host, not by a widget.
GRID_TYPE = "grid"
REVISION_KEY = "revision"
#: Revision a freshly created document is stored with.
INITIAL_REVISION = 1

_NODE_KEYS = ("type", "layout", "children", "props", "style")
_OBJECT_KEYS = ("layout", "props", "style")
_NODE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_MAX_TYPE_LENGTH = 128
#: Deepest array/object nesting a request body may have, well below what any
#: recursive JSON parser can handle.
MAX_JSON_NESTING = 64
# A string literal (consumed whole, terminated or not, so the scan stays
# linear on any input) or a single bracket.
_JSON_TOKEN = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"?|[\[\]{}]', re.DOTALL)


class DocumentValidationError(ValueError):
    """The submitted v2 document is malformed."""


@dataclass(frozen=True)
class DocumentLimits:
    """Upper bounds a submitted document must stay within."""

    #: Maximum number of nodes, the root included.
    max_nodes: int = 500
    #: Maximum distance of any node from the root (the root is at depth 0).
    max_depth: int = 16
    #: Maximum size in bytes of the request body and of the stored document.
    max_bytes: int = 1024 * 1024
    #: Maximum nesting of the JSON value held by ``layout``/``props``/``style``.
    max_value_depth: int = 32


def current_limits() -> DocumentLimits:
    """
    The limits configured for the running app, or the defaults outside an
    application context.

    Read from ``DASHBOARD_V2_MAX_NODES``, ``DASHBOARD_V2_MAX_DEPTH``,
    ``DASHBOARD_V2_MAX_DOCUMENT_BYTES`` and ``DASHBOARD_V2_MAX_VALUE_DEPTH``.
    """
    defaults = DocumentLimits()
    if not has_app_context():
        return defaults
    config = current_app.config
    return DocumentLimits(
        max_nodes=int(config.get("DASHBOARD_V2_MAX_NODES", defaults.max_nodes)),
        max_depth=int(config.get("DASHBOARD_V2_MAX_DEPTH", defaults.max_depth)),
        max_bytes=int(
            config.get("DASHBOARD_V2_MAX_DOCUMENT_BYTES", defaults.max_bytes)
        ),
        max_value_depth=int(
            config.get("DASHBOARD_V2_MAX_VALUE_DEPTH", defaults.max_value_depth)
        ),
    )


@dataclass(frozen=True)
class DocumentWidget:
    """A node whose props are validated by a registered widget type."""

    node_id: str
    widget_type: str
    props: dict[str, Any]
    is_container: bool = False


def is_container(node: dict[str, Any]) -> bool:
    """Whether the node holds other nodes."""
    return isinstance(node.get("children"), list)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """``object_pairs_hook`` refusing an object that repeats a key."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DocumentValidationError(f"duplicate key {key!r} in JSON object")
        result[key] = value
    return result


def _reject_constant(name: str) -> Any:
    """``parse_constant`` hook refusing ``NaN`` and the infinities."""
    raise DocumentValidationError(f"{name} is not a valid JSON value")


def _nesting_exceeds(text: str, max_depth: int) -> bool:
    """
    Whether arrays and objects in ``text`` nest deeper than ``max_depth``.

    A flat scan over the brackets outside string literals; it is exact for
    well-formed JSON, which is all that matters since anything else is
    refused by the parser afterwards.
    """
    depth = 0
    for match in _JSON_TOKEN.finditer(text):
        first = match.group()[0]
        if first in "[{":
            depth += 1
            if depth > max_depth:
                return True
        elif first in "]}":
            depth -= 1
    return False


def parse_strict_json(raw: bytes | str, max_depth: int = MAX_JSON_NESTING) -> Any:
    """
    Parse a request body as strict JSON.

    Unlike a lenient parser this refuses duplicate object keys (which would
    silently collapse two nodes sharing an id into one), ``NaN``/``Infinity``,
    and arrays or objects nested deeper than ``max_depth`` — checked before
    parsing, so no recursive parser ever sees a body able to exhaust it.

    :raises DocumentValidationError: If the body is not strict JSON
    """
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    except UnicodeDecodeError as ex:
        raise DocumentValidationError("request body is not valid JSON") from ex
    if _nesting_exceeds(text, max_depth):
        raise DocumentValidationError("JSON is nested too deeply")
    try:
        return stdlib_json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except RecursionError as ex:
        raise DocumentValidationError("JSON is nested too deeply") from ex
    except (ValueError, UnicodeDecodeError) as ex:
        if isinstance(ex, DocumentValidationError):
            raise
        raise DocumentValidationError("request body is not valid JSON") from ex


def _check_json_value(value: Any, where: str, max_depth: int) -> None:
    """
    Verify ``value`` is plain JSON (objects with string keys, arrays, strings,
    finite numbers, booleans, null) nested at most ``max_depth`` levels.
    """
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if current is None or isinstance(current, (str, bool, int)):
            continue
        if isinstance(current, float):
            if not math.isfinite(current):
                raise DocumentValidationError(f"{where} contains a non-finite number")
            continue
        if not isinstance(current, (dict, list)):
            raise DocumentValidationError(
                f"{where} contains a non-JSON value of type {type(current).__name__}"
            )
        if depth > max_depth:
            raise DocumentValidationError(
                f"{where} is nested deeper than {max_depth} levels"
            )
        if isinstance(current, dict):
            for key, item in current.items():
                if not isinstance(key, str):
                    raise DocumentValidationError(
                        f"{where} contains a non-string object key"
                    )
                stack.append((item, depth + 1))
        else:
            stack.extend((item, depth + 1) for item in current)


def _normalize_node(
    node_id: Any, node: Any, nodes: dict[str, Any], limits: DocumentLimits
) -> dict[str, Any]:
    """Validate one node in isolation and return the keys to store."""
    if not isinstance(node_id, str) or not _NODE_ID_PATTERN.match(node_id):
        raise DocumentValidationError(
            f"node id {str(node_id)[:80]!r} must match [A-Za-z0-9_-]{{1,64}}"
        )
    if not isinstance(node, dict):
        raise DocumentValidationError(
            f"node {node_id!r} must be an object with a string type"
        )
    node_type = node.get("type")
    if (
        not isinstance(node_type, str)
        or not node_type
        or len(node_type) > _MAX_TYPE_LENGTH
    ):
        raise DocumentValidationError(
            f"node {node_id!r} must be an object with a string type"
        )
    stored: dict[str, Any] = {"type": node_type}
    for key in _OBJECT_KEYS:
        value = node.get(key)
        if value is None:
            continue
        if not isinstance(value, dict):
            raise DocumentValidationError(f"node {node_id!r} {key} must be an object")
        _check_json_value(value, f"node {node_id!r} {key}", limits.max_value_depth)
        stored[key] = value
    if (children := node.get("children")) is not None:
        stored["children"] = _normalize_children(node_id, children, nodes)
    return {key: stored[key] for key in _NODE_KEYS if key in stored}


def _normalize_children(
    node_id: str, children: Any, nodes: dict[str, Any]
) -> list[str]:
    """Validate a container's ``children``: distinct ids of existing nodes."""
    if not isinstance(children, list) or not all(
        isinstance(child, str) for child in children
    ):
        raise DocumentValidationError(
            f"node {node_id!r} children must be an array of node ids"
        )
    if len(set(children)) != len(children):
        raise DocumentValidationError(
            f"node {node_id!r} lists the same child more than once"
        )
    if unknown := [child for child in children if child not in nodes]:
        raise DocumentValidationError(
            f"node {node_id!r} references unknown children {unknown[:5]}"
        )
    return list(children)


def _check_tree(nodes: dict[str, dict[str, Any]], max_depth: int) -> None:
    """
    Verify the nodes form one tree rooted at ``root``: no cycle, no node with
    two parents, nothing unreachable, nothing deeper than ``max_depth``.

    The walk keeps its own stack, so its cost and stack use are bounded by the
    node count rather than by the shape of the document.
    """
    on_path = 1
    done = 2
    state: dict[str, int] = {ROOT_ID: on_path}
    stack: list[tuple[str, Iterator[str]]] = [
        (ROOT_ID, iter(nodes[ROOT_ID].get("children", ())))
    ]
    while stack:
        node_id, remaining = stack[-1]
        child = next(remaining, None)
        if child is None:
            state[node_id] = done
            stack.pop()
            continue
        if state.get(child) == on_path:
            raise DocumentValidationError(
                f"node {child!r} is its own ancestor (cycle through {node_id!r})"
            )
        if state.get(child) == done:
            raise DocumentValidationError(
                f"node {child!r} is reachable through more than one parent"
            )
        if len(stack) > max_depth:
            raise DocumentValidationError(
                f"document is nested deeper than {max_depth} levels at {child!r}"
            )
        state[child] = on_path
        stack.append((child, iter(nodes[child].get("children", ()))))
    if unreachable := [node_id for node_id in nodes if node_id not in state]:
        raise DocumentValidationError(
            f"nodes {unreachable[:5]} are not reachable from the root"
        )


def normalize_document(
    document: Any,
    *,
    limits: DocumentLimits | None = None,
    known_types: Collection[str] | None = None,
) -> tuple[dict[str, Any], list[DocumentWidget]]:
    """
    Validate a submitted document and return the version to store (unknown
    node keys dropped, no revision) plus the nodes whose props a registered
    widget type has to validate.

    :param document: The client-supplied document
    :param limits: Bounds to enforce; the configured ones when omitted
    :param known_types: Registered widget types. When given, every node type
        other than the root grid has to be one of them.
    :raises DocumentValidationError: If the document is malformed, is not a
        single tree, names an unknown type or exceeds a limit
    """
    limits = limits or current_limits()
    if not isinstance(document, dict) or not isinstance(document.get("nodes"), dict):
        raise DocumentValidationError("document.nodes must be an object")
    version = document.get("version", DOCUMENT_VERSION)
    if isinstance(version, bool) or version != DOCUMENT_VERSION:
        raise DocumentValidationError(
            f"unsupported document version; expected {DOCUMENT_VERSION}"
        )
    nodes: dict[str, Any] = document["nodes"]
    if len(nodes) > limits.max_nodes:
        raise DocumentValidationError(
            f"document has {len(nodes)} nodes; the limit is {limits.max_nodes}"
        )
    root = nodes.get(ROOT_ID)
    if not isinstance(root, dict) or not is_container(root):
        raise DocumentValidationError("document must contain a root container")

    stored: dict[str, dict[str, Any]] = {}
    widgets: list[DocumentWidget] = []
    for node_id, node in nodes.items():
        stored_node = _normalize_node(node_id, node, nodes, limits)
        node_type = stored_node["type"]
        container = "children" in stored_node
        if node_type == GRID_TYPE:
            if not container:
                raise DocumentValidationError(
                    f"node {node_id!r} of type {GRID_TYPE!r} must have children"
                )
        else:
            if known_types is not None and node_type not in known_types:
                raise DocumentValidationError(
                    f"node {node_id!r} has unknown type {node_type!r}"
                )
            widgets.append(
                DocumentWidget(
                    node_id, node_type, stored_node.get("props") or {}, container
                )
            )
        stored[node_id] = stored_node

    _check_tree(stored, limits.max_depth)

    result = {"version": DOCUMENT_VERSION, "nodes": stored}
    size = len(
        stdlib_json.dumps(result, allow_nan=False, separators=(",", ":")).encode(
            "utf-8"
        )
    )
    if size > limits.max_bytes:
        raise DocumentValidationError(
            f"document is {size} bytes; the limit is {limits.max_bytes}"
        )
    return result, widgets


def document_revision(stored: dict[str, Any]) -> int:
    """
    The revision of a stored document; ``0`` for one stored without a
    revision.
    """
    revision = stored.get(REVISION_KEY)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        return 0
    return revision


def with_revision(stored: dict[str, Any], revision: int) -> dict[str, Any]:
    """A copy of a normalized document stamped with ``revision``."""
    return {
        "version": stored.get("version", DOCUMENT_VERSION),
        REVISION_KEY: revision,
        "nodes": stored["nodes"],
    }


def without_revision(stored: dict[str, Any]) -> dict[str, Any]:
    """The document as served to clients: the revision travels beside it."""
    return {key: value for key, value in stored.items() if key != REVISION_KEY}


def validate_stored_document(value: Any) -> None:
    """
    Structural validation for a ``v2_document`` arriving inside a dashboard's
    ``json_metadata`` (dashboard update, import) instead of through the
    Dashboard v2 API. Widget types are not checked on this path.

    :raises DocumentValidationError: If the document is malformed
    """
    if value is None:
        return
    normalize_document(value)
    revision = value.get(REVISION_KEY)
    if revision is not None and (
        isinstance(revision, bool) or not isinstance(revision, int) or revision < 0
    ):
        raise DocumentValidationError(
            "document.revision must be a non-negative integer"
        )


def load_stored_document(json_metadata: Any) -> dict[str, Any] | None:
    """The stored document from a dashboard's ``json_metadata``, or ``None``
    when the dashboard is not a v2 dashboard."""
    if not isinstance(json_metadata, str):
        return None
    try:
        metadata = json.loads(json_metadata or "{}")
    except json.JSONDecodeError:
        return None
    document = metadata.get(V2_DOCUMENT_KEY) if isinstance(metadata, dict) else None
    if not isinstance(document, dict) or not isinstance(document.get("nodes"), dict):
        return None
    return document


def write_stored_document(json_metadata: Any, stored: dict[str, Any]) -> str:
    """``json_metadata`` with the v2 document replaced, other keys untouched."""
    try:
        metadata = json.loads(str(json_metadata) if json_metadata else "{}")
    except json.JSONDecodeError:
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    metadata[V2_DOCUMENT_KEY] = stored
    return json.dumps(metadata)
