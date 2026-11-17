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
The widget routes' OpenAPI docstrings. One docstring that is not valid YAML
breaks the whole generated spec, and with it ``/swagger`` for every API.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest
import yaml

from superset.widgets.api import SavedWidgetRestApi, WidgetControlsRestApi


@pytest.mark.parametrize("api", [WidgetControlsRestApi, SavedWidgetRestApi])
def test_openapi_docstrings_are_valid_yaml(api: type) -> None:
    documented = 0
    for name, method in inspect.getmembers(api, predicate=inspect.isfunction):
        doc = inspect.getdoc(method) or ""
        if not hasattr(method, "_urls") or "---" not in doc:
            continue
        spec = yaml.safe_load(doc.split("---", 1)[1])
        assert isinstance(spec, dict), name
        for operation in spec.values():
            assert operation["responses"], name
        documented += 1
    assert documented >= 3


@pytest.mark.parametrize("app", [{"FAB_API_SWAGGER_UI": True}], indirect=True)
def test_widget_routes_are_in_the_openapi_spec(
    client: Any, full_api_access: None
) -> None:
    """The spec is built whether or not ``DASHBOARD_V2`` is on."""
    response = client.get("/api/v1/_openapi")

    assert response.status_code == 200
    paths = response.get_json()["paths"]
    assert "/api/v1/widget/data" in paths
    assert "/api/v1/widget/values" in paths
    assert "/api/v1/widgets/type/{widget_type}/control-schema" in paths
    listing = paths["/api/v1/widget/"]["get"]
    assert {"page", "page_size"} <= {
        parameter["name"] for parameter in listing["parameters"]
    }
    description = paths["/api/v1/widgets/type/{widget_type}/control-schema"]["post"][
        "responses"
    ]["200"]["description"]
    assert "{path: schema}" in description
