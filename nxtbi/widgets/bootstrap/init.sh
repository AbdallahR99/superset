#!/bin/bash
#
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
#
# One-shot initialisation of the Widget Framework stack (compose project
# "nxtbi-widgets"). Runs on every `docker compose up` and converges: every step is
# idempotent.
#
# One-off switch (environment of the superset-init service):
#   docker compose -f nxtbi/widgets/docker-compose.yml run --rm -e WIDGETS_FORCE_SEED=yes superset-init
#     WIDGETS_FORCE_SEED=yes   rebuild the example tables and the RLS demo table
set -euo pipefail

BOOTSTRAP=/app/nxtbi-widgets/bootstrap/widgets_bootstrap.py

step() { printf '\n=== [nxtbi-widgets-init] %s ===\n' "$1"; }

step "0/5 preflight"
python - <<'PY'
import os
import sys

import psycopg2

try:
    psycopg2.connect(
        host=os.environ.get("DATABASE_HOST", "db"),
        port=os.environ.get("DATABASE_PORT", "5432"),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        connect_timeout=10,
    ).close()
except psycopg2.OperationalError as exc:
    if "password authentication failed" in str(exc):
        sys.exit(
            "nxtbi/widgets/.env does not match the existing database volume (passwords "
            "are set when the volume is created).\nRestore the previous nxtbi/widgets/.env, "
            "or start clean with: docker compose -f nxtbi/widgets/docker-compose.yml down -v"
        )
    sys.exit(f"cannot reach the metadata database: {exc}")
print("metadata database credentials ok")
PY
if [ ! -s /app/superset/translations/ar/LC_MESSAGES/messages.json ]; then
  echo "NOTE: the Arabic language pack is not in this image (built without" >&2
  echo "      BUILD_TRANSLATIONS=true). Arabic pages are right-to-left with English text." >&2
fi

step "1/5 metadata database migrations"
superset db upgrade

step "2/5 roles and permissions"
superset init

step "3/5 admin, Gamma demo user, WidgetGuest and WidgetsRlsDemo roles"
python "$BOOTSTRAP" accounts

step "4/5 example datasets birth_names and video_game_sales"
python "$BOOTSTRAP" examples

step "5/5 row level security demo"
python "$BOOTSTRAP" rls

step "done"
