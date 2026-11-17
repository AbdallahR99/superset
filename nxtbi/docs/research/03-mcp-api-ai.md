# 03 - MCP server, headless REST API, SDKs, AI integrations

Scope: fork == apache/superset master @ f3f3d10d5c (post 7.0.0rc2, `0.0.0-dev`). Read-only research; nothing was run.
Labels: **V** = VERIFIED-IN-CODE, **D** = DOCS-CLAIMED, **U** = UNVERIFIED. Paths are repo-relative.

## 1. MCP service architecture

| Topic | Finding | Evidence |
|---|---|---|
| Framework | FastMCP (`from fastmcp import ...`), Starlette/uvicorn ASGI process, separate from the Flask web server | V `superset/mcp_service/app.py:744`, `server.py:1272-1288` |
| Pin / extra | pip extra `fastmcp`: `fastmcp>=4.1.4,<5.0`, `mcp>=1.29.1,<3.0`, `httpx`, `tiktoken`, `joserfc`, `python-multipart`. Dev lock: `fastmcp==4.1.6`, `mcp==2.3.0` | V `pyproject.toml:204-222`, `requirements/development.txt:288,616` |
| Pin drift | 6.1.0: `fastmcp>=3.1.0,<4.0`; 7.0.0rc2: `>=3.4.7,<4.0`; master: 4.x. Major bump between rc2 and this commit | V `git show 6.1.0:pyproject.toml` L147, `7.0.0rc2` L199 |
| Image | Dockerfile target `superset` (default published image) installs `.[postgres,mysql,fastmcp]` + Playwright Chromium; `lean` has no fastmcp; `dev` gets it via `requirements/development.txt` | V `Dockerfile:338-369,376-400`, `UPDATING.md:1222-1232` |
| Start (supported) | `superset mcp run --host 127.0.0.1 --port 5008 [--debug]` -> `run_server()`; streamable-http only | V `superset/cli/mcp.py:28-37`, `server.py:1115-1288` |
| Start (compose helper) | `/app/docker/docker-bootstrap.sh mcp` = `superset mcp run --host 0.0.0.0 --port ${MCP_PORT:-5008} --debug`. No compose file defines an MCP service | V `docker/docker-bootstrap.sh:102-105`; grep of `docker-compose*.yml` = no hits |
| Start (stdio / other) | `python -m superset.mcp_service`; env `FASTMCP_TRANSPORT` (default `stdio`; `streamable-http`, else passed to `mcp.run(transport=...)` e.g. `sse`), `FASTMCP_HOST` (127.0.0.1), `FASTMCP_PORT` (5008) | V `superset/mcp_service/__main__.py:102-215` |
| Endpoint | `http://<host>:5008/mcp` (FastMCP `streamable_http_path`); browser GET with `Accept: text/html` returns a hello page with a config snippet | V `jwt_verifier.py:300-342`; D `docs/admin_docs/configuration/mcp-server.mdx:447` |
| Health | `GET /health` -> `{"status":"ok"}`, unauthenticated, only on `superset mcp run` path | V `server.py:1100-1112,1236` |
| App/config sharing | Standalone process calls `superset.app.create_app()` -> same `superset_config.py`, same metadata DB, same `SECRET_KEY`, same security manager. Overlays `get_mcp_config()` (app config wins) | V `flask_singleton.py:78-110`, `mcp_config.py:980-1012` |
| Needs web server? | No for tool execution (direct DAO/command access). Yes for: clickable links (built from `WEBDRIVER_BASEURL_USER_FRIENDLY`), PNG previews (Playwright loads `Superset.slice` from web app), and DB migrations/init must have run | V `utils/url_utils.py:41-56`, `chart/tool/get_chart_preview.py:1260-1300` |
| Sessions | `MCP_STATELESS_HTTP=True` default: each POST is self-contained, no `Mcp-Session-Id` affinity. `False` = stateful sessions | V `mcp_config.py:130-146` |
| Tool discovery | Default "compatibility" mode: `tools/list` returns only `health_check`, `get_instance_info`, `search_tools`, `call_tool`. Set `MCP_TOOL_SEARCH_CONFIG={"enabled": False}` for native full listing. All tools callable by name in both modes | V `mcp_config.py:564-577`; D `mcp-server.mdx:1085-1096` |
| Middleware | ToolResultCompatibility -> RBACToolVisibility -> Logging -> GlobalErrorHandler -> ResponseSizeGuard (50k bytes default, on) -> optional ResponseCaching (off) | V `server.py:1020-1043,1205-1210`, `mcp_config.py:502-514,396-404` |
| Feature flag | None gates MCP itself. `GLOBAL_TASK_FRAMEWORK` off removes `list_tasks`/`get_task_info` at startup | V `app.py:1037-1057`; `superset/config.py` has no MCP flag |

### Config keys (all in `superset_config.py`)

| Key | Default | Notes | Evidence |
|---|---|---|---|
| `MCP_DEV_USERNAME` | unset | Dev/no-auth identity; user must exist. Refused together with `MCP_AUTH_ENABLED=True` | V `auth.py:922-929`, `mcp_config.py:648-653` |
| `MCP_AUTH_ENABLED` | False | JWT bearer verification | V `mcp_config.py:638` |
| `MCP_JWT_ALGORITHM` | `RS256` | HS256/384/512 require `MCP_JWT_SECRET` and forbid JWKS/public key | V `mcp_config.py:886-928` |
| `MCP_JWKS_URI` / `MCP_JWT_PUBLIC_KEY` / `MCP_JWT_SECRET` | None | One is mandatory when auth enabled (fail closed) | V `mcp_config.py:674-688` |
| `MCP_JWT_ISSUER` | None | str or list. List with >1 issuer requires `MCP_USER_RESOLVER` or startup fails | V `mcp_config.py:750-794`, `jwt_verifier.py:672-689` |
| `MCP_JWT_AUDIENCE` | None | **Mandatory** when `MCP_AUTH_ENABLED` (docs say optional) | V `mcp_config.py:662-667` |
| `MCP_REQUIRED_SCOPES` | `[]` | Scopes every token must carry | V `mcp_config.py:883` |
| `MCP_USER_RESOLVER` | `default_user_resolver` | `(app, access_token) -> username` | V `auth.py:750`, `mcp_config.py:940-972` |
| `MCP_AUTH_FACTORY` | None | `(flask_app) -> provider`; overrides everything incl. guest/API-key wiring | V `server.py:953-984` |
| `MCP_JWT_DEBUG_ERRORS` | False | Detailed server-side JWT failure logs | V `mcp_config.py:240-248` |
| `MCP_API_KEY_ENABLED` | None -> falls back to `FAB_API_KEY_ENABLED` | Accept FAB API keys (`sst_` prefix, `FAB_API_KEY_PREFIXES`) as Bearer | V `mcp_config.py:604-622,838-840` |
| `MCP_EMBEDDED_GUEST_AUTH_ENABLED` | False | Guest tokens as Bearer; needs `EMBEDDED_SUPERSET` + non-default `GUEST_TOKEN_JWT_SECRET` | V `mcp_config.py:727-814` |
| `MCP_GUEST_ALLOWED_TOOLS` / `MCP_RESTRICTED_TOOL_POLICY` | 8 read tools / None | Default-deny allow-list for guests | V `mcp_config.py:272-287` |
| `MCP_RBAC_ENABLED` | True | FAB permission check per tool | V `mcp_config.py:150`, `auth.py:439-523` |
| `MCP_DISABLED_TOOLS` | `set()` | Remove tools at startup | V `mcp_config.py:163` |
| `MCP_DATASET_ROLE_ALLOWLIST` | None | Optional role -> dataset UUID routing scope | V `mcp_config.py:73-100` |
| `MCP_STRUCTURED_OUTPUT_ENABLED` | False | `outputSchema`/`structuredContent` opt-in | V `mcp_config.py:165-170` |
| `MCP_SERVICE_URL` | None | Base URL of MCP itself for generated links; fallback `http://localhost:5008` | V `utils/url_utils.py:77-104` |
| `MCP_CACHE_CONFIG`, `MCP_STORE_CONFIG`, `MCP_RESPONSE_SIZE_CONFIG`, `MCP_TOOL_SEARCH_CONFIG`, `MCP_NATIVE_TOOL_LIST_CONFIG`, `MCP_TOOL_WORKERS`, `MCP_METADATA_TOOL_WORKERS`, `MCP_HELLO_PAGE`, `MCP_ERROR_HOOK`, `MCP_BUG_REPORT_CONTACT`, `MCP_DISABLED_CHART_PLUGINS` | see file | Tuning | V `mcp_config.py:71-601` |
| `MCP_SERVICE_HOST` / `MCP_SERVICE_PORT` | - | **Docs only; no code reads them.** Bind via CLI flags | D `mcp-server.mdx:839-840,958-959`; V grep: only `MCP_SERVICE_URL` used |

## 2. MCP auth, identity, RBAC/RLS

Identity resolution order per tool call (V `auth.py:889-958`): (1) JWT/guest token from FastMCP context, (2) FAB API key, (3) `MCP_DEV_USERNAME`, (4) `g.user` set by external middleware. No source -> "Authentication required".

| Mode | Config | Runs as | Status |
|---|---|---|---|
| Dev / no auth | `MCP_DEV_USERNAME="admin"`; no bearer needed | That one Superset user for every caller | STABLE for local dev, D "never in production" (`mcp-server.mdx:516-530`) |
| API key | `FAB_API_KEY_ENABLED=True` + `FEATURE_FLAGS["FAB_API_KEY_ENABLED"]=True`; key created in UI *User Info -> API Keys*; `Authorization: Bearer sst_...` | Key owner; optional per-key scopes | EXPERIMENTAL: flag `@lifecycle: development` (V `config.py:760-761,2437-2438`; D `docs/admin_docs/security/security.mdx:522-570`) |
| JWT (IdP) | `MCP_AUTH_ENABLED` + keys + audience | User whose `username` (then email if value contains `@`) matches resolver output; must pre-exist in `ab_user`, no auto-provisioning | BETA-TESTING (V `auth.py:750-775`) |
| Embedded guest | `MCP_EMBEDDED_GUEST_AUTH_ENABLED` + `EMBEDDED_SUPERSET` | `GuestUser` limited to 8 read tools and token dashboards/RLS | BETA-TESTING (V `auth.py:691-716`) |

Enforcement (V): `mcp_auth_hook` sets `g.user` per call and checks `security_manager.can_access("can_<method>", <Class>)` (`auth.py:1286`, `481-483`); object access/RLS come from the same DAOs/commands/`raise_for_access` as the web app (D `PRODUCTION.md:32`). `tools/list` is RBAC-filtered. `execute_sql` needs `can_execute_sql_query on SQLLab`; RLS inside SQL Lab SQL only with `RLS_IN_SQLLAB` (testing flag, `config.py:891-892`). `list_users`/`get_user_info`/`list_roles`/`get_role_info`/RLS tools are admin-only (D `app.py:168-176`).

### Keycloak JWT (realm `nxtbi`) - what is required and what breaks

```python
MCP_AUTH_ENABLED = True
MCP_JWT_ALGORITHM = "RS256"
MCP_JWKS_URI = "http://keycloak:8080/realms/nxtbi/protocol/openid-connect/certs"  # container-reachable
MCP_JWT_AUDIENCE = "nxtbi-mcp"          # mandatory; must appear in token aud
MCP_JWT_ISSUER = None                    # or a single pinned issuer string
# MCP_DEV_USERNAME must be unset
```

| Pitfall | Detail | Evidence |
|---|---|---|
| Audience | Keycloak access tokens do not carry a custom audience by default; add an Audience protocol mapper for `nxtbi-mcp` (or point `MCP_JWT_AUDIENCE` at an existing `aud` value) | V requirement `mcp_config.py:662`; U Keycloak side |
| Dynamic issuer | `iss` changes with the host used to reach Keycloak (`localhost:8080` vs `keycloak:8080`). Options: pin Keycloak hostname; leave `MCP_JWT_ISSUER=None` (issuer check skipped, signature still bound to realm JWKS); or list both issuers **plus** a `MCP_USER_RESOLVER` (mandatory for lists) | V `jwt_verifier.py:672-689`, `mcp_config.py:769-794` |
| **Scopes deny everything** | If the token advertises any scopes (Keycloak always sends `scope: "openid profile email"`), scope enforcement turns on and each tool additionally needs `superset:read`/`superset:write` or `superset:<resource>:<action>` in the token. Without them every RBAC-protected tool is denied | V `auth.py:162-235,493-503`, `superset/security/api_key_scopes.py:22-80`; scope claim is a space-separated string: `tests/unit_tests/mcp_service/test_jwt_verifier.py:987` |
| Fix for scopes | Create Keycloak client scopes literally named `superset:read` and `superset:write` and assign them to the client; or supply `MCP_AUTH_FACTORY` with a verifier that returns no scopes (U, not tested) | - |
| User mapping | Default resolver takes `preferred_username` -> `username` -> `email` -> `sub`. Superset usernames created by the Keycloak OAuth login must equal `preferred_username` (or email) | V `mcp_config.py:940-958` |
| Docs drift | Docs list `sub` first and call `iss`/`aud` optional; code differs (above) | D `mcp-server.mdx:587-608` |

## 3. Tool / resource / prompt inventory (83 tools, 6 resources, 2 prompts)

Count verified by parsing `@tool` decorators and `tests/unit_tests/mcp_service/native_tool_inventory.json` (83). One-line purposes are quoted from `app.py:125-266`. Perm = FAB class checked (`can_read` unless noted).

| Domain | Tools | Perm | Extra infra / flag |
|---|---|---|---|
| System | `health_check`, `get_instance_info` (stats + current user), `get_schema` (filterable/sortable columns per model), `find_users`, `generate_bug_report` (only unprotected tool) | none | - |
| Catalog | `get_catalog` (compact permission-filtered page of databases/datasets/charts/dashboards) | per asset class | - |
| Dashboards (18) | read: `list_dashboards`, `get_dashboard_info`, `get_dashboard_layout`, `get_dashboard_datasets`, `get_dashboard_data`, `apply_dashboard_filters` (returns permalink); write: `generate_dashboard`, `update_dashboard`, `duplicate_dashboard`, `add_chart_to_existing_dashboard`, `remove_chart_from_dashboard`, `manage_native_filters`, `manage_dashboard_markdown`, `manage_dashboard_owners`, `manage_dashboard_roles`, `manage_dashboard_certification`, `delete_dashboard`, `restore_dashboard` | Dashboard | restore/trash need `SOFT_DELETE` (testing, default True) |
| Charts (11) | read: `list_charts`, `get_chart_info`, `get_chart_data`, `get_chart_preview`, `get_chart_sql` (SQLLab perm), `get_chart_type_schema`; write: `generate_chart`, `update_chart`, `update_chart_preview`, `delete_chart`, `restore_chart` | Chart | `get_chart_preview` formats `ascii` (default), `table`, `vega_lite`, `url` need nothing; `png` needs Playwright+Chromium in the MCP container and web app reachable at `WEBDRIVER_BASEURL`, saved chart only (V `chart/schemas.py:6919-6929`, `get_chart_preview.py:1235-1300`) |
| Explore | `generate_explore_link` (interactive explore URL from a chart config) | Explore | Link host = `WEBDRIVER_BASEURL_USER_FRIENDLY` |
| Datasets (14) | read: `list_datasets`, `get_dataset_info`, `query_dataset` (metrics/dimensions/filters without a chart); write: `create_dataset`, `create_virtual_dataset`, `update_dataset`, `create/update/delete_dataset_column`, `create/update/delete_dataset_metric`, `delete_dataset`, `restore_dataset` | Dataset | - |
| Semantic layer (5) | `list_semantic_views`, `list_metrics`, `get_table`, `get_compatible_dimensions`, `get_compatible_metrics` | Dataset + data-model metadata perm | Work on built-in datasets today; external semantic views need `SEMANTIC_LAYERS` (`@lifecycle: development`, `config.py:775-776`) and a provider extension |
| SQL Lab (3+4) | `execute_sql` (`can_execute_sql_query`), `save_sql_query`, `open_sql_lab_with_context`; `list_saved_queries`, `get_saved_query_info`, `list_queries`, `get_query_info` | SQLLab / SavedQuery / Query | DB must allow SQL Lab; `SQLLAB_TIMEOUT` |
| Databases | `list_databases`, `get_database_info` | Database | - |
| Admin read-only | `list_users`, `get_user_info`, `list_roles`, `get_role_info`, `list_rls_filters`, `get_rls_filter_info` | User / Role / RLS (admin) | - |
| Reports | `list_reports`, `get_report_info` | ReportSchedule | return disabled-feature error unless `ALERT_REPORTS` (V `report/tool/list_reports.py:104`) |
| Tags / Themes / Annotations | `list_tags`, `get_tag_info`; `list_themes`, `get_theme_info`, `create_theme`; `list_annotation_layers`, `get_annotation_layer_info`, `list_layer_annotations`, `get_layer_annotation_info` | Tag / Theme / Annotation | - |
| Tasks | `list_tasks`, `get_task_info` | Task | removed unless `GLOBAL_TASK_FRAMEWORK` |
| Synthetic | `search_tools`, `call_tool` | - | only in compatibility mode |

Resources (V grep `@mcp.resource`): `instance://metadata`, `chart://configs`, `superset://schema/chart`, `superset://schema/dataset`, `superset://schema/dashboard`, `superset://schema/all`. Prompts: `quickstart`, `create_chart_guided`.

Maturity: MCP shipped in 6.1.0 (versioned docs `docs/admin_docs_versioned_docs/version-6.1.0/configuration/mcp-server.mdx`), docs carry no experimental label, but `UPDATING.md` "Next" (L25-2902) has ~40 MCP behaviour changes and the FastMCP major changed after rc2. Classification: **BETA-TESTING** overall; semantic-view, API-key, chat-extension and task pieces **EXPERIMENTAL** (development flags). `superset/mcp_service/PRODUCTION.md:22-44` still lists auth/rate-limit/metrics as "development-only" (partly stale).

## 4. Smoke tests (U: payloads follow the MCP streamable-HTTP spec and repo docs; not executed here)

Headers: `Content-Type: application/json`, `Accept: application/json, text/event-stream` (docs' curl omits `Accept`; the MCP SDK normally answers 406 without it), `MCP-Protocol-Version: 2025-06-18` after initialize, `Authorization: Bearer ...` only when auth is on. Responses arrive as SSE frames (`event: message` / `data: {json}`). With the default stateless mode no `Mcp-Session-Id` is issued; if `MCP_STATELESS_HTTP=False`, copy the `mcp-session-id` response header from `initialize` into every later request and send `notifications/initialized` first.

```bash
U=http://localhost:5008/mcp; H=(-H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream')
curl -fsS http://localhost:5008/health                      # {"status":"ok"}
curl -sS -D - "${H[@]}" -X POST $U -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"nxtbi-smoke","version":"0.1"}}}'
curl -sS "${H[@]}" -H 'MCP-Protocol-Version: 2025-06-18' -X POST $U -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'
curl -sS "${H[@]}" -H 'MCP-Protocol-Version: 2025-06-18' -X POST $U -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
curl -sS "${H[@]}" -H 'MCP-Protocol-Version: 2025-06-18' -X POST $U -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"health_check","arguments":{}}}'
curl -sS "${H[@]}" -H 'MCP-Protocol-Version: 2025-06-18' -X POST $U -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"list_dashboards","arguments":{"request":{"page":1,"page_size":5}}}}'
curl -sS "${H[@]}" -H 'MCP-Protocol-Version: 2025-06-18' -X POST $U -d '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"search_tools","arguments":{"query":"execute sql"}}}'
curl -sS "${H[@]}" -H 'MCP-Protocol-Version: 2025-06-18' -X POST $U -d '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"call_tool","arguments":{"name":"execute_sql","arguments":{"request":{"database_id":1,"sql":"SELECT 1 AS ok","limit":10}}}}}'
curl -sS "${H[@]}" -H 'MCP-Protocol-Version: 2025-06-18' -X POST $U -d '{"jsonrpc":"2.0","id":7,"method":"resources/list"}'
```

Request shape: most tools wrap arguments in `request` (V `app.py:280-288`); `health_check` takes none (`system/tool/health_check.py:46`). Append `| sed -n 's/^data: //p'` to extract JSON.

Claude Code `.mcp.json` (repo docs show `"type": "url"`, which Claude Code does not accept; `http` is required when `url` is present - https://code.claude.com/docs/en/mcp):

```json
{ "mcpServers": { "nxtbi-superset": { "type": "http", "url": "http://localhost:5008/mcp",
    "headers": { "Authorization": "Bearer ${NXTBI_MCP_TOKEN}" } } } }
```

Drop `headers` in dev mode. CLI equivalent: `claude mcp add --transport http nxtbi-superset http://localhost:5008/mcp`. Claude Desktop: `{"mcpServers":{"superset":{"url":"http://localhost:5008/mcp"}}}` or, with a token, `npx -y mcp-remote@latest http://localhost:5008/mcp --header "Authorization: Bearer <token>"` (D `mcp-server.mdx:697-728`).

## 5. Headless REST API

| Item | Finding | Evidence |
|---|---|---|
| Spec size | Static OpenAPI 3.0.2 snapshot: 251 paths / 329 operations | V `docs/static/resources/openapi.json` |
| Swagger UI | `/swagger/v1`, spec `/api/v1/_openapi`; both gated by `FAB_API_SWAGGER_UI`, default from env `SUPERSET_ENABLE_SWAGGER_UI` (false). Dev compose sets it true | V `config.py:529-537`, `docker/.env:73`; U that FAB hides the spec route when off |
| Prefix-aware variant | `FAB_API_SWAGGER_UI_SUPERSET_APP_ROOT=True` registers `SupersetOpenApi`/`SupersetSwaggerView` | V `config.py:544`, `initialization/__init__.py:520-528`, `openapi/manager.py:74-145` |
| Login | `POST /api/v1/security/login` `{"username","password","provider":"db","refresh":true}` -> `access_token`,`refresh_token`; `POST /api/v1/security/refresh` | D `docs/developer_docs/api.mdx:28-52`. U: with `AUTH_TYPE=AUTH_OAUTH` only users that have a local password (e.g. the bootstrap admin) can use provider `db` |
| API keys | `Authorization: Bearer sst_...` on every REST route when `FAB_API_KEY_ENABLED` | D `security.mdx:552-560` |
| CSRF | `WTF_CSRF_ENABLED=True` globally. Exempt: `charts.data.api.data`, `datasource.api.query`, `dashboards.api.cache_dashboard_screenshot`, `dashboards.api.export_xlsx`, `views.core.log`, datasource `samples`, SAML `acs`. Other mutating calls need `GET /api/v1/security/csrf_token/` then `X-CSRFToken` plus the returned session cookie | V `config.py:387-405`, `initialization/__init__.py:1792-1797`, `security/api.py:179-185`; U exact behaviour with bearer tokens |

High-value endpoints (all V in `openapi.json`; flag column V in code):

| Purpose | Endpoint | Notes |
|---|---|---|
| Chart data (query context) | `POST /api/v1/chart/data` | CSRF-exempt; `async_mode` opt-in only with `GLOBAL_ASYNC_QUERIES` |
| Saved chart data | `GET /api/v1/chart/{pk}/data/` | chart needs saved `query_context` |
| Semantic query by names | `POST /api/v1/datasource/{type}/{id}/query` | metrics/dimensions/filters/time_range; JSON or Arrow stream; CSRF-exempt (V `datasource/api.py:795-836`) |
| CRUD | `/api/v1/chart/`, `/dashboard/`, `/dataset/`, `/database/`, `/saved_query/`, `/tag/`, `/theme/`, `/report/`, `/rowlevelsecurity/` | CSRF for writes |
| Dashboard structure | `GET /api/v1/dashboard/{id_or_slug}`, `/charts`, `/datasets`, `/tabs` | |
| SQL | `POST /api/v1/sqllab/execute/`, `GET /api/v1/sqllab/results/`, `POST /api/v1/sqllab/estimate/`, `/format_sql/` | CSRF |
| Permalinks | `POST /api/v1/explore/permalink`, `GET /api/v1/explore/permalink/{key}`, `POST /api/v1/dashboard/{pk}/permalink`, `POST /api/v1/explore/form_data` | |
| Assets as code | `GET /api/v1/assets/export/`, `POST /api/v1/assets/import/`; per-type `/export/` and `/import/` | ZIP of YAML |
| Security admin | `/api/v1/security/users/`, `/roles/`, `/roles/{id}/permissions`, `/groups/`, `/permissions/`, `/me/`, `/me/roles/` | `FAB_ADD_SECURITY_API=True` (V `config.py:2428`) |
| Embedding | `POST /api/v1/security/guest_token/`, `GET/POST/PUT/DELETE /api/v1/dashboard/{id_or_slug}/embedded`, `GET /api/v1/embedded_dashboard/{uuid}` | `EMBEDDED_SUPERSET`; perm `can_grant_guest_token` |
| Screenshots | `/api/v1/chart/{pk}/cache_screenshot/`, `/screenshot/{digest}/`, `/thumbnail/{digest}/`, dashboard equivalents | `THUMBNAILS` / `ENABLE_DASHBOARD_SCREENSHOT_ENDPOINTS` + Celery + Chromium |
| Tasks | `/api/v1/task/...`, `GET /api/v1/task/status_changes` | `GLOBAL_TASK_FRAMEWORK` (V `initialization/__init__.py:342-345`) |
| Semantic layers | `/api/v1/semantic_layer/`, `/api/v1/semantic_view/` | registered always; feature is `development` |
| Extensions | `/api/v1/extensions/` | `ENABLE_EXTENSIONS` (development) |
| **Removed** | `/api/v1/async_event/` and `GET /api/v1/chart/data/<cache_key>` no longer exist; async chart data now polls `task/status_changes` | V `UPDATING.md:1371-1396` |

## 6. SDKs and clients

| Package | Version | What it is | Evidence |
|---|---|---|---|
| `@superset-ui/embedded-sdk` | 0.4.0 | `embedDashboard({id, supersetDomain, mountPoint, fetchGuestToken, dashboardUiConfig, iframeSandboxExtras, referrerPolicy, resolvePermalinkUrl})`; iframe on `/embedded/<uuid>`; CDN `https://unpkg.com/@superset-ui/embedded-sdk` (global `supersetEmbeddedSdk`) | V `superset-embedded-sdk/package.json:2-3`, `src/index.ts:77-204`, `README.md:35-90` |
| Embedding config | - | `FEATURE_FLAGS["EMBEDDED_SUPERSET"]=True` (`@lifecycle: stable`), `GUEST_ROLE_NAME="Public"`, `GUEST_TOKEN_JWT_SECRET` (must change), `GUEST_TOKEN_JWT_ALGO="HS256"`, `GUEST_TOKEN_JWT_EXP_SECONDS=300`, `GUEST_TOKEN_JWT_AUDIENCE`, `GUEST_TOKEN_HEADER_NAME="X-GuestToken"`; per-dashboard Allowed Domains checked against `Referer` (empty = any); `TALISMAN_CONFIG` `frame-ancestors` | V `config.py:998-1000,3431-3443`; D `docs/docs/using-superset/embedding.mdx:31,60,377` |
| Guest token body | - | `{"user":{...},"resources":[{"type":"dashboard","id":"<embedded uuid>"}],"rls":[{"clause":"...","dataset":<id>}]}`; `rls` and `resources` required | V `security/api.py:110-160,207-262` |
| Single chart embed | - | `EMBEDDABLE_CHARTS` (stable, default True): iframe share of a chart, session-cookie based | V `config.py:987-990`; D `embedding.mdx:351-368` |
| `apache-superset-core` (Python) | 0.1.0, "Development Status :: 3 - Alpha" | Extension-facing API: `superset_core.mcp.decorators` (`tool`, `prompt`, `ToolAnnotations`), `rest_api`, `queries`, `tasks`, `semantic_layers`, `common`, `extensions` | V `superset-core/pyproject.toml:20-33`, `superset-core/src/superset_core/` |
| `@apache-superset/core` (TS) | 0.1.0 | Namespaces: `authentication`, `chat`, `commands`, `components`, `contributions`, `editors`, `extensions`, `menus`, `navigation`, `sqlLab`, `storage`, `theme`, `translation`, `utils`, `views` | V `superset-frontend/packages/superset-core/package.json`, `src/` |
| `apache-superset-extensions-cli` | 0.1.0 | Build/bundle extensions | V `superset-extensions-cli/pyproject.toml:19-20` |
| `superset-websocket` | 0.0.1 | Node realtime push server (task-status + entity nudges over Redis pub/sub); enabled by `WEBSOCKET_ENABLE`/`WEBSOCKET_URL`/`WEBSOCKET_JWT_SECRET`; optional accelerator, polling works without it | V `superset-websocket/package.json`, `README.md`, `UPDATING.md:1371-1380` |
| Official Python REST client | none in repo or docs | Use `requests`/`httpx` against OpenAPI | V grep of `docs/` found none |

## 7. AI integrations - strict status

| Capability | Status on this commit | Evidence |
|---|---|---|
| MCP server (tools for external AI clients) | SHIPPED, BETA-TESTING | sections 1-3 |
| Built-in LLM / text-to-SQL / assistant | **Not present.** No `openai`, `anthropic`, `langchain`, `ollama` dependency or call in `superset/`, `superset-core/`, `superset-frontend/src`, `pyproject.toml` | V `git grep` (hits are only docstrings, `tiktoken` size estimator, `GPT.md`/`CLAUDE.md` contributor guides) |
| Chat UI | Extension point only: `chat.registerChat(descriptor, Trigger, Panel)`; host mounts floating/docked panel. Rendered only when `ENABLE_EXTENSIONS` (development) and an extension registers a chat. No chat extension ships | V `superset-frontend/packages/superset-core/src/chat/index.ts`, `src/views/App.tsx:180-183`, `config.py:787-788`; D `docs/developer_docs/extensions/extension-points/chat.md` |
| Extension MCP tools/prompts | Extension-only: `@tool` / `@prompt` from `superset_core.mcp.decorators`, names prefixed `extensions.<org>.<ext>.` | V `superset/core/mcp/core_mcp_injection.py:157-229`; D `docs/developer_docs/extensions/mcp.md` |
| Embeddings / vector search | Not present (tool search is BM25/regex, `mcp_config.py:566`) | V |
| AI-related SIPs in repo | none (`docs/sip/` holds 4 unrelated SIPs) | V `ls docs/sip` |
| User doc | "Using AI with Superset" describes MCP clients only | D `docs/docs/using-superset/using-ai-with-superset.mdx:27-29` |

## 8. Minimal recipe: MCP as its own compose service on 5008

1. Image: reuse the same image/build as the `superset` service (`dev` or `superset` target both contain fastmcp; `lean` does not).
2. `superset_config` (e.g. `docker/pythonpath_dev/superset_config_docker.py`, imported by `superset_config.py:142-147`):

```python
MCP_DEV_USERNAME = "admin"                               # demo identity; must exist
WEBDRIVER_BASEURL_USER_FRIENDLY = "http://localhost:8088/"  # host used in links returned by tools
MCP_SERVICE_URL = "http://localhost:5008"
MCP_TOOL_SEARCH_CONFIG = {"enabled": False}              # optional: native tools/list (all 83 tools)
```

3. Compose service (same env files, volumes and network as `superset`):

```yaml
  superset-mcp:
    env_file: [{path: docker/.env, required: true}, {path: docker/.env-local, required: false}]
    build: {<<: *common-build}
    command: ["/app/docker/docker-bootstrap.sh", "mcp"]     # superset mcp run --host 0.0.0.0 --port ${MCP_PORT:-5008} --debug
    environment: {MCP_PORT: "5008"}
    ports: ["127.0.0.1:5008:5008"]                          # loopback only while in dev-user mode
    user: *superset-user
    depends_on: {superset-init: {condition: service_completed_successfully}}
    volumes: *superset-volumes
    healthcheck: {test: ["CMD", "curl", "-f", "http://localhost:5008/health"], interval: 15s, retries: 10}
```

4. Verify with section 4 curls, then connect Claude Code via `.mcp.json`.
5. Upgrade path for per-user identity: API keys first (two flags, no IdP work), Keycloak JWT second (audience mapper + `superset:read`/`superset:write` client scopes + fixed issuer).

### Honest demo list

Can show: health endpoint and hello page; `tools/list` (compat and native); instance info with current user; listing/searching dashboards, charts, datasets, databases; dataset metadata; `query_dataset` and semantic-layer tools over built-in datasets; `execute_sql` on the examples DB; `generate_chart` + `generate_explore_link` + `generate_dashboard` producing clickable URLs; `get_chart_data`; chart previews as ASCII/table/Vega-Lite; RBAC-filtered tool visibility by switching `MCP_DEV_USERNAME` or API key between Admin and Gamma; MCP calls in *Settings -> Action Log*; REST login + chart data + asset export; embedded dashboard with guest token and RLS clause; Swagger UI.

Must not claim: a native AI assistant/copilot, text-to-SQL, chat panel out of the box, production-grade MCP auth in dev-user mode, PNG previews without Chromium + reachable web app, external semantic views (Cube/Wren) without a provider extension, `/api/v1/async_event/`, an official Python SDK.
