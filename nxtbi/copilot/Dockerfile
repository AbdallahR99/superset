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

FROM python:3.12-slim AS agent
ENV PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY nxtbi/copilot/agent/requirements.txt /tmp/copilot-requirements.txt
RUN pip install --no-cache-dir -r /tmp/copilot-requirements.txt \
    && useradd --system --uid 10001 copilot
COPY nxtbi/copilot/agent /app/nxtbi/copilot/agent
USER copilot
EXPOSE 8100
CMD ["uvicorn", "nxtbi.copilot.agent.app:app", "--host", "0.0.0.0", "--port", "8100"]

FROM node:24-bookworm AS standalone-web
WORKDIR /build
COPY superset-frontend/packages/nxtbi-copilot superset-frontend/packages/nxtbi-copilot
COPY nxtbi/copilot/standalone nxtbi/copilot/standalone
WORKDIR /build/nxtbi/copilot/standalone
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit && npm run build

FROM agent AS standalone
COPY nxtbi/copilot/standalone/gateway.py /app/nxtbi/copilot/standalone/gateway.py
COPY --from=standalone-web /build/nxtbi/copilot/standalone/dist /app/site
ENV NXTBI_COPILOT_STATIC_DIR=/app/site
EXPOSE 8101
CMD ["uvicorn", "nxtbi.copilot.standalone.gateway:app", "--host", "0.0.0.0", "--port", "8101"]
