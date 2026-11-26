#!/bin/bash
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

# Run once against the new tenant PostgreSQL volume, as its bootstrap user.
(
set -euo pipefail

: "${NXTBI_SAAS_MIGRATION_PASSWORD:?}"
: "${NXTBI_SAAS_RUNTIME_PASSWORD:?}"
: "${NXTBI_SAAS_READER_PASSWORD:?}"
: "${NXTBI_SAAS_TENANT_VALUE:?}"

psql --no-psqlrc --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<'SQL'
\getenv migration_password NXTBI_SAAS_MIGRATION_PASSWORD
\getenv runtime_password NXTBI_SAAS_RUNTIME_PASSWORD
\getenv reader_password NXTBI_SAAS_READER_PASSWORD
\getenv tenant_value NXTBI_SAAS_TENANT_VALUE

CREATE ROLE nxtbi_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS
  PASSWORD :'migration_password';
CREATE ROLE nxtbi_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS
  PASSWORD :'runtime_password';
CREATE ROLE nxtbi_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS
  PASSWORD :'reader_password';

CREATE DATABASE nxtbi_metadata OWNER nxtbi_migrator;
CREATE DATABASE nxtbi_warehouse;

REVOKE ALL ON DATABASE postgres FROM PUBLIC;
REVOKE ALL ON DATABASE template1 FROM PUBLIC;
REVOKE ALL ON DATABASE nxtbi_metadata FROM PUBLIC;
REVOKE ALL ON DATABASE nxtbi_warehouse FROM PUBLIC;
GRANT CONNECT ON DATABASE nxtbi_metadata TO nxtbi_runtime;
GRANT CONNECT ON DATABASE nxtbi_warehouse TO nxtbi_reader;

\connect nxtbi_metadata
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO nxtbi_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE nxtbi_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO nxtbi_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE nxtbi_migrator IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO nxtbi_runtime;

\connect nxtbi_warehouse
REVOKE ALL ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA analytics;
CREATE TABLE analytics.workspace_kpis (
  value bigint NOT NULL,
  visible boolean NOT NULL
);
INSERT INTO analytics.workspace_kpis (value, visible)
VALUES
  (:'tenant_value'::bigint, TRUE),
  (CASE WHEN :'tenant_value'::bigint = 1000000 THEN 1000001 ELSE 1000000 END, FALSE);

ALTER TABLE analytics.workspace_kpis ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics.workspace_kpis FORCE ROW LEVEL SECURITY;
CREATE POLICY reader_visible_kpis ON analytics.workspace_kpis
  FOR SELECT TO nxtbi_reader USING (visible);
GRANT USAGE ON SCHEMA analytics TO nxtbi_reader;
GRANT SELECT ON analytics.workspace_kpis TO nxtbi_reader;
SQL
)
