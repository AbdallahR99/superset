# NxtBI Capability Matrix: Apache Superset master @ f3f3d10d5c

Audience: NxtBI engineering leads deciding what to adopt. Source: `nxtbi/docs/research/01..07-*.md` (cited as R01..R07). Maturity, flags and evidence come from the research (code reading and docs). The `Demo` column is different: it records what was actually run against the demo stack on 2026-11-17 (see `TEST-RESULTS.md`). "Tested" means an automated check passed; "Partly tested" names what was and was not covered; everything else was not run and is not claimed to work.

## Executive summary

1. This is **master**, not a release: `f3f3d10d5c` (2026-11-16) is `7.0.0rc2` plus 1489 commits (105 `feat`), version string `0.0.0-dev`. 7.0.0 final was not released as of 2026-11-17 (R07 s1, s2).
2. Superset gives NxtBI a mature BI core (dashboards, native filters, cross-filters, ~60 ECharts/d3/deck.gl chart types, SQL Lab, RLS, assets-as-code, embedding) that is STABLE.
3. Branding is config-only and STABLE (theme tokens `brandAppName`, `brandLogoUrl`, `fontUrls`); Arabic is translation-only with no RTL layout (see I18N-RTL.md).
4. Keycloak login works through FAB `AUTH_OAUTH` plus a custom security manager (own code, R02). Keycloak bearer tokens do **not** work on REST; the MCP service can be configured to accept them (designed, not tested in this demo).
5. The MCP server (83 tools) is the only shipped AI integration and is BETA. There is no built-in LLM, text-to-SQL or chat UI (R03 s7).
6. Semantic layers (`SEMANTIC_LAYERS`) and extensions (`ENABLE_EXTENSIONS`) are EXPERIMENTAL; no semantic provider ships in-tree, so Cube/Wren need custom code (R04 s3).
7. Multi-tenancy is not a product feature: one metadata DB, one role namespace, RLS on datasets only (see limitations below).
8. Top risks: (a) master churn (~50 commits/day, unfrozen `UPDATING.md`); (b) breaking changes since 6.1 (Subjects model, GAQ re-platform, FastMCP 4.x, Ant Design 6); (c) EXPERIMENTAL SDKs documented as "unreleased"; (d) Arabic catalogue 54.2% non-fuzzy and no RTL; (e) Alerts & Reports, MCP, viewers are only BETA.
9. Fallback if master proves unstable: `apache/superset:7.0.0rc2` (prebuilt, amd64+arm64), then `6.1.0` (R07 s6).
10. Config-only customisation covers most NxtBI needs; anything needing new chart types, RTL or UI extension points requires a frontend rebuild (R04 s1.4, s2).

Legend. Maturity labels are copied from the research (STABLE / TESTING (beta) / EXPERIMENTAL (development) / DEPRECATED / NOT AVAILABLE). `(untagged)` = the research gives no lifecycle tag; the feature has no flag and is core behaviour, so no label is claimed beyond that. Evidence tags: V = verified in code, D = docs-claimed, U = unverified. Value: High / Med / Low for NxtBI.

## Matrix

| Capability | Maturity | Flag / config | Demo | NxtBI value | Evidence |
|---|---|---|---|---|---|
| **Dashboards & filters** | | | | | |
| Native filters (select, range, time, timecolumn, timegrain), scoping, cascading | STABLE | none | **Tested** - 5 native filters per dashboard (time range, selects, one cascading pair, tab-scoped); applying Sector = Health changed the KPI tiles in a real browser | High: core UX | V `superset-frontend/src/constants.ts:197-203`; R06 s2 |
| Cross-filtering | STABLE | `cross_filters_enabled` in dashboard metadata; flag removed | **Partly tested** - enabled in each dashboard's metadata with emitter scopes (verified through the API); clicking a chart to cross-filter was not automated | High: interactive demo | V `UPDATING.md:3239`; R06 s2 |
| Drill-by | STABLE | `DRILL_BY` (True) | On by default; not exercised | Med: self-service depth | V `superset/config.py:982` |
| Drill-to-detail | DEPRECATED | `DRILL_TO_DETAIL` (True) | On by default; not exercised | Low: flag heading to removal | V `superset/config.py:1059` |
| Dynamic chart customisation (group by, time grain, time column controls) | STABLE | no flag gate | Not used in the demo dashboards | Med: end-user pivoting | V `superset-frontend/src/constants.ts:205-210`, `MainPreset.ts:150-165` |
| Tags and certification | TESTING (beta) | `TAGGING_SYSTEM` (default on); certification fields in chart/dashboard schemas | Not exercised | Med: catalog feel | V `superset/config.py:900`; R06 s2 |
| Per-dashboard theme, CSS templates, auto-refresh, permalinks | STABLE | `CSS_TEMPLATES`, `theme_uuid`, `DASHBOARD_AUTO_REFRESH_*` | Not exercised | Med: branding per dashboard | V `superset/config.py:1362,2078-2080`; R06 s2 |
| Mobile consumption mode | EXPERIMENTAL | `MOBILE_CONSUMPTION_MODE` | Not enabled | Low: label as experimental | V `superset/config.py:798`; R07 s4 |
| **Charts (counts taken from the R06 s1 table)** | | | | | |
| ECharts core families: timeseries bar/line/scatter/smooth/step/area (7), mixed (1), pie, big number x2, heatmap, histogram, box, bubble, funnel, gauge, treemap, sunburst, sankey, radar, waterfall, graph, tree, gantt, rose, time pivot, bullet, butterfly, candlestick = 30 viz_types | STABLE | none (butterfly, candlestick new since 6.0.0, no gate) | **Tested** - 13 ECharts-based types across 33 charts rendered in Chromium with 0 failed queries (bar, smooth line, area, mixed, pie, treemap, heatmap, sankey, funnel, gauge, box plot, big number, big number total) | High: main visual vocabulary | V `superset-frontend/src/visualizations/presets/MainPreset.ts:80-205`; R06 s1 |
| Table, pivot_table_v2, handlebars, time_table (4) | STABLE (time_table legacy renderer) | `HTML_SANITIZATION=True` for handlebars | **Tested** - table with conditional formatting and pivot_table_v2 rendered; handlebars and time_table not used | High: tabular reporting | V R06 s1; `superset/config.py:1679` |
| Legacy d3 family: cal_heatmap, chord, horizon, para, paired_ttest, partition, word_cloud, world_map, country_map (9) | STABLE | none | Not used | Low: dated look, maps useful | V R06 s1 |
| Maps: deck.gl (11 types), point_cluster_map, cartodiagram | STABLE | `MAPBOX_API_KEY` optional; OSM tiles need browser internet | Not used (needs a Mapbox key) | Med: geo story, needs internet | V `config.py:1883`; R06 s1 |
| pop_kpi, ag-grid-table | EXPERIMENTAL | `CHART_PLUGINS_EXPERIMENTAL`, `AG_GRID_TABLE_ENABLED` | Not enabled | Low: avoid in demo | V `superset/config.py:733,747` |
| **Explore** | | | | | |
| Drag-and-drop explore, ad-hoc metrics/filters, annotations, conditional formatting, currency formatting | STABLE | none | **Partly tested** - a saved chart opens in Explore in the browser and all 33 charts' form_data were accepted by the Explore API; editing in the UI was not automated | High | V `UPDATING.md:3326`; R06 s2 |
| Time comparison; date-range shifts | STABLE; shifts EXPERIMENTAL | `DATE_RANGE_TIMESHIFTS_ENABLED` (development) | Not exercised | Med | V `superset/config.py:757` |
| Forecast (Prophet) | STABLE | needs `.[prophet]`, not in default image | Not available: Prophet is not in the image | Low: extra dependency | V `pyproject.toml:274-281`; `Dockerfile:352` |
| Matrixify (small multiples) | EXPERIMENTAL | `MATRIXIFY` | Not enabled | Low | V `superset/config.py:791` |
| **SQL Lab** | | | | | |
| SQL editor, saved queries, history, CTAS/CVAS, async execution | STABLE | async: Celery + `RESULTS_BACKEND` + per-DB toggle | **Tested** - synchronous and asynchronous execution (Celery worker, Redis results backend) through the API; the editor opens in the browser. Saved queries and CTAS/CVAS not exercised | High: analyst workflow | V `superset/config.py:1032,2303`; R01 s4 |
| Jinja templating in SQL | STABLE | `ENABLE_TEMPLATE_PROCESSING` (off by default; SSTI warning) | Flag ENABLE_TEMPLATE_PROCESSING is on; not exercised | Med: per-user macros | V `superset/config.py:1004`; R06 s2 |
| Query cost estimate; RLS inside SQL Lab | TESTING (beta) | `ESTIMATE_QUERY_COST`, `RLS_IN_SQLLAB` | **Tested, with a defect found** - raw SQL by a planning user returned only planning rows and the other tenant's table was refused. A request with `"catalog": ""` bypassed RLS on this build; the demo config now refuses it (regression test passes). Cost estimate not exercised | Med: RLS bypass risk if off | V `superset/config.py:889-892` |
| **Datasets & native semantic layer** | | | | | |
| Saved metrics, calculated columns, certification, virtual datasets, currency, d3 formats | STABLE | none | **Tested** - 35 saved metrics and 11 calculated columns on 4 datasets; charts and a headless API query reference metrics by name | High: the demo's semantic story | V `superset/connectors/sqla/models.py:1360-1389,1741-1761`; R04 s3.2 |
| Dataset folders | EXPERIMENTAL | `DATASET_FOLDERS` | Not enabled | Low-Med: UX nicety | V `superset/config.py:751-753` |
| `is_managed_externally` marker | STABLE | dataset field | Not used | Med: code-owned assets | V `models.py:390-396` |
| **External semantic layers** | | | | | |
| Semantic layer / semantic views API, UI, MCP tools | EXPERIMENTAL | `SEMANTIC_LAYERS`, `SEMANTIC_LAYER_CONTAINMENT_CACHE` (development) | Not enabled (development-lifecycle flag); see FUTURE-INTEGRATIONS.md | Med: strategic bridge | V `superset/config.py:774-782`; `superset/semantic_layers/api.py:257-276` |
| In-tree providers (Cube, dbt MetricFlow, Snowflake, Malloy, Wren) | NOT AVAILABLE | registry is empty; only test stubs | Out of scope; nothing built | n/a: must be written | V `superset/semantic_layers/registry.py:24`; R04 s3.1 |
| Cube Core via Postgres-wire SQL API as a plain database | STABLE (Superset side); Cube SQL-API behaviour UNVERIFIED | ordinary PostgreSQL engine spec | Out of scope by request; documented in FUTURE-INTEGRATIONS.md | Med: cheapest bridge | D docs.cube.dev SQL API; R04 s3.3 |
| **Caching & async** | | | | | |
| Redis result/data/thumbnail caches, cache warm-up | STABLE (untagged) | `CACHE_CONFIG`, `DATA_CACHE_CONFIG` default `NullCache` | **Tested** - a repeated identical query was served from the Redis data cache (is_cached=true); thumbnails are rendered per user by the worker (digests differ between tenants). Cache warm-up not exercised | High: dashboard speed | V `superset/config.py:1444,1547-1550`; R06 s3 |
| Global async queries (on Global Task Framework, breaking re-platform) | TESTING (beta) | `GLOBAL_ASYNC_QUERIES`, `DISTRIBUTED_COORDINATION_CONFIG` | Not enabled (testing lifecycle, re-platformed on master) | Low: leave off for small data | V `superset/config.py:885`; R01 s4 |
| **Exports** | | | | | |
| CSV / XLSX / JSON chart data, dashboard to Excel | STABLE | `EXCEL_EXPORT_SYNC_MAX_ROWS` 100k | Not exercised (asset export was tested, data export was not) | Med | V `superset/charts/data` result formats; `superset/config.py:1780`; R06 s2 |
| Dashboard / chart PDF and PNG | TESTING (beta) | `THUMBNAILS`, `ENABLE_DASHBOARD_SCREENSHOT_ENDPOINTS`, `ENABLE_DASHBOARD_DOWNLOAD_WEBDRIVER_SCREENSHOT` | **Partly tested** - PNG screenshots are produced by the report pipeline; the UI download buttons were not exercised | Med: needs Celery + Chromium | V `superset/config.py:866,870,1041` |
| Granular export controls | EXPERIMENTAL | `GRANULAR_EXPORT_CONTROLS` | Not exercised | Low | V `superset/config.py:765` |
| **Alerts & reports** | | | | | |
| Scheduled email/Slack V2/webhook reports and alerts (PDF/PNG/CSV/XLSX/TEXT) | TESTING (beta) | `ALERT_REPORTS`, Celery beat, Playwright, SMTP | **Tested** - a scheduled dashboard report was created through the API, run by Celery beat and worker, screenshotted with Chromium and delivered to Mailpit as an e-mail with a PNG. Alerts on SQL conditions, Slack, PDF and CSV not exercised | Med: demo to Mailpit | V `superset/config.py:833`; `superset/reports/models.py:67-90` |
| Dynamic executor, report tabs | EXPERIMENTAL | `ALERT_REPORT_DYNAMIC_EXECUTOR`, `ALERT_REPORT_TABS` | Not enabled | Low | V R01 s6 |
| **Embedding** | | | | | |
| Embedded dashboards, SDK 0.4.0, guest tokens with RLS | STABLE | `EMBEDDED_SUPERSET`, `GUEST_TOKEN_JWT_SECRET` (must change) | **Partly tested** - embedding enabled on a dashboard, a guest token with an RLS clause minted, `/embedded/<uuid>` served, embedding removed again; rendering inside a host page with the SDK was not exercised and the guest role is the permission-less default | High: portal integration | V `superset/config.py:998-1000,3431-3438`; R03 s6 |
| Embeddable single charts | STABLE | `EMBEDDABLE_CHARTS` (True) | Not exercised | Low-Med | V `superset/config.py:987-990` |
| Embedded credential fallback | TESTING (beta) | `EMBEDDED_CREDENTIAL_FALLBACK` (master only) | Not exercised | Low | R07 s1, s4 |
| **REST API** | | | | | |
| OpenAPI REST (251 paths / 329 operations), CRUD, chart data, SQL Lab, permalinks | STABLE | Swagger UI off unless `SUPERSET_ENABLE_SWAGGER_UI`; CSRF on writes | **Tested** - login, OpenAPI spec (252 paths on this build), asset lists, chart data, SQL Lab execute, assets export, RLS list, guest token, report create/delete; anonymous calls get 401 | High: integration surface | V `docs/static/resources/openapi.json`; `superset/config.py:529-537` |
| Bearer API keys (`sst_...`) | EXPERIMENTAL | `FAB_API_KEY_ENABLED` (config + flag) | Not enabled | Med: service identity | V `superset/config.py:758-761,2433-2438` |
| Keycloak access token as REST bearer | NOT AVAILABLE | needs custom `request_loader` | Not available (confirmed gap; not built) | Med: would need own code | V `superset/security/manager.py:2462-2471`; R02 s5 |
| **MCP server** | | | | | |
| MCP service (`superset mcp run`, 83 tools, 6 resources, 2 prompts) | TESTING (beta) | separate process, `fastmcp` extra, no flag | **Tested** - initialize, tools/list (81 tools for an Admin identity), list_dashboards, list_databases, execute_sql and list_charts over streamable HTTP | High: AI-client story | V `superset/mcp_service/app.py`, `server.py:1115-1288`; R03 s1, s3 |
| Dev identity (no auth) | STABLE (local dev only) | `MCP_DEV_USERNAME` | Not used. The first version of the demo ran this way; a review showed the port is reachable from other containers on the host, so it was replaced | Med: demo only, not production | V `auth.py:922-929`; D `mcp-server.mdx:516-530` |
| JWT auth with Keycloak | TESTING (beta) | `MCP_AUTH_ENABLED`, `MCP_JWKS_URI`, `MCP_JWT_AUDIENCE` (mandatory) | **Partly tested** - MCP JWT auth is on with locally minted HS256 tokens: no/forged token gets 401, and a token for a tenant user sees only that tenant's dashboards and rows. Keycloak-issued RS256 tokens are configured as an option but not tested | High: per-user MCP | V `mcp_config.py:638-688`; R03 s2 |
| FAB API key and embedded-guest auth for MCP | EXPERIMENTAL (keys); TESTING (beta) (guest) | `MCP_API_KEY_ENABLED`, `MCP_EMBEDDED_GUEST_AUTH_ENABLED` | Not enabled | Low-Med | V `mcp_config.py:604-622,727-814`; R03 s2 |
| **AI integrations** | | | | | |
| Built-in LLM, text-to-SQL, assistant, embeddings | NOT AVAILABLE | none | Not available in Superset | n/a: do not claim | V git grep (R03 s7) |
| Chat UI contribution point (SIP-214) | EXPERIMENTAL | `ENABLE_EXTENSIONS`; no chat extension ships | Not enabled | Med: future host for NxtBI assistant | V `superset-frontend/packages/superset-core/src/chat/index.ts`; R03 s7 |
| **Extensions & plugins** | | | | | |
| Extensions framework (`.supx`, REST, MCP tools, semantic providers) | EXPERIMENTAL | `ENABLE_EXTENSIONS`, `LOCAL_EXTENSIONS`, `EXTENSIONS_PATH`; packages 0.1.0 Alpha | Not enabled | Med: backend-only hello is feasible | V `superset/config.py:786-788,3732-3744`; R04 s1 |
| UI contributions | EXPERIMENTAL | SQL Lab scope only; no chart/dashboard/Explore/nav points | Not enabled | Low | V `superset-frontend/src/SqlLab/contributions.ts:42-48` |
| Classic hooks (`BLUEPRINTS`, `FLASK_APP_MUTATOR`, `CUSTOM_SECURITY_MANAGER`, mutators, event logger) | STABLE | config hooks | **Tested** - CUSTOM_SECURITY_MANAGER (custom OAuth view and manager), EXTRA_CATEGORICAL_COLOR_SCHEMES, THEME_*, FEATURE_FLAGS; the whole demo is config-only. Other hooks not used | High: no-fork customisation | V R04 s2 table (`config.py` lines cited there) |
| Custom viz plugin | NOT AVAILABLE as extension (needs frontend rebuild) | npm package in `MainPreset.ts` | Not built | Low-Med | D `docs/developer_docs/contributing/howtos.md:84-108` |
| `DYNAMIC_PLUGINS` | TESTING (beta), effectively legacy | `DYNAMIC_PLUGINS` | Not built | Low: do not use | V `superset/config.py:860-862` |
| **Theming & branding** | | | | | |
| Theme tokens, dark mode, theme admin UI, logo, favicon, fonts | STABLE | `THEME_DEFAULT`, `THEME_DARK`, `ENABLE_UI_THEME_ADMINISTRATION` | **Tested** - NxtBI logo, favicon, colours and the IBM Plex Sans Arabic font are applied (checked in the browser). The dark theme is defined but was not checked; the theme admin UI is switched off on purpose | High: brand without fork | V `superset/config.py:1245-1377`; R05 s1 |
| Custom colour schemes | STABLE (untagged) | `EXTRA_CATEGORICAL_COLOR_SCHEMES` | **Tested** - the nxtbiColors categorical scheme is registered and used by all three dashboards | Med | V `superset/config.py:1237,1380` |
| **i18n / Arabic / RTL** | | | | | |
| Language picker, Arabic translation | STABLE (untagged); ar catalogue 54.2% non-fuzzy | `LANGUAGES`, `BUILD_TRANSLATIONS=true` build arg | **Tested** - language picker with English and Arabic; the Arabic pack is served (5,941 entries) and menus, buttons and pivot totals render in Arabic after switching | High but partial | V `superset/config.py:590-624`; `Dockerfile:32,131`; R05 s4 |
| RTL layout | NOT AVAILABLE | none | **Confirmed absent** - the document direction stays ltr under the Arabic locale; see I18N-RTL.md | High need, no support | V R05 s5; upstream apache/superset#25258 |
| **AuthN (OIDC / Keycloak)** | | | | | |
| Keycloak OIDC login (PKCE, group to role mapping) | STABLE (official recipe); NxtBI split-hostname + RP logout is own code | `AUTH_TYPE=AUTH_OAUTH`, `CUSTOM_SECURITY_MANAGER`; needs `Authlib` added to image | **Tested** - five users through the full code flow over HTTP and two through the Keycloak UI in Chromium: PKCE S256, group to role mapping, deny by default for a user without groups, wrong password rejected. Revoking roles when a user loses all groups is implemented but not exercised | High: SSO | D `docs/admin_docs/security/oauth.mdx:107-307`; V `requirements/development.txt:68-69`; R02 s1, s6 |
| Keycloak RP-initiated logout | EXPERIMENTAL (own code) | custom `AuthOAuthView.logout` | **Tested** - RP-initiated logout with id_token_hint ends the Superset session and the Keycloak SSO session | Med | R02 s6 (not executed) |
| Local DB-password API login under OAuth | STABLE | `POST /api/v1/security/login` works for local users | **Tested** - works only with AUTH_API_LOGIN_ALLOW_MULTIPLE_PROVIDERS = True (FAB 5.3.0 rejects it otherwise; the research had this wrong) | Med: change default admin | V FAB `security/api.py:101-103`; R02 s5 |
| **AuthZ (roles, RLS, subjects, viewers)** | | | | | |
| Roles (Admin, Alpha, Gamma, sql_lab, Public, custom) and dataset/schema perms | STABLE | role mapping | **Tested** - custom nxt_org_* roles carry the dataset grants; the other organisation's datasets return 403 and its dashboards are not listed | High | V `superset/security/manager.py:3718-3738,3835-3954` |
| Row-level security (Regular/Base, group keys, subject-scoped) | STABLE | REST `/api/v1/rowlevelsecurity/` | **Tested** - one Regular rule per organisation plus a Base deny rule; verified through the chart API, SQL Lab, MCP and the browser | High: tenant data split | V `security/manager.py:6295-6365`; R02 s4 |
| Subjects, FAB groups, dashboard viewers | TESTING (beta) | `ENABLE_VIEWERS`, `ASSIGN_CREATOR_GROUPS_AS_VIEWERS`, `AUTH_GROUPS_SYNC_AT_LOGIN` | Not used (roles are mapped from Keycloak groups instead) | Med: per-dashboard access | V `superset/config.py:954-956`; `superset/subjects/hooks.py:47-82` |
| Guest-token RLS | STABLE | `EMBEDDED_SUPERSET` | **Partly tested** - a guest token carrying an RLS clause was minted; its enforcement in an embedded view was not exercised | High | V `superset/config.py:3432-3475` |
| **Multi-tenancy** | | | | | |
| Workspaces / organisations / per-tenant metadata isolation | NOT AVAILABLE | none; hooks `DB_CONNECTION_MUTATOR`, `SQL_QUERY_MUTATOR`, `GET_FEATURE_FLAGS_FUNC` | **Partly tested** - row and dataset isolation by role and RLS inside one instance is demonstrated; the limits below still apply | High need, emulate with roles + RLS | R04 s5 |
| Sub-path deployment | STABLE (untagged) | `SUPERSET_APP_ROOT` | Not exercised | Low-Med | V `superset/app.py:59-94` |
| **Assets as code / versioning** | | | | | |
| YAML bundle export/import (CLI + `/api/v1/assets/*`) | STABLE | none | **Tested** - a 42-file YAML bundle is generated and imported with overwrite on every start (idempotent, stable UUIDs); the export API returns a ZIP | High: reproducible demo | V `superset/importexport/api.py:53-223`; `superset/cli/importexport.py:36-419` |
| Version history, soft delete, recently archived | TESTING (beta) | `VERSION_HISTORY`, `SOFT_DELETE` (default True) | On by default; not exercised | Med: enterprise recovery | V `superset/config.py:773,820` |
| Git sync | NOT AVAILABLE | none | Not available in Superset | n/a: use export + CI | V R04 s4 |
| **Operations** | | | | | |
| Docker default image (psycopg2, mysqlclient, fastmcp, Chromium); `-lean` minimal | STABLE (untagged) | Dockerfile target `superset` | **Tested** - built from the fork's own Dockerfile (target superset, BUILD_TRANSLATIONS=true), 4.76 GB | High | V `Dockerfile:338-371`; R01 s1 |
| Celery worker + beat on Redis; websocket optional | STABLE (untagged) | `CELERY_CONFIG`, `WEBSOCKET_ENABLE` | **Tested** - exercised by async SQL Lab and by the scheduled report | High | V `superset/config.py:2107-2198`; R01 s4 |
| Health endpoint, healthchecks | STABLE (untagged) | `GET /health` | **Tested** - /health on the web tier and on the MCP service; compose healthchecks gate start-up | Med | V `superset/views/health.py:26-33` |

## Worth adopting for NxtBI (prioritised, max 12)

| # | Item | Verdict | Main caveat |
|---|---|---|---|
| 1 | Theme tokens + theme admin (brand, fonts, dark) | STABLE: adopt now | `ENABLE_UI_THEME_ADMINISTRATION=True` lets a DB theme override config; Arabic needs a font |
| 2 | Keycloak OIDC with group to role mapping | STABLE recipe, own code for split hostnames | Authlib must be added to the image; use `SESSION_SERVER_SIDE=True` (#45587) |
| 3 | RLS + roles for tenant data split | STABLE: adopt | Datasets only; Alpha/Admin can bypass; SQL Lab bypass unless `RLS_IN_SQLLAB` |
| 4 | Assets as code (YAML ZIP via REST/CLI) | STABLE: adopt | No diff, no delete of absent assets; RLS, roles, alerts not in bundle |
| 5 | Embedded SDK + guest tokens with RLS | STABLE: adopt | Replace `GUEST_TOKEN_JWT_SECRET`; allowed domains/CSP |
| 6 | Native semantic layer (metrics, calculated columns, certification) | STABLE: adopt | Per-dataset, not a shared metric store |
| 7 | MCP server with Keycloak JWT | TESTING (beta): optional demo | Audience mapper, `superset:read/write` scopes, fixed issuer; fast-moving |
| 8 | Dashboard native filters, cross-filters, drill-by | STABLE: adopt | Emitter support varies by chart type |
| 9 | Alerts & Reports to Mailpit | TESTING (beta): adopt in demo | Needs worker, beat, Chromium; dry run on by default in docker config |
| 10 | Soft delete + version history | TESTING (beta): keep on | Retention and beat purge tasks |
| 11 | Cube Core via Postgres-wire SQL API | Superset side STABLE: prototype | Cube behaviour with Superset SQL UNVERIFIED |
| 12 | Backend-only extension ("hello NxtBI") | EXPERIMENTAL: prototype only | SDK 0.x Alpha, CLI needs npm, no sandbox |

## Do not rely on yet

- `SEMANTIC_LAYERS` provider path (EXPERIMENTAL, "unreleased" SDK, breaking changes between commits).
- Extension UI contributions and chat panel (EXPERIMENTAL; SQL Lab scope only; no chat ships).
- RTL layout (NOT AVAILABLE) and full Arabic UI (54.2% non-fuzzy).
- FAB API keys and MCP API keys (EXPERIMENTAL); MCP dev-user mode as production auth.
- AG Grid table, `pop_kpi`, Matrixify, dataset folders, mobile mode (EXPERIMENTAL).
- Global async queries (TESTING (beta), re-platformed, leave off for the demo).
- Any claim of a native AI assistant, text-to-SQL, official Python SDK or Git sync (NOT AVAILABLE).
- `DRILL_TO_DETAIL` (DEPRECATED) and `DYNAMIC_PLUGINS` (legacy).

## Multi-tenancy limitations

- There are no workspaces or organisations: one metadata DB, one role namespace, instance-global user and role lists (R02 s4, R04 s5).
- RLS protects datasets, not tables: anyone with dataset write plus database access (Alpha, Admin) can build an unfiltered dataset.
- SQL Lab bypasses RLS unless `RLS_IN_SQLLAB` (TESTING (beta), described as possibly allowing bypass), so tenant roles must only hold org-private schema access.
- Role changes from Keycloak apply at next login only (no back-channel logout or introspection).
- Dashboard viewers (`ENABLE_VIEWERS`) are TESTING (beta) and change access semantics.
- A new tenant needs config + role + RLS rule. Hard isolation means one deployment (metadata DB + cache prefix) per tenant, optionally under different app roots.

## Release and maturity context

| Version | Date (git) | Headline | Source |
|---|---|---|---|
| 5.0.0 | final 2025-06-18 | Ant Design 5, SQL Lab refresh, Slack V2, legacy charts migrated | R07 s2 (D: Preset blog) |
| 6.0.0 | final 2025-12-04 | Theming system, URL prefix, dataset folders, groups, AG Grid (flagged), FAB 5 | R07 s2 |
| 6.1.0 | final 2026-05-01 | Extensions, MCP "early foundation", Global Task Framework, Parquet examples | R07 s2 |
| 7.0.0rc1 / rc2 | 2026-10-13 / 2026-10-16 | Subjects, SQLAlchemy 2, Flask 3, Ant Design 6, soft delete, semantic layers, batteries-included image | R07 s2 |
| master `f3f3d10d5c` | 2026-11-16 | rc2 + 1489 commits (SIP-209, forgot-password, OAuth cookie fix #45593) | R07 s1 |

Breaking changes relevant to a fresh install (R07 s3): Python >= 3.11, Node ^24.16.0, FAB 5.3.0, SQLAlchemy 2.0.55; Selenium removed (Playwright only); GAQ keys removed and `/api/v1/async_event/` gone; `owners` became `editors`, dashboard `roles` became `viewers`, RLS `roles` became `subjects`; `APP_NAME` no longer sets branding, `CUSTOM_FONT_URLS` removed; Ant Design 6 renames `.ant-*` classes; prod refuses default `SECRET_KEY` and `GUEST_TOKEN_JWT_SECRET`; default image is batteries-included, minimal is `-lean`; password complexity on; Swagger UI off; `MCP_JWT_AUDIENCE` mandatory.

Known open or recent problems (R07 s5): #45587 OAuth `mismatching_state` (fixed on master by #45593, not in rc2; workaround `SESSION_SERVER_SIDE=True`); #45632 admin list search only first field (open); #42568 extensions CLI bundle resolves stale PyPI core (open); #39682 embedding after 6.0 upgrade (open); #45937 ADBC dependency failures on source installs (open). Search coverage is incomplete (UNVERIFIED after ~2026-11-02).

Fallback recommendation (R07 s6): master is risky for reproducibility, so pin the SHA and keep the built image. If it misbehaves, use `apache/superset:7.0.0rc2` (loses SIP-209, #45593 fix, newest MCP tools), then `6.1.0` (minimal image; loses Subjects, soft delete, SQLAlchemy 2, semantic layers). Never run `docker compose down -v` on the demo stack (#45731).

## Demo column legend

| Wording | Meaning |
|---|---|
| **Tested** | An automated check in `nxtbi/scripts/smoke_test.py` or `nxtbi/scripts/browser_check.py` passed against the running stack. |
| **Partly tested** | Part of the capability was checked; the sentence says which part was not. |
| Not exercised / On by default | Available in this build, never run in the demo. No claim that it works. |
| Not enabled / Not used / Not built | Deliberately left off (usually because the flag is experimental) or outside the demo scope. |
| Not available | Superset does not ship it. |
