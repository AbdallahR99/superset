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
The ``DASHBOARD_V2`` feature gate shared by the widget and Dashboard V2 routes.

Kept free of other ``superset.widgets`` imports so any API or view module can
use it without pulling in the widget registry.
"""

from __future__ import annotations

import functools
from typing import Any, Callable, TypeVar

from flask import abort

DASHBOARD_V2_FLAG = "DASHBOARD_V2"

F = TypeVar("F", bound=Callable[..., Any])


def is_dashboard_v2_enabled() -> bool:
    """Whether the Dashboard V2 builder and the widget APIs are switched on."""
    # pylint: disable=import-outside-toplevel
    from superset import is_feature_enabled

    return bool(is_feature_enabled(DASHBOARD_V2_FLAG))


def requires_dashboard_v2(func: F) -> F:
    """
    Answer 404 from a REST API or view method unless ``DASHBOARD_V2`` is on.

    Apply it directly under ``@expose`` (above ``@protect()`` / ``@has_access``
    and ``@safe``) so a disabled deployment gives the same "no such route"
    answer to every caller, signed in or not, and no handler code runs.
    """

    @functools.wraps(func)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        if not is_dashboard_v2_enabled():
            if callable(response_404 := getattr(self, "response_404", None)):
                return response_404()
            abort(404)
        return func(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]
