# 01 - Runtime, Docker and configuration architecture (fork @ f3f3d10d5c)

Scope: read-only research for the NxtBI Superset demo. Repo `E:/Work_Lab/nxtbi-superset`, branch `nxtbi-demo`, HEAD `f3f3d10d5c` (2026-11-16, after tag `7.0.0rc2`), version string `0.0.0-dev` (`superset-frontend/package.json:3`).
Labels: **V** = VERIFIED-IN-CODE, **D** = DOCS-CLAIMED, **U** = UNVERIFIED. Lifecycle mapping used below (from `superset/config.py:713-722`): `development` -> EXPERIMENTAL, `testing` -> BETA-TESTING, `stable` -> STABLE, `deprecated` -> DEPRECATED.

## 1. Dockerfile (443 lines)

| Stage / target | FROM | Produces | Evidence |
|---|---|---|---|
| `superset-node-ci` / `superset-node` | `node:24-trixie-slim` (digest-pinned) | `npm ci` + `npm run build` (webpack prod, `--max_old_space_size=8192`) unless `DEV_MODE=true`; nags if < 3 GB free RAM | `Dockerfile:59-134`, `superset-frontend/package.json:42`, `docker/frontend-mem-nag.sh:22` |
| `superset-websocket` | node 24 | esbuild bundle `/app/superset-websocket/dist/index.cjs` | `Dockerfile:141-163` |
| `python-base` | `python:3.11-slim-trixie` (digest in `PY_VER`) | user `superset` (home `/app/superset_home`, chmod 1777), `uv>=0.11`, venv `/app/.venv` | `Dockerfile:169-191` |
| `python-common` | python-base | env `SUPERSET_ENV=production`, `FLASK_APP=superset.app:create_app()`, `PYTHONPATH=/app/pythonpath`, `SUPERSET_PORT=8088`; apt `curl libsasl2 libpq-dev libldap2-dev`; `/app/data` (DuckDB); Node runtime + websocket bundle; `HEALTHCHECK`, `CMD run-server.sh` | `Dockerfile:215-290` |
| **`lean`** | python-common | `requirements/base.txt` + source + built assets, `uv pip install -e . --no-deps`, `compileall`, `USER superset`. **No DB drivers at all** | `Dockerfile:295-331` |
| **`superset`** (default published image) | lean | + `.[postgres,mysql,fastmcp]` + `playwright` + headless Chromium (always, no build arg) | `Dockerfile:338-371` |
| `dev` | python-common | `requirements/development.txt`, git, editable `.[postgres]`; no compileall; Chromium only with `INCLUDE_CHROMIUM=true` | `Dockerfile:376-425` |
| `ci` / `showtime` | lean | + `.[postgres,duckdb]` / `.[duckdb]`; `CMD docker-ci.sh` (= `docker-init.sh` then gunicorn) | `Dockerfile:430-443`, `docker/entrypoints/docker-ci.sh` |

Build args (V): `PY_VER` (`:26`), `BUILDPLATFORM` (`:29`), `BUILD_TRANSLATIONS=false` (`:32`), `DEV_MODE=false` (`:62`, true skips npm ci/build), `NPM_BUILD_CMD=build` (`:67`), `SUPERSET_HOME` (`:171`), `INCLUDE_CHROMIUM=false` (`:243`, only affects python-common, i.e. `dev`/`lean`). `INCLUDE_FIREFOX` is **removed** (`UPDATING.md:1210-1216`). `LOAD_EXAMPLES_DUCKDB` does **not exist** on this commit (no match in Dockerfile/compose) (V).

What is pre-installed (V unless noted):

| Package | lean | superset | dev | Evidence |
|---|---|---|---|---|
| psycopg2-binary 2.9.13 | no | yes | yes | `pyproject.toml` extra `postgres`; `Dockerfile:357,423` |
| mysqlclient | no | yes | yes | `Dockerfile:357` |
| fastmcp (>=4.1.4,<5), mcp, tiktoken | no | yes | yes | `pyproject.toml` extra `fastmcp`; `Dockerfile:357` |
| playwright + Chromium | no (unless `INCLUDE_CHROMIUM=true`) | yes | arg | `Dockerfile:243-253,365-369` |
| duckdb / duckdb-engine | no | **no** | yes (dev reqs) | `Dockerfile:432,441`; `requirements/development.txt:263` |
| Authlib | no (not in `requirements/base.txt`) | transitive via `fastmcp-slim` (U until built; `requirements/development.txt:68-69`) | yes | - |
| redis 8.1.0, celery 5.7.0, gunicorn 26.2.0, flask-cors, flask-session, FAB 5.3.0, SQLAlchemy 2.0.55, pandas 3.1.1 | yes | yes | yes | `requirements/base.txt:51,123,171,340,377` |

Adding pip packages (V): (a) image layer: `USER root` + `/app/docker/pip-install.sh [--requires-build-essential] <pkgs>` or `uv pip install` (docs example activates `/app/.venv` first) then `USER superset` (`docker/pip-install.sh`, `docs/admin_docs/installation/docker-builds.mdx` "Building your own production Docker image"); (b) runtime: `/app/docker/requirements-local.txt` is installed on every container start by `docker-bootstrap.sh:35-61` - only present when `./docker` is bind-mounted, needs network at each start. Prefer (a).

Entrypoints (V):
- `docker/entrypoints/run-server.sh`: `exec gunicorn` bind `0.0.0.0:${SUPERSET_PORT:-8088}`, `--workers ${SERVER_WORKER_AMOUNT:-1}`, `--worker-class ${SERVER_WORKER_CLASS:-gthread}`, `--threads ${SERVER_THREADS_AMOUNT:-20}`, `--timeout ${GUNICORN_TIMEOUT:-60}`, `--keep-alive ${GUNICORN_KEEPALIVE:-2}`, `--max-requests ${WORKER_MAX_REQUESTS:-0}`, app `${FLASK_APP}` (`:30-45`).
- `docker/docker-bootstrap.sh <app|app-gunicorn|worker|beat|mcp>`: if root + `DEV_MODE=true` reinstalls `superset-core` and `.` editable (`:22-34`); if root + `DATABASE_DIALECT=postgres*` runs `uv pip install -e .[postgres]` (`:38-48`); installs `requirements-local.txt` (`:52-61`); then `worker` = `celery --app=superset.tasks.celery_app:app worker -O fair -l INFO --concurrency=${CELERYD_CONCURRENCY:-2}` (`:67`), `beat` = `celery ... beat --pidfile /tmp/celerybeat.pid -s $SUPERSET_HOME/celerybeat-schedule` (`:72`), `app` = `flask run --reload` with `FLASK_DEBUG=1` default (`:74-97`), `app-gunicorn` = `/usr/bin/run-server.sh` (`:98-101`), `mcp` = `superset mcp run --host 0.0.0.0 --port ${MCP_PORT:-5008} --debug` (`:102-105`). All root-only blocks are skipped when the container runs as `superset`.
- `docker/entrypoints/run-websocket.sh`: `node /app/superset-websocket/dist/index.cjs start`, env `JWT_SECRET`, `JWT_COOKIE_NAME`, `REDIS_HOST/PORT`, `PORT`.
- `docker/docker-healthcheck.sh`: `curl -f http://localhost:${SUPERSET_PORT}/${SUPERSET_APP_ROOT/\//}/health` - image-level HEALTHCHECK, so worker/beat/mcp/init services must override or disable it.

`docker/docker-init.sh` exact sequence (V, `:23-96`): 1) `docker-bootstrap.sh` (no arg: installs only) 2) `superset db upgrade` 3) `superset fab create-admin --username admin --email admin@superset.com --password "${ADMIN_PASSWORD:-admin}" --firstname Superset --lastname Admin` 4) `superset init` 5) if `SUPERSET_LOAD_EXAMPLES=yes`: skip when dashboard slug `world_health` exists AND examples table `wb_health_population` exists, unless `SUPERSET_FORCE_LOAD_EXAMPLES=yes`; otherwise `superset load_examples`. `set -e`; idempotent on re-run.

## 2. Compose files

| File | Image source | Services | Bind mounts | Ports | Notes |
|---|---|---|---|---|---|
| `docker-compose.yml` | build `target: ${SUPERSET_BUILD_TARGET:-dev}`, `DEV_MODE=true` | nginx, redis:7, db postgres:17, superset (`flask run`), superset-websocket (built from `./superset-websocket`), superset-init, superset-node (webpack dev server), worker, beat, tests-worker (profile `optional`) | `./docker ./superset ./superset-core ./superset-frontend ./tests ./local_extensions` | 80 nginx, 8088, 9000, 8080, 5432, 6379 | Dev only; webpack dev server required |
| `docker-compose-light.yml` | same build, dev | db-light, superset-light, init, node-light, pytest-runner (profile `test`) | `./docker ./superset ./superset-frontend ./tests` | `${NODE_PORT:-9001}` only | No Redis/Celery; `SUPERSET_CONFIG_PATH=.../superset_config_docker_light.py`; `SimpleCache`, `CELERY_CONFIG=None` |
| **`docker-compose-non-dev.yml`** | build `target: superset` from local source | redis, db, superset (`docker-bootstrap.sh app-gunicorn`), superset-init, worker, beat, superset-websocket (profile `websocket`, 8080) | only `./docker:/app/docker` + volume `superset_home` | 8088 | All app services `user: "root"` |
| `docker-compose-image-tag.yml` | `apachesuperset.docker.scarf.sh/apache/superset:${TAG:-latest}` | redis, db, superset, init, worker, beat | `./docker:/app/docker` | 8088 | Does not build the fork; `DEV_MODE: "false"` forced |

All four read `docker/.env` (required) then `docker/.env-local` (optional, git-ignored `.gitignore:127`). Named volumes: `superset_home`, `db_home`, `redis` (+ `superset_data` in dev). Postgres init script `docker/docker-entrypoint-initdb.d/examples-init.sh` creates user/DB `${EXAMPLES_USER}`/`${EXAMPLES_DB}` (first volume init only).

**Best base = `docker-compose-non-dev.yml`** (D: "immutable image based on the local branch", `docs/admin_docs/installation/docker-compose.mdx` option 3; V: `docker-compose-non-dev.yml:32-39`). Do not use it as-is, because (V):
1. It still bind-mounts `./docker` (config `pythonpath_dev` is NOT in the image - only `docker/*.sh` and `docker/entrypoints` are copied, `Dockerfile:180,225`).
2. It reuses `docker/.env` which sets `DEV_MODE=true`, `FLASK_DEBUG=true`, `SUPERSET_ENV=development` (`docker/.env:22,66,71`); with `user: root` every start runs `uv pip install -e .` and `-e .[postgres]` (network at boot, not reproducible) and Flask debug selects `TALISMAN_DEV_CONFIG` and tolerates default secrets.
3. Container names are hard-coded (`superset_app`, ...) and collide with any other Superset stack.

## 3. Config loading

Order (V, `superset/config.py:3888-3975`): defaults -> if env `SUPERSET_CONFIG_PATH` set: exec that file and copy every UPPERCASE name; else if module `superset_config` importable on `PYTHONPATH`: `from superset_config import *` -> finally env `SUPERSET__SQLALCHEMY_DATABASE_URI` / `SUPERSET__SQLALCHEMY_EXAMPLES_URI` override everything (`:3980-3988`). Feature flags can also come from env `SUPERSET_FEATURE_<NAME>` (merged into `DEFAULT_FEATURE_FLAGS`, `:1094-1101`; `FEATURE_FLAGS` in the config file wins).

`docker/pythonpath_dev/superset_config.py` (compose only; `PYTHONPATH=/app/pythonpath:/app/docker/pythonpath_dev`, `docker/.env:60`) consumes: `DATABASE_DIALECT/USER/PASSWORD/HOST/PORT/DB`, `EXAMPLES_USER/PASSWORD/HOST/PORT/DB`, `SUPERSET__SQLALCHEMY_EXAMPLES_URI`, `REDIS_HOST/PORT`, `REDIS_CELERY_DB` (0), `REDIS_RESULTS_DB` (1), `SUPERSET_APP_ROOT`, `SUPERSET_LOG_LEVEL` (`:31-66,131,138`). It sets `RESULTS_BACKEND = FileSystemCache("/app/superset_home/sqllab")`, Redis `CACHE_CONFIG = DATA_CACHE_CONFIG = THUMBNAIL_CACHE_CONFIG`, a `CeleryConfig`, `FEATURE_FLAGS = {ALERT_REPORTS, DATASET_FOLDERS, ENABLE_EXTENSIONS, MOBILE_CONSUMPTION_MODE, SEMANTIC_LAYERS: True}`, `EXTENSIONS_PATH="/app/docker/extensions"` (dir absent in repo -> only a warning, `superset/extensions/discovery.py:43-47`), `ALERT_REPORTS_NOTIFICATION_DRY_RUN=True`, `WEBDRIVER_BASEURL="http://superset:8088/..."`, `WEBDRIVER_BASEURL_USER_FRIENDLY="http://localhost:8888/..."` (wrong port for 8088), then tries `from superset_config_docker import *` (`:145-153`, git-ignored hook, template `superset_config_local.example`). Other env read by core config: `SUPERSET_SECRET_KEY` (`config.py:289`), `FLASK_DEBUG` (`:408`), `SUPERSET_ENV` (`:432`), `TALISMAN_ENABLED` (`:3146`), `SCARF_ANALYTICS` (`:3143`), `MAPBOX_API_KEY` (`:1883`), `ENABLE_VERSIONING_CAPTURE` (`:1919`), `SUPERSET_ENABLE_SWAGGER_UI` (`docker/.env:73`, `config.py:535`).

## 4. Metadata DB, Redis, Celery, caches (core defaults, V)

| Key | Core default | Line | Demo value |
|---|---|---|---|
| `SQLALCHEMY_DATABASE_URI` | SQLite in `DATA_DIR` | `config.py:292` | `postgresql://...@db:5432/superset` |
| `SQLALCHEMY_EXAMPLES_URI` | SQLite `examples.db` | `:3272` | Postgres DB `examples` |
| `CACHE_CONFIG`, `DATA_CACHE_CONFIG` | `NullCache` | `:1547,1550` | `RedisCache` db 1 |
| `FILTER_STATE_CACHE_CONFIG`, `EXPLORE_FORM_DATA_CACHE_CONFIG` | `SupersetMetastoreCache` (works without Redis; required caches) | `:1569,1583` | keep default or Redis |
| `CHART_QUERY_CANCEL_CACHE_CONFIG` | `SupersetMetastoreCache` | `:1599` | keep |
| `THUMBNAIL_CACHE_CONFIG` | `NullCache` | `:1444` | `RedisCache` (needed for THUMBNAILS/screenshot endpoints) |
| `RESULTS_BACKEND` | `None` (SQL Lab async results unavailable) | `:2303` | `RedisCache(host, port, key_prefix="superset_results")` or FileSystemCache on shared volume |
| `CELERY_CONFIG` | broker `sqla+sqlite`, 8 imports, beat: `reports.scheduler` (every minute), `reports.prune_log`, `version_history.prune_old_versions`, `deletion_retention.*` | `:2107-2198` | Redis broker db 0 / result db 1; keep all default imports (docker config drops `superset.tasks.slack` and `version_history_retention`) |
| `DISTRIBUTED_COORDINATION_CONFIG` | `None` | `:3822` | `RedisCache` (required by GAQ/GTF/locks/realtime) |
| `RATELIMIT_ENABLED` | `SUPERSET_ENV == "production"` (true in the image) | `:432` | set `RATELIMIT_STORAGE_URI="redis://redis:6379/3"` |

SQL Lab async (D, `docs/admin_docs/configuration/async-queries-celery.mdx`): needs Celery worker + broker + `RESULTS_BACKEND` + per-database "Asynchronous query execution" toggle; `SQLLAB_ASYNC_TIME_LIMIT_SEC` 6 h (`config.py:2230`), sync `SQLLAB_TIMEOUT` 30 s (`:2218`). One beat instance only.

**GLOBAL_ASYNC_QUERIES was re-platformed (breaking, `UPDATING.md` "Next", ~`:1370-1475`)**: it now runs on the Global Task Framework. `GLOBAL_ASYNC_QUERIES_JWT_*`, `_TRANSPORT`, `_CACHE_BACKEND`, `_WEBSOCKET_URL`, `_REDIS_STREAM_*` are **removed** - there is no GAQ JWT secret any more. Requirements: `FEATURE_FLAGS["GLOBAL_ASYNC_QUERIES"]=True` (auto-enables `GLOBAL_TASK_FRAMEWORK`), `DISTRIBUTED_COORDINATION_CONFIG` Redis, Celery workers, a persisting `DATA_CACHE_CONFIG`. Default transport = polling `GET /api/v1/task/status_changes` (`GLOBAL_ASYNC_QUERIES_POLLING_DELAY` 500 ms, `config.py:3332`). Optional websocket: `WEBSOCKET_ENABLE=True`, `WEBSOCKET_URL="ws://localhost:8080/"`, `WEBSOCKET_JWT_SECRET` **>= 32 bytes and not the default** or the app exits when not in debug (`superset/initialization/__init__.py:1211-1230`), websocket container `JWT_SECRET` must match, same browser-visible host, and CSP `connect-src` must allow the ws URL (default list `config.py:3167-3181`). Async is opt-in per request; UI default `GLOBAL_ASYNC_QUERIES_DEFAULT=True` (`:3380`). Lifecycle: testing -> BETA-TESTING.

## 5. Alerts & Reports, screenshots, thumbnails

| Requirement | Detail | Evidence |
|---|---|---|
| Flag | `ALERT_REPORTS: True` (testing) | `config.py:833`; D `docs/admin_docs/configuration/alerts-reports.mdx:47` |
| Scheduler | Celery beat with `reports.scheduler` every minute + worker importing `superset.tasks.scheduler` | `config.py:2126-2131` |
| Browser | Playwright + Chromium only; Selenium, Firefox, `WEBDRIVER_TYPE`, flag `PLAYWRIGHT_REPORTS_AND_THUMBNAILS` removed; only the worker needs the browser | `alerts-reports.mdx:63-69`, `UPDATING.md:1828-1845` |
| URLs | `WEBDRIVER_BASEURL="http://superset:8088/"` (core default `http://0.0.0.0:8080/` is wrong for compose), `WEBDRIVER_BASEURL_USER_FRIENDLY="http://localhost:8088/"` | `config.py:3029-3031` |
| Executor | default `ALERT_REPORTS_EXECUTORS=[ExecutorType.EDITOR]`; demo: `[FixedExecutor("admin")]` | `config.py:2871` |
| Dry run | core default `False`; docker config sets `True` | `config.py:2921`, `docker/pythonpath_dev/superset_config.py:124` |
| SMTP -> Mailpit | `SMTP_HOST="host.docker.internal"`, `SMTP_PORT=1025`, `SMTP_STARTTLS=False`, `SMTP_SSL=False`, `SMTP_USER=""`, `SMTP_PASSWORD=""`, `SMTP_MAIL_FROM="superset@nxtbi.local"`; UI at `http://localhost:8025` | core defaults `config.py:2400-2419`; empty user = unauthenticated (D `alerts-reports.mdx:394-395`) |
| Thumbnails | flag `THUMBNAILS` (stable, off) + non-Null `THUMBNAIL_CACHE_CONFIG` + worker with Chromium; `THUMBNAIL_EXECUTORS=[CURRENT_USER]` | `config.py:1041,1425,1444` |
| Dashboard PDF/PNG download | `ENABLE_DASHBOARD_SCREENSHOT_ENDPOINTS` + `ENABLE_DASHBOARD_DOWNLOAD_WEBDRIVER_SCREENSHOT` (testing) | `config.py:866,870` |

## 6. Feature flag inventory (`superset/config.py:724-1060`, 69 flags, V)

**EXPERIMENTAL (`development`, all default False):** AG_GRID_TABLE_ENABLED, ALERT_REPORT_DYNAMIC_EXECUTOR, ALERT_REPORT_TABS, CHART_PLUGINS_EXPERIMENTAL, CSV_UPLOAD_PYARROW_ENGINE, DATASET_FOLDERS, DATE_RANGE_TIMESHIFTS_ENABLED, FAB_API_KEY_ENABLED, GRANULAR_EXPORT_CONTROLS, SEMANTIC_LAYERS, SEMANTIC_LAYER_CONTAINMENT_CACHE, ENABLE_ADVANCED_DATA_TYPES, ENABLE_EXTENSIONS, MATRIXIFY, MOBILE_CONSUMPTION_MODE, OPTIMIZE_SQL, PARTITION_FILTER_MAPPING, PRESTO_EXPAND_DATA, TABLE_V2_TIME_COMPARISON_ENABLED.

**BETA-TESTING (`testing`):** default True: SOFT_DELETE, VERSION_HISTORY, ALERT_REPORT_SLACK_V2, TAGGING_SYSTEM. Default False: ALERT_REPORTS, ALERT_REPORTS_FILTER, ALERT_REPORTS_RETRY, ALERT_REPORT_WEBHOOK, ALLOW_FULL_CSV_EXPORT, CACHE_IMPERSONATION, DATE_FORMAT_IN_EMAIL_SUBJECT, DYNAMIC_PLUGINS, ENABLE_DASHBOARD_SCREENSHOT_ENDPOINTS, ENABLE_DASHBOARD_DOWNLOAD_WEBDRIVER_SCREENSHOT, ENABLE_SUPERSET_META_DB, ESTIMATE_QUERY_COST, GLOBAL_ASYNC_QUERIES, IMPERSONATE_WITH_EMAIL_PREFIX, RLS_IN_SQLLAB, SSH_TUNNELING, AWS_DATABASE_IAM_AUTH, GLOBAL_TASK_FRAMEWORK (no `@lifecycle` tag, sits in the testing block `:907-909`), USE_ANALOGOUS_COLORS, ENABLE_VIEWERS, ASSIGN_CREATOR_GROUPS_AS_VIEWERS, EMBEDDED_CREDENTIAL_FALLBACK.

**STABLE:** default True: DASHBOARD_VIRTUALIZATION, ALERTS_ATTACH_REPORTS, CSS_TEMPLATES, DRILL_BY, EMBEDDABLE_CHARTS, SQLLAB_BACKEND_PERSISTENCE. Default False: ALLOW_ADHOC_SUBQUERY, CACHE_QUERY_BY_USER, DASHBOARD_VIRTUALIZATION_DEFER_DATA, DATAPANEL_CLOSED_BY_DEFAULT, DISABLE_EMBEDDED_SUPERSET_LOGOUT, DRUID_JOINS, EMBEDDED_SUPERSET, ENABLE_TEMPLATE_PROCESSING, ESCAPE_MARKDOWN_HTML, FILTERBAR_CLOSED_BY_DEFAULT, FORCE_GARBAGE_COLLECTION_AFTER_EVERY_REQUEST, LISTVIEWS_DEFAULT_CARD_VIEW, MENU_HIDE_USER_INFO, SLACK_ENABLE_AVATARS, SQLLAB_FORCE_RUN_ASYNC, THUMBNAILS, ENABLE_FACTORY_RESET_COMMAND.

**DEPRECATED:** DRILL_TO_DETAIL (True).

No flag exists for: cross-filters (always on; `DASHBOARD_CROSS_FILTERS` removed `UPDATING.md:3239`), horizontal filter bar (`UPDATING.md:3227`), `DASHBOARD_RBAC` (removed, replaced by viewers/`ENABLE_VIEWERS`, `UPDATING.md:2241,2297`), MCP (separate process, needs `fastmcp`; no feature flag), themes (`ENABLE_UI_THEME_ADMINISTRATION=True`, `THEME_DEFAULT_MODE="system"`, `config.py:1362-1365`). `THUMBNAILS_SQLA_LISTENERS` appears in `docs/admin_docs/configuration/cache.mdx:292` but is not in `DEFAULT_FEATURE_FLAGS` (stale doc, U).

Recommended demo set:

| Flag | Lifecycle | Why | Extra requirement |
|---|---|---|---|
| DRILL_BY, DRILL_TO_DETAIL, TAGGING_SYSTEM, CSS_TEMPLATES, EMBEDDABLE_CHARTS, VERSION_HISTORY, SOFT_DELETE | on by default | drill, tags, history | none |
| ENABLE_TEMPLATE_PROCESSING | STABLE | Jinja in SQL | none |
| EMBEDDED_SUPERSET | STABLE | embedding SDK | non-default `GUEST_TOKEN_JWT_SECRET` or exit (`initialization/__init__.py:1184-1209`); CSP frame-ancestors / CORS |
| THUMBNAILS | STABLE | card thumbnails | Redis thumbnail cache + worker Chromium |
| ALERT_REPORTS (+ ALERT_REPORTS_FILTER, ALERT_REPORT_WEBHOOK optional) | BETA | scheduled reports to Mailpit | section 5 |
| ENABLE_DASHBOARD_SCREENSHOT_ENDPOINTS + ENABLE_DASHBOARD_DOWNLOAD_WEBDRIVER_SCREENSHOT | BETA | PDF/PNG dashboard download | Celery + thumbnail cache |
| GLOBAL_ASYNC_QUERIES | BETA | async charts (polling) | section 4; enable last, easy to turn off |
| ENABLE_VIEWERS | BETA | per-dashboard access | changes access semantics |
| SEMANTIC_LAYERS, ENABLE_EXTENSIONS, DATASET_FOLDERS, MATRIXIFY, AG_GRID_TABLE_ENABLED, FAB_API_KEY_ENABLED, MOBILE_CONSUMPTION_MODE | EXPERIMENTAL | showcase; first three plus MOBILE are already on in upstream docker config | label as experimental in the demo |

## 7. Examples (`superset load_examples`)

- V: data is **bundled in the repo/image as Parquet** - 21 files, ~32 MB, 135 YAML configs, 10 example folders (+ `_shared`) under `superset/examples/` (`world_health`, `featured_charts`, `sales_dashboard`, `deckgl_demo`, ...). `discover_datasets()` globs `*/data.parquet` and `*/data/*.parquet` (`superset/examples/data_loading.py`), loads with `pandas.to_sql(method="multi")` (`generic_loader.py:51-208`), then `ImportExamplesCommand` imports dashboards/charts YAML (`examples/utils.py:172-198`). **No network needed** (reads `file://` paths); not git-LFS.
- V: flags `--load-test-data/-t`, `--load-big-data/-b`, `--only-metadata/-m`, `--force/-f` (`superset/cli/examples.py`). `load_examples` and `load-examples` are both accepted (token normalizer `superset/cli/main.py:35`).
- V: target DB = `SQLALCHEMY_EXAMPLES_URI`; the `examples` Database row is created/updated to that URI on each run (`superset/utils/database.py:39-74`), so changing the URI later repoints the connection.
- DuckDB: driver only in `ci`/`showtime`/`dev` targets; `/app/data` exists for it (`Dockerfile:271-273`); no compose file wires a DuckDB examples URI (U how Showtime sets it). Postgres is the path of least resistance with the `superset` target.
- D: "can take a few minutes and a good amount of CPU" (`docker-compose.mdx`). Actual duration on this host: U.
- Risks (V): per-dataset loader failures are only logged as warnings (`cli/examples.py`, `_load_dataset`), so init can "succeed" with missing tables - check logs for `Failed to load`; deck.gl examples need map tiles/`MAPBOX_API_KEY` (internet); upstream skip-check keys on `world_health` + `wb_health_population` only.

## 8. Server, security defaults relevant to local http

| Topic | Fact | Evidence |
|---|---|---|
| Health | `GET /health`, `/healthcheck`, `/ping` -> `OK`, unauthenticated, `force_https=False` | `superset/views/health.py:26-33` |
| SECRET_KEY | `SUPERSET_SECRET_KEY` env or placeholder; with placeholder/empty and not debug -> `sys.exit(1)` | `config.py:289`; `initialization/__init__.py:1148-1182` |
| Talisman | enabled by default; debug -> `TALISMAN_DEV_CONFIG`, else `TALISMAN_CONFIG` (nonce + `'strict-dynamic'`, `force_https: False`, `session_cookie_secure: False`) -> works on plain http://localhost | `config.py:3146-3244`; `initialization/__init__.py:1710-1721` |
| Cookies | `SESSION_COOKIE_SECURE=False`, `SAMESITE="Lax"`, `HTTPONLY=True` | `config.py:3252-3254` |
| CSRF | `WTF_CSRF_ENABLED=True`, `WTF_CSRF_TIME_LIMIT` 1 week; exempt: `superset.charts.data.api.data`, `superset.datasource.api.query`, `superset.dashboards.api.cache_dashboard_screenshot`, `superset.dashboards.api.export_xlsx`, `superset.views.core.log`, `superset.views.datasource.views.samples`, `flask_appbuilder.security.views.acs` | `config.py:387-404,2445` |
| Unsafe DBs | `PREVENT_UNSAFE_DB_CONNECTIONS=True` (blocks e.g. SQLite as analytics DB), `PREVENT_UNSAFE_DEFAULT_URLS_ON_DATASET=True` | `config.py:3282-3285` |
| Rate limit | on when `SUPERSET_ENV=production`; `AUTH_RATE_LIMIT="5 per second"` | `config.py:432-446` |
| Passwords | `FAB_PASSWORD_COMPLEXITY_ENABLED=True`, min length 8 for forms/API; whether `fab create-admin` with a short password is rejected: U | `config.py:463-465` |
| Proxy | `ENABLE_PROXY_FIX=False`; CORS `ENABLE_CORS=True` with `CORS_OPTIONS` | `config.py:422,1663` |
| Timeouts | `SUPERSET_WEBSERVER_TIMEOUT=60` should match `GUNICORN_TIMEOUT` | `config.py:227` |
| MCP | `superset mcp run --host 127.0.0.1 --port 5008` (CLI defaults), streamable HTTP at `/mcp`; dev auth `MCP_AUTH_ENABLED=False` + `MCP_DEV_USERNAME="admin"` | `superset/cli/mcp.py`; D `docs/admin_docs/configuration/mcp-server.mdx:429-523` |

## 9. Recommended design: additive overlay in `nxtbi/`

Principles: build from fork source with upstream `Dockerfile --target superset` (frontend baked, no webpack dev server); **no source bind mounts**; run as non-root `superset`; config baked into the image at `/app/pythonpath/superset_config.py` (already on the image `PYTHONPATH`); own env file with `DEV_MODE=false`, `FLASK_DEBUG=false`, `SUPERSET_ENV=production`; own project/volume names.

Files to add (nothing outside `nxtbi/`):

| File | Content |
|---|---|
| `nxtbi/Dockerfile` | `ARG BASE_IMAGE=nxtbi/superset-base:f3f3d10d5c` / `FROM ${BASE_IMAGE}` / `USER root` / `COPY nxtbi/requirements-nxtbi.txt` + `RUN /app/docker/pip-install.sh -r ...` (pinned extras, e.g. Authlib; optionally `duckdb duckdb-engine`) / `COPY nxtbi/config/superset_config.py /app/pythonpath/superset_config.py` / `USER superset` |
| `nxtbi/config/superset_config.py` | env-driven: DB URIs, Redis caches, `RESULTS_BACKEND`, `CeleryConfig` (extend core imports + beat), `DISTRIBUTED_COORDINATION_CONFIG`, `FEATURE_FLAGS`, SMTP->Mailpit, `WEBDRIVER_BASEURL*`, executors, `RATELIMIT_STORAGE_URI`, secrets from env only |
| `nxtbi/docker-compose.yml` | `name: nxtbi`; services below; `env_file: .env` |
| `nxtbi/.env.example` | variable names only, no real secrets; `nxtbi/.env` git-ignored via `nxtbi/.gitignore` |
| `nxtbi/.gitattributes` | `*.sh text eol=lf`, `*.py text eol=lf`, `*.yml text eol=lf` (repo root only covers `docker/**/*.sh`) |

| Service | Image | Command | User | Ports | Volumes | Healthcheck |
|---|---|---|---|---|---|---|
| `db` | `postgres:17` | default | - | none (or `127.0.0.1:5433:5432`) | `nxtbi_db:/var/lib/postgresql/data`; `../docker/docker-entrypoint-initdb.d:/docker-entrypoint-initdb.d:ro` (LF enforced by root `.gitattributes`) | `pg_isready` |
| `redis` | `redis:7` | default | - | none | `nxtbi_redis:/data` | `redis-cli ping` |
| `superset-init` | `nxtbi/superset:dev` | `/app/docker/docker-init.sh` | superset | - | `nxtbi_home:/app/superset_home` | disable |
| `superset` | same | `/app/docker/entrypoints/run-server.sh` | superset | `8088:8088` | `nxtbi_home` | image default (`/health`) |
| `superset-worker` | same | `/app/docker/docker-bootstrap.sh worker` | superset | - | `nxtbi_home` | `celery -A superset.tasks.celery_app:app inspect ping -d celery@$$HOSTNAME` |
| `superset-worker-beat` | same | `/app/docker/docker-bootstrap.sh beat` | superset | - | `nxtbi_home` (schedule file) | disable |
| `superset-mcp` | same | `superset mcp run --host 0.0.0.0 --port 5008` | superset | `5008:5008` | - | override (not 8088) |
| `superset-websocket` (profile `realtime`, optional) | same | `/app/docker/entrypoints/run-websocket.sh` | superset | `8080:8080` (host port availability U) | - | `curl -f http://localhost:8080/health` |

All app services: `depends_on` db/redis healthy and `superset-init: service_completed_successfully`; worker gets `extra_hosts: ["host.docker.internal:host-gateway"]` for Mailpit. Build args for the base: defaults (`DEV_MODE=false`, `BUILD_TRANSLATIONS=false`); no `INCLUDE_CHROMIUM` needed for target `superset`.

`.env.example` keys: `SUPERSET_SECRET_KEY`, `DATABASE_DIALECT=postgresql`, `DATABASE_HOST=db`, `DATABASE_PORT=5432`, `DATABASE_DB`, `DATABASE_USER`, `DATABASE_PASSWORD`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `EXAMPLES_DB`, `EXAMPLES_HOST=db`, `EXAMPLES_PORT=5432`, `EXAMPLES_USER`, `EXAMPLES_PASSWORD`, `REDIS_HOST=redis`, `REDIS_PORT=6379`, `SUPERSET_ENV=production`, `FLASK_DEBUG=false`, `DEV_MODE=false`, `SUPERSET_PORT=8088`, `SUPERSET_LOAD_EXAMPLES=yes`, `ADMIN_PASSWORD`, `SERVER_WORKER_AMOUNT=4`, `SERVER_THREADS_AMOUNT=20`, `GUNICORN_TIMEOUT=120`, `CELERYD_CONCURRENCY=4`, `MCP_PORT=5008`, `SMTP_HOST=host.docker.internal`, `SMTP_PORT=1025`, `GUEST_TOKEN_JWT_SECRET`, `WEBSOCKET_JWT_SECRET` (>= 32 bytes), `SCARF_ANALYTICS=false`, `MAPBOX_API_KEY` (optional), `PYTHONUNBUFFERED=1`.

Exact command sequence (run from repo root; Git Bash or PowerShell):

```
docker build -f Dockerfile --target superset -t nxtbi/superset-base:f3f3d10d5c .
docker compose -f nxtbi/docker-compose.yml --env-file nxtbi/.env build
docker compose -f nxtbi/docker-compose.yml --env-file nxtbi/.env up -d db redis
docker compose -f nxtbi/docker-compose.yml --env-file nxtbi/.env run --rm superset-init
#   = superset db upgrade -> superset fab create-admin ... -> superset init -> superset load_examples
docker compose -f nxtbi/docker-compose.yml --env-file nxtbi/.env up -d superset superset-worker superset-worker-beat superset-mcp
curl -f http://localhost:8088/health
```

Persistence: metadata + examples in `nxtbi_db`, Redis in `nxtbi_redis`, beat schedule (and SQL Lab results if FileSystemCache) in `nxtbi_home`. `down` keeps volumes; `down -v` resets.

## 10. Open risks / to verify at build time

- Stray untracked 10-byte file `726` in the repo root (not created by this research; looks like a mis-redirected shell command). It enters the Docker build context and `git status`; lead should remove it.
- `superset` target reinstalls the package non-editable (`Dockerfile:357`, `pip-install.sh ... .[postgres,mysql,fastmcp]`); confirm which copy is imported (`python -c "import superset; print(superset.__file__)"`) before patching Python source in a derived layer (U).
- Extras and Playwright in the `superset` stage are not pinned by `requirements/base.txt` -> versions resolve at build time; tag and keep the built base image for reproducibility.
- First frontend build is heavy (webpack with 8 GB heap); give Docker Desktop >= 12 GB RAM. Build duration U.
- `superset db upgrade` (full migration history on an empty Postgres) and `load_examples` timing on Docker Desktop: U.
- Docs state "Superset does not have official support for Windows" (`docker-compose.mdx`); this design avoids bind mounts of source, the only bind mount is the read-only LF-enforced initdb script.
