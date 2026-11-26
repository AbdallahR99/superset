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
CACHE_CONFIG = {"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": 300}
DATA_CACHE_CONFIG = CACHE_CONFIG
SCARF_ANALYTICS = False
WEBSOCKET_ENABLE = False
