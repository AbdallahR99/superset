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
Runtime gate for everything that belongs to Dashboard v2.

The views stay registered regardless of the flag, so permissions and the
OpenAPI spec do not depend on it, and a flag resolved per request (through
``GET_FEATURE_FLAGS_FUNC`` / ``IS_FEATURE_ENABLED_FUNC``) is honoured. While
``DASHBOARD_V2`` is off every gated route answers 404 before authentication
or any handler side effect, exactly as if it did not exist.
"""

from __future__ import annotations

from collections.abc import Iterable

from flask import abort, Flask, jsonify, request
from flask.typing import ResponseReturnValue
from flask_appbuilder.api import BaseApi
from flask_appbuilder.baseviews import BaseView

from superset.widgets.feature import is_dashboard_v2_enabled


def register_dashboard_v2_gate(app: Flask, views: Iterable[type[BaseView]]) -> None:
    """
    Make every route of ``views`` answer 404 while ``DASHBOARD_V2`` is off.

    Flask-AppBuilder names a view's blueprint after its class, which is what
    the hook matches on; it is installed on the app because a blueprint
    accepts no further hooks once registered.

    :param app: The Flask app the views are registered on
    :param views: The API and HTML view classes that make up Dashboard v2
    """
    view_classes = tuple(views)
    gated = frozenset(view.__name__ for view in view_classes)
    apis = frozenset(
        view.__name__ for view in view_classes if issubclass(view, BaseApi)
    )

    def refuse_disabled_dashboard_v2() -> ResponseReturnValue | None:
        """Hide the gated blueprints while the feature flag is off."""
        blueprint = request.blueprint
        if blueprint not in gated or is_dashboard_v2_enabled():
            return None
        if blueprint in apis:
            return jsonify({"message": "Not found"}), 404
        abort(404)

    app.before_request(refuse_disabled_dashboard_v2)
