# 07 - Release intelligence: what is new and how mature it is

Researched 2026-11-17. Repo: fork identical to apache/superset master `f3f3d10d5c` (2026-11-16). Labels: **[CODE]** verified in repo, **[DOCS]** docs/blog claim, **[GH]** GitHub API/issue, **[UNVERIFIED]**.
Lifecycle source for flags: `superset/config.py` `DEFAULT_FEATURE_FLAGS` (line 724+), legend at lines 712-722 (`development | testing | stable | deprecated`).

## 1. Critical framing: master is NOT 7.0.0rc2

| Fact | Evidence |
|---|---|
| 7.0.0rc1/rc2 were cut from master at `3d01094d23` (2026-09-11, "feat(docker): batteries-included default image") | `git merge-base 7.0.0rc2 HEAD` [CODE] |
| `7.0.0rc2` (`e4aee71493`, 2026-10-16) is NOT an ancestor of master; the 7.0 branch only received cherry-picked fixes (22 commits rc1..rc2) | `git merge-base --is-ancestor` = false [CODE] |
| Master has **1489 commits** (105 `feat`) beyond the 7.0 branch point | `git log 3d01094d23..HEAD` [CODE] |
| Master-only (absent from rc2 CHANGELOG): SIP-209 Improved Alerts & Reports (#44992), SIP-201 forgot-password for AUTH_DB (#45277), embedded OAuth2 fallback credential `EMBEDDED_CREDENTIAL_FALLBACK` (#45890), partition filter mapping (#43870), runtime toggle of `SEMANTIC_LAYERS` (#45061), semantic containment cache (#42760), semantic SDK conformance kit (#45395), admin management of DB OAuth2 tokens (#45676), TS6 migration (#44726), many MCP tools (dataset column CRUD #46048, governed source discovery #46120, PNG previews #44558) | `grep pull/<n> CHANGELOG/7.0.0.md` at rc2 = 0 [CODE] |
| Master-only fix needed for local image builds: libatomic before Playwright (#46124, merged 2026-11-10) | GH PR 46124 [GH] |
| `version` = `0.0.0-dev` in `superset-frontend/package.json:3`; `superset-core` and `superset-extensions-cli` are `0.1.0` in pyproject at HEAD (rc2 tag commits bumped them to 0.2.0) | [CODE] |
| `UPDATING.md` has one `## Next` section, lines 25-2902 (~2900 lines), then `## 6.1.0` at 2903, `6.0.0` at 3209, `5.0.0` at 3232. "Next" covers everything after 6.1.0 INCLUDING master-only items | [CODE] |

## 2. Release timeline

| Version | Tag date (git) | Public announce | Headline features | Source |
|---|---|---|---|---|
| 5.0.0 | rc1 2025-02-04, final 2025-06-18 | Preset blog 2025-06-23 | Ant Design 5 components, SQL Lab refresh, Redis Sentinel for GAQ, OAuth2 DB expansion (BigQuery/Trino/Firebolt), Slack V2, single-PDF tabs export, legacy charts removed | tags; https://preset.io/blog/superset-5-0-0-release-notes/ [DOCS] |
| 6.0.0 | rc1 2025-08-18, final 2025-12-04 (rc4 changelog commit `6a1c30e5e7`) | Preset blog 2026-02-09 | Theming system (Ant Design v5 tokens, dark mode, theme admin UI), URL prefix support, Dataset Folders, Security Groups (SIP-152 ph1), AG Grid Table V2 (flagged), deck.gl OSM default, Gantt, FAB 5.0, embedded SDK drill/dataMask | https://preset.io/blog/apache-superset-6-0-release/ [DOCS]; UPDATING.md:3211 [CODE] |
| 6.0.1rc1 | 2026-02-05 | - | patch line | tag [CODE] |
| 6.1.0 | rc1 2026-03-11, rc3 + final 2026-05-01 | Preset blog 2026-06-11 | Extensions framework (core/CLI 0.1.0 RC), MCP service ("early foundation", opt-in `fastmcp`), Global Task Framework (flag), Matrixify revamp, Dataset Folders editor, dynamic currency (SIP-193), embeddable charts flag, Node 22, example data as Parquet | https://preset.io/blog/apache-superset-6-1-release/ [DOCS]; UPDATING.md:2903-3200 [CODE] |
| 7.0.0rc1 | 2026-10-13 (`be7657e91b`) | GH pre-release | see 7.0 list below | `gh releases` [GH] |
| 7.0.0rc2 | 2026-10-16 (`e4aee71493`), Docker Hub `7.0.0rc2` pushed 2026-10-17, amd64+arm64 | GH pre-release | same + 22 backported fixes | Docker Hub API [GH] |
| 7.0.0 final | NOT released as of 2026-11-17 (latest GH release = rc2) | - | - | `list_releases` [GH]; Preset has no 7.0 post (search negative) |
| master | 2026-11-16 `f3f3d10d5c` | - | rc2 + 1489 commits | [CODE] |

**7.0 headline content** (`CHANGELOG/7.0.0.md` at rc2; ~3860 lines, 304 feature lines) [CODE]:
- Subjects model (users/roles/groups) replacing owners, dashboard roles and RLS roles (#38831; UPDATING.md:2233).
- SQLAlchemy 2.0 + flask-sqlalchemy 3.1.1 (#42803), Flask 3 (#43875), Python 3.11+, Node 24, Ant Design 6 (#41636), TS7 tooling, Oxfmt/Oxlint.
- Soft delete + Recently Archived + purge, version history + restore (all default ON), tagging default ON.
- GAQ re-platformed onto Global Task Framework (#43407, breaking).
- Selenium removed, Playwright only (#43028); Alerts retry, XLSX attachments, per-schedule Run-As executor (SIP-209 partly).
- Semantic layers (`SEMANTIC_LAYERS`), semantic views in Explore/dashboards/MCP; SIP-216 DB-rollup pivot/table totals.
- MCP service expansion: scoped tokens (#42297), observability, many chart plugins, semantic tools, embedded-guest auth.
- Extensions: Storage API (#39171), Chat contribution type SIP-214 (#41205), slots, security hooks (#40707).
- Batteries-included default Docker image (psycopg2, mysqlclient, fastmcp, Chromium); minimal moves to `-lean` (#44100).
- Snowflake + Databricks OAuth2, FAB API keys (#37973), mobile consumption mode, Butterfly chart, Table V1->V2 opt-in migration (#42088), AI-backfilled i18n catalogs.

## 3. Breaking changes that matter to a fresh install on master

| Area | Change | UPDATING.md line / evidence |
|---|---|---|
| Runtime floors | Python **>=3.11** (3.10 dropped); Docker `PY_VER=3.11-slim-trixie` (py312 variants published too); Node **^24.16.0**, npm ^11.13.0 (`.nvmrc` v24.16.0) | UPDATING.md:2184; `pyproject.toml:27`; `Dockerfile:26`; `superset-frontend/package.json:408-409` |
| Core libs | flask 3.1.3, **flask-appbuilder 5.3.0**, SQLAlchemy 2.0.55, pandas 3.1.1, numpy 2.4.6, celery 5.7.0, redis 8.1.0 | `requirements/base.txt:108,123,377,269,248,51,340` |
| FAB major | 6.0 moved to FAB 5.0 (`AUTH_OID` removed; use OAuth). Legacy FAB password-reset pages removed (404); use SPA profile / Users modal | UPDATING.md:3211, 1172 |
| Auth defaults | Password complexity ON (`FAB_PASSWORD_COMPLEXITY_ENABLED`, `AUTH_PASSWORD_MIN_LENGTH=8`); sessions end when account disabled; Swagger UI OFF (`SUPERSET_ENABLE_SWAGGER_UI=true` to enable); build SHA admin-only (`SUPERSET_EXPOSE_BUILD_DETAILS`); SMTP cert validation ON (`SMTP_SSL_SERVER_AUTH=False` to relax) | UPDATING.md:2620, 2386, 2390, 2707 |
| Secrets at startup | Prod refuses default `SECRET_KEY`, `GUEST_TOKEN_JWT_SECRET` (when `EMBEDDED_SUPERSET`), `GLOBAL_ASYNC_QUERIES_JWT_SECRET` (when GAQ on) | UPDATING.md:2663 |
| Guest tokens | RLS rules accept only `dataset` + `clause` keys; identities validated warn-first; revocation opt-in `GUEST_TOKEN_REVOCATION_ENABLED` | UPDATING.md:2378, 2677, ~296 |
| Subjects (RBAC) | `owners`->`editors`, dashboard `roles`/`DASHBOARD_RBAC` -> `viewers` behind `ENABLE_VIEWERS`, RLS `roles`->`subjects`; legacy junction tables dropped on upgrade. Fresh installs unaffected by data, but API clients/import YAMLs must use new fields | UPDATING.md:2233-2262 |
| Theming | 6.0: dynamic Ant Design theme system; `THEME_OVERRIDES` broken (replaced by `THEME_DEFAULT`/`THEME_DARK`, UI admin via `ENABLE_UI_THEME_ADMINISTRATION=True`, `THEME_DEFAULT_MODE="system"`). 6.1: `APP_NAME` no longer sets title/branding (use theme token `brandAppName`), `CUSTOM_FONT_URLS` removed (use per-theme `fontUrls`). 7.0: Ant Design v5->v6 (CSS vars default, `.ant-*` internal class renames break custom CSS; tokens unchanged). LESS is gone: there is no LESS->token tool, `.less` overrides must be rewritten as tokens/CSS | UPDATING.md:3228, 3144, 3167, 2368; `config.py:1251-1365` |
| Screenshots | Selenium removed; keys removed: `PLAYWRIGHT_REPORTS_AND_THUMBNAILS`, `WEBDRIVER_TYPE`, `WEBDRIVER_CONFIGURATION`, `SCREENSHOT_PAGE_LOAD_WAIT`, `SCREENSHOT_SELENIUM_RETRIES`, `SCREENSHOT_WAIT_FOR_ERROR_MODAL_*`, `EMAIL_PAGE_RENDER_WAIT`, `INCLUDE_FIREFOX` arg | UPDATING.md:1828, 1210 |
| Docker images | Default `apache/superset:<tag>` now batteries-included (psycopg2-binary, mysqlclient, fastmcp, headless Chromium); minimal = `-lean` (`7.0.0-lean`, `master-lean`). Dev images `-dev` unchanged. Standalone `websocket`/`dockerize` tags no longer published (websocket bundled: `/app/docker/entrypoints/run-websocket.sh`) | UPDATING.md:1222, 1248 |
| GAQ | Removed `/api/v1/async_event/`, `AsyncQueryManager`, config keys `GLOBAL_ASYNC_QUERIES_{CACHE_BACKEND,TRANSPORT,WEBSOCKET_URL,REDIS_STREAM_*,JWT_*,REGISTER_REQUEST_HANDLERS}`, `GLOBAL_ASYNC_QUERY_MANAGER_CLASS`; now `DISTRIBUTED_COORDINATION_CONFIG` + polling `GET /api/v1/task/status_changes` | UPDATING.md:1371 |
| Default-on data features | `SOFT_DELETE` (purge live, `SOFT_DELETE_RETENTION_DAYS=30`), `VERSION_HISTORY` + `ENABLE_VERSIONING_CAPTURE`, `TAGGING_SYSTEM`; Celery beat needs `deletion_retention.purge_soft_deleted` and `version_history.prune_old_versions` if `CELERY_CONFIG` is replaced | UPDATING.md:1909, 1937, 1314; `config.py:773,820,900` |
| SQL safety | `DISALLOWED_SQL_FUNCTIONS/TABLES` now block PG `lo_*` and `information_schema`; `SQL_MAX_PARSE_LENGTH=1_000_000`; `UPLOAD_MAX_FILE_SIZE_BYTES`=100 MB | UPDATING.md:2347, 2358, 2633 |
| Removed legacy | 5.0: legacy Area/Bar/Heatmap/Histogram/Line/Sankey charts auto-migrated to ECharts, `DASHBOARD_CROSS_FILTERS`, `DISABLE_LEGACY_DATASOURCE_EDITOR` flags removed; 6.0: `HORIZONTAL_FILTER_BAR` flag removed; 7.0: legacy `explore_json`+`viz.py` pipeline removed (#41714), deck.gl JS controls + `ENABLE_JAVASCRIPT_CONTROLS` removed, `from_dttm/to_dttm` Jinja vars removed | UPDATING.md:3330-3340, 3225, 2213, 2191; CHANGELOG 7.0.0 |
| Examples | 6.1: examples are Parquet + YAML under `superset/examples/<name>/` (`data.parquet`), `load_test_data` moved to `superset/cli/test_loaders.py`. Master: docker-compose dev loop skips `load_examples` once loaded; `SUPERSET_FORCE_LOAD_EXAMPLES=yes` forces; `docker/.env:74` sets `SUPERSET_LOAD_EXAMPLES=yes`; `BUILD_TRANSLATIONS` default false (`docker-compose.yml:46,197`) | UPDATING.md:2992, 2886 |
| Misc | Helm chart switches to `app.kubernetes.io/*` labels (delete workloads before `helm upgrade`); MySQL metadata DB needs READ COMMITTED; Snowflake catalog case rules; `NOT IN` now includes NULL rows; MCP with JWT needs `MCP_JWT_AUDIENCE` | UPDATING.md:2394, 1142, 25+, 2886, 2382 |

## 4. Maturity map (flags verified in `superset/config.py`; "first release" = first tag where the flag/config exists in `config.py`)

| Capability | Flag / config | First release | Status (fork evidence) | Notes / source |
|---|---|---|---|---|
| New theming (Ant Design tokens) | `THEME_DEFAULT`, `THEME_DARK`, `ENABLE_UI_THEME_ADMINISTRATION=True`, `THEME_DEFAULT_MODE` | 6.0.0 | **STABLE** (no flag, default on) | `config.py:1269-1365` [CODE] |
| Dark mode | `THEME_DARK` (set `None` to force single theme) | 6.0.0 | **STABLE** | `config.py:1327-1357` [CODE]; 6.1.0rc3 dark theme bug #39855 closed |
| Extensions framework | `ENABLE_EXTENSIONS` (+`DYNAMIC_PLUGINS` testing) | 6.1.0 | **EXPERIMENTAL** (`@lifecycle: development`, `config.py:788`); core/CLI pkgs 0.x ("moving toward 1.0") | `.supx` bundles; docs `docs/developer_docs/extensions/*`; CLI bundle bug #42568 open |
| MCP service | no flag; `superset mcp run`, `pip install apache-superset[fastmcp]` (in default image from 7.0), `MCP_AUTH_ENABLED`, `MCP_RBAC_ENABLED=True`, `MCP_STRUCTURED_OUTPUT_ENABLED=False` | 6.1.0 | **BETA** (Preset called it "early foundation"; fast-moving, many breaking notes under UPDATING "Next") | `superset/mcp_service/`; `docs/admin_docs/configuration/mcp-server.mdx` [CODE/DOCS] |
| Semantic layers API/SDK | `SEMANTIC_LAYERS` (+`SEMANTIC_LAYER_CONTAINMENT_CACHE`) | 7.0.0 (rc1) | **EXPERIMENTAL** (`@lifecycle: development`, `config.py:776,783`); provider SDK/contracts still changing weekly on master | `docs/developer_docs/extensions/semantic-provider-*.md` [CODE] |
| Embedded SDK / embedding | `EMBEDDED_SUPERSET` | 4.0 (pre-5.0) | **STABLE** (`config.py:1000`) | SDK `superset-embedded-sdk`; setDataMask added #35754 |
| Guest tokens | `GUEST_TOKEN_JWT_SECRET`, `GUEST_TOKEN_JWT_EXP_SECONDS`, `GUEST_TOKEN_REVOCATION_ENABLED` | 1.x/4.0 | **STABLE** core; revocation + validation new/opt-in | UPDATING.md:2378,2677 |
| Embedded credential fallback | `EMBEDDED_CREDENTIAL_FALLBACK` | master (not in rc2) | **TESTING** (`config.py` category security) | UPDATING.md:~85 |
| Dataset folders | `DATASET_FOLDERS` | 6.0.0 | **EXPERIMENTAL** (`development`, `config.py:753`) | Folder DnD in Explore #42483 |
| AG Grid table (Table V2) | `AG_GRID_TABLE_ENABLED` | 6.0.0 | **EXPERIMENTAL** (`development`, `config.py:733`); opt-in V1->V2 migration #42088 | 500k rows server pagination [DOCS] |
| Global async queries | `GLOBAL_ASYNC_QUERIES` + `GLOBAL_TASK_FRAMEWORK` | GAQ 1.x; GTF 6.1.0 | GAQ **TESTING** (`config.py:885`); GTF in "IN TESTING" block, no lifecycle tag (`config.py:909`); breaking re-platform in 7.0 | UPDATING.md:1371 |
| Alerts & Reports | `ALERT_REPORTS` (+`ALERT_REPORTS_RETRY`, `ALERT_REPORT_WEBHOOK`, `ALERT_REPORT_SLACK_V2=True`) | 1.x | **TESTING** (`config.py:833`); Playwright only from 7.0; `ALERT_REPORT_TABS`, `ALERT_REPORT_DYNAMIC_EXECUTOR` = development | needs `playwright install chromium`; bundled in default image |
| Tagging | `TAGGING_SYSTEM` | 1.x | **TESTING but default ON** from 7.0 (`config.py:900`) | implicit tags removed |
| Dashboard RBAC | `DASHBOARD_RBAC` removed; `ENABLE_VIEWERS` | 7.0 | **TESTING** (`config.py:956`, security) | replaces DASHBOARD_RBAC; `ASSIGN_CREATOR_GROUPS_AS_VIEWERS` testing |
| Drill by / drill to detail | `DRILL_BY=True` | 3.0/4.0 | `DRILL_BY` **STABLE** (`config.py:982`); `DRILL_TO_DETAIL` **DEPRECATED** tag (flag path to removal) | |
| Cross-filters | flag removed in 5.0 (`DASHBOARD_CROSS_FILTERS`) | 5.0 | **STABLE** (always on) | UPDATING.md:3336 |
| SSH tunnel | `SSH_TUNNELING`, `SSH_TUNNEL_STRICT_HOST_KEY_CHECKING=False` | 1.x | **TESTING** (`config.py:897`) | host key verification opt-in |
| Database OAuth2 | `DATABASE_OAUTH2_CLIENTS` (no flag) | 4.x/5.0 | **STABLE** config; Snowflake/Databricks OAuth new in 7.0 (#36856,#41421); token admin on master (#45676) | |
| Impersonation | DB-level "Impersonate logged in user"; `CACHE_IMPERSONATION`, `IMPERSONATE_WITH_EMAIL_PREFIX` | 1.x | core **STABLE**; the two flags **TESTING** | `config.py:~870` |
| Row-level security | RLS UI/API; `RLS_IN_SQLLAB` | 1.x | **STABLE**; `RLS_IN_SQLLAB` TESTING; RLS roles->subjects in 7.0 | UPDATING.md:2021 |
| API keys | `FAB_API_KEY_ENABLED`, `MCP_API_KEY_ENABLED` | 7.0.0 | **EXPERIMENTAL** (`development`, `config.py:761`) | #45492: `MCP_API_KEY_CREATE_URL` default 404 |
| Matrixify / small multiples | `MATRIXIFY` | 6.1.0 | **EXPERIMENTAL** (`development`, `config.py:791`) | control panel revamped #38519 |
| Mobile consumption | `MOBILE_CONSUMPTION_MODE` | 7.0.0 | **EXPERIMENTAL** (`development`, `config.py:798`) | |
| Soft delete / version history | `SOFT_DELETE=True`, `VERSION_HISTORY=True` | 7.0.0 | **TESTING**, default ON | `config.py:773,820` |
| Granular export controls | `GRANULAR_EXPORT_CONTROLS` | 7.0.0 | **EXPERIMENTAL** (`development`, `config.py:765`) | |
| Embeddable charts | `EMBEDDABLE_CHARTS=True` | 6.1.0 | **STABLE** (category runtime_config) | |
| AI features | MCP service; extension `Chat` contribution type (SIP-214, #41205); AI-generated i18n catalogs | 6.1.0 / 7.0 | MCP BETA; Chat EXPERIMENTAL; **no built-in LLM chat or text-to-SQL in core** [CODE: grep CHANGELOG] | user guide `docs/docs/using-superset/using-ai-with-superset.mdx` |

## 5. Known open problems with master / 7.0.0rc (GitHub, last ~60 days; index current to ~2026-11-02)

| Issue | State | Impact | Workaround |
|---|---|---|---|
| #45587 OAuth `mismatching_state` intermittent (rc2 regression from #44605; anonymous `/log/` beacon overwrites session cookie) | closed 2026-10-30 by #45593 (master; not in rc2) | **Direct for Keycloak/OAuth** with cookie sessions | set `SESSION_SERVER_SIDE=True` (Redis/DB session store, also the documented secure setup), or pin master >= #45593; retry login works |
| #45632 admin list pages (Users, Groups, RLS, Action Log) search only first field | open; fix PR #46041 open | UX only | filter by first field, use API |
| #45494 Table chart search box lost record count | closed | cosmetic | |
| #45492 `MCP_API_KEY_CREATE_URL` defaults to `/profile/` (404) | closed 2026-10-30 | MCP API keys | set `MCP_API_KEY_CREATE_URL="/user_info/"` (master default already) |
| #45390 MCP BrowserHelloMiddleware intercepts browser GETs, breaks `MCP_AUTH_FACTORY` OAuth | closed 2026-10-22 | MCP OAuth/Keycloak | use master; or JWT static verifier |
| #43327 failing `MCP_AUTH_FACTORY` is swallowed, MCP starts unauthenticated | closed (Aug) | security | verify `MCP_AUTH_ENABLED` logs; UPDATING requires `MCP_JWT_AUDIENCE` |
| #45937 Flight SQL/ADBC source-install dependency failures | open | only source installs with ADBC | use Docker image |
| #42568 `superset-extensions bundle` resolves stale PyPI `apache-superset-core` 0.1.0 | open | extension build | pin `apache-superset-core` to the local `superset-core` path |
| #45731 docs: `docker compose down -v` deletes local data | closed (docs) | data loss | never use `-v` on the demo stack |
| Master `libatomic` build failure, fixed #46124 (2026-11-10) | merged | full-image **local builds** before 11-10 | fork is at f3f3d10d5c (after fix) so OK; rc2 images are prebuilt so unaffected |
| #39682 embedding broken after 6.0 upgrade | open | embedding | check `ENABLE_PROXY_FIX`, allowed domains, referrer policy |
| No 7.0-specific open issues found for `load_examples`, translations build or compose in the last 60 days | - | - | [UNVERIFIED] search is semantic and incomplete |

Pitfalls in repo docs (not issues): `BUILD_TRANSLATIONS` defaults false so non-English UI needs the build arg (UPDATING.md:3343 area); `docker/.env` has `SUPERSET_LOAD_EXAMPLES=yes`.

## 6. Risk verdict and fallback

- Master moves ~50 commits/day, has no frozen UPDATING (`## Next`), and carries unreleased security/auth changes. Risky for a demo that must be reproducible.
- **Safest pre-built option: `apache/superset:7.0.0rc2`** (amd64 + arm64, pushed 2026-10-17; variants `-lean`, `-dev`, `-py311`, `-py312`) [GH Docker Hub API]. Keeps Subjects, soft delete, MCP scopes, SQLA 2, Ant Design 6. Loses: SIP-209, forgot-password (SIP-201), embedded credential fallback, OAuth cookie fix #45593, semantic containment cache, newest MCP tools.
- **Most conservative: `6.1.0`** (tag 2026-05-01; image `apache/superset:6.1.0` is the *minimal* image, no psycopg2/Chromium, so layer `psycopg2-binary`, `playwright`). Loses: Subjects/viewers, soft delete/version history, SQLA 2/Flask 3, Python 3.12 images, semantic layers, most MCP tools, Selenium-free reports; still has theming, folders, AG Grid flag, extensions 0.1, MCP early.
- If building from the fork (master), pin to a commit SHA and rebuild `-lean`+custom or use default image; keep `SUPERSET_FORCE_LOAD_EXAMPLES` off after first load.

## 7. "Worth adopting for NxtBI" shortlist (priority order)

| # | Item | Why | Verdict |
|---|---|---|---|
| 1 | Theming via `THEME_DEFAULT`/`THEME_DARK` + theme admin UI (brand tokens, `brandAppName`, `fontUrls`) | core of NxtBI brand without frontend fork; no flag | STABLE - adopt now |
| 2 | Embedded SDK + guest tokens (set `GUEST_TOKEN_JWT_SECRET`, strict `rls` shape) | portal integration | STABLE - adopt |
| 3 | Subjects / `ENABLE_VIEWERS` + groups | dashboard-level access replacing DASHBOARD_RBAC; demo of multi-tenant RBAC | TESTING - adopt with caution |
| 4 | OAuth login (Keycloak) with `SESSION_SERVER_SIDE=True` | needed for SSO demo; avoids #45587 | STABLE (bug fixed on master only) |
| 5 | MCP service (`superset mcp run`, JWT + `MCP_JWT_AUDIENCE`, `MCP_RBAC_ENABLED`) | AI-assistant story without custom LLM code; preview-first charts | BETA - adopt as optional demo |
| 6 | Alerts & Reports with Playwright (default image has Chromium) + Redis/Celery | scheduled email demo | TESTING - adopt |
| 7 | Database OAuth2 / impersonation + RLS | governance narrative | STABLE core - adopt |
| 8 | Soft delete + version history + Recently Archived (default ON) | enterprise-grade recovery demo; no setup | TESTING (default on) - keep on, size purge |
| 9 | Dataset Folders + AG Grid Table V2 | nicer large-table UX | EXPERIMENTAL - enable only in demo env |
| 10 | Tagging (default on) + certification | catalog feel | TESTING - keep on |
| 11 | Semantic layers API (`SEMANTIC_LAYERS`) | future bridge to NxtBI Semantic Layer / Cube / Wren (out of scope now) | EXPERIMENTAL - document only, do not enable for demo |
| 12 | Extensions framework (`ENABLE_EXTENSIONS`, `.supx`, Chat contribution SIP-214) | clean path for NxtBI plugins without forking | EXPERIMENTAL (core 0.x) - prototype only |

## 8. Unverified / not confirmed

- Whether 7.0.0 final has a release date or a published 7.x roadmap SIP list (no announcement found, no Preset 7.0 post).
- GitHub issue coverage after ~2026-11-02 and complete absence of docker-compose/load_examples/translation-build regressions (semantic search only).
- Exact first-release tag for flags added before 5.0 (listed 1.x/4.0 from memory, not checked by `git show`).
- Why `superset-core`/`extensions-cli` read 0.1.0 at HEAD while rc2 commits bump to 0.2.0 (not investigated).
- Whether `DASHBOARD_VIRTUALIZATION`, `THUMBNAILS` etc. matter to demo (not relevant here).
- Line `UPDATING.md:~85/296` references are approximate (offsets within "Next" excerpt); other cited line numbers were directly grep-verified.
