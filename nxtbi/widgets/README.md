<!--
Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
-->

# Widget Framework: isolated runtime and end-to-end harness

A second, separate Superset stack for the Widget Framework (Dashboard V2 builder, saved
widgets, widget data API, embedding in host applications), with the scripts that test
it end to end.

It shares nothing with the main demo in `nxtbi/`:

| | Main demo | This stack |
|---|---|---|
| Compose project | `nxtbi-superset` | `nxtbi-widgets` |
| Compose file | `nxtbi/docker-compose.yml` | `nxtbi/widgets/docker-compose.yml` |
| Image | `nxtbi/superset-fork:local` | `nxtbi/superset-fork:widgets` |
| Web | http://localhost:8088 | http://localhost:8089 |
| MCP | http://localhost:5008 | http://localhost:5009 (optional) |
| Env file | `nxtbi/.env` | `nxtbi/widgets/.env` |
| Volumes | `nxtbi-superset_*` | `nxtbi-widgets_*` |
| Session cookie | `nxtbi_superset_session` | `nxtbi_widgets_session` |
| Login | Keycloak | username and password (Keycloak optional, section 8) |

Every command below runs from the repository root. Every published port is bound to
`127.0.0.1`. Nothing here stops, recreates or migrates the main demo, and nothing
touches the Keycloak container.

## 1. Prerequisites

- Docker with Compose v2.
- Python 3.11+ on the host, with `pip install requests playwright` and
  `playwright install chromium` for the end-to-end script.
- Node 24 with `npm install` done in `superset-frontend` (upstream Playwright specs,
  example app) and in `superset-frontend/packages/superset-widgets/example` (example
  app only).
- Free ports on the loopback: 8089, and for the optional parts 8099, 5009, 5173, 5174
  and 3011.
- On Windows, a checkout with LF line endings (`git clone -c core.autocrlf=false`), and
  Git Bash for the two shell scripts.

## 2. Build the image

The compose file does not build. Build the image once, and again after a code change:

```bash
docker build --target superset -t nxtbi/superset-fork:widgets .
```

Add `--build-arg BUILD_TRANSLATIONS=true` to get the Arabic language pack. Without it
the Arabic interface is right-to-left with English text; the RTL checks still apply.

## 3. Secrets

```bash
python nxtbi/widgets/scripts/gen_env.py
```

writes `nxtbi/widgets/.env` (git-ignored by `nxtbi/widgets/.gitignore`) with random
values for `SUPERSET_SECRET_KEY`, `GUEST_TOKEN_JWT_SECRET`, `MCP_JWT_SECRET`, the
database passwords and the passwords of the two accounts. It refuses to overwrite an
existing file; `--add-missing` keeps every value and adds what is new.

| Account | Variable | Roles |
|---|---|---|
| `admin` | `WIDGETS_ADMIN_PASSWORD` | Admin |
| `widgets_gamma` | `WIDGETS_GAMMA_PASSWORD` | Gamma + WidgetsRlsDemo |

The database passwords are fixed when the volume is created. After regenerating `.env`
for an existing volume, the init job stops with an explanation: restore the old file
or start clean (section 9).

## 4. Start, and what the init job seeds

```bash
docker compose -f nxtbi/widgets/docker-compose.yml up -d
docker compose -f nxtbi/widgets/docker-compose.yml logs -f superset-init   # first start: a few minutes
```

`superset-init` runs on every `up` and converges (`bootstrap/init.sh`):

1. `superset db upgrade`, `superset init`.
2. Accounts and roles: `admin`, `widgets_gamma`, the guest role `WidgetGuest`, the
   role `WidgetsRlsDemo`.
3. The example datasets `birth_names` and `video_game_sales`, which the upstream
   Playwright specs look up by name. `superset load_examples` cannot load a subset, so
   the bundled loaders of exactly these two are called; if an image does not ship
   them, two small tables with the same names and columns are created instead.
4. The row-level-security demo: dataset `widgets_rls_demo` (12 rows, 3 regions) with
   the rule `region = 'north'` for `WidgetsRlsDemo`. Admin reads 12 rows, `widgets_gamma`
   reads 4.

Rebuild the seeded tables:

```bash
docker compose -f nxtbi/widgets/docker-compose.yml run --rm -e WIDGETS_FORCE_SEED=yes superset-init
```

Open http://localhost:8089, sign in as `admin`, and create a dashboard at
http://localhost:8089/dashboard/v2/new/.

### What the configuration sets (`config/superset_config.py`)

- Feature flags `DASHBOARD_V2` and `EMBEDDED_SUPERSET` on; `ENABLE_EXTENSIONS` with
  `NXTBI_WIDGETS_EXTENSIONS=on`.
- Guest role `WidgetGuest`, holding exactly `can read on Chart`, which is all the
  widget endpoints check. `NXTBI_WIDGETS_GUEST_DASHBOARD_READ=on` adds
  `can read on Dashboard` for the embedded Dashboard V2 document route.
- A guest token validator: a token for a dataset that has row-level-security rules is
  refused (400) unless it brings an `rls` rule for that dataset. Role-based rules do
  not apply to a guest, so without this a host could hand out unfiltered rows.
- CORS for `NXTBI_WIDGETS_CORS_ORIGINS` (default `http://localhost:5173` and `:5174`)
  with credentials, `allow_headers` `Content-Type, X-GuestToken, X-CSRFToken, If-Match`,
  `expose_headers` `ETag`, plus the origins of Superset's own default.
- `RATELIMIT_APPLICATION` raised from 50 to 400 requests per second per client
  address: a page with a few dozen widgets exceeds the default on its first load.
- Languages English and Arabic.

## 5. End-to-end checks: `scripts/widgets_e2e.py`

```bash
python nxtbi/widgets/scripts/widgets_e2e.py                    # everything
python nxtbi/widgets/scripts/widgets_e2e.py --list             # names and one-line descriptions
python nxtbi/widgets/scripts/widgets_e2e.py --only f,g         # groups or name fragments
python nxtbi/widgets/scripts/widgets_e2e.py --api-only         # no browser
python nxtbi/widgets/scripts/widgets_e2e.py --manage-flag-off  # start and remove the flag-off web itself
python nxtbi/widgets/scripts/widgets_e2e.py --keep --headed    # keep created objects, show the browser
```

Each check ends as `PASS`, `FAIL` or `SKIP`; a skip says what to start to make it run.
Results go to `nxtbi/out/widgets-e2e-results.json` (exit code 1 on a failure),
screenshots of failed browser checks to `nxtbi/out/widgets-e2e/`. `nxtbi/out/` is
git-ignored. The script deletes the dashboards and widgets it creates.

Set `NXTBI_WIDGETS_ENV_FILE` to use a separate validation stack. The example
app and Playwright runner read the same path. Start that stack's flag-off
service before the run, since `--manage-flag-off` uses the default stack.

| Group | What is checked | Needs |
|---|---|---|
| a | builder: place chart, AG Grid table, metric, filter and markdown widgets (each block's control form has to render), save, reload, every widget shows real content (table rows, a painted chart, a number), an edit made in the control form reaches the widget and the server | browser |
| b | two editors: the second save gets the conflict dialog, the stored document and revision are untouched; "reload" shows the other editor's block and writes nothing; the next save is accepted | browser |
| c | a structured filter narrows widget data (API); in the builder a filter value and a chart click refetch with a filter, and the table and the metric tile on screen show the narrowed data | browser for c2 |
| d | a saved widget and the same definition sent inline return the same rows and values | |
| e | standalone React example with the Superset session and with guest tokens: widgets render, a host filter changes data, the second provider is not refetched, RTL switch; CORS preflight | example app (section 7) |
| f | guest token for widget A refused for widget B; dashboard token with `datasets` refused for inline widgets; inline grant per dataset; SQL in a guest definition refused; SQL authoring rule for Gamma; RLS in widget data; widget token bound to its dataset; guest role limits; flag off answers 404 | flag-off web for f7 |
| g | saved widget CRUD; Dashboard V2 create, read, update, idempotent create; stale revision 409, missing revision 428; cyclic, orphaned, too deep, too large documents 422; oversized body 413; malformed body 400 | |
| h | Arabic: builder mirrored, all five widgets rendered with content, AG Grid RTL, charts LTR; MCP: tool list, `list_widget_types`, `get_widget_data` | browser for h1, MCP for h2 |

Every browser check also fails when a page it drove threw an uncaught error or broke
the Content Security Policy of the stack (the browser reports both to the console only;
`Ctx.expect_no_page_problems` collects them). The policy has no `'unsafe-eval'`, so
this is what catches a library that compiles code at run time.

The flag-off server is the same application on the same database with
`NXTBI_WIDGETS_DASHBOARD_V2=off`, on http://localhost:8099:

```bash
docker compose -f nxtbi/widgets/docker-compose.yml --profile flag-off up -d --no-deps --wait superset-flag-off
docker compose -f nxtbi/widgets/docker-compose.yml --profile flag-off rm -sf superset-flag-off
```

The optional MCP server, on http://localhost:5009/mcp (bearer tokens signed with
`MCP_JWT_SECRET`; the script mints its own):

```bash
docker compose -f nxtbi/widgets/docker-compose.yml --profile mcp up -d superset-mcp
```

Two request shapes are still being worked on in the backend. The script builds each
in one function, under "payloads under change" at the top of `widgets_e2e.py`:
`guest_token_request` (which resource grants what) and `v2_update_body` /
`v2_if_match` (how a save names its base revision). `DATASET_READERS_MAY_AUTHOR_SQL`
in the same place states the SQL authoring rule check f5 expects.

## 6. Other scripts

### Concurrent Dashboard V2 saves on PostgreSQL

```bash
python nxtbi/widgets/scripts/dashboard_v2_concurrency.py \
  --base-url http://localhost:8089 \
  --env-file nxtbi/widgets/.env \
  --db-container nxtbi-widgets-db-1
```

Run against a disposable copy of the widgets stack with database login and at
least three concurrent web requests. The script creates a dashboard and holds
its row lock until three separate PostgreSQL connections are waiting. It checks
that one of two same-revision V2 saves wins, the other receives the committed
revision in a 409, and a concurrent classic metadata edit survives. It then
checks that a cyclic document returns 422 and leaves the dashboard unchanged
before deleting the dashboard through the API.

### Migration cycle

```bash
bash nxtbi/widgets/scripts/migration_cycle.sh
```

Starts a disposable PostgreSQL container on a disposable network, runs
`superset db upgrade`, asserts a single head and that the database is on it, downgrades
to `b8f3a2c91d64` (the revision before the Widget Framework migration), upgrades
again, and removes the container and the network it created, also on failure. It
publishes no port and touches no other container. `IMAGE`, `DOWNGRADE_TO` and
`POSTGRES_IMAGE` override the defaults; `SUPERSET_SOURCE_DIR=<checkout>` mounts that
checkout's Python code over the image to test a working tree before a rebuild.

### Upstream Playwright specs

```bash
bash nxtbi/widgets/scripts/run_upstream_playwright.sh                    # all of playwright/tests/dashboard-v2
bash nxtbi/widgets/scripts/run_upstream_playwright.sh filters.spec.ts    # one spec
bash nxtbi/widgets/scripts/run_upstream_playwright.sh -- --grep conflict # arguments for Playwright
HEADED=1 bash nxtbi/widgets/scripts/run_upstream_playwright.sh
```

Sets `PLAYWRIGHT_BASE_URL` and `PLAYWRIGHT_ADMIN_USERNAME` / `PLAYWRIGHT_ADMIN_PASSWORD`
from `nxtbi/widgets/.env` and runs the upstream specs and page objects, unchanged,
through `scripts/playwright.widgets.config.ts`: the upstream `playwright.config.ts`
with absolute paths and this stack's sign-in (`scripts/playwright.widgets.global-setup.ts`).
The upstream global setup cannot be used here. It recognises a finished login by a
cookie named `session`; this stack names its session cookie `nxtbi_widgets_session`
(`SESSION_COOKIE_NAME` in `config/superset_config.py`), so the upstream setup times out
on a login that succeeded. The runner reads the name from the configuration and passes
it as `PLAYWRIGHT_SESSION_COOKIE_NAME`. Needs `npx playwright install chromium` once in
`superset-frontend`, and the database login form (`NXTBI_WIDGETS_AUTH=db`).

### Rebuilding the frontend the stack serves

The web containers serve the bundle in the volume `nxtbi_widgets_fe_assets` and read
its asset manifest once, at start. A production rebuild renames the entry files (content
hashes), so after one the web container has to be restarted, or every page stays on the
loading logo with a 404 for `spa.<hash>.entry.js`:

```bash
docker restart nxtbi-widgets-superset-1
```

## 7. The standalone example app against this stack

```bash
python nxtbi/widgets/scripts/example_app.py              # session mode, http://localhost:5173
python nxtbi/widgets/scripts/example_app.py --guest      # guest tokens, http://localhost:5174, broker on 3011
python nxtbi/widgets/scripts/example_app.py --print-env  # the settings it would pass
```

The script asks the running stack for the ids of `birth_names` and
`video_game_sales`, creates one saved widget to show, and starts
`superset-frontend/packages/superset-widgets/example` (Vite, plus `server.mjs` in guest
mode) with those settings in the process environment. It writes no file in the example
folder. Both modes can run side by side; the end-to-end group `e` tests whichever is
up.

- Session mode: sign in at http://localhost:8089/login/ in the same browser first. The
  app and Superset are the same site (`localhost`), so the session cookie reaches the
  API.
- Guest mode: the broker signs in as `admin` and mints one token per provider.

## 8. Keycloak instead of the database login

```bash
python nxtbi/widgets/scripts/gen_env.py --add-missing --copy-keycloak   # reads nxtbi/.env, changes only nxtbi/widgets/.env
# set NXTBI_WIDGETS_AUTH=keycloak in nxtbi/widgets/.env, then
docker compose -f nxtbi/widgets/docker-compose.yml up -d
```

With this switch the configuration loads `nxtbi/config/superset_config.py` (mounted
read-only) and takes over its Keycloak settings unchanged: `AUTH_TYPE`,
`OAUTH_PROVIDERS`, `AUTH_ROLES_MAPPING`, `AUTH_ROLES_SYNC_AT_LOGIN`,
`AUTH_USER_REGISTRATION`, `AUTH_API_LOGIN_ALLOW_MULTIPLE_PROVIDERS` and the security
manager with its logout view.

The main demo's Keycloak client is not changed from here. A browser login on this
stack needs two additions to that client, which someone with access to it has to make:

- redirect URI `http://localhost:8089/oauth-authorized/keycloak`
- post-logout redirect URI `http://localhost:8089/login/`

Until then Keycloak refuses the redirect. The API login of `admin` and `widgets_gamma`
keeps working, so `widgets_e2e.py --api-only` and the token broker run in this mode;
the browser checks and the upstream Playwright specs need the database login form. The
organisation roles of the group mapping (`nxt_org_*`) do not exist on this stack, so an
organisation user arrives with the built-in roles of the mapping only.

## 9. Stop and remove

```bash
docker compose -f nxtbi/widgets/docker-compose.yml --profile flag-off --profile mcp down      # keeps the data
docker compose -f nxtbi/widgets/docker-compose.yml --profile flag-off --profile mcp down -v   # deletes it
```

`down -v` is safe here and only here: it is scoped to the project `nxtbi-widgets` and
removes its three volumes, which hold nothing but seeded data. Never run `down -v`
with `nxtbi/docker-compose.yml`: that deletes the main demo's metadata database.

## Files

| Path | Purpose |
|---|---|
| `docker-compose.yml` | the stack: `db`, `redis`, `superset-init`, `superset`, optional `superset-flag-off` and `superset-mcp` |
| `config/superset_config.py` | configuration, mounted at `/app/pythonpath` |
| `bootstrap/init.sh`, `bootstrap/widgets_bootstrap.py` | the init job |
| `docker/postgres-init.sh` | creates the `examples` database |
| `scripts/gen_env.py`, `.env.example` | secrets |
| `scripts/widgets_e2e.py` | end-to-end checks |
| `scripts/example_app.py` | starts the example app against this stack |
| `scripts/migration_cycle.sh`, `scripts/migration_config.py` | migration cycle |
| `scripts/run_upstream_playwright.sh` | upstream Dashboard V2 specs |
| `scripts/playwright.widgets.config.ts`, `scripts/playwright.widgets.global-setup.ts` | Playwright configuration and sign-in for this stack, used by the runner |
