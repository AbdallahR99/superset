# NxtBI Superset demo - test results

Generated 2026-11-17 08:01 UTC by `nxtbi/scripts/test_report.py` from the last runs of `smoke_test.py` and `browser_check.py`. Superset source: fork commit `f3f3d10d5c` (branch `nxtbi-demo`).

Every row is a check that was executed against the running stack. Nothing here is inferred.

| Suite | Passed | Failed |
|---|---|---|
| HTTP smoke test (`smoke_test.py`) | 48 | 0 |
| Browser check (`browser_check.py`, Chromium) | 15 | 0 |

## Stack, branding and language packs

| Result | Check | Observed |
|---|---|---|
| PASS | superset /health | 200 OK |
| PASS | mcp /health | {"status": "ok"} |
| PASS | NxtBI logo served | 200, 630 bytes |
| PASS | NxtBI favicon served | 200, 383 bytes |
| PASS | Arabic language pack | 5941 translated UI strings in the Arabic pack |
| PASS | theme + language bootstrap | brand name, logo, font, primary colour, palette and ar language present in bootstrap data |
| PASS | login page is SSO-only | provider keycloak offered; /register/ -> 404 |

## Keycloak single sign-on

| Result | Check | Observed |
|---|---|---|
| PASS | authorize redirect (PKCE, scopes) | 302 to localhost:8180/realms/nxtbi/protocol/openid-connect/auth with PKCE S256, nonce, state, scope='openid groups' |
| PASS | login + role mapping: planning.admin@nxtbi.local | logged in via Keycloak; roles = ['Gamma', 'nxt_org_ministry-of-planning', 'sql_lab'] |
| PASS | login + role mapping: planning.editor@nxtbi.local | logged in via Keycloak; roles = ['Gamma', 'nxt_org_ministry-of-planning'] |
| PASS | login + role mapping: stats.admin@nxtbi.local | logged in via Keycloak; roles = ['Gamma', 'nxt_org_statistics-bureau', 'sql_lab'] |
| PASS | login + role mapping: stats.editor@nxtbi.local | logged in via Keycloak; roles = ['Gamma', 'nxt_org_statistics-bureau'] |
| PASS | login + role mapping: superset.admin@nxtbi.local | logged in via Keycloak; roles = ['Admin'] |
| PASS | deny by default: unaffiliated@nxtbi.local | authenticated at Keycloak but refused by Superset (landed on /login/, /api/v1/me/ 401) |
| PASS | wrong password | stays on the Keycloak form; no Superset session |
| PASS | logout (Superset + Keycloak session) | RP-initiated logout with id_token_hint; Superset session and Keycloak SSO session both ended |

## Tenant isolation (roles, row level security, SQL Lab)

| Result | Check | Observed |
|---|---|---|
| PASS | Admin sees both organisations | service_requests rows by org: {'ministry-of-planning': 28525, 'statistics-bureau': 40703} |
| PASS | planning admin sees only planning rows | service_requests rows by org: {'ministry-of-planning': 28525} |
| PASS | stats admin sees only statistics rows | service_requests rows by org: {'statistics-bureau': 40703} |
| PASS | stats editor sees only statistics rows | service_requests rows by org: {'statistics-bureau': 40703} |
| PASS | datasets of the other organisation are inaccessible | cross-tenant dataset access refused (403/403) and hidden from the dataset list |
| PASS | dashboard visibility per organisation | planning: ['nxtbi-budget-execution', 'nxtbi-service-operations']; stats: ['nxtbi-service-operations', 'nxtbi-trade-population']; admin: all 3 |
| PASS | SQL Lab: RLS applies to ad-hoc SQL | RLS_IN_SQLLAB applied to raw SQL: {'ministry-of-planning': 28525} |
| PASS | SQL Lab: empty-catalog RLS bypass is blocked | request with an empty catalog is refused (HTTP 400); the upstream bypass is closed |
| PASS | thumbnails are rendered per user | thumbnail digests differ for planning, statistics and admin users (rendered per user, not as a fixed account) |
| PASS | SQL Lab: table and role restrictions | other tenant's table refused (TABLE_SECURITY_ACCESS_ERROR, HTTP 500); user without the sql_lab role refused (HTTP 403) |
| PASS | SQL Lab as Admin (Arabic data round-trip) | 3 rows, Arabic values intact: ['البنية التحتية', 'الصحة', 'التعليم'] |

## REST API

| Result | Check | Observed |
|---|---|---|
| PASS | POST /api/v1/security/login (provider db) | JWT issued for local service account nxtbi-service |
| PASS | OpenAPI spec | OpenAPI 3.0.2: 252 paths |
| PASS | unauthenticated access refused | anonymous requests 401; default admin/admin credentials rejected |
| PASS | asset inventory | {'dashboard': 12, 'chart': 136, 'dataset': 25, 'database': 2} |
| PASS | POST /api/v1/chart/data (saved metric) | headless query on saved metric execution_rate: top Digital Government = 0.735 |
| PASS | query result caching | second identical query served from the Redis data cache (is_cached=true) |
| PASS | GET /api/v1/assets/export/ (assets as code) | ZIP bundle of all assets, 651 KiB |
| PASS | POST /api/v1/security/guest_token/ | embedding enabled, guest token minted with an RLS clause, embedded page served, embedding removed again (rendering inside a host application with the embedded SDK not exercised) |
| PASS | RLS rules present | ['NxtBI org isolation: deny by default', 'NxtBI org isolation: ministry-of-planning', 'NxtBI org isolation: statistics-bureau'] |
| PASS | SQL Lab async (Celery + results backend) | async query ran on the Celery worker; results backend returned 2 rows |

## MCP server

| Result | Check | Observed |
|---|---|---|
| PASS | unauthenticated and forged requests are refused | no token -> 401; token signed with a wrong secret -> 401 |
| PASS | initialize (streamable HTTP) | server NxtBI MCP Server 4.2.0, protocol 2025-06-18 |
| PASS | tools/list | 81 tools, e.g. ['add_chart_to_existing_dashboard', 'apply_dashboard_filters', 'create_dataset', 'create_dataset_column', 'create_dataset_metric', 'create_theme'] |
| PASS | tools/call list_dashboards | all three NxtBI dashboards returned through MCP |
| PASS | tools/call execute_sql | SQL executed through MCP, Arabic result values returned |
| PASS | tools/call list_charts | list_charts returned 4 chart records |
| PASS | per-user identity, RBAC and RLS through MCP | token for planning.admin: MCP reports that user (no Admin role), lists only the planning dashboards, and execute_sql returns only planning rows |

## Dashboards and charts

| Result | Check | Observed |
|---|---|---|
| PASS | dashboards imported (charts, native filters, cross-filters) | nxtbi-budget-execution: 11 charts, 5 native filters; nxtbi-trade-population: 11 charts, 5 native filters; nxtbi-service-operations: 11 charts, 5 native filters |
| PASS | every chart opens in Explore (form_data round-trip) | 33 charts accepted by Explore; viz types: ['big_number', 'big_number_total', 'box_plot', 'echarts_area', 'echarts_timeseries_bar', 'echarts_timeseries_smooth', 'funnel', 'gauge_chart', 'heatmap_v2', 'mixed_timeseries', 'pie', 'pivot_table_v2', 'sankey_v2', 'table', 'treemap_v2'] |
| PASS | bundled Superset examples loaded | 9 Superset example dashboards available, e.g. ['Slack Dashboard', 'FCC New Coder Survey 2018', 'Misc Charts', 'USA Births Names'] |

## Alerts and reports

| Result | Check | Observed |
|---|---|---|
| PASS | scheduled dashboard report by e-mail | e-mail '[NxtBI]  NxtBI smoke report 1794902374: NxtBI · Budget Execution \| تنفيذ الميزانية' delivered with a 290 KiB PNG screenshot |

## Browser check (real Chromium, Keycloak UI login)

| Result | Check | Observed |
|---|---|---|
| PASS | login page: NxtBI branding, Keycloak button, no password form | title='NxtBI'; password inputs=0 |
| PASS | SSO login through the Keycloak UI (platform admin) | http://localhost:8088/welcome/ |
| PASS | theme applied (font, logo) | font='"IBM Plex Sans Arabic", "Noto Sans Arabic", Inter, "Segoe UI'; logo=http://localhost:8088/static/nxtbi/nxtbi-logo.svg |
| PASS | dashboard renders: nxtbi-budget-execution | {"title": "NxtBI · Budget Execution \| تنفيذ الميزانية", "charts_drawn": 11, "data_calls": 15, "failed_calls": 0, "empty_results": 0, "error_alerts": 0} |
| PASS | dashboard renders: nxtbi-trade-population | {"title": "NxtBI · Trade & Population \| التجارة والسكان", "charts_drawn": 6, "data_calls": 9, "failed_calls": 0, "empty_results": 0, "error_alerts": 0} |
| PASS | dashboard tab switch (Population) | second tab rendered without error alerts |
| PASS | dashboard renders: nxtbi-service-operations | {"title": "NxtBI · Service Operations \| عمليات الخدمات", "charts_drawn": 11, "data_calls": 15, "failed_calls": 0, "empty_results": 0, "error_alerts": 0} |
| PASS | native filter changes the dashboard (Sector = Health) | first KPI before='6.79B\nAllocated \| المخصص' after='1.07B\nAllocated \| المخصص' |
| PASS | Explore opens a saved chart | chart id 113; url http://localhost:8088/explore/?form_data_key=BBFGGsDPsT0PmvveIGLg4Q&sl |
| PASS | SQL Lab opens with an editor tab | http://localhost:8088/sqllab/ |
| PASS | Arabic UI strings after switching language | 37 Arabic characters in the navigation; layout direction = ltr |
| PASS | logout returns to the login page | http://localhost:8088/login/ |
| PASS | second SSO login needs credentials again (Keycloak session ended) | http://localhost:8088/welcome/ |
| PASS | RLS in the UI: planning user sees only its organisation | {"title": "NxtBI · Service Operations \| عمليات الخدمات", "charts_drawn": 11, "data_calls": 15, "failed_calls": 0, "empty_results": 0, "error_alerts": 0, "mentions_planning": true, "mentions_statistics": false} |
| PASS | other organisation's dashboard is not reachable | url=http://localhost:8088/dashboard/nxtbi-trade-population/ title='404: Not found \| Superset' |

Browser console errors during the run: 6 (Failed to load resource: the server responded with a status of 401 (UNAUTHORIZED); Failed to load resource: the server responded with a status of 403 (FORBIDDEN); Failed to load resource: the server responded with a status of 404 (NOT FOUND)).
Screenshots: `nxtbi/docs/screenshots/`.
