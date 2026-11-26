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
"""Local configuration for the disposable Copilot lifecycle check."""

import os

from flask_appbuilder.const import AUTH_DB

SECRET_KEY = os.environ["A2UI_FIXTURE_APP_SECRET"]
SQLALCHEMY_DATABASE_URI = os.environ["A2UI_FIXTURE_METADATA_URI"]
SQLALCHEMY_EXAMPLES_URI = os.environ["A2UI_FIXTURE_DATA_URI"]
AUTH_TYPE = AUTH_DB
LANGUAGES = {
    "en": {"flag": "us", "name": "English"},
    "ar": {"flag": "sa", "name": "Arabic"},
}
BABEL_DEFAULT_LOCALE = "en"

FEATURE_FLAGS = {
    "DASHBOARD_V2": True,
    "ENABLE_EXTENSIONS": True,
    "EMBEDDED_SUPERSET": True,
    "NXTBI_AI_COPILOT": True,
    "VERSION_HISTORY": True,
}

LOCAL_EXTENSIONS = ["/app/copilot-extension"]
NXTBI_COPILOT_AGENT_URL = os.environ["A2UI_FIXTURE_AGENT_URL"]
NXTBI_COPILOT_SHARED_SECRET = os.environ["NXTBI_COPILOT_SHARED_SECRET"]
NXTBI_COPILOT_CSV_DATABASE = "Lifecycle uploads"
NXTBI_COPILOT_CSV_SCHEMA = "public"

CACHE_CONFIG = {"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": 300}
DATA_CACHE_CONFIG = CACHE_CONFIG
GUEST_ROLE_NAME = "Gamma"
GUEST_TOKEN_WIDGET_RLS_GUARD = True
GUEST_TOKEN_JWT_SECRET = os.environ["A2UI_FIXTURE_GUEST_SECRET"]
GUEST_TOKEN_JWT_AUDIENCE = "nxtbi-copilot-lifecycle"  # noqa: S105 - Public audience.

ENABLE_CORS = True
CORS_OPTIONS = {
    "origins": [os.environ["A2UI_FIXTURE_WIDGET_ORIGIN"]],
    "supports_credentials": True,
    "allow_headers": ["Content-Type", "X-GuestToken", "X-CSRFToken"],
}

ENABLE_VERSIONING_CAPTURE = True
SCARF_ANALYTICS = False
WEBSOCKET_ENABLE = False

MCP_AUTH_ENABLED = True
MCP_JWT_ALGORITHM = "HS256"
MCP_JWT_SECRET = os.environ["A2UI_FIXTURE_MCP_SECRET"]
MCP_JWT_ISSUER = "copilot-lifecycle"
MCP_JWT_AUDIENCE = "copilot-lifecycle-mcp"
NXTBI_COPILOT_MCP_URL = os.environ["A2UI_FIXTURE_MCP_URL"]
MCP_TOOL_SEARCH_CONFIG = {"enabled": False}
MCP_TOOL_SEARCH_CONFIG = {"enabled": False}
