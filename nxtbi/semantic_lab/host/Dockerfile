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

ARG SUPERSET_ASSETS_IMAGE=nxtbi/superset-fork:localization-assets
ARG SUPERSET_BASE_IMAGE=nxtbi/superset-fork:copilot-localization-verified

FROM ${SUPERSET_ASSETS_IMAGE} AS assets
WORKDIR /app/superset-frontend
COPY superset-frontend/packages/superset-core/src/widgets/ packages/superset-core/src/widgets/
COPY superset-frontend/packages/superset-widgets/src/ packages/superset-widgets/src/
COPY superset-frontend/src/core/dashboard/EmbedWidgetModal.tsx src/core/dashboard/EmbedWidgetModal.tsx
COPY superset-frontend/src/pages/DashboardBuilderV2/SchemaControlPanel.tsx src/pages/DashboardBuilderV2/SchemaControlPanel.tsx
COPY superset-frontend/src/pages/DashboardBuilderV2/EmbedDashboardModal.tsx src/pages/DashboardBuilderV2/EmbedDashboardModal.tsx
RUN npm run build > /tmp/semantic-lab-assets.log 2>&1 || { tail -n 100 /tmp/semantic-lab-assets.log; exit 1; }

FROM ${SUPERSET_BASE_IMAGE}
COPY --from=assets /app/superset/static/assets /app/superset/static/assets
COPY --from=assets /app/superset/static/service-worker.js /app/superset/static/service-worker.js
