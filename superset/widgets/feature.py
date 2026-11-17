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
The ``DASHBOARD_V2`` feature flag: its name and the one way to resolve it.

There is a single gate. ``superset.dashboard_v2.feature.register_dashboard_v2_gate``
installs one ``before_request`` hook that answers 404, before authentication,
for every route of the Dashboard V2 document API, the widget control API, the
saved-widget API and the builder view while the flag is off; the MCP widget
tools refuse on the same flag. Both resolve the flag through
``is_dashboard_v2_enabled`` here, so no route carries a gate of its own and
there is one place that decides whether the feature is on.

Kept free of other ``superset.widgets`` imports so any API, view or tool module
can use it without pulling in the widget registry.
"""

from __future__ import annotations

DASHBOARD_V2_FLAG = "DASHBOARD_V2"


def is_dashboard_v2_enabled() -> bool:
    """Whether the Dashboard V2 builder and the widget APIs are switched on."""
    # pylint: disable=import-outside-toplevel
    from superset import is_feature_enabled

    return bool(is_feature_enabled(DASHBOARD_V2_FLAG))
