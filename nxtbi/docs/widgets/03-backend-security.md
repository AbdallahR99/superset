# 03 - Backend inventory, master compatibility and security review (PR #44471)

Legend: **PR** = `E:/Work_Lab/nxtbi-superset-pr44471` (detached 71be990689). **FORK** = `E:/Work_Lab/nxtbi-superset` at ref `master` (f3f3d10d5c, read with `git show master:<path>`). Merge-base = 6856d0fc67. Everything is read from code unless marked **UNVERIFIED**. "PR claims" = PR body / docstrings; "code does" = what was read.

> **Status of this document.** Sections 1 to 4 are the review of upstream PR #44471 **as it was submitted**; they describe the defects that motivated the port and are kept as a record. They do not describe the code on `feature/nxtbi-widgets`. The security model that branch implements is in **section 5**, which supersedes 1.5, 1.7, 3 and the "minimal fix" column of 4(a) wherever they differ. In particular: the `datasets` claim no longer grants anything, a `widget` resource carries a server-recorded `dataset_id`, and there is a `dataset` resource type.

Verdict in five lines (of the PR as submitted):
- The backend is small (about 4.6k lines of source, 93 backend files) and mostly additive; `git merge-tree --write-tree master upstream/pr-44471` gives only 4 backend textual conflicts (`superset/config.py`, `superset/security/manager.py`, `superset/mcp_service/mcp_config.py`, `superset-core/.../semantic_layers/config.py`).
- The PR already uses the Subjects model for v2 dashboards (`populate_subjects`, `editors`, `raise_for_editorship`); saved widgets use plain `created_by_fk` ownership.
- Data execution reuses `ChartDataCommand`/`QueryContext`, so dataset permission, RLS, cache keys and row caps are the standard chart-data ones. No client SQL for guests; authenticated users can send ad-hoc SQL metrics/filters inline (same power as `/api/v1/chart/data`).
- Security holes are in authorization glue, not in SQL generation: no dataset check when a widget is saved or when a token is minted for it, the `datasets` claim is turned from a restriction into a grant, any signed-in user can read any saved widget by uuid, and the v2 document validator accepts cycles and unbounded input.
- Out of scope for this effort and recommended NOT to port: `superset/mcp_oauth/*` (OAuth authorization server for Claude artifacts), migration 2, `superset/mcp_service/auth_oauth.py`, `widgets/prompts/build_widget_artifact.py`, `MCP_WIDGETS_BUNDLE_URL`.

## 1. Inventory (PR checkout)

### 1.1 Model and migrations

| Item | Evidence | Facts |
|---|---|---|
| `SavedWidget(Model, AuditMixinNullable)` | PR `superset/models/saved_widget.py:28-49` | table `saved_widgets`; `uuid` `UUIDType(binary=True)` PK default `uuid4`; `widget_type` String(250) NOT NULL; `title` String(500) NULL; `props` Text NOT NULL default `"{}"` (raw JSON as sent, not normalized); `dataset_id` Integer NULL (derived from props on save, **no FK, no index**); audit columns. No owners/editors/viewers, no `SoftDeleteMixin`, no `ImportExportMixin`, not versioned. |
| Migration 1 `3c9e1a7b5d2f` add_saved_widgets | PR `superset/migrations/versions/2026-09-15_12-00_3c9e1a7b5d2f_add_saved_widgets.py:25-68` | `down_revision = "e5f6a7b8c9d0"`. Creates `saved_widgets` + FKs `created_by_fk`/`changed_by_fk` -> `ab_user.id` + index `ix_saved_widgets_created_by_fk`. Downgrade drops index then table: reversible, uses `superset.migrations.shared.utils` helpers (still present on FORK `superset/migrations/shared/utils.py:259,281,434,479`). |
| Migration 2 `8f2d4c6a1b3e` add_mcp_oauth_tables | PR `.../2026-09-15_18-00_8f2d4c6a1b3e_add_mcp_oauth_tables.py:25-123` | `down_revision = "3c9e1a7b5d2f"`. Creates `mcp_oauth_clients`, `mcp_oauth_authorization_codes`, `mcp_oauth_refresh_tokens` (FK CASCADE to clients and `ab_user`). Reversible. Only needed for `superset/mcp_oauth`. |
| Master head | computed from every `revision`/`down_revision` on FORK master (409 revisions) | **Single head `b8f3a2c91d64`** (`2026-10-29_00-00_b8f3a2c91d64_migrate_databricks_connector_uri.py`, `down_revision = "f72b6e9c104a"`). `e5f6a7b8c9d0` already has two children on master (`d3b9a1f6c204`, merge `0be4b8f436f2`), so the PR chain as-is creates a second head. |
| Re-chain | - | Set migration 1 `down_revision = "b8f3a2c91d64"`, rename the file with the port date, update the `Revises:` docstring line. Drop migration 2 (or chain it after 1 if mcp_oauth is kept). Fork branches `nxtbi-demo` and `feature/nxtbi-arabic-rtl` add no migrations (`git diff --name-only master <branch> -- superset/migrations` is empty). The PR author states migrations were never run up/down (PR body, checklist unchecked). |

### 1.2 Modules

| Path (PR) | Role | Key symbols |
|---|---|---|
| `superset/widgets/registry.py:32` | process-global `registry: dict[str, type[Widget]]` | written only by the `@widget` decorator at import/init |
| `superset/widgets/builtin.py:73-259` | built-in types: `markdown`, `echarts`, `metric-tile`, `ag-grid-table`, `filter.select`, `filter.bar` | `Echarts._populate_chart_series` (MAX_SERIES=100), `FilterSelect._populate_datasets` (`DatasetDAO.find_all()`, base-filtered), `_populate_columns` (`dataset.raise_for_access()`), `FilterSelect.fetch_values` |
| `superset/widgets/controls.py` (504 l.) | Pydantic control models = JSON Schema of `node.props` | `DataBinding` (`datasetId:int`, `metrics:list[Any]`, `dimensions:list[str]`, `filters:list[dict]` hidden from schema, `rowLimit>=1` no upper bound) `:39-84`; all models default `extra="ignore"` |
| `superset/widgets/data.py` (368 l.) | server-side execution | `WidgetContext` `:69-82`, `props_dataset_id` `:89`, `resolved_filters_to_adhoc` `:149`, `build_widget_query` `:177`, `validate_guest_inline_props` `:260`, `raise_for_widget_datasource_access` `:299`, `fetch_column_values` `:320`, `DataBindingWidget.fetch_data` `:335` |
| `superset/widgets/schema_tools.py` | `get_subtrees(schema, paths)` for progressive disclosure | `SchemaPathError` |
| `superset/widgets/schemas.py:30-81` | marshmallow request/response | `WidgetSelectorSchema` (exactly one of `id` / `widget{type,props}`), `WidgetDataPostSchema.filters`, `SavedWidgetPostSchema`, `SavedWidgetPutSchema` |
| `superset/widgets/api.py` | `WidgetControlsRestApi` `:55`, `SavedWidgetRestApi` `:355` | see 1.3 |
| `superset/commands/widget/{data,saved,utils,exceptions}.py` | commands | `resolve_widget` data.py`:51`, `load_saved_widget` utils.py`:47`, `raise_for_widget_ownership` utils.py`:59`, `validate_widget_props` utils.py`:35` |
| `superset/daos/saved_widget.py:26-48` | `SavedWidgetDAO` (`find_by_uuid`, `find_by_creator`), no `base_filter` | legacy `db.session.query(...)` style |
| `superset/dashboard_v2/{document,schemas,api}.py` | v2 document stored in `dashboards.json_metadata["v2_document"]` | `normalize_document` document.py`:70`, `_NODE_KEYS` `:37`, `DashboardV2RestApi` api.py`:48` |
| `superset/commands/dashboard_v2/{get,save,exceptions}.py` | `resolve_dashboard` get.py`:32`, `load_v2_dashboard` `:42`, `CreateDashboardV2Command` save.py`:70`, `UpdateDashboardV2Command` `:97` | |
| `superset/views/dashboard/views.py:136-157` | `DashboardBuilderV2View` (`/dashboard/v2/new/`, `/dashboard/v2/<int:pk>/`, `@has_access`, class perm `Dashboard`) | SPA shell only |
| `superset-core/src/superset_core/widgets/{base,decorators,enrichment,composites}.py` | public contract for extensions | `Widget` base.py`:62` (`validate_control_schema`, `get_control_schema`, `validate_control_values`, `fetch_data`, `fetch_values`), stub `widget()` decorators.py`:46`, `composite_control`, `MetricControl` |
| `superset/core/api/core_api_injection.py:284-366,417` | `inject_widget_implementations()` makes `@widget` concrete; extension types are namespaced `extensions.<publisher>.<name>.<type>`; collision raises | imports `superset.widgets.builtin` |
| `superset/extensions/api.py:34-57,147,199` | `protect_unless_assets_public()` on `get` and `content` | flag `EMBEDDED_EXTENSION_ASSETS_PUBLIC` |
| `superset/mcp_service/widgets/*` | 6 MCP tools + 1 prompt, see 1.6 | |
| `superset/mcp_oauth/*`, `superset/mcp_service/auth_oauth.py` | OAuth AS (DCR, code+PKCE S256, refresh rotation, RS256 JWKS) + RFC 9728 resource server | views `/.well-known/oauth-*`, `/oauth/mcp/{register,authorize,token,jwks.json}` |

Origin: the control-schema half (registry, controls, builtin, schema_tools, `WidgetControlsRestApi`, superset-core widgets, 3 MCP control tools) comes from the `dashboard-v2` base branch; saved widgets, `data.py`, `dashboard_v2`, guest-token changes, MCP data tools, mcp_oauth and both migrations come from the 13 PR commits.

### 1.3 REST endpoints added

All use `@protect()` + `@safe`, `allow_browser_login = True`; no new permission names (reuse `Chart` / `Dashboard`).

| Method + route | Class.method (PR `path:line`) | Permission | Request -> response | What it touches |
|---|---|---|---|---|
| GET `/api/v1/widgets/types` | `WidgetControlsRestApi.types` api.py`:78` | `can read on Chart` | -> `[{id,name,description}]` | registry only |
| GET,POST `/api/v1/widgets/type/<t>/control-schema` | `.control_schema` `:112` | `can read on Chart` | body `{control_values?, series?, paths?}` (untyped) -> JSON Schema | enrichers: `DatasetDAO.find_all()`, dataset column names after `raise_for_access` |
| POST `/api/v1/widgets/type/<t>/validate` | `.validate` `:249` | `can read on Chart` | `{control_values}` -> `{errors, values}` | Pydantic only |
| GET `/api/v1/widget/` | `SavedWidgetRestApi.get_list` `:380` | `can read on Chart` | -> list (no pagination) | admin: all rows; others: `created_by_fk == me`; guest: 403 (saved.py`:128-140`) |
| POST `/api/v1/widget/` | `.post` `:416` | `can write on Chart` | `SavedWidgetPostSchema` -> 201 | guest 403; props validated by type; **no dataset access check** (saved.py`:65-70`) |
| GET `/api/v1/widget/<uuid>` | `.get` `:460` | `can read on Chart` | -> `{uuid,widget_type,title,props,dataset_id,changed_on}` | **no owner/dataset check for signed-in users**; guest must be named in token (utils.py`:47-56`) |
| PUT `/api/v1/widget/<uuid>` | `.put` `:499` | `can write on Chart` | `SavedWidgetPutSchema` (`props`,`title`; type immutable) | creator or admin (utils.py`:59-66`) |
| DELETE `/api/v1/widget/<uuid>` | `.delete` `:550` | `can write on Chart` | hard delete | creator or admin |
| POST `/api/v1/widget/data` | `.data` `:582` | `can read on Chart`, **CSRF-exempt** | `{id | widget{type,props}, filters[]}` -> `{columns, rows}` | 1.4 |
| POST `/api/v1/widget/values` | `.values` `:633` | `can read on Chart`, **CSRF-exempt** | `{id | widget}` -> `[values]` | `values_for_column`, limit `FILTER_SELECT_ROW_LIMIT` capped by `apply_max_row_limit` (data.py`:320-332`) |
| POST `/api/v1/dashboard_v2/` | `DashboardV2RestApi.post` dashboard_v2/api.py`:67` | `can write on Dashboard` | `{dashboard_title, document}` -> 201 | `DashboardDAO.create` with `editors` = caller (`populate_subjects(..., include_viewers=False)` save.py`:89`) |
| PUT `/api/v1/dashboard_v2/<int:pk>` | `.put` `:118` | `can write on Dashboard` | `{document, dashboard_title?}` | `DashboardDAO.find_by_id` (base filter) + `raise_for_editorship` (save.py`:117-128`) |
| GET `/api/v1/dashboard_v2/<ref>` | `.get` `:176` | `can read on Dashboard` | -> `{id,uuid,dashboard_title,changed_on,document,embedded{uuid,allowed_domains}}` | ref = embedded uuid, then id/slug/uuid; `dashboard.raise_for_access()` (get.py`:42-60`) |
| GET `/api/v1/dashboard_v2/embedded/<uuid>` | `.get_by_embedded` `:216` | `can read on Dashboard` | same command as above | guest path through `has_guest_access` |
| GET `/dashboard/v2/new/`, `/dashboard/v2/<pk>/` | `DashboardBuilderV2View` | `can write` / `can read on Dashboard` | HTML shell | none |
| (changed) GET `/api/v1/extensions/<publisher>/<name>[/<path:file>]` | `ExtensionsRestApi.get/content` | **unauthenticated when `EMBEDDED_EXTENSION_ASSETS_PUBLIC`** | | extension manifest data + bundle files |
| (mcp_oauth, not recommended) | `MCPOAuthView`, `MCPOAuthWellKnownView` mcp_oauth/views.py`:125-251` | none (`BaseView`), `register`/`token` CSRF-exempt, `Access-Control-Allow-Origin: *` (`:43`) | | 3 oauth tables |

No feature flag gates any of these: registration is unconditional (PR `superset/initialization/__init__.py:263-265,469`).

### 1.4 Data execution path (saved or inline widget)

1. `SavedWidgetRestApi.data` loads `WidgetDataPostSchema`, pops `filters`, runs `WidgetDataCommand` (api.py`:623-631`).
2. `resolve_widget` (commands/widget/data.py`:51-78`): saved -> `load_saved_widget` + stored `props_dict` + `WidgetContext(dataset_id, uuid)`; inline -> `validate_widget_props` (Pydantic model of the type) + `WidgetContext(props_dataset_id(props))`; guest + inline + dataset known -> `guest_widget_grants_dataset` then `validate_guest_inline_props`.
3. `DataBindingWidget.fetch_data` (widgets/data.py`:338-368`): `get_table(dataset_id)` (`DatasourceDAO.get_datasource(TABLE, id)`; SQL datasets only), client `filters` -> SIMPLE adhoc filters restricted to `datasource.column_names` and 6 operators (`:54-56,149-174`), `build_widget_query` -> `{metrics, columns, filters, extras{where,having}, row_limit}` (`:177-229`).
4. `QueryContextFactory().create(datasource={id,type:"table"}, queries=[query], form_data=..., result_type=FULL, result_format=JSON)`; then `query_context.widget_context = context` (`:356-363`); `ChartDataCommand.validate()` -> `QueryContext.raise_for_access()` -> `security_manager.raise_for_access(query_context=...)`; `.run()`; first query's `colnames`/`data` returned.
5. Access check: signed-in user -> `can_access_schema` / `datasource_access` / `is_editor(datasource)` (PR manager.py`:4018-4021`); guest -> only `widget_context_grants_data_access` (`:1141-1157,4022`) then the `datasets` allowlist (`:1160-1178,4121`). `form_data` has no `slice_id`/`dashboardId`, so the dashboard-RBAC and `query_context_modified` branches never apply.
6. RLS: applied inside the dataset query (`get_sqla_row_level_filters`): role/subject RLS for the calling user, plus guest-token `rls` rules for guests (`get_guest_rls_filters` PR manager.py`:4244`). `values_for_column` also applies RLS (FORK `superset/models/helpers.py:6425-6427`).
7. Caching: the standard chart-data cache (`DATA_CACHE_CONFIG`); cache key is the `QueryObject` key, which already includes RLS and guest-RLS (`get_rls_cache_key`). `/values` is not cached. No widget-level cache was added.
8. Limits: `rowLimit` default 1000 (`:52,206-208`), capped by the query-object factory at `SQL_MAX_ROW` (100000 on FORK `superset/config.py:1886`); values capped by `FILTER_SELECT_ROW_LIMIT` (10000). Timeouts: none specific; synchronous request, the database/webserver timeouts apply. No async (GAQ) path.

### 1.5 What a client may send inline

| Caller | Accepted | Rejected / how |
|---|---|---|
| Signed-in user (REST or MCP) | `dataBinding{datasetId, metrics, dimensions, filters, rowLimit}`; metrics may be saved-metric names, SIMPLE aggregates **or `{"expressionType":"SQL","sqlExpression":...}`** (PR `superset-core/.../composites.py:93-109`); `filters` may be adhoc **SQL** filters (`controls.py:76`, `data.py:201-205`). SQL expressions go through the dataset's normal adhoc pipeline (sanitize, `ALLOW_ADHOC_SUBQUERY=False`, Jinja if `ENABLE_TEMPLATE_PROCESSING`). | No whole-statement SQL anywhere. Dataset access via `raise_for_access`. Equivalent power to `/api/v1/chart/data`. |
| Guest | saved metric names or SIMPLE aggregates in `{AVG,COUNT,COUNT_DISTINCT,MAX,MIN,SUM}` on existing columns; dimensions in the groupable set; SIMPLE filters whose `subject` is a dataset column; `column` of `filter.select` must exist (`data.py:58,239-296`) | `sqlExpression` anywhere -> 400; dataset not in token `datasets` claim -> 403 (`manager.py:4766-4778`). **Not validated**: filter `operator`/`comparator`, `rowLimit`, which columns (all columns of the dataset are reachable). |
| Guest, widget type without detectable dataset | `props_dataset_id` returns None -> **guest checks skipped** (`commands/widget/data.py:74`); built-ins then fail closed ("no data binding"), an extension `fetch_data` would run with unvalidated props | |

Top-level `filters` in the request are always structured `{column, operator, value}`; scalars only; they can only AND onto the query (`data.py:99-174`).

### 1.6 MCP (`superset/mcp_service/widgets`)

| Tool (PR path) | Decorator | Behaviour |
|---|---|---|
| `list_widget_types` tool/list_widget_types.py`:44` | `@tool(tags=["discovery"], class_permission_name="Chart", readOnlyHint=True)` | registry listing |
| `get_widget_control_schema` `:68` | same | schema + `paths` + `control_values` |
| `set_widget_control_values` `:61` | `tags=["mutate"]`, `Chart`, `readOnlyHint=False` | mutates the process-global `node_store.nodes` (`node_store.py:45`); nothing in production code seeds it, so it always returns `unknown_node` |
| `get_widget_data` `:52` | `tags=["data"]`, `Chart`, read-only | `WidgetDataCommand` (same checks as REST) |
| `get_widget_values` `:45` | same | `WidgetValuesCommand` |
| `get_saved_widget` `:46` | `tags=["discovery"]`, `Chart` | `GetSavedWidgetCommand` (no owner check) |
| prompt `build_widget_artifact` | prompts/ | Claude-artifact instructions; uses `MCP_WIDGETS_BUNDLE_URL` |

Auth is whatever the MCP service is configured with; tools already import `tool, ToolAnnotations` from `superset_core.mcp.decorators`, the location FORK `superset/mcp_service/CLAUDE.md:88,111` requires. Registered in PR `superset/mcp_service/app.py:863-871`.

### 1.7 Security manager and guest token

| Change (PR) | Evidence | Effect |
|---|---|---|
| `GuestTokenResourceType.WIDGET = "widget"` | `superset/security/guest_token.py:123` | `ResourceSchema.type` is `fields.Enum(GuestTokenResourceType)` (`superset/security/api.py:75`), so `POST /api/v1/security/guest_token/` accepts `{"type":"widget","id":"<uuid>"}` with no API change |
| `validate_guest_token_resources` widget branch | `manager.py:4502-4504` | only checks the saved widget exists; no check on the minter or on the widget's dataset |
| `guest_token_names_widget`, `guest_widget_grants_dataset`, `guest_widget_grants_datasource`, `raise_for_guest_dataset_allowlist` | `manager.py:4754-4797` | saved widget: token must name its uuid; inline: dataset id must be in the token `datasets` claim; datasource must be `type == "table"` and equal the context dataset |
| `widget_context_grants_data_access` in `raise_for_access` | `manager.py:1141-1157,4022` | grant keyed on `QueryContext.widget_context` (set only server-side, `superset/common/query_context.py:61`); `isinstance(context, WidgetContext)` blocks duck-typed forgeries |
| allowlist extracted to `_raise_for_guest_dataset_allowlist` | `manager.py:1160-1178,4121` | same logic as before, reused by `/values` |
| Token signing | `manager.py:4472-4476,4513-4531,4694-4698` | unchanged: same `GUEST_TOKEN_JWT_SECRET`, `GUEST_TOKEN_JWT_AUDIENCE`, `type: "guest"` for dashboard and widget tokens; scoping is only in the `resources` / `datasets` claims |

### 1.8 Config / flags added

`WTF_CSRF_EXEMPT_LIST += superset.widgets.api.data, superset.widgets.api.values, superset.mcp_oauth.views.register, superset.mcp_oauth.views.token` (PR `superset/config.py:367-370`); `MCP_OAUTH_*` (9 keys, `:384-398`); `EMBEDDED_EXTENSION_ASSETS_PUBLIC = False` (`:3086`); `MCP_WIDGETS_BUNDLE_URL` (mcp_config.py). Needs existing `EMBEDDED_SUPERSET` (guest tokens) and `ENABLE_EXTENSIONS` (extension widgets). `DashboardJSONMetadataSchema.v2_document` (PR `superset/dashboards/schemas.py:208`).

### 1.9 Tests in the PR

| Folder | Tests | Covers | Gaps |
|---|---|---|---|
| `tests/unit_tests/widgets/` | 96 in 10 files | registry, enrichment, schema tools, builtin controls, saved-widget commands (mocked DAO), guest grant logic (`test_saved_widget_security.py`, 14) | no REST test for `SavedWidgetRestApi` (only 4 tests on `/validate`); no test with a real database, RLS or cache; no cross-user read test |
| `tests/unit_tests/dashboard_v2/test_document.py` | 8 | normalize/round-trip, filter conversion, query building | no cycle/size test, no API or command test |
| `tests/unit_tests/mcp_service/widgets/` | 33 | tool impls with mocks, prompt | no RBAC/auth test |
| `tests/unit_tests/mcp_oauth/`, `mcp_service/test_auth_oauth.py` | 35 | keys, service, views | out of scope |
| `tests/unit_tests/extensions/test_api.py` | 5 | public assets flag | |

CI state reported on the PR: unit tests, pre-commit and all three DB backends failing (rusackas, 2026-09-29, https://github.com/apache/superset/pull/44471); patch coverage 41.6%, `superset/widgets/data.py` 24.7% (codecov bot, 2026-09-21).

## 2. Master compatibility

### 2.1 Files the PR modifies

| File | Merge result | Drift on master (6856d0fc67..master) and required action |
|---|---|---|
| `superset/security/manager.py` | **CONFLICT x2** | (a) access `or`-chain: master added `_semantic_layer_grant_allows(datasource)` and changed `is_editor(datasource)` to `(allow_editorship and self.is_editor(datasource))`; keep master's lines and add `or widget_context_grants_data_access(self, query_context, datasource)`. (b) allowlist block: master added `datasource.type != DatasourceType.TABLE` to the deny condition; port that into `_raise_for_guest_dataset_allowlist`. (c) no textual conflict but semantic: `validate_guest_token_resources` is now an instance method `(self, resources, datasets=None)` that requires the **minter** to pass `raise_for_access(dashboard=...)` and `_raise_for_guest_token_datasource_access` (FORK manager.py`:6512-6590`); the PR's static version with only an existence check must be rewritten in that style. (d) `create_guest_access_token` now calls `enforce_guest_token_identity`; guest tokens can be revoked (FORK `:6638-6670`). File grew by about 3000 lines; PR helper names do not collide (grep on master: none). |
| `superset/security/guest_token.py` | auto-merge | master added identity validation and audit fields; enum addition applies cleanly |
| `superset/config.py` | **CONFLICT** | exempt list: master added `superset.datasource.api.query`, `export_xlsx`, removed `explore_json`. Keep master's list and append only the two widget entries. |
| `superset/common/query_context.py` | auto-merge | master added `force_nonce`, `client_id`, `is_async_execution`, `prepare_contribution_totals`; the class attribute `widget_context` still works. `QueryContextFactory.create` is keyword-only and still accepts the PR's arguments (FORK `superset/common/query_context_factory.py:65-79`). |
| `superset/dashboards/schemas.py` | auto-merge | one field |
| `superset/views/dashboard/views.py` | auto-merge | master's `Dashboard.new` now sets default viewers and calls `AFTER_ASSET_CREATE`; the v2 create command should do the same (see 2.2) |
| `superset/initialization/__init__.py` | auto-merge | `add_api` / `add_view_no_menu` pattern unchanged (FORK `:298,504`); `init_core_dependencies` still calls `initialize_core_api_dependencies()` (`:627-637`) |
| `superset/core/api/core_api_injection.py` | clean | unchanged on master since the merge-base |
| `superset/extensions/api.py` | auto-merge | master rebased the class on `BaseSupersetApi`; re-check the decorator order after merge |
| `superset/mcp_service/app.py`, `server.py` | auto-merge | imports only |
| `superset/mcp_service/mcp_config.py` | **CONFLICT x3** | all in the OAuth hunks (master added `MCPAuthConfigError` guards for `MCP_DEV_USERNAME` and HMAC). Dropping mcp_oauth removes the conflicts; keep only nothing from this file. |
| `superset-core/.../semantic_layers/config.py` | **CONFLICT x2** | master added `SemanticCredentialReadiness(Enum)`; PR added `_iter_nested_models` and nested-model field ordering. Keep both; `build_configuration_schema` / `check_dependencies` still exist (FORK `:37,74`). Re-run `tests/unit_tests/semantic_layers/config_test.py` (added by the base branch, absent on master). |

### 2.2 Semantic drift affecting the files the PR adds

| Topic | Finding |
|---|---|
| SQLAlchemy 2 (`sqlalchemy>=2.0.55` on master vs `<2` at merge-base) | PR code uses `db.session.query(...).filter(...).one_or_none()/all()` and classic `Column` declarations; both remain valid in 2.0 and master still uses `db.session.query` in DAOs. `UUIDType(binary=True)` is still the house style (FORK `superset/models/helpers.py:1166`). `sqlalchemy-utils` moved to 0.43. No rewrite required; add typing if mypy complains. |
| `BaseDAO` | master `find_by_id(model_id, skip_base_filter, id_column, query_options, *, skip_visibility_filter, force_fetch)` (FORK `superset/daos/base.py:377-410`) and coerces uuid strings itself (`:299-317`); has `uuid_column_name`. `SavedWidgetDAO.find_by_uuid` can become `find_by_id(ref)` with `id_column_name = "uuid"`. `EmbeddedDashboardDAO.find_by_id("12")` returns None on master instead of raising. |
| Flask 3 / FAB 5.3 | `flask>=2.2.5,<4`, `flask-appbuilder>=5.3.0`. PR uses only `expose/protect/safe`, `BaseSupersetApi`, `has_access`: unchanged API. |
| Subjects / editors / viewers | Already present at the merge-base. Dashboard v2 uses `editors` and `raise_for_editorship` (compatible; `populate_subjects(properties, exceptions, *, include_viewers=True)` FORK `superset/commands/utils.py:215-219`). **SavedWidget does not use owners or subjects**: ownership = `created_by_fk` (breaks when the creator is deleted or the widget must be shared). Decide: keep creator-only for the demo, or add `editors`/`viewers` association tables like other assets. |
| Create path | master `CreateDashboardCommand` flushes, links slices, and calls `AFTER_ASSET_CREATE` (FORK `superset/commands/dashboard/create.py:44-70`); `CreateDashboardV2Command` calls `DashboardDAO.create` directly and skips the hook and default viewers. Align it. |
| Soft delete / version history | master `Dashboard(CoreDashboard, SoftDeleteMixin, ...)` with Continuum versioning (FORK `superset/models/dashboard.py:308`). v2 documents live in `json_metadata`, so they are soft-deleted and versioned with the dashboard (version rows for every save: **UNVERIFIED** size impact). `SavedWidget` is hard-deleted and unversioned. |
| Chart data command | `ChartDataCommand.run()` still returns `{"queries": [...]}`; validation errors now raise `ChartDataQueryValidationError(ChartDataQueryFailedError)` (FORK `superset/commands/chart/exceptions.py:161-166`), already caught by `_execute`. `DatasourceDAO.get_datasource` unchanged for `TABLE`. |
| MCP on FastMCP 4.x (`fastmcp>=4.1.4,<5` vs `>=3.4.3,<4`) | Tool registration matches master's convention. Differences to fix: master tools are `async def tool(request, ctx: Context)` wrapped in `event_logger.log_context` (FORK CLAUDE.md`:125-128,336-345`); `method_permission_name` defaults to write for `mutate` tags; every `readOnlyHint=False` tool must be listed in `MCP_CACHE_CONFIG["excluded_tools"]` (enforced by `test_mcp_caching.py::test_excluded_tools_covers_every_mutating_tool`, FORK mcp_config.py`:415-423`); guests are default-denied by `MCP_GUEST_ALLOWED_TOOLS` (FORK mcp_config.py`:272`), which is the right default for widget tools. `fastmcp.server.auth.RemoteAuthProvider/TokenVerifier` import path under 4.x: **UNVERIFIED** (only matters if mcp_oauth is kept). |

## 3. Security review

**(1) Authorization.** Route level is consistent (`@protect()` everywhere, table 1.3). Object level: v2 dashboards are correct (`raise_for_access` on read, `raise_for_editorship` on write, creator becomes editor), so user A cannot read user B's draft. Saved widgets: write/delete = creator or admin; list = own; **read by uuid = anyone with `can read on Chart`** (utils.py`:47-56`), REST and MCP alike, returning props (SQL expressions, filter literals, dataset id). Data of that widget is still gated by the caller's own dataset permission and RLS.

**(2) Data access.** Signed-in: standard `raise_for_access(query_context)`, RLS by subject, guest-RLS n/a. Guests: saved widget -> access comes solely from the token naming the uuid; the dataset is whatever the stored props say. Nothing checks that the **author** could read that dataset (saved.py`:65-70,90-96`) or that the **minter** can (manager.py`:4502-4504`). Client SQL: guests none; signed-in users ad-hoc expressions only. Jinja: runs for dataset SQL / ad-hoc expressions under `ENABLE_TEMPLATE_PROCESSING` (on in the fork); for a guest it runs with the guest identity. SIMPLE filter comparators are not templated (no `process_template` call on filter values found on FORK `superset/models/helpers.py`, call sites `:2450,4447,6526,6611,6633`; light check).

**(3) Guest tokens.** Token for widget X cannot read widget Y (`guest_token_names_widget`), cannot read a dashboard (`has_guest_access` filters `type == dashboard`, PR manager.py`:4722-4742`), cannot use `/api/v1/chart/data` (no `widget_context`). Inline needs the `datasets` claim. Problems: the claim was a pure restriction for dashboard tokens and now doubles as a grant for arbitrary aggregates over every column of the listed datasets; `resources: []` + `datasets: [n]` is a valid token; a token mixing a saved widget and a `datasets` list silently denies the saved widget if its dataset is not listed (`_raise_for_guest_dataset_allowlist`). RLS rules in the token are applied as before; a token without `rls` sees all rows the dataset returns (PR README states this). Same secret and audience for all guest tokens. **Legacy embedded route mix-up** (review comment sadpandajoe, 2026-09-30, `superset-frontend/src/pages/DashboardBuilderV2/DashboardHeader.tsx:331`): the v2 header reuses the legacy embed modal; its `EmbeddedDashboard` uuid is served by `superset/embedded/view.py` (not touched by the PR), which renders the legacy dashboard, not the v2 document. Backend consequences: there is no guest data path for widgets of an embedded v2 dashboard other than inline + `datasets`; `allowed_domains` is enforced only by the iframe view's referrer check and is returned to guests by `serialize_dashboard` (get.py`:71-73`).

**(4) Cross-user / cross-request leakage.** `registry` is written only at import (safe). `Echarts._populate_chart_series` deep-copies `$defs` (safe). `node_store.nodes` is a process-global, user-less dict mutated by an MCP tool (unsafe by design, currently dead). Data cache keys are the standard ones (include RLS). MCP response caching on master refuses to start unless `dangerously_share_cache_across_principals` is set (FORK `superset/mcp_service/caching.py:227-240`). Frontend module-global `active` in `extensionHost.tsx:250` is flagged by the same review (frontend file).

**(5) Input validation.** `normalize_document` (document.py`:70-101`) checks: `nodes` is a dict, `root` is a container, each node has a string `type`, `props` is a dict, children exist. It does **not** check cycles or self-reference (review comment on document.py:93), depth, node count, payload size, id format, single-parent, orphans; a non-hashable child raises `TypeError` (500). Unknown widget types skip prop validation (save.py`:53-54`). `layout`/`style` are stored verbatim. Legacy `PUT /api/v1/dashboard/<id>` can now carry `json_metadata.v2_document` with no validation at all. Mass assignment is fine (marshmallow rejects unknown fields; `widget_type` immutable on PUT; `editors` forced to caller). `control-schema` accepts unbounded `paths` and unvalidated `series`. `echartsOptions`/`columnDefs` are arbitrary JSON rendered for other viewers (HTML in tooltip formatters: frontend sanitization **UNVERIFIED**).

**(6) CSRF / CORS.** `/widget/data` and `/widget/values` are CSRF-exempt read endpoints (same reasoning as chart data); create/update/delete and `dashboard_v2` writes keep CSRF. An external React app needs: `ENABLE_CORS = True` (already the master default, FORK `superset/config.py:1663`), `CORS_OPTIONS = {"origins": [<host origins>], "resources": [r"/api/*"], "allow_headers": ["Content-Type", "X-GuestToken"], "expose_headers": ["ETag"]}`; guest mode sends `credentials: 'omit'` (PR `superset-frontend/packages/superset-widgets/src/embed/httpClient.ts:76`) so `supports_credentials` is only for session mode, which also needs a `SameSite=None; Secure` cookie. There is no per-widget `allowed_domains`: CORS origins are the only origin control and CORS is not authorization; the guest token is. `EMBEDDED_EXTENSION_ASSETS_PUBLIC` is required for extension widgets under guest tokens and also un-protects the extension metadata route.

**(7) Fork deployment** (`git show nxtbi-demo:nxtbi/config/superset_config.py`, `nxtbi/bootstrap/bootstrap.py`).
- `NxtbiSecurityManager(SupersetSecurityManager)` only overrides OIDC hooks; new manager methods are inherited. No conflict.
- Every organisation level maps to `Gamma` (+ `nxt_org_<org>`): all users including "viewer" get `can write on Chart/Dashboard`, so all can create saved widgets and v2 dashboards.
- Tenant isolation = `datasource_access` on org datasets + RLS by role subject on `service_requests` + a BASE rule ("neither Admin nor an org role sees nothing"). Signed-in widget queries honour all of it. Cross-tenant exposure is limited to widget definitions (defect D3) and the confused-deputy path (D1).
- `RLS_IN_SQLLAB` is irrelevant to widgets (no SQL Lab path); it still applies to virtual datasets used as widget datasets.
- Guests: `GUEST_ROLE_NAME` stays `Public` with no permissions, so every guest widget call is a 403 until a dedicated role with only `can read on Chart` (and `can read on Dashboard` for v2 documents) exists. Do not follow the PR README's `GUEST_ROLE_NAME = "Gamma"`. Under the BASE RLS rule a guest sees zero rows on RLS tables unless the guest role's subject is exempted, and then the token `rls` clause is the only tenant boundary: enforce it with `GUEST_TOKEN_VALIDATOR_HOOK` (reject tokens without an `rls` rule for RLS-protected datasets).
- `SESSION_COOKIE_SAMESITE = "Lax"`, `SESSION_COOKIE_SECURE = False`: session-mode embedding works only same-site (localhost ports); real hosts must use guest tokens. No `CORS_OPTIONS` override in the fork yet.
- MCP bearer tokens (`local-jwt` HS256 or Keycloak RS256): widget tools run as the token's user with `Chart` RBAC, same command checks. `MCP_OAUTH_*` is not needed.
- `ENABLE_TEMPLATE_PROCESSING` is on: inline SQL expressions from signed-in users are Jinja-rendered (already true for chart data).

## 4. Conclusions

### (a) Security defects, ranked, with minimal fix

| # | Sev | Defect (evidence, PR) | Principal / effect | Minimal fix |
|---|---|---|---|---|
| D1 | High | Saved widget create/update never checks the author's access to `dataBinding.datasetId` (saved.py`:65-70,90-96`); mint only checks existence (manager.py`:4502-4504`); guest grant = token names uuid (`:4766-4792`) | Gamma user of org A saves a widget on org B's dataset; any backend that mints tokens for a requested uuid exposes B's rows to a guest | In both `validate()` methods call `get_table(id).raise_for_access()`; in `validate_guest_token_resources` require the minter to pass `can_access_datasource` on the widget's dataset (master pattern FORK manager.py`:6540-6549`) |
| D2 | High | `datasets` claim is a grant for inline queries (manager.py`:4776-4778`) while master validates it only as a restriction on dashboard slices (FORK `:6553-6590`) | minter with `can_grant_guest_token` but no dataset access, or any existing dashboard token with `datasets`, yields arbitrary aggregates on all columns | Use a distinct claim (`inline_datasets`) or resource type; at mint require `can_access_datasource` for each id; reject `resources: []` unless that claim is present |
| D3 | Medium | Any `can read on Chart` user reads any saved widget by uuid (utils.py`:47-56`; MCP `get_saved_widget`) | cross-tenant disclosure of definitions | For non-guests require creator/admin or `raise_for_access` on the widget's dataset; answer 404 |
| D4 | Medium | v2 document: cycles, no depth/count/size/id limits, unknown types unvalidated, legacy PUT bypass (document.py`:70-101`, save.py`:53-54`, dashboards/schemas.py`:208`) | editor stores a document that hangs/crashes every viewer's renderer; oversized metadata | DFS from `root` with visited set; each non-root node exactly one parent, no orphans; limits (e.g. 500 nodes, depth 16, 1 MiB); id regex `^[A-Za-z0-9_-]{1,64}$`; reject unknown leaf types; make the legacy dashboard update reject or validate `v2_document` |
| D5 | Medium | Guest inline guard is skipped when no dataset is derivable (commands/widget/data.py`:74`); operator/comparator/rowLimit/columns unchecked (widgets/data.py`:260-296`); lowercase aggregate passes the guard then fails in SQLA lookup | guest reaches extension `fetch_data` unvalidated; wider column access than any widget shows | Default-deny guest inline (`if is_guest and inline: require grant else 403`); operator allowlist; guest row cap; normalize aggregate; optional per-token column allowlist |
| D6 | Medium | No feature flag; endpoints, view and CSRF exemptions always on (initialization`:263-265,469`, config.py`:367-370`) | experimental surface exposed on every deployment | Gate registration and handlers behind a `DASHBOARD_V2` / `EMBEDDABLE_WIDGETS` flag, default False |
| D7 | Medium | Legacy embed flow for v2 dashboards (review 2026-09-30); `allowed_domains` returned to guests (get.py`:71-73`) and not enforced on API routes | broken embed pushes hosts to over-broad `datasets` tokens (D2) | Hide the v2 embed action until a v2 embedded renderer exists; add a dashboard-scoped data endpoint (`dashboard ref + node id`, authorized by `has_guest_access`, props read from the stored document); drop `allowed_domains` from guest responses |
| D8 | Low | Process-global `nodes` store mutated by MCP tool (`node_store.py:45`) | cross-user tampering if ever seeded | Remove `set_widget_control_values` and `node_store` from the port, or rebuild it on the stored document with `raise_for_editorship` |
| D9 | Low | `EMBEDDED_EXTENSION_ASSETS_PUBLIC` also un-protects extension metadata (`extensions/api.py:147`) | anonymous enumeration by name | Apply the public decorator to `content` only |
| D10 | Low | `saved_widgets.dataset_id` has no FK/index; list unpaginated; raw props stored; `paths`/`series` unbounded | integrity, minor DoS | FK `ON DELETE SET NULL` + index; paginate; store `model_dump(by_alias=True)`; cap list lengths |
| D11 | Low (if ported) | mcp_oauth: open dynamic registration, CSRF-exempt, `ACAO: *`, any https redirect by default (`MCP_OAUTH_ALLOWED_REDIRECT_URIS=None`) | new unauthenticated attack surface | Do not port |

### (b) Ordered backend porting plan onto master

1. New worktree and branch from `master` (do not touch the RTL checkout). Do not merge the PR branch; transplant files.
2. **Copy unchanged**: `superset-core/src/superset_core/widgets/*`; `superset/widgets/{__init__,registry,controls,schema_tools,schemas,builtin}.py`; `superset/models/saved_widget.py`; `superset/daos/saved_widget.py`; `superset/commands/widget/*`; `superset/dashboard_v2/*`; `superset/commands/dashboard_v2/*`; `superset/widgets/{api,data}.py`; tests under `tests/unit_tests/{widgets,dashboard_v2}`, `tests/unit_tests/semantic_layers/config_test.py`, `tests/unit_tests/extensions/test_api.py`.
3. **Re-apply by hand** (small hunks): `core_api_injection.py` (+`inject_widget_implementations`), `initialization/__init__.py` (3 `add_api`, 1 view), `query_context.py` (attribute), `dashboards/schemas.py`, `views/dashboard/views.py`, `guest_token.py` enum, `config.py` (two exempt entries + `EMBEDDED_EXTENSION_ASSETS_PUBLIC`), `extensions/api.py`, `semantic_layers/config.py` (keep master's enum, add PR helpers).
4. **Rewrite**: the `security/manager.py` hunks per 2.1 (keep `allow_editorship`, `_semantic_layer_grant_allows`, `DatasourceType.TABLE` check; instance-method `validate_guest_token_resources` with minter entitlement); `CreateDashboardV2Command` to mirror master's create (flush, `AFTER_ASSET_CREATE`, viewers decision); `SavedWidgetDAO` on `BaseDAO.find_by_id`; MCP tools as async + `ctx` + `event_logger`, add mutating tool to `excluded_tools` or drop it.
5. **Drop**: `superset/mcp_oauth/*`, `mcp_service/auth_oauth.py`, all `mcp_config.py`/`server.py` OAuth hunks, migration 2, `tests/unit_tests/mcp_oauth`, `test_auth_oauth.py`, the artifact prompt and `MCP_WIDGETS_BUNDLE_URL`.
6. **Migration**: one file, `revision = "3c9e1a7b5d2f"`, `down_revision = "b8f3a2c91d64"`, plus the D10 FK/index. Re-check the head right before merging (`git grep -E "^(revision|down_revision)" master -- superset/migrations/versions`), master moves fast.
7. Apply fixes D1-D7 before exposing anything to guests; add the feature flag first (D6).
8. Fork config (in `nxtbi/`, additive): guest role, `CORS_OPTIONS`, `GUEST_TOKEN_VALIDATOR_HOOK`, feature flag on.
9. Migration test on a disposable database (repeat for PostgreSQL, MySQL, SQLite, the three CI backends):
   ```bash
   docker run --rm -d --name wdg-mig -e POSTGRES_PASSWORD=pw -p 55432:5432 postgres:16
   # throwaway superset_config.py: SECRET_KEY + SQLALCHEMY_DATABASE_URI=postgresql+psycopg2://postgres:pw@localhost:55432/postgres
   superset db upgrade && superset db heads            # exactly one head: 3c9e1a7b5d2f
   superset db downgrade b8f3a2c91d64                  # saved_widgets and its index are gone
   superset db upgrade                                 # second upgrade succeeds
   superset db downgrade -1 && superset db upgrade     # round trip
   ```
   Also run the upgrade against a copy of the demo metadata database, never against the running stack.

### (c) Regression tests that must exist

| Area | Test |
|---|---|
| Migration | single head; upgrade/downgrade/upgrade round trip on 3 backends; model columns match the table |
| Saved widget API | CRUD happy path through the Flask client; user B gets 404/403 on GET/PUT/DELETE of user A's widget; list shows only own rows; guest gets 403 on list/create/update/delete |
| D1 | create and update with a dataset the author cannot access -> 403; mint token for a widget whose dataset the minter cannot access -> 400/403 |
| Data path, signed-in | no dataset permission -> 403; with permission -> rows; RLS rule by role subject filters rows on `/data` and `/values`; two users with different RLS never share a cache entry; BASE rule yields zero rows |
| Data path, guest | token names X: X ok, Y 403, inline 403, `/api/v1/chart/data` 403, `dashboard_v2` 403; token `rls` clause applied on `/data` and `/values`; `datasets` allowlist excludes X's dataset -> 403; dashboard-only token + inline -> 403 |
| D2 | `datasets`/inline claim with a dataset the minter cannot access -> rejected; `resources: []` without inline claim -> rejected |
| Guest inline hardening | SQL metric, SQL filter, unknown column, non-groupable dimension, string `datasetId`, dict dimension, lowercase aggregate, unknown operator, huge `rowLimit`, extension type without dataset -> 400/403, never 500 |
| Filters | each of the 6 operators; unknown column; non-scalar value; SQL text inside a value is bound, not interpolated |
| v2 document | self-child, 2-cycle, orphan, two parents, 501 nodes, depth 17, oversized body, bad id, unknown leaf type, non-hashable child -> 422; legacy dashboard PUT cannot inject an invalid `v2_document` |
| v2 dashboard authz | non-editor PUT -> 403; draft invisible to other users; guest with matching embedded uuid reads the document, other uuid 403; soft-deleted dashboard -> 404 |
| Security manager | `widget_context` forged via `form_data` or duck-typed object is ignored; non-`table` datasource denied; master's existing guest-token tests still pass |
| Flag / CSRF | flag off -> 404 on every new route; `/widget/data` works without CSRF token, `POST /widget/` does not |
| MCP | RBAC: user without `can read on Chart` denied; guest principal denied by `MCP_GUEST_ALLOWED_TOOLS`; `test_excluded_tools_covers_every_mutating_tool` green |
| Extensions | `EMBEDDED_EXTENSION_ASSETS_PUBLIC` off -> 401 unauthenticated; on -> only bundle files public |

## 5. The model as implemented (`feature/nxtbi-widgets`)

Read from `superset/security/guest_token.py`, `superset/security/manager.py`, `superset/security/api.py`, `superset/widgets/{data,safety,controls}.py`, `superset/commands/widget/{data,utils}.py` and `superset/dashboard_v2/{access,feature}.py` in this worktree. Symbol names are given instead of line numbers.

### 5.1 Feature flag

Everything is behind `DASHBOARD_V2` (default off). `register_dashboard_v2_gate` answers 404 for the Dashboard V2 API, the widget control API, the saved-widget API and the builder view, before CSRF protection and authentication. The MCP widget tools refuse on the same flag. Details: `05-dashboard-v2-api-contract.md` section 1. (Closes D6.)

### 5.2 Guest token: resources and the `datasets` claim

`GuestTokenResourceType` has three members. Each `resources` entry is authorized at mint time by `validate_guest_token_resources`; a type it does not know is a validation error, so nothing unchecked is ever signed.

| Resource | What it grants a guest | Checked when the token is minted |
|---|---|---|
| `{"type": "dashboard", "id": <embedded uuid or id>}` | the embedded dashboard, as before | the dashboard is embedded; the **minter** passes `raise_for_access(dashboard=...)` and can read every member datasource the token will expose (`_raise_for_guest_token_datasource_access`) |
| `{"type": "widget", "id": <saved widget uuid>}` | the definition of that saved widget, and data from **the dataset the widget bound at mint time** | the widget exists and is of a registered type; a type that queries data must bind a dataset; the minter passes `can_access_datasource` on it (`_guest_token_widget_dataset`, `_guest_token_minter_dataset`). The server then writes `dataset_id` into the resource. |
| `{"type": "dataset", "id": <dataset id>}` | **inline**, SQL-free widget definitions against that one dataset | the id is a positive integer in plain decimal digits; the dataset exists; the minter passes `can_access_datasource` (`_guest_token_inline_dataset`) |

Rules that follow from the code:

- **`dataset` is the inline grant, and the only one.** `guest_widget_grants_dataset` serves an inline definition only when the token has a `dataset` resource for the definition's dataset (`guest_token_grants_inline_dataset`). A `dashboard` resource, a `widget` resource and the `datasets` claim never grant one, so a dashboard-scoped token cannot run an inline definition. (Closes D2.)
- **`datasets` only narrows.** The claim is consulted in exactly one way, `_raise_for_guest_dataset_allowlist`: when present, a datasource that is not a SQL dataset or whose id is not listed is refused even if a resource would grant it; a malformed list refuses everything. It is never read as a grant. A token mixing a `widget` resource with a `datasets` list that omits the widget's dataset therefore gets no data for that widget.
- **A `widget` resource carries a server-recorded `dataset_id`.** `GuestTokenResource.dataset_id` is set by the server and a value sent by the caller is always replaced. It is `None` for a type that queries nothing (markdown, a filter bar). At request time `guest_token_binds_widget_dataset` requires the token to name the widget **and** the recorded id to equal the dataset the widget binds on that request. A saved widget that was re-pointed at another dataset after the token was minted, and a token without a recorded dataset, get no data. (Closes D1 on the mint side.)
- **Data access is keyed on a server-built context.** `widget_context_grants_data_access` grants a guest a datasource only for a `QueryContext` whose `widget_context` is a real `WidgetContext` (never populated from a request), whose dataset is the datasource being queried, and for a SQL dataset (`type == "table"`). Forged form data or a duck-typed object grants nothing. `/widget/values` uses the same rule through `raise_for_widget_datasource_access`.
- A token for widget X cannot read widget Y (`guest_token_names_widget`), a dashboard (`has_guest_access` looks at `dashboard` resources only) or `/api/v1/chart/data`.
- Signing is unchanged: one `GUEST_TOKEN_JWT_SECRET` / audience for every guest token; scoping lives in the `resources` and `datasets` claims. `enforce_guest_token_identity` and revocation apply to widget and dataset tokens as to dashboard tokens.

### 5.3 Row level security at mint, and `GUEST_TOKEN_VALIDATOR_HOOK`

A guest is not the widget's author. The rows a guest reads are bounded by the `rls` rules in its token plus the RLS rules that apply to the guest role (`GUEST_ROLE_NAME`), never by the author's role rules.

`create_guest_access_token` therefore calls `_raise_for_guest_token_widget_rls`: for every dataset granted by a `widget` resource (its recorded `dataset_id`) or a `dataset` resource, if the dataset carries RLS rules (`row_level_security_filters`), the token must hold an `rls` rule that covers it: a rule without `dataset` (applies to all) or one naming that dataset id. Otherwise minting fails with a validation error. `dashboard` resources are not subject to this rule.

A deployment that decides this itself sets `GUEST_TOKEN_VALIDATOR_HOOK` (a callable taking the token request body, `superset/security/api.py`). When a callable hook is configured the built-in requirement steps aside and the hook is the authority; it runs for every guest-token request after `validate_guest_token_resources`, and a falsy result rejects the request. A configured value that is not callable is an error.

Guest RLS on a semantic view cannot be enforced and is refused (`raise_for_unsupported_guest_rls`); widgets only bind SQL datasets.

### 5.4 Who may author SQL

`find_sql_in_props` defines "SQL-free": metrics are saved-metric names or SIMPLE aggregates of a named column, dimensions are column names, authored filters are SIMPLE `WHERE` comparisons on a named column with an operator from `SIMPLE_FILTER_OPERATORS`, and nothing in the binding holds a SQL-bearing key (`sqlExpression`, `sql`, `where`, `having`, `extras`, `expression`) or a Jinja marker (`{{`, `{%`, `{#`).

| Caller | SQL expressions in a definition |
|---|---|
| Admin | allowed |
| Signed-in user who can read the bound dataset (`can_access_datasource`) | allowed. This is the rule Explore applies to an ad-hoc SQL metric or filter of a classic chart: the expression runs through the dataset's normal ad-hoc pipeline (sanitizing, `ALLOW_ADHOC_SUBQUERY`, template processing), so the builder is exactly as permissive as `/api/v1/chart/data` for the same role. A Gamma user with dataset access may author SQL. |
| Signed-in user without access to the dataset, or a definition that binds no dataset (non-admin) | refused (`WidgetSqlNotAllowedError`) |
| Guest | **never**, whatever the guest role grants (`user_may_author_widget_sql`) |

Where it is enforced: saving a widget (`raise_for_widget_authoring`: read access to the bound dataset, then the SQL rule; closes D1 on the author side), and an inline data request from a signed-in user (`resolve_widget`, only when the definition carries SQL).

Guest inline definitions are default-deny (`resolve_widget`): no derivable dataset or no `dataset` resource for it is a 403; then `validate_guest_inline_props` requires saved metrics or SIMPLE aggregates in `GUEST_AGGREGATES` on existing columns, groupable dimensions, SIMPLE filters on existing columns, `rowLimit` between 1 and `GUEST_INLINE_ROW_LIMIT` (10000), an existing `column`, and finally `find_sql_in_props` returning nothing. (Closes D5.)

SQL stored in a **saved** widget is its author's, checked when it was saved; it is served to a guest unchanged, the way a chart's SQL metric is on an embedded dashboard.

### 5.5 Reading definitions

- Saved widget (`raise_for_widget_read`): a guest needs a token naming the widget; otherwise admin, the creator, or read access to the dataset it binds. A widget that binds no dataset is readable by its creator and admins only. Change and delete: creator or admin, never a guest. (Closes D3.)
- Dashboard V2 document (`can_read_document`): admin, editor, viewer, or an embedded guest whose token names the dashboard; anyone else needs access to every dataset the document binds, and a document binding none is for editors and viewers only. The same rule decides whether a dashboard export carries `metadata.v2_document`. See `05-dashboard-v2-api-contract.md` sections 3.2 and 6.1.

### 5.6 Free-form JSON: ECharts options and AG Grid column definitions

An ECharts `option` and AG Grid `columnDefs` are written by one principal and drawn in another's browser, so a definition is accepted only when it is declarative. The rules live in `superset/widgets/safety.py` and run inside the control models (`superset/widgets/controls.py`: the `echarts_options` and `column_defs` field validators), which means on every write path: the validate route, saved widgets, Dashboard V2 documents and imports. They reject; they do not rewrite.

| Input | Accepted | Rejected |
|---|---|---|
| any string | up to 20000 characters | HTML markup (`<` followed by a letter, `!`, `/` or `?`); `javascript:`, `vbscript:`, `data:`, `livescript:` URLs (after dropping control characters and spaces) |
| `echartsOptions` (`echarts_option_problem`) | top-level keys from `ECHARTS_OPTION_KEYS` (canvas-only components); below them any JSON of scalars; `toolbox.feature` limited to `dataZoom`, `magicType`, `restore`, `saveAsImage`; a `formatter` / `*Formatter` that is a text template (or an object of templates); `link` / `sublink` that are http(s), mailto or relative | any other top-level component; keys that reach the DOM or run code wherever they sit (`ECHARTS_FORBIDDEN_KEYS`, for example `graphic`, `dataView`, `extraCssText`, `className`, `appendTo`) and DOM event handlers (`onclick`, ...); a formatter holding function source; nesting deeper than 32 levels or more than 20000 values; non-JSON leaves |
| `columnDefs` (`column_defs_problem`) | at most 500 flat objects whose keys all come from `AG_GRID_COLUMN_SETTINGS` with the listed type (text up to 500 characters, numbers 0 to 100000, booleans; `sort` in `asc`/`desc`, `pinned` in `left`/`right`) | every other setting by name: renderers, value getters and formatters, class rules, anything AG Grid would compile or mount |

The frontend renderer keeps its own allowlist; the server rule is what guarantees that a stored definition is clean for any renderer.

### 5.7 What is still open

- D7: the V2 header's embed action and a dashboard-scoped guest data path for the widgets of an embedded V2 dashboard are not covered here; check the frontend inventory before relying on V2 embedding.
- D9, D10 and the fork deployment items of section 3 (7) (guest role, `CORS_OPTIONS`, hook) are deployment and follow-up work, not verified in this section.
- Version restore reverts a V2 dashboard's document together with its revision and does not validate it again (`05-dashboard-v2-api-contract.md` section 6.1).
