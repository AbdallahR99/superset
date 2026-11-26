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

ARG SUPERSET_BASE_IMAGE=nxtbi/superset-fork:upstream-sync-2c58859901
FROM ${SUPERSET_BASE_IMAGE} AS superset
COPY --chown=superset:superset superset/copilot /app/superset/copilot
COPY --chown=superset:superset superset/config.py /app/superset/config.py
COPY --chown=superset:superset superset/initialization/__init__.py /app/superset/initialization/__init__.py
COPY --chown=superset:superset superset/dashboards/api.py /app/superset/dashboards/api.py
COPY --chown=superset:superset superset/daos/log.py /app/superset/daos/log.py
COPY --chown=superset:superset superset/models/dashboard.py /app/superset/models/dashboard.py
COPY --chown=superset:superset superset/views/core.py /app/superset/views/core.py
COPY --chown=superset:superset superset/commands/dashboard_v2/get.py /app/superset/commands/dashboard_v2/get.py
COPY --chown=superset:superset superset/dashboard_v2/api.py /app/superset/dashboard_v2/api.py
COPY --chown=superset:superset superset/dashboard_v2/schemas.py /app/superset/dashboard_v2/schemas.py
COPY --chown=superset:superset superset/thumbnails/layout.py /app/superset/thumbnails/layout.py
