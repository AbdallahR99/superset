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
from base64 import b64decode

from superset.thumbnails.layout import layout_thumbnail
from superset.utils import json


def test_v2_layout_uses_spans_without_widget_content() -> None:
    nodes = {
        "root": {"children": ["metric", "plot"], "layout": {"columns": 24}},
        "metric": {"type": "metric-tile", "layout": {"colSpan": 8}},
        "plot": {
            "type": "echarts",
            "layout": {"colSpan": 16},
            "props": {"sql": "private"},
        },
    }
    uri = layout_thumbnail(json.dumps({"v2_document": {"nodes": nodes}}), None, 49)
    image = b64decode(uri.split(",")[1])
    assert b'width="77"' in image
    assert b'width="157"' in image
    assert b"private" not in image


def test_classic_preview_uses_first_tab_and_handles_cycles() -> None:
    nodes = {
        "ROOT_ID": {"children": ["tabs"]},
        "tabs": {"type": "TABS", "children": ["row", "other"]},
        "row": {"type": "ROW", "children": ["first", "second", "ROOT_ID"]},
        "first": {"type": "CHART", "meta": {"width": 6}},
        "second": {"type": "CHART", "meta": {"width": 6}},
        "other": {"type": "CHART", "meta": {"width": 12}},
    }
    image = b64decode(layout_thumbnail(None, json.dumps(nodes), 1).split(",")[1])
    assert image.count(b'width="117"') == 2
    assert b'width="237"' not in image
