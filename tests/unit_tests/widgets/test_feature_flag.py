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
The widget REST APIs are part of Dashboard V2: with ``DASHBOARD_V2`` off (the
default) every route answers 404, to signed-in and anonymous callers alike.
"""

from __future__ import annotations

from typing import Any

import pytest

from superset.utils import json

ROUTES: list[tuple[str, str]] = [
    ("GET", "/api/v1/widgets/types"),
    ("GET", "/api/v1/widgets/type/metric-tile/control-schema"),
    ("POST", "/api/v1/widgets/type/metric-tile/control-schema"),
    ("POST", "/api/v1/widgets/type/metric-tile/validate"),
    ("GET", "/api/v1/widget/"),
    ("POST", "/api/v1/widget/"),
    ("GET", "/api/v1/widget/3f0e6f0e-0d5a-4f55-9d0b-3f6f4a2b9c11"),
    ("PUT", "/api/v1/widget/3f0e6f0e-0d5a-4f55-9d0b-3f6f4a2b9c11"),
    ("DELETE", "/api/v1/widget/3f0e6f0e-0d5a-4f55-9d0b-3f6f4a2b9c11"),
    ("POST", "/api/v1/widget/data"),
    ("POST", "/api/v1/widget/values"),
]


def _call(client: Any, method: str, url: str) -> Any:
    return client.open(
        url, method=method, data=json.dumps({}), content_type="application/json"
    )


@pytest.mark.parametrize("method, url", ROUTES)
def test_widget_routes_are_404_when_flag_is_off(
    client: Any, full_api_access: None, method: str, url: str
) -> None:
    assert _call(client, method, url).status_code == 404


@pytest.mark.parametrize("method, url", ROUTES)
def test_widget_routes_are_404_for_anonymous_when_flag_is_off(
    client: Any, method: str, url: str
) -> None:
    # 404 rather than 401: a disabled deployment does not reveal the routes.
    assert _call(client, method, url).status_code == 404


def test_requires_dashboard_v2_falls_back_to_abort_for_plain_views(
    app_context: None,
) -> None:
    from werkzeug.exceptions import NotFound

    from superset.widgets.feature import requires_dashboard_v2

    class View:
        @requires_dashboard_v2
        def page(self) -> str:
            return "rendered"

    with pytest.raises(NotFound):
        View().page()
