#!/bin/bash
# Runs once, when the Postgres data volume is empty (docker-entrypoint-initdb.d).
# The metadata database ($POSTGRES_DB) already exists at this point.
#   examples    - Superset's bundled example datasets (owner: examples)
#   nxtbi_demo  - NxtBI demo warehouse (owner: nxtbi_owner, Superset reads as nxtbi_ro)
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v examples_pw="$EXAMPLES_PASSWORD" \
     -v owner_pw="$NXTBI_DEMO_OWNER_PASSWORD" \
     -v ro_pw="$NXTBI_DEMO_RO_PASSWORD" <<'SQL'
CREATE ROLE examples    LOGIN PASSWORD :'examples_pw';
CREATE ROLE nxtbi_owner LOGIN PASSWORD :'owner_pw';
CREATE ROLE nxtbi_ro    LOGIN PASSWORD :'ro_pw';
CREATE DATABASE examples   OWNER examples;
CREATE DATABASE nxtbi_demo OWNER nxtbi_owner;
REVOKE ALL ON DATABASE nxtbi_demo FROM PUBLIC;
GRANT CONNECT ON DATABASE nxtbi_demo TO nxtbi_ro;
SQL
