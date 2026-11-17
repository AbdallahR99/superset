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
# Migration cycle of the Widget Framework branch against a real PostgreSQL:
#
#   upgrade to head -> exactly one head -> downgrade to the revision before the
#   Widget Framework migration -> upgrade to head again
#
#   bash nxtbi/widgets/scripts/migration_cycle.sh
#
# Everything runs in a disposable PostgreSQL container on a disposable network, both
# named with a random suffix and removed at the end, also on failure. No other
# container, network or volume is created, changed or removed, and no port is
# published.
#
# Environment:
#   IMAGE                 image with the branch's code   (default nxtbi/superset-fork:widgets)
#   DOWNGRADE_TO          revision to step back to       (default b8f3a2c91d64)
#   POSTGRES_IMAGE        database image                 (default postgres:17)
#   SUPERSET_SOURCE_DIR   optional checkout root: its superset/ and superset-core/ are
#                         mounted read-only over the image's code, to test a working
#                         tree before the image is rebuilt
set -euo pipefail

IMAGE="${IMAGE:-nxtbi/superset-fork:widgets}"
DOWNGRADE_TO="${DOWNGRADE_TO:-b8f3a2c91d64}"
POSTGRES_IMAGE="${POSTGRES_IMAGE:-postgres:17}"
SUPERSET_SOURCE_DIR="${SUPERSET_SOURCE_DIR:-}"

# Git Bash rewrites arguments that look like POSIX paths; container paths must survive.
export MSYS_NO_PATHCONV=1

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Docker Desktop wants a Windows-style path for bind mounts.
host_path() { (cd "$1" && (pwd -W 2>/dev/null || pwd)); }
CONFIG_DIR="$(host_path "$HERE")"

SUFFIX="$(date +%s)-$RANDOM"
NETWORK="nxtbi-widgets-migration-${SUFFIX}"
DATABASE="nxtbi-widgets-migration-db-${SUFFIX}"
DB_PASSWORD="$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
SECRET_KEY="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
FAILED=0

say() { printf '\n=== [migration-cycle] %s ===\n' "$1"; }
pass() { printf 'PASS  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; FAILED=1; }

cleanup() {
  say "cleanup"
  docker rm -f -v "$DATABASE" >/dev/null 2>&1 && echo "removed container $DATABASE" || true
  docker network rm "$NETWORK" >/dev/null 2>&1 && echo "removed network $NETWORK" || true
}
trap cleanup EXIT

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "image $IMAGE not found. Build it first:" >&2
  echo "  docker build --target superset -t nxtbi/superset-fork:widgets ." >&2
  exit 2
fi

SOURCE_MOUNTS=()
if [ -n "$SUPERSET_SOURCE_DIR" ]; then
  SOURCE_ROOT="$(host_path "$SUPERSET_SOURCE_DIR")"
  SOURCE_MOUNTS=(
    -v "${SOURCE_ROOT}/superset:/app/superset:ro"
    -v "${SOURCE_ROOT}/superset-core/src/superset_core:/app/superset-core/src/superset_core:ro"
  )
  echo "code under test: ${SOURCE_ROOT} mounted over the image"
fi

# Runs a `superset` command in a throwaway container on the disposable network.
superset_cli() {
  docker run --rm --network "$NETWORK" \
    -e MIGRATION_SECRET_KEY="$SECRET_KEY" \
    -e MIGRATION_DATABASE_URI="postgresql+psycopg2://superset:${DB_PASSWORD}@${DATABASE}:5432/superset" \
    -e PYTHONPATH=/app/migration-config:/app \
    -e SUPERSET_ENV=production \
    -v "${CONFIG_DIR}/migration_config.py:/app/migration-config/superset_config.py:ro" \
    "${SOURCE_MOUNTS[@]}" \
    --entrypoint superset "$IMAGE" "$@"
}

# The revision ids a `superset db <heads|current>` call prints, one per line.
# An empty answer is asked again twice; the last attempt shows the command's own output.
revisions() {
  local found="" attempt
  for attempt in 1 2 3; do
    found="$(superset_cli db "$1" 2>/dev/null | grep -oE '^[0-9a-f]{12}' || true)"
    [ -n "$found" ] && break
    sleep 2
  done
  if [ -z "$found" ]; then
    echo "superset db $1 printed no revision; its output:" >&2
    superset_cli db "$1" 2>&1 | tail -n 15 >&2 || true
  fi
  printf '%s\n' "$found"
}

say "disposable network and database"
docker network create "$NETWORK" >/dev/null
docker run -d --name "$DATABASE" --network "$NETWORK" \
  -e POSTGRES_DB=superset -e POSTGRES_USER=superset -e POSTGRES_PASSWORD="$DB_PASSWORD" \
  "$POSTGRES_IMAGE" >/dev/null
echo "network $NETWORK, container $DATABASE"
for _ in $(seq 1 60); do
  # The first readiness answer can come from the temporary init server; a query over
  # TCP only succeeds on the final one.
  if docker exec -e PGPASSWORD="$DB_PASSWORD" "$DATABASE" \
       psql -h 127.0.0.1 -U superset -d superset -tAc 'select 1' >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 1
done
[ "${READY:-0}" = "1" ] || { echo "the database did not become ready" >&2; exit 1; }

say "1/4 upgrade to head"
superset_cli db upgrade
HEADS="$(revisions heads)"
HEAD_COUNT="$(printf '%s\n' "$HEADS" | grep -c . || true)"
if [ "$HEAD_COUNT" = "1" ]; then
  pass "single migration head: $HEADS"
else
  fail "expected exactly one migration head, found $HEAD_COUNT: $(echo $HEADS)"
fi
HEAD="$(printf '%s\n' "$HEADS" | head -n 1)"
CURRENT="$(revisions current)"
if [ "$CURRENT" = "$HEAD" ]; then
  pass "database is at head $HEAD after the upgrade"
else
  fail "database is at '$CURRENT' after the upgrade, expected $HEAD"
fi

say "2/4 downgrade to $DOWNGRADE_TO"
if [ "$HEAD" = "$DOWNGRADE_TO" ]; then
  fail "head is already $DOWNGRADE_TO: the image holds no migration above it"
fi
superset_cli db downgrade "$DOWNGRADE_TO"
CURRENT="$(revisions current)"
if [ "$CURRENT" = "$DOWNGRADE_TO" ]; then
  pass "database is at $DOWNGRADE_TO after the downgrade"
else
  fail "database is at '$CURRENT' after the downgrade, expected $DOWNGRADE_TO"
fi

say "3/4 upgrade to head again"
superset_cli db upgrade
CURRENT="$(revisions current)"
if [ "$CURRENT" = "$HEAD" ]; then
  pass "database is back at head $HEAD"
else
  fail "database is at '$CURRENT' after the second upgrade, expected $HEAD"
fi

say "4/4 result"
if [ "$FAILED" = "0" ]; then
  echo "migration cycle passed: head $HEAD <-> $DOWNGRADE_TO"
else
  echo "migration cycle FAILED (see the FAIL lines above)" >&2
fi
exit "$FAILED"
