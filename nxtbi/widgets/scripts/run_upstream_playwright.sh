#!/usr/bin/env bash
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
# Runs the upstream Playwright specs of Dashboard V2
# (superset-frontend/playwright/tests/dashboard-v2) against the Widget Framework stack.
#
#   bash nxtbi/widgets/scripts/run_upstream_playwright.sh                    # all dashboard-v2 specs
#   bash nxtbi/widgets/scripts/run_upstream_playwright.sh filters.spec.ts    # one spec (name or path)
#   bash nxtbi/widgets/scripts/run_upstream_playwright.sh -- --grep "conflict"
#   HEADED=1 bash nxtbi/widgets/scripts/run_upstream_playwright.sh           # watch the browser
#
# How the suite takes its target and login:
#   playwright.widgets.config.ts  the upstream playwright.config.ts with absolute paths
#                                 and this stack's sign-in; PLAYWRIGHT_BASE_URL
#   playwright.widgets.global-setup.ts
#                                 PLAYWRIGHT_ADMIN_USERNAME / PLAYWRIGHT_ADMIN_PASSWORD,
#                                 signs in through the login form once and stores the
#                                 session in playwright/.auth/user.json (git-ignored)
# The upstream global setup is not used: it recognises a finished login by a cookie
# named "session", and this stack names its session cookie differently
# (SESSION_COOKIE_NAME in nxtbi/widgets/config/superset_config.py), so it times out
# on a login that succeeded. The stack's own setup reads the name from
# PLAYWRIGHT_SESSION_COOKIE_NAME, which this script takes from that configuration.
# The base URL and the admin credentials come from nxtbi/widgets/.env; the password is
# handed to Playwright through the environment and never printed. The login form
# exists only with NXTBI_WIDGETS_AUTH=db.
#
# CI=1 is set unless HEADED=1: the upstream config runs headless only when CI is set.
# Its other CI effects are overridden here (one worker, no retries, list reporter).
#
# Requirements: superset-frontend/node_modules installed and `npx playwright install
# chromium` run once. The specs need DASHBOARD_V2 on (they skip themselves otherwise)
# and the birth_names and video_game_sales datasets, which the init job loads.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WIDGETS_DIR="$(cd "$HERE/.." && pwd)"
REPO_ROOT="$(cd "$WIDGETS_DIR/../.." && pwd)"
ENV_FILE="$WIDGETS_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "$ENV_FILE not found: run python nxtbi/widgets/scripts/gen_env.py" >&2
  exit 2
fi

# Reads one KEY=value from the env file without evaluating it as shell.
env_value() {
  local line
  line="$(grep -E "^$1=" "$ENV_FILE" | tail -n 1 || true)"
  printf '%s' "${line#*=}" | tr -d '\r'
}

BASE_URL="$(env_value SUPERSET_PUBLIC_URL)"
BASE_URL="${BASE_URL:-http://localhost:8089}"
ADMIN_USERNAME="$(env_value WIDGETS_ADMIN_USERNAME)"
ADMIN_PASSWORD="$(env_value WIDGETS_ADMIN_PASSWORD)"
if [ -z "$ADMIN_PASSWORD" ] || [ "$ADMIN_PASSWORD" = "__GENERATE__" ]; then
  echo "WIDGETS_ADMIN_PASSWORD is missing in $ENV_FILE" >&2
  exit 2
fi
if [ "$(env_value NXTBI_WIDGETS_AUTH)" = "keycloak" ]; then
  echo "NXTBI_WIDGETS_AUTH=keycloak: the upstream suite signs in through the database" >&2
  echo "login form, which this mode does not serve. Switch to NXTBI_WIDGETS_AUTH=db." >&2
  exit 2
fi

# The name the stack gives its session cookie, read from its configuration.
SESSION_COOKIE_NAME="$(sed -n 's/^SESSION_COOKIE_NAME *= *"\([^"]*\)".*/\1/p' \
  "$WIDGETS_DIR/config/superset_config.py" | tail -n 1)"

if ! curl -fsS "${BASE_URL%/}/health" >/dev/null 2>&1; then
  echo "${BASE_URL%/}/health does not answer. Start the stack:" >&2
  echo "  docker compose -f nxtbi/widgets/docker-compose.yml up -d" >&2
  exit 2
fi

# Arguments before `--` select specs (a bare file name is resolved inside the
# dashboard-v2 folder); everything after `--` goes to Playwright unchanged.
SPEC_DIR="playwright/tests/dashboard-v2"
SPECS=()
EXTRA=()
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--" ]; then
    shift
    EXTRA=("$@")
    break
  fi
  case "$1" in
    */*) SPECS+=("$1") ;;
    *) SPECS+=("$SPEC_DIR/$1") ;;
  esac
  shift
done
if [ "${#SPECS[@]}" -eq 0 ]; then
  SPECS=("$SPEC_DIR")
fi

export PLAYWRIGHT_BASE_URL="$BASE_URL"
export PLAYWRIGHT_ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
export PLAYWRIGHT_ADMIN_PASSWORD="$ADMIN_PASSWORD"
export PLAYWRIGHT_SESSION_COOKIE_NAME="${SESSION_COOKIE_NAME:-session}"
# Never open the HTML report in a browser at the end of a failed run.
export PLAYWRIGHT_HTML_OPEN=never
if [ "${HEADED:-0}" != "1" ]; then
  export CI=1
fi

cd "$REPO_ROOT/superset-frontend"
echo "Playwright dashboard-v2 specs against $PLAYWRIGHT_BASE_URL as $PLAYWRIGHT_ADMIN_USERNAME"
exec npx --no-install playwright test "${SPECS[@]}"   --config="$HERE/playwright.widgets.config.ts" \
  --project=chromium --workers=1 --retries=0 --reporter=list "${EXTRA[@]}"
