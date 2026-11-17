#!/bin/bash
# One-shot initialisation of the NxtBI Superset demo. Runs on every `docker compose up`
# and converges: every step is idempotent.
#
# One-off switches (environment of the superset-init service), for example:
#   docker compose -f nxtbi/docker-compose.yml run --rm -e NXTBI_FORCE_SEED=yes superset-init
#     NXTBI_FORCE_SEED=yes              rebuild the demo warehouse tables
#     SUPERSET_FORCE_LOAD_EXAMPLES=yes  reload Superset's example dashboards
#     NXTBI_SKIP_CONTENT_IMPORT=yes     keep UI edits to the NxtBI dashboards (skip step 6)
set -euo pipefail

step() { printf '\n=== [nxtbi-init] %s ===\n' "$1"; }

step "0/6 preflight"
python - <<'PY'
import os, sys
import psycopg2

try:
    psycopg2.connect(host=os.environ.get("DATABASE_HOST", "db"), port=os.environ.get("DATABASE_PORT", "5432"),
                     dbname=os.environ["POSTGRES_DB"], user=os.environ["POSTGRES_USER"],
                     password=os.environ["POSTGRES_PASSWORD"], connect_timeout=10).close()
except psycopg2.OperationalError as exc:
    if "password authentication failed" in str(exc):
        sys.exit("nxtbi/.env does not match the existing database volume (passwords are set when the "
                 "volume is created).\nRestore the previous nxtbi/.env, or start clean with: "
                 "docker compose -f nxtbi/docker-compose.yml down -v")
    sys.exit(f"cannot reach the metadata database: {exc}")
print("metadata database credentials ok")
PY
if [ ! -s /app/superset/translations/ar/LC_MESSAGES/messages.json ]; then
  echo "WARNING: the Arabic language pack is missing from the image: the UI will stay English." >&2
  echo "         Build with BUILD_TRANSLATIONS=true from a checkout with LF line endings" >&2
  echo "         (git config core.autocrlf false, then a fresh checkout)." >&2
fi

step "1/6 metadata database migrations"
superset db upgrade

step "2/6 roles and permissions"
superset init

step "3/6 NxtBI demo warehouse"
NXTBI_DEMO_ADMIN_DSN="postgresql://nxtbi_owner:${NXTBI_DEMO_OWNER_PASSWORD}@${DATABASE_HOST:-db}:${DATABASE_PORT:-5432}/nxtbi_demo" \
  python /app/nxtbi/seed/seed_demo_data.py --if-missing

step "4/6 service account and organisation roles"
python /app/nxtbi/bootstrap/bootstrap.py accounts

step "5/6 Superset example dashboards"
if [ "${SUPERSET_LOAD_EXAMPLES:-no}" = "yes" ]; then
  if python /app/nxtbi/bootstrap/bootstrap.py examples-loaded; then
    echo "examples already loaded - skipping (SUPERSET_FORCE_LOAD_EXAMPLES=yes to reload)"
  else
    superset load_examples
  fi
else
  echo "SUPERSET_LOAD_EXAMPLES is not 'yes' - skipping"
fi

step "6/6 NxtBI dashboards, data access and row level security"
if [ "${NXTBI_SKIP_CONTENT_IMPORT:-no}" = "yes" ]; then
  echo "NXTBI_SKIP_CONTENT_IMPORT=yes - the NxtBI bundle is not re-imported"
else
  # The import overwrites: the NxtBI dashboards, charts and datasets are code
  # (bootstrap/build_bundle.py). Save a copy in the UI to keep manual changes.
  python /app/nxtbi/bootstrap/bootstrap.py content
fi

step "done"
