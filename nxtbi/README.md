# NxtBI Superset demo

A running Apache Superset, built from this fork's own source, signed in through the
existing NxtBI Keycloak, with three NxtBI dashboards, tenant isolation by Keycloak
group, the REST API, the MCP server, an NxtBI theme and an Arabic UI.

Everything NxtBI-specific lives in this `nxtbi/` folder. No upstream file is modified,
so `git merge upstream/master` stays conflict-free.

- Capability matrix and adoption shortlist: [docs/CAPABILITY-MATRIX.md](docs/CAPABILITY-MATRIX.md)
- What was tested and what was observed: [docs/TEST-RESULTS.md](docs/TEST-RESULTS.md)
- Arabic and RTL status: [docs/I18N-RTL.md](docs/I18N-RTL.md)
- Cube, Wren, Schema-Sense, NxtBI semantic layer (documentation only): [docs/FUTURE-INTEGRATIONS.md](docs/FUTURE-INTEGRATIONS.md)
- Background research with code references: [docs/research/](docs/research/)

## URLs

| What | URL | Notes |
|---|---|---|
| Superset | http://localhost:8088 | "Sign in with Keycloak" is the only login |
| Swagger UI | http://localhost:8088/swagger/v1 | after signing in |
| MCP server | http://localhost:5008/mcp | streamable HTTP, bearer token required, health at `/health` |
| Keycloak (existing) | http://localhost:8180/realms/nxtbi | container `ld-shared-keycloak-1`, owned by NxtDash |
| Mailpit (existing) | http://localhost:8025 | receives report e-mails |

All ports published by this stack are bound to `127.0.0.1`.

## Start

Prerequisites:

- Docker with Compose v2 and about 12 GB of memory for the first image build (the
  frontend build alone uses up to 8 GB); the image is 4.8 GB.
- Python 3.11+ on the host for the scripts.
- The NxtBI Keycloak container (`ld-shared-keycloak-1`, realm `nxtbi`, port 8180) and
  NxtDash's realm file. `KEYCLOAK_CONTAINER` and `NXTBI_REALM_FILE` in `nxtbi/.env`
  point at them and are specific to the machine this was built on.
- Optional: Mailpit on port 1025/8025 for report e-mails.
- On Windows, clone with `git clone -c core.autocrlf=false` so shell scripts and
  translation files keep LF endings inside the Linux image.

Commands are run from the repository root.

```bash
python nxtbi/scripts/gen_env.py
```

```bash
python nxtbi/scripts/keycloak_setup.py apply
```

```bash
docker compose -f nxtbi/docker-compose.yml up -d --build
```

1. `gen_env.py` writes `nxtbi/.env` (git-ignored) with random secrets. It refuses to
   overwrite an existing file.
2. `keycloak_setup.py apply` adds what Superset needs to the realm, and only what is
   missing: the `nxtbi-superset` client, the `groups` client scope, the canonical group
   tree and demo users from NxtDash's `realm-nxtbi.json`, and one platform admin. It
   never changes or deletes anything that was already there. It also stores the demo
   users' password in `nxtbi/.env`. Re-run it whenever the Keycloak container is
   recreated: that container has no data volume.
3. The first `up --build` builds the image from the fork (about 15 minutes, then cached)
   and runs the one-shot `superset-init` service: migrations, warehouse seed, Superset's
   example dashboards (about 4 minutes, first start only), the NxtBI dashboards, data
   grants and row level security. Later starts take about 90 seconds.

Check it:

```bash
python nxtbi/scripts/smoke_test.py
```

```bash
python nxtbi/scripts/browser_check.py
```

`smoke_test.py` needs `requests`; `browser_check.py` needs `playwright` with Chromium
(`pip install playwright && playwright install chromium`) and rewrites the images in
`docs/screenshots/`. `test_report.py` turns both result files into
`docs/TEST-RESULTS.md`. Run `smoke_test.py sso` (or sign in once per user) before the MCP
per-user check: MCP only knows users who have signed in.

## Demo logins

List the accounts, their groups and where each password is stored:

```bash
python nxtbi/scripts/keycloak_setup.py show-credentials
```

Add `--reveal` to print the passwords on your own terminal. They are never written to
the repository.

| User | Keycloak group | Superset roles | Sees |
|---|---|---|---|
| `superset.admin@nxtbi.local` | none (listed in `NXTBI_PLATFORM_ADMINS`) | Admin | everything |
| `planning.admin@nxtbi.local` | `/nxt/ministry-of-planning/admin` | Gamma, sql_lab, nxt_org_ministry-of-planning | Budget Execution, Service Operations (planning rows only), SQL Lab |
| `planning.editor@nxtbi.local` | `/nxt/ministry-of-planning/editor` | Gamma, nxt_org_ministry-of-planning | same dashboards, no SQL Lab |
| `stats.admin@nxtbi.local` | `/nxt/statistics-bureau/admin` | Gamma, sql_lab, nxt_org_statistics-bureau | Trade & Population, Service Operations (statistics rows only), SQL Lab |
| `stats.editor@nxtbi.local` | `/nxt/statistics-bureau/editor` | Gamma, nxt_org_statistics-bureau | same dashboards, no SQL Lab |
| `unaffiliated@nxtbi.local` | none | none | login is refused |

The demo users' password is NxtDash's own development default, so the same credentials
work in both products. `nxtbi-service` is a local Admin machine account for the REST API
and scheduled reports; it cannot be used on the login page and cannot be reached
through SSO. Workspace groups (`/nxt/<org>/<workspace>/...`) are not mapped and give no
access. `editor` and `viewer` both map to Superset's Gamma role, which can still create
its own charts and dashboards on the datasets it may read: there is no read-only tier.

## What to show

1. **SSO and roles**: sign in as `planning.admin`, then as `stats.admin` in a private
   window. Each sees a different dashboard list. Sign out: the Keycloak session ends too.
2. **Dashboards**: `NxtBI · Budget Execution`, `NxtBI · Trade & Population` (two tabs),
   `NxtBI · Service Operations`. Use the filter bar (Programme depends on Sector) and
   click a bar or pie slice to cross-filter.
3. **Row level security**: open Service Operations as both users. Same dashboard,
   different rows. In SQL Lab, `SELECT org_slug, count(*) FROM nxtbi.service_requests
   GROUP BY 1` returns only the caller's organisation.
4. **Explore**: open any chart title menu, "Edit chart". Metrics such as
   `execution_rate` are defined once on the dataset and reused everywhere.
5. **Arabic**: language picker (flag, top right), choose Arabic. The interface text is
   translated; the layout stays left-to-right (see docs/I18N-RTL.md).
6. **Reports**: as `superset.admin`, Settings, Alerts & Reports, add an e-mail report;
   it arrives in Mailpit with a screenshot.
7. **API**: Swagger UI, or the calls in `scripts/smoke_test.py` (`group_api`).
8. **MCP**: connect a client (below) and ask for the NxtBI dashboards or run SQL.
9. **Superset's own examples**: nine bundled dashboards (visible to Admin) show the
   wider chart catalogue.

## MCP client

The MCP server requires a bearer token. `mcp_token.py` mints a short-lived token for any
Superset user who has signed in at least once; every tool call then runs with that
user's roles and row level security. Without a token, or with a forged one, the server
answers 401.

```bash
python nxtbi/scripts/mcp_token.py --user planning.admin@nxtbi.local --ttl 28800
```

Give the token to the client as an `Authorization: Bearer <token>` header:

```bash
claude mcp add --transport http nxtbi-superset http://localhost:5008/mcp --header "Authorization: Bearer <token>"
```

Without `--user` the token is for `nxtbi-service`, which is Admin: it can run SQL on
every tenant's data and delete dashboards. The token is a credential; anyone who holds
it, or `MCP_JWT_SECRET`, can act as that user until it expires. Tokens signed with a
shared secret are a demo mechanism: the production path is Keycloak-issued tokens
(`NXTBI_MCP_AUTH=keycloak`, designed but not tested here). `NXTBI_MCP_AUTH=dev` switches
authentication off entirely; port 5008 is reachable from every local process and from
other containers on this Docker host, so do not use it with real data.

## How it is put together

| Service | Purpose |
|---|---|
| `db` (postgres:17) | three databases: `superset` (metadata), `examples`, `nxtbi_demo` (demo warehouse, read by Superset as `nxtbi_ro`) |
| `redis` | Celery broker and results, caches, SQL Lab results, server-side web sessions, rate limits |
| `superset-init` | one-shot, idempotent provisioning (`bootstrap/init.sh`) |
| `superset` | web app (gunicorn) on 8088 |
| `superset-worker`, `superset-beat` | async SQL Lab, thumbnails, scheduled reports (Playwright Chromium) |
| `superset-mcp` | MCP server on 5008 |

The image `nxtbi/superset-fork:local` is the fork's `Dockerfile`, target `superset`,
with `BUILD_TRANSLATIONS=true`. There is no NxtBI image layer: configuration, assets
and scripts are mounted read-only.

| Path | Content |
|---|---|
| `config/superset_config.py` | all Superset settings: Keycloak OIDC, role mapping, logout, caches, Celery, feature flags, theme, languages, reports, MCP |
| `bootstrap/build_bundle.py` | dashboards as code: generates the YAML bundle (1 database, 4 datasets, 33 charts, 3 dashboards, stable UUIDs) |
| `bootstrap/bootstrap.py` | service account, organisation roles, bundle import, dataset grants, RLS rules |
| `bootstrap/validate_bundle.py` | validates a bundle against the fork's import schemas |
| `seed/seed_demo_data.py` | deterministic demo warehouse (about 86,000 rows, English and Arabic labels) |
| `scripts/keycloak_setup.py` | Keycloak provisioning: `apply`, `status`, `verify`, `teardown`, `show-credentials` |
| `scripts/mcp_token.py` | mints MCP bearer tokens for a Superset user |
| `scripts/smoke_test.py`, `scripts/browser_check.py`, `scripts/test_report.py` | tests and the test report |
| `assets/` | NxtBI logo and favicon, served at `/static/nxtbi/` |

### Keycloak integration in one paragraph

Login is the OIDC authorization-code flow with PKCE against the `nxtbi-superset`
confidential client. Keycloak group paths in the signed id_token decide the roles on
every login (`/nxt/<org>/admin` gives Gamma, sql_lab and `nxt_org_<org>`; `editor` and
`viewer` give Gamma and `nxt_org_<org>`); a user with no NxtBI group is refused and no
account is created. A user who had access and then lost every group is refused at the
next login, loses the Superset roles and has the remaining sessions invalidated (this
branch is implemented but was not exercised, because it needs a group change in the
shared Keycloak). Sessions last 8 hours and are not extended by activity, so a group
change takes effect within that time at the latest. Organisation users never get Alpha or Admin, because both see every
tenant's data. Logout is RP-initiated, so it also ends the Keycloak session. The shared
development Keycloak derives its URLs from the request host, so the browser uses
`KEYCLOAK_BROWSER_URL` and the containers use `KEYCLOAK_INTERNAL_URL`; tokens carry the
browser-side issuer. Both values are in `.env`.

To point the demo at another realm (for example a production-like Keycloak with a fixed
hostname), change the `KEYCLOAK_*` values in `nxtbi/.env` and restart.

## Operate

```bash
docker compose -f nxtbi/docker-compose.yml ps
```

```bash
docker compose -f nxtbi/docker-compose.yml logs -f superset
```

```bash
docker compose -f nxtbi/docker-compose.yml down
```

`down` keeps all data (named volumes `nxtbi-superset_db_data`, `_redis_data`,
`_superset_home`). `down -v` deletes it; the next `up` rebuilds everything from code.

- Change a dashboard: edit `bootstrap/build_bundle.py`, then
  `docker compose -f nxtbi/docker-compose.yml run --rm superset-init`. The import
  overwrites, so changes made to those dashboards in the UI are replaced.
- Change configuration: edit `config/superset_config.py`, then restart `superset`,
  `superset-worker`, `superset-beat` and `superset-mcp`.
- Rebuild the warehouse:
  `docker compose -f nxtbi/docker-compose.yml run --rm -e NXTBI_FORCE_SEED=yes superset-init`.
- Keep UI edits to the NxtBI dashboards across restarts: set `NXTBI_SKIP_CONTENT_IMPORT=yes`
  in `nxtbi/.env`. Otherwise every `up` re-imports the bundle and resets the dataset
  grants of the `nxt_org_*` roles to what `bootstrap.py` declares.
- Remove what was added to Keycloak: `python nxtbi/scripts/keycloak_setup.py teardown --dry-run`,
  then without `--dry-run`.
- Update from upstream: `git fetch upstream && git merge upstream/master`, rebuild the
  image, re-run the tests. Import schemas change between releases, so run
  `validate_bundle.py` after every upgrade.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `superset-init` exits with "nxtbi/.env does not match the existing database volume" | `.env` was regenerated while the volume was kept. Restore the old `.env` or run `down -v`. |
| Login button leads to a Keycloak error, or `invalid_client` | The Keycloak container was recreated and lost the client. Run `keycloak_setup.py apply` again. |
| Login returns to the login page with "Invalid login" | The user has no `/nxt/<org>/{admin,editor,viewer}` group (deny by default); see the `nxtbi.config` lines in `logs superset`. |
| Token exchange fails from the container (native Linux) | A Keycloak port published on the host loopback is not reachable through `host.docker.internal`. Attach the Superset services to Keycloak's compose network and set `KEYCLOAK_INTERNAL_URL=http://keycloak:8080`. Not tested here (built on Docker Desktop). |
| UI stays English after choosing Arabic | The image was built without `BUILD_TRANSLATIONS=true` or from a CRLF checkout; `superset-init` prints a warning. Rebuild from an LF checkout. |
| `docker pull`/`build` fails with "error getting credentials" in a non-interactive Windows session | The Windows credential helper is unavailable. Use a `DOCKER_CONFIG` directory whose `config.json` has a dummy `auths` entry and `"currentContext": "desktop-linux"`. |
| MCP answers 401 | No or expired token: mint a new one with `mcp_token.py`. A token for a user who never signed in is also refused. |
| Report e-mails do not arrive | Mailpit is not running on `SMTP_HOST:SMTP_PORT`; `smoke_test.py reports` is skipped in that case. |

## Known limits

- This is Superset `master` after 7.0.0rc2, not a release. See the release section of
  the capability matrix for the fallback image.
- The demo runs over plain http on localhost. For anything else: https,
  `SESSION_COOKIE_SECURE`, a fixed Keycloak hostname, and real secret storage.
- Isolation between organisations is by role and row level security inside one
  Superset. It is not hard multi-tenancy; the limits are listed in the capability matrix.
- Row level security in SQL Lab (`RLS_IN_SQLLAB`) is a testing-stage Superset feature.
  While testing, a bypass was found on this build: a request with `"catalog": ""` ran
  without the caller's RLS predicates. The demo refuses such requests
  (`FLASK_APP_MUTATOR` in `superset_config.py`, covered by a regression test), but the
  underlying defect is upstream and other variants may exist. Do not give SQL Lab on
  shared tables to tenants who must not see each other's rows; use per-tenant schemas
  or database credentials for that.
- MCP tokens are signed with a shared secret and minted locally. Keycloak tokens on MCP
  and on the REST API are described in docs/FUTURE-INTEGRATIONS.md and were not built.
- `POST /api/v1/security/login` has no brute-force limit in Flask-AppBuilder. Only the
  service account has a password (64 random characters).
- A browser that visits several localhost applications shares cookies between them;
  the session cookie is named `nxtbi_superset_session` to avoid collisions.
- Charts are imported without a saved query context (as Superset's own examples are).
  They render; dashboard Excel export skips most chart types until a chart is opened
  and saved once in Explore.
- Experimental Superset features (semantic layers API, extensions, dataset folders,
  API keys, global async queries) are off. `NXTBI_EXPERIMENTAL_FLAGS` in `.env` turns
  feature flags on by name for exploration.
- These files carry no ASF licence header: they are NxtBI additions to a fork, not
  contributions to Apache Superset.
