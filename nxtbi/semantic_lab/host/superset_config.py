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
"""Configure the disposable Superset semantic-layer lab."""

import os

from flask_appbuilder.const import AUTH_DB

SECRET_KEY = os.environ["NXTBI_SEMANTIC_LAB_APP_SECRET"]
AUTH_TYPE = AUTH_DB
SQLALCHEMY_DATABASE_URI = "sqlite:////tmp/nxtbi-semantic-lab.db"
LANGUAGES = {
    "en": {"flag": "us", "name": "English"},
    "ar": {"flag": "sa", "name": "Arabic"},
}
FEATURE_FLAGS = {
    "ENABLE_EXTENSIONS": True,
    "SEMANTIC_LAYERS": True,
    "SEMANTIC_LAYER_CONTAINMENT_CACHE": False,
}
LOCAL_EXTENSIONS = ["/semantic-lab-extension"]
if widget_origin := os.getenv("NXTBI_SEMANTIC_LAB_WIDGET_ORIGIN"):
    FEATURE_FLAGS.update(DASHBOARD_V2=True, EMBEDDED_SUPERSET=True)
    GUEST_TOKEN_JWT_SECRET = os.environ["NXTBI_SEMANTIC_LAB_GUEST_SECRET"]
    ENABLE_CORS = True
    CORS_OPTIONS = {
        "origins": [widget_origin],
        "supports_credentials": True,
        "allow_headers": ["Content-Type", "X-CSRFToken"],
    }
NXTBI_COPILOT_SEMANTIC_LAB = os.getenv("NXTBI_COPILOT_SEMANTIC_LAB") == "1"
if NXTBI_COPILOT_SEMANTIC_LAB:
    FEATURE_FLAGS["NXTBI_AI_COPILOT"] = True
    EXTENSIONS_PATH = "/semantic-lab-bundles"
    NXTBI_COPILOT_AGENT_URL = os.environ["NXTBI_COPILOT_AGENT_URL"]
    NXTBI_COPILOT_SHARED_SECRET = os.environ["NXTBI_COPILOT_SHARED_SECRET"]

CACHE_CONFIG = {"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": 300}
DATA_CACHE_CONFIG = CACHE_CONFIG
SCARF_ANALYTICS = False
WEBSOCKET_ENABLE = False
