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
from __future__ import annotations

import sys
from typing import Any

import pytest

from superset.dashboard_v2.document import (
    document_revision,
    DocumentLimits,
    DocumentValidationError,
    load_stored_document,
    normalize_document,
    parse_strict_json,
    validate_stored_document,
    with_revision,
    without_revision,
    write_stored_document,
)
from superset.utils import json
from superset.widgets.data import (
    build_widget_query,
    FilterValidationError,
    resolved_filters_to_adhoc,
    WidgetDataError,
)

COLUMNS = {"gender", "num", "ds"}


def _document() -> dict[str, Any]:
    return {
        "version": 1,
        "nodes": {
            "root": {"type": "grid", "layout": {"columns": 24}, "children": ["tabs"]},
            "tabs": {
                "type": "tabs",
                "children": ["node_1", "node_2"],
                "props": {"title": "Tabs"},
            },
            "node_1": {
                "type": "echarts",
                "layout": {"colSpan": 12},
                "props": {"dataBinding": {"datasetId": 7, "metrics": ["count"]}},
                "widgetUuid": "stale-key-from-an-older-document",
            },
            "node_2": {"type": "markdown", "props": {"content": "# hi"}},
        },
    }


def test_normalize_document_keeps_props_inline_and_drops_unknown_keys() -> None:
    stored, leaves = normalize_document(_document())

    assert stored["version"] == 1
    assert stored["nodes"]["node_1"] == {
        "type": "echarts",
        "layout": {"colSpan": 12},
        "props": {"dataBinding": {"datasetId": 7, "metrics": ["count"]}},
    }
    assert stored["nodes"]["tabs"]["children"] == ["node_1", "node_2"]
    assert "revision" not in stored
    # Every node but the root grid is handed to its widget type's validation,
    # containers included.
    assert [(leaf.node_id, leaf.widget_type, leaf.is_container) for leaf in leaves] == [
        ("tabs", "tabs", True),
        ("node_1", "echarts", False),
        ("node_2", "markdown", False),
    ]
    assert leaves[2].props == {"content": "# hi"}


def _grid(**nodes: Any) -> dict[str, Any]:
    return {"nodes": nodes}


def _chain(length: int) -> dict[str, Any]:
    """A root with ``length`` containers nested one inside the other."""
    nodes: dict[str, Any] = {"root": {"type": "grid", "children": ["n1"]}}
    for index in range(1, length + 1):
        children = [f"n{index + 1}"] if index < length else []
        nodes[f"n{index}"] = {"type": "grid", "children": children}
    return {"nodes": nodes}


@pytest.mark.parametrize(
    "document, message",
    [
        # A node that contains itself.
        (_grid(root={"type": "grid", "children": ["root"]}), "own ancestor"),
        (
            _grid(
                root={"type": "grid", "children": ["a"]},
                a={"type": "grid", "children": ["a"]},
            ),
            "own ancestor",
        ),
        # A cycle through two containers.
        (
            _grid(
                root={"type": "grid", "children": ["a"]},
                a={"type": "grid", "children": ["b"]},
                b={"type": "grid", "children": ["a"]},
            ),
            "own ancestor",
        ),
        # The same node under two parents.
        (
            _grid(
                root={"type": "grid", "children": ["a", "b"]},
                a={"type": "grid", "children": ["leaf"]},
                b={"type": "grid", "children": ["leaf"]},
                leaf={"type": "markdown"},
            ),
            "more than one parent",
        ),
        # The same id twice in one children array.
        (
            _grid(
                root={"type": "grid", "children": ["a", "a"]},
                a={"type": "markdown"},
            ),
            "same child more than once",
        ),
        # A node nothing points at, and a cycle detached from the root.
        (
            _grid(root={"type": "grid", "children": []}, orphan={"type": "markdown"}),
            "not reachable from the root",
        ),
        (
            _grid(
                root={"type": "grid", "children": []},
                a={"type": "grid", "children": ["b"]},
                b={"type": "grid", "children": ["a"]},
            ),
            "not reachable from the root",
        ),
        # Children that are not node ids (unhashable values included).
        (
            _grid(root={"type": "grid", "children": [{"id": "a"}]}),
            "array of node ids",
        ),
        (_grid(root={"type": "grid", "children": [["a"]]}), "array of node ids"),
        (
            _grid(
                root={"type": "grid", "children": ["a"]},
                a={"type": "markdown", "children": "root"},
            ),
            "array of node ids",
        ),
        # Ids outside the allowed alphabet or length.
        (
            _grid(
                **{
                    "root": {"type": "grid", "children": ["a b"]},
                    "a b": {"type": "markdown"},
                }
            ),
            "node id",
        ),
        (
            _grid(
                **{
                    "root": {"type": "grid", "children": ["x" * 65]},
                    "x" * 65: {"type": "markdown"},
                }
            ),
            "node id",
        ),
        # A grid that is not a container, an unsupported version.
        (
            _grid(
                root={"type": "grid", "children": ["a"]},
                a={"type": "grid"},
            ),
            "must have children",
        ),
        (
            {"version": 2, "nodes": {"root": {"type": "grid", "children": []}}},
            "version",
        ),
        # Values JSON cannot represent.
        (
            _grid(
                root={"type": "grid", "children": ["a"]},
                a={"type": "markdown", "props": {"value": float("nan")}},
            ),
            "non-finite",
        ),
        (
            _grid(
                root={"type": "grid", "children": ["a"]},
                a={"type": "markdown", "style": {"width": float("inf")}},
            ),
            "non-finite",
        ),
        (
            _grid(
                root={"type": "grid", "children": ["a"]},
                a={"type": "markdown", "props": {"value": {1, 2}}},
            ),
            "non-JSON value of type set",
        ),
        (
            _grid(
                root={"type": "grid", "children": ["a"]},
                a={"type": "markdown", "layout": {"value": b"bytes"}},
            ),
            "non-JSON value of type bytes",
        ),
        (
            _grid(
                root={"type": "grid", "children": ["a"]},
                a={"type": "markdown", "props": {1: "integer key"}},
            ),
            "non-string object key",
        ),
    ],
)
def test_normalize_document_rejects_invalid_trees_and_values(
    document: Any, message: str
) -> None:
    with pytest.raises(DocumentValidationError, match=message):
        normalize_document(document)


def test_normalize_document_enforces_depth_limit() -> None:
    limits = DocumentLimits(max_depth=3)

    normalize_document(_chain(3), limits=limits)
    with pytest.raises(DocumentValidationError, match="deeper than 3 levels"):
        normalize_document(_chain(4), limits=limits)


def test_normalize_document_enforces_node_limit() -> None:
    def flat(count: int) -> dict[str, Any]:
        names = [f"n{index}" for index in range(count)]
        return _grid(
            root={"type": "grid", "children": names},
            **{name: {"type": "markdown"} for name in names},
        )

    limits = DocumentLimits(max_nodes=5)

    normalize_document(flat(4), limits=limits)
    with pytest.raises(DocumentValidationError, match="6 nodes; the limit is 5"):
        normalize_document(flat(5), limits=limits)


def test_normalize_document_enforces_size_limit() -> None:
    document = _grid(
        root={"type": "grid", "children": ["a"]},
        a={"type": "markdown", "props": {"content": "x" * 2000}},
    )

    normalize_document(document, limits=DocumentLimits(max_bytes=4000))
    with pytest.raises(DocumentValidationError, match="the limit is 1000"):
        normalize_document(document, limits=DocumentLimits(max_bytes=1000))


def test_normalize_document_enforces_value_depth_limit() -> None:
    def nested(levels: int) -> dict[str, Any]:
        value: Any = "leaf"
        for _ in range(levels):
            value = {"next": value}
        return _grid(
            root={"type": "grid", "children": ["a"]},
            a={"type": "markdown", "props": value},
        )

    limits = DocumentLimits(max_value_depth=4)

    normalize_document(nested(4), limits=limits)
    with pytest.raises(DocumentValidationError, match="deeper than 4 levels"):
        normalize_document(nested(5), limits=limits)


def test_normalize_document_survives_hostile_nesting_without_recursion() -> None:
    """Neither a very long chain of containers nor a self-referential value
    reaches the interpreter's recursion limit: both are refused by a bound."""
    depth = sys.getrecursionlimit() * 5
    unlimited = DocumentLimits(max_nodes=depth + 10, max_depth=depth + 10)

    stored, _ = normalize_document(_chain(depth), limits=unlimited)
    assert len(stored["nodes"]) == depth + 1

    with pytest.raises(DocumentValidationError, match="deeper than 16 levels"):
        normalize_document(_chain(depth), limits=DocumentLimits(max_nodes=depth + 10))

    looped: dict[str, Any] = {}
    looped["self"] = looped
    with pytest.raises(DocumentValidationError, match="nested deeper"):
        normalize_document(
            _grid(
                root={"type": "grid", "children": ["a"]},
                a={"type": "markdown", "props": looped},
            )
        )


def test_normalize_document_rejects_unknown_types_when_types_are_known() -> None:
    document = _grid(
        root={"type": "grid", "children": ["a", "box"]},
        a={"type": "markdown"},
        box={"type": "mystery-container", "children": []},
    )

    normalize_document(document, known_types={"markdown", "mystery-container"})
    with pytest.raises(
        DocumentValidationError, match="unknown type 'mystery-container'"
    ):
        normalize_document(document, known_types={"markdown"})


@pytest.mark.parametrize(
    "raw, message",
    [
        ('{"nodes": {"a": 1, "a": 2}}', "duplicate key 'a'"),
        ('{"value": NaN}', "NaN is not a valid JSON value"),
        ('{"value": -Infinity}', "-Infinity is not a valid JSON value"),
        ("{not json", "not valid JSON"),
        (b"\xff\xfe", "not valid JSON"),
        ("[" * 200_000, "nested too deeply"),
        ('{"a":' * 200_000, "nested too deeply"),
    ],
)
def test_parse_strict_json_rejects(raw: bytes | str, message: str) -> None:
    with pytest.raises(DocumentValidationError, match=message):
        parse_strict_json(raw)


def test_parse_strict_json_accepts_plain_json() -> None:
    assert parse_strict_json(b'{"a": [1, 2.5, "x", null, true]}') == {
        "a": [1, 2.5, "x", None, True]
    }


def test_revision_helpers() -> None:
    stored, _ = normalize_document(_document())

    assert document_revision(stored) == 0
    stamped = with_revision(stored, 7)
    assert document_revision(stamped) == 7
    assert stamped["nodes"] is stored["nodes"]
    assert without_revision(stamped) == stored
    for junk in (True, -1, "3", 2.0, None):
        assert document_revision({**stored, "revision": junk}) == 0


def test_validate_stored_document() -> None:
    stored, _ = normalize_document(_document())

    validate_stored_document(None)
    validate_stored_document(with_revision(stored, 3))
    with pytest.raises(DocumentValidationError, match="revision"):
        validate_stored_document({**stored, "revision": "3"})
    with pytest.raises(DocumentValidationError, match="own ancestor"):
        validate_stored_document(
            _grid(root={"type": "grid", "children": ["root"]}),
        )


def test_dashboard_json_metadata_rejects_a_malformed_v2_document() -> None:
    """A legacy dashboard update cannot smuggle in a cyclic document."""
    from marshmallow import ValidationError

    from superset.dashboards.schemas import validate_json_metadata

    stored, _ = normalize_document(_document())
    validate_json_metadata(json.dumps({"v2_document": with_revision(stored, 2)}))
    with pytest.raises(ValidationError, match="own ancestor"):
        validate_json_metadata(
            json.dumps(
                {"v2_document": _grid(root={"type": "grid", "children": ["root"]})}
            )
        )


@pytest.mark.parametrize(
    "document, message",
    [
        (None, "document.nodes"),
        ({"nodes": {}}, "root container"),
        (
            {"nodes": {"root": {"type": "grid", "children": ["missing"]}}},
            "unknown children",
        ),
        (
            {
                "nodes": {
                    "root": {"type": "grid", "children": ["a"]},
                    "a": {"type": "markdown", "props": ["not", "a", "dict"]},
                }
            },
            "props must be an object",
        ),
        (
            {
                "nodes": {
                    "root": {"type": "grid", "children": ["a"]},
                    "a": {"props": {}},
                }
            },
            "string type",
        ),
    ],
)
def test_normalize_document_rejects_malformed(document: Any, message: str) -> None:
    with pytest.raises(DocumentValidationError, match=message):
        normalize_document(document)


def test_stored_document_round_trips_through_json_metadata() -> None:
    stored, _ = normalize_document(_document())
    json_metadata = write_stored_document(
        json.dumps({"color_scheme": "supersetColors"}), stored
    )

    metadata = json.loads(json_metadata)
    assert metadata["color_scheme"] == "supersetColors"
    assert load_stored_document(json_metadata) == stored


def test_load_stored_document_rejects_non_v2() -> None:
    assert load_stored_document(json.dumps({"color_scheme": "x"})) is None
    assert load_stored_document("not json") is None
    assert load_stored_document(None) is None


@pytest.mark.parametrize(
    "resolved, expected",
    [
        ({"column": "gender", "operator": "EQUALS", "value": "boy"}, [("==", "boy")]),
        (
            {"column": "gender", "operator": "NOT_EQUALS", "value": "boy"},
            [("!=", "boy")],
        ),
        (
            {"column": "gender", "operator": "IN", "value": ["a", "b"]},
            [("IN", ["a", "b"])],
        ),
        (
            {"column": "gender", "operator": "NOT_IN", "value": ["a"]},
            [("NOT IN", ["a"])],
        ),
        (
            {"column": "num", "operator": "RANGE", "value": {"min": 1, "max": 5}},
            [(">=", 1), ("<=", 5)],
        ),
        (
            {
                "column": "ds",
                "operator": "TIME_RANGE",
                "value": {"start": "2020-01-01", "end": "2021-01-01"},
            },
            [(">=", "2020-01-01"), ("<", "2021-01-01")],
        ),
        ({"column": "gender", "operator": "IN", "value": []}, []),
        (
            {
                "column": "gender",
                "operator": "EQUALS",
                "value": "boy",
                "datasource": 7,
            },
            [("==", "boy")],
        ),
    ],
)
def test_resolved_filters_to_adhoc(
    resolved: dict[str, Any], expected: list[tuple[str, Any]]
) -> None:
    adhoc = resolved_filters_to_adhoc([resolved], COLUMNS)

    assert [(item["operator"], item["comparator"]) for item in adhoc] == expected
    assert all(
        item["expressionType"] == "SIMPLE"
        and item["clause"] == "WHERE"
        and item["subject"] == resolved["column"]
        for item in adhoc
    )


@pytest.mark.parametrize(
    "filters, message",
    [
        ({"column": "gender"}, "must be a list"),
        (["gender = 'boy'"], "must be an object"),
        (
            [{"column": "salary", "operator": "EQUALS", "value": 1}],
            "unknown column",
        ),
        (
            [{"column": "gender", "operator": "LIKE", "value": "b%"}],
            "unsupported operator",
        ),
        (
            [{"expressionType": "SQL", "clause": "WHERE", "sqlExpression": "1 = 1"}],
            "unknown column",
        ),
        (
            [{"column": "gender", "operator": "EQUALS", "value": ["a"]}],
            "scalar",
        ),
        (
            [{"column": "gender", "operator": "IN", "value": [{"a": 1}]}],
            "list of scalars",
        ),
        (
            [
                {
                    "column": "num",
                    "operator": "RANGE",
                    "value": {"min": 1, "sqlExpression": "1"},
                }
            ],
            "object with",
        ),
    ],
)
def test_resolved_filters_to_adhoc_rejects(filters: Any, message: str) -> None:
    with pytest.raises(FilterValidationError, match=message):
        resolved_filters_to_adhoc(filters, COLUMNS)


def test_build_widget_query_uses_stored_binding() -> None:
    props = {
        "dataBinding": {
            "datasetId": 7,
            "metrics": ["count", ""],
            "dimensions": ["gender", ""],
            "filters": [
                {"expressionType": "SQL", "clause": "WHERE", "sqlExpression": "1 = 1"},
                {
                    "expressionType": "SIMPLE",
                    "clause": "WHERE",
                    "subject": "num",
                    "operator": ">",
                    "comparator": 0,
                },
                {},
            ],
        }
    }
    host_filters = resolved_filters_to_adhoc(
        [{"column": "gender", "operator": "EQUALS", "value": "boy"}], COLUMNS
    )

    dataset_id, query, form_data = build_widget_query(props, host_filters)

    assert dataset_id == 7
    assert query["metrics"] == ["count"]
    assert query["columns"] == ["gender"]
    assert query["row_limit"] == 1000
    assert query["extras"] == {"where": "(1 = 1)", "having": ""}
    assert query["filters"] == [
        {"col": "num", "op": ">", "val": 0},
        {"col": "gender", "op": "==", "val": "boy"},
    ]
    assert form_data["datasource"] == "7__table"


@pytest.mark.parametrize(
    "props",
    [{}, {"dataBinding": {"metrics": ["count"]}}, {"dataBinding": {"datasetId": "7"}}],
)
def test_build_widget_query_requires_binding(props: dict[str, Any]) -> None:
    with pytest.raises(WidgetDataError):
        build_widget_query(props, [])
