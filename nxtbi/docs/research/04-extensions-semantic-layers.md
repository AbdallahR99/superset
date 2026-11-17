# 04 - Extensions, classic customization, semantic layers, assets-as-code, multi-tenancy

Scope: fork at `f3f3d10d5c` (2026-11-16, master after 7.0.0rc2). Read-only research; nothing was run.
Labels: **VIC** = VERIFIED-IN-CODE, **DOC** = DOCS-CLAIMED, **UNV** = UNVERIFIED.
Lifecycle uses the fork's own flag annotations (`superset/config.py:714-722`: development / testing / stable / deprecated).

## 0. Verdict for the demo

| Topic | Lifecycle on this commit | Practical for the demo? |
|---|---|---|
| Extensions framework (`ENABLE_EXTENSIONS`) | EXPERIMENTAL (`@lifecycle: development`, `config.py:786-788`); packages are `0.1.0`, "Development Status :: 3 - Alpha" (`superset-core/pyproject.toml:20,34`, `superset-extensions-cli/pyproject.toml:20,33`) | Yes, **backend-only** "hello NxtBI" (REST endpoint, optionally MCP tool) with zero Node toolchain. A UI panel needs npm >= 10.8.2 + webpack and only lands in SQL Lab. |
| Semantic layers (`SEMANTIC_LAYERS`) | EXPERIMENTAL (`@lifecycle: development`, `config.py:774-776`); provider SDK called "unreleased" in its own docs | Show as a roadmap item only. **No provider ships in-tree**, so the UI has nothing to connect to unless we write a provider. |
| Native dataset semantic layer (metrics, calculated columns, certification, currency, Jinja) | STABLE (no flag, except `DATASET_FOLDERS` = development, `ENABLE_TEMPLATE_PROCESSING` = stable/off) | Yes - this is the demo's semantic story. |
| Assets as code (YAML ZIP, CLI, `/api/v1/assets/*`) | STABLE | Yes. |
| Version history + soft delete | BETA-TESTING (`VERSION_HISTORY`, `SOFT_DELETE` both `@lifecycle: testing`, default **True**, `config.py:766-773,814-820`) | Yes, on by default. No git-sync. |
| `DYNAMIC_PLUGINS` | BETA-TESTING per annotation (`config.py:860-862`), effectively legacy/undocumented | No. |
| Multi-tenancy | Not a product feature (no docs hit for "multi-tenan*" in `docs/`) | Demo via roles + RLS + per-tenant deployment narrative. |

## 1. Extensions framework

### 1.1 Pieces (all VIC)

| Piece | Where | Notes |
|---|---|---|
| Backend SDK `apache-superset-core` 0.1.0 | `superset-core/src/superset_core/{common,extensions,mcp,queries,rest_api,semantic_layers,tasks}` | Abstract decorators/DAOs/models; host injects implementations at startup (`superset/core/api/core_api_injection.py:164-281`, `superset/initialization/__init__.py:640-655`). Hard dependency of Superset (`pyproject.toml:37-38`, `requirements/base.txt:3`). |
| Frontend SDK `@apache-superset/core` 0.1.0 | `superset-frontend/packages/superset-core/src/{authentication,chat,commands,contributions,editors,extensions,menus,navigation,sqlLab,storage,theme,translation,views,components}` | Shared to extensions as a Module Federation singleton. |
| CLI `apache-superset-extensions-cli` 0.1.0 (`superset-extensions`) | `superset-extensions-cli/src/superset_extensions_cli/cli.py` | Commands: `init` (:792, flags `--publisher --name --display-name --version --license --frontend/--no-frontend --backend/--no-backend`), `validate` (:314), `update` (:461), `build` (:556), `bundle [-o]` (:595), `dev` (:636). In Superset dev extras only (`pyproject.toml:324-325`). |
| Host loader | `superset/extensions/utils.py:326-387` (`get_extensions`), `discovery.py:31-93`, `initialization/__init__.py:657-702` | In-memory importer inserted at `sys.meta_path[0]` (`utils.py:72-158`); entrypoint eagerly imported inside `extension_context(manifest)`. A failing extension is logged and skipped, app still boots. |
| Host REST | `superset/extensions/api.py:74,119,167` | `GET /api/v1/extensions/`, `/<publisher>/<name>`, `/<publisher>/<name>/<path:file>` (serves remoteEntry + chunks). Registered only when flag is on (`initialization/__init__.py:335-340`). No upload/install endpoint. |
| Storage API | `superset/extensions/storage/api.py:127-708`; migration `2026-07-07_12-00_e5f6a7b8c9d0_add_extension_storage_table.py` | `/api/v1/extensions/<publisher>/<name>/storage/{ephemeral,persistent}/<key>`; writes are CSRF-protected (`UPDATING.md:271-276`). |
| UI | Manage > Extensions menu (`initialization/__init__.py:474-483`); `superset-frontend/src/extensions/ExtensionsStartup.tsx` (mounted in `src/views/App.tsx:261`), `ExtensionsLoader.ts`, `ExtensionsList.tsx` | Frontend loads remotes after login when `EnableExtensions` flag is on. |
| Docs | `docs/developer_docs/extensions/` (overview, quick-start, architecture, contribution-types, dependencies, deployment, development, mcp, security, storage, tasks, registry, `extension-points/{sqllab,editors,chat,semantic-layers}.md`) | Site path `/developer-docs/extensions/...`. |

### 1.2 Config keys (VIC)

| Key | Default | Evidence | Meaning |
|---|---|---|---|
| `FEATURE_FLAGS["ENABLE_EXTENSIONS"]` | `False` | `config.py:786-788` | **Startup** setting; gates loader, REST APIs, menu. Not runtime-toggleable (`docs/admin_docs/configuration/feature-flags.mdx:80`). |
| `LOCAL_EXTENSIONS` | `[]` | `config.py:3732`, `utils.py:329-354` | List of directories, each containing a `dist/` folder. Wins over `EXTENSIONS_PATH` on id clash (`utils.py:372-385`). |
| `EXTENSIONS_PATH` | `None` | `config.py:3733`, `discovery.py:52-91` | Directory scanned (non-recursive) for `*.supx`. |
| `EXTENSION_DENYLIST` | `[]` | `config.py:3734-3738`, `utils.py:267-277` | `"<id>"` or `"<id>@<version>"`. |
| `EXTENSION_VERSION_POLICY` | `{}` | `config.py:3740-3744`, `utils.py:280-305` | Minimum PEP 440 version per id; unparsable = refused. |
| Hot reload | debug only | `superset/app.py:111-113`, `extensions/local_extensions_watcher.py:240-256,123-144` | watchdog on `LOCAL_EXTENSIONS` dirs touches `superset/extensions/.reload_trigger`; Flask reloader restarts. No hot reload under gunicorn or for `.supx`. |

Docker dev config already sets `ENABLE_EXTENSIONS: True`, `SEMANTIC_LAYERS: True`, `DATASET_FOLDERS: True` and `EXTENSIONS_PATH = "/app/docker/extensions"` (`docker/pythonpath_dev/superset_config.py:116-123`); every compose file mounts `./docker:/app/docker`, and `docker-compose.yml:37` also mounts `./local_extensions:/app/local_extensions`. Neither `docker/extensions/` nor `local_extensions/` exists in the repo, so nothing loads by default (discovery only logs a warning, `discovery.py:43-47`). Overrides go in `docker/pythonpath_dev/superset_config_docker.py` (`superset_config.py:147-150`).

### 1.3 Bundle format (VIC)

- `.supx` = plain zip of the `dist/` folder (`cli.py:620-626`). Allowed entries only: `manifest.json`, `frontend/dist/**`, `backend/src/**`; anything else raises "Unexpected file in bundle" (`superset/extensions/utils.py:43-48,206-226`).
- `manifest.json` schema = `superset_core.extensions.types.Manifest` (`superset-core/src/superset_core/extensions/types.py:38-152`): `publisher`, `name`, `displayName`, `version`, optional `license`, `description`, `dependencies`, `permissions`, `frontend{remoteEntry,moduleFederationName}`, `backend{entrypoint}`. Extension id = `publisher.name`.
- Pitfall: `.supx` discovery reads `manifest_data["id"]` literally (`discovery.py:63-68`); a hand-written manifest must include `"id": "<publisher>.<name>"`. `LOCAL_EXTENSIONS` does not need it (in-repo proof: `tests/e2e_extensions/semantic_stub/dist/manifest.json`).
- `permissions` in the manifest is declarative only; no host code under `superset/extensions/` or `superset/core/api/` reads it (grep, VIC).

### 1.4 Contribution points

| Contribution | API | Where it surfaces | Evidence |
|---|---|---|---|
| Views | `views.registerView(desc, location, factory)` | SQL Lab only: `sqllab.rightSidebar`, `sqllab.panels`, `sqllab.statusBar` (+ menus on `leftSidebar`, `editor`, `results`, `queryHistory`) | `superset-frontend/src/SqlLab/contributions.ts:42-48`; type `ViewContributions { sqllab? }` in `packages/superset-core/src/contributions/index.ts:57-59` |
| Commands / menus | `commands.registerCommand`, `menus.registerMenuItem(..., 'primary'|'secondary'|'context')` | SQL Lab toolbars | `docs/developer_docs/extensions/contribution-types.md:48-91` |
| Editors | `editors.registerEditor` | Replaces Ace per language everywhere | `extension-points/editors.md` |
| Chat | `chat.registerChat(desc, Trigger, Panel)` | Global floating/docked panel, one active chat | `superset-frontend/src/core/chat/ChatHost.tsx`; `extension-points/chat.md` |
| REST API | `@api(id,name,...)` on `RestApi` | `/extensions/<publisher>/<name>/[resource_name]/...`, FAB permissions auto-created | `core_api_injection.py:179-227` |
| MCP tools / prompts | `@tool`, `@prompt` from `superset_core.mcp.decorators` | MCP service | `superset-core/src/superset_core/mcp/decorators.py:51`; `docs/developer_docs/extensions/mcp.md` |
| Semantic layer provider | `@semantic_layer(id,name)` on `SemanticLayer` | Type id `extensions.<publisher>.<name>.<id>` in registry | `core_api_injection.py:259-281` |
| Tasks | `@task` (needs `GLOBAL_TASK_FRAMEWORK`, testing) | Task framework | `docs/developer_docs/extensions/tasks.md` |
| **Chart types, dashboard components, Explore controls, nav/menu entries** | none | **Not contribution points on this commit** | Only `sqllab` scope exists in `contributions/index.ts` |

Module federation (DOC + VIC): each extension's webpack config exposes exactly `./index` -> `./src/index.tsx`, shares `react`, `react-dom`, `antd`, `@apache-superset/core` as singletons with `import: false`, and uses `publicPath /api/v1/extensions/<publisher>/<name>/` (`docs/developer_docs/extensions/quick-start.md:224-298`; template `superset-extensions-cli/.../templates/frontend/webpack.config.js.j2`).

Security model (DOC, `docs/developer_docs/extensions/security.md:24-35`): off by default; **no sandbox** - extension code runs in-process with full host privileges; admins vet extensions like any PyPI/npm dependency; sandboxing is "planned" in a future SIP; third-party extension bugs are not Superset vulnerabilities. Supply-chain controls = denylist + minimum-version policy only (VIC, 1.2). The quick-start itself states "No complete real-world extension is bundled in this repository yet" (`quick-start.md:516`); community list is `registry.md` (9 SQL Lab extensions, unvetted).

### 1.5 Minimal "hello NxtBI" (backend-only, no frontend toolchain)

Proven pattern: the e2e stub is a hand-authored `dist/` loaded through `LOCAL_EXTENSIONS` (`tests/integration_tests/superset_test_config_semantic.py:33-41`, `.github/workflows/superset-e2e.yml:256-269`).

```
nxtbi/extensions/hello-nxtbi/
  dist/
    manifest.json                                   # publisher "nxtbi", name "hello-nxtbi", displayName, version,
                                                    # backend.entrypoint "nxtbi_hello.entrypoint"
    backend/src/nxtbi_hello/__init__.py
    backend/src/nxtbi_hello/entrypoint.py           # from .api import HelloNxtbiAPI  (import triggers @api)
    backend/src/nxtbi_hello/api.py                  # @api(...) class HelloNxtbiAPI(RestApi): @expose("/message") @protect() @safe
```

Config: `FEATURE_FLAGS["ENABLE_EXTENSIONS"]=True`, `LOCAL_EXTENSIONS=["/app/local_extensions/hello-nxtbi"]` (compose already mounts `./local_extensions`). Result: `GET /extensions/nxtbi/hello-nxtbi/message` (session or JWT auth, role needs the generated permission), listed at `GET /api/v1/extensions/` and Manage > Extensions.

- Can it be built without Node? **Yes if authored by hand** (VIC: loader only needs `dist/manifest.json` + `dist/backend/src/**`). **No via the CLI**: `validate` calls `validate_npm()` unconditionally (`cli.py:314-317`, min npm `10.8.2` in `constants.py:19`) and `build`/`bundle` invoke `validate` (`cli.py:558,597`), even for `--no-frontend` projects.
- To ship as `.supx`: zip the contents of `dist/` (manifest at zip root), add `"id"` to the manifest, drop into `EXTENSIONS_PATH`.
- Entry-point module path is free-form for the host (stub uses flat `superset_e2e_semantic_stub`); the `backend/src/<publisher>/<name>/entrypoint.py` convention is only enforced by the CLI (`cli.py:367-385`). Avoid a top-level package name that collides with a real importable package: the in-memory finder sits first on `sys.meta_path` and synthesizes namespace packages (`utils.py:92-120`).

## 2. Classic customization without a fork (all STABLE config hooks unless noted; VIC)

| Hook | `config.py` line | Use for NxtBI |
|---|---|---|
| `APP_NAME`, `APP_ICON`, `LOGO_TARGET_PATH`, `LOGO_TOOLTIP`, `LOGO_RIGHT_TEXT`, `FAVICONS` | 499, 505, 513, 520, 524, 131 | Branding |
| `THEME_DEFAULT`, `THEME_DARK`, `THEME_DEFAULT_MODE`, `ENABLE_UI_THEME_ADMINISTRATION` | 1322, 1337, 1365, 1362 | Theming (see file 05) |
| `EXTRA_CATEGORICAL_COLOR_SCHEMES`, `EXTRA_SEQUENTIAL_COLOR_SCHEMES` | 1237, 1394 | Brand palettes |
| `D3_FORMAT`, `D3_TIME_FORMAT`, `CURRENCIES` | 643, 701, 703 | Locale number/date/currency |
| `FLASK_APP_MUTATOR` | 2397 | Arbitrary app mutation (before/after request, extra routes) |
| `BLUEPRINTS` | 2464 | Custom Flask blueprints (simplest "hello NxtBI" endpoint without extensions) |
| `ADDITIONAL_MIDDLEWARE` | 1843 | WSGI middleware |
| `CUSTOM_SECURITY_MANAGER` | 255 | Subclass `SupersetSecurityManager` (OIDC/Keycloak mapping, custom access rules) |
| `JINJA_CONTEXT_ADDONS`, `CUSTOM_TEMPLATE_PROCESSORS` | 2374, 2382 | Custom SQL macros (need `ENABLE_TEMPLATE_PROCESSING`, stable, default off, `config.py:1004`) |
| `SQL_QUERY_MUTATOR`, `MUTATE_AFTER_SPLIT` | 2789, 2804 | Query tagging / `SET ROLE` per statement |
| `DB_CONNECTION_MUTATOR`, `DB_SQLA_URI_VALIDATOR`, `ENGINE_CONTEXT_MANAGER` | 2534, 2545, 2517 | Per-user/tenant connection rewriting |
| `EVENT_LOGGER`, `STATS_LOGGER`, `QUERY_LOGGER` | 96, 90, 1880 | Audit / metrics sinks |
| `GET_FEATURE_FLAGS_FUNC`, `IS_FEATURE_ENABLED_FUNC`, `COMMON_BOOTSTRAP_OVERRIDES_FUNC` | 1200, 1208, 1219 | Per-user/tenant flags and bootstrap payload |
| `EXTRA_RELATED_QUERY_FILTERS`, `EXTRA_DYNAMIC_QUERY_FILTERS` | 3578, 3630 | Restrict user/role pickers per tenant |
| `GUEST_TOKEN_VALIDATOR_HOOK` | 3452 | Embedded guest-token policy |
| Custom DB engine spec | `superset/db_engine_specs/__init__.py:80-92` | Python entry-point group `superset.db_engine_specs`; SQLAlchemy dialects via `sqlalchemy.dialects` (:217). No fork needed, but needs a pip-installed package in the image. |
| Custom viz plugin | `docs/developer_docs/contributing/howtos.md:84-108` | npm package registered in `superset-frontend/src/visualizations/presets/MainPreset.ts` => **requires a frontend rebuild / custom image**. |
| `DYNAMIC_PLUGINS` | `config.py:860-862` (`testing`, off) | Legacy model/view exist (`superset/models/dynamic_plugins.py`, `superset/views/dynamic_plugins.py`), no docs in `docs/`. Do not use. `CHART_PLUGINS_EXPERIMENTAL` is `development` (:745-747). |

## 3. Semantic layers

### 3.1 New external "semantic layer / semantic view" (SIP-182) - EXPERIMENTAL

| Aspect | Finding | Evidence |
|---|---|---|
| SIP | SIP-182 "Semantic Layer Support in Apache Superset" (not cited in-repo) | DOC: https://github.com/apache/superset/issues/35003 ; extensions referred to as SIP-151 in other SIPs (UNV number) |
| First shipped | Commit `cb53745d43` "feat: semantic layer extension (#37815)" 2026-05-05; in tags 7.0.0rc1/rc2, not 6.1.0. Extensions POC `a8be5a5a0c` is in 6.1.0. | `git tag --contains` |
| Flags | `SEMANTIC_LAYERS` (development, off), `SEMANTIC_LAYER_CONTAINMENT_CACHE` (development, off; needs shared `DATA_CACHE_CONFIG` + Redis `DISTRIBUTED_COORDINATION_CONFIG`) | `config.py:774-782` |
| Other config | `SEMANTIC_LAYER_CACHE_NAMESPACE` (:113), `SEMANTIC_LAYER_DOCUMENTATION_URL` (:3045), `SEMANTIC_LAYER_ALLOW_INTERNAL_HOSTS` (:3133), `SEMANTIC_VIEW_BULK_CREATE_MAX_VIEWS`=100, `SEMANTIC_VIEW_BULK_CREATE_TIMEOUT`=30s | `config.py`; `UPDATING.md:244-247` |
| Models | `semantic_layers` (uuid PK, `type`, encrypted `configuration`, `cache_version`, `perm`) and `semantic_views` (int id + uuid, encrypted `configuration`, FK `semantic_layer_uuid`) | `superset/semantic_layers/models.py:194-216,334-372` |
| Migrations | `2025-11-04_11-26_33d7e0e21daa_add_semantic_layers_and_views.py`, `2026-09-03_..._retire_semantic_layer_views_connections_pvms.py`, `2026-10-08_..._add_semantic_layer_cache_version.py` | `superset/migrations/versions/` |
| REST | `/api/v1/semantic_layer/` (`types`, `schema/configuration`, `<uuid>/schema/runtime`, `<uuid>/views`, CRUD, `<uuid>/clear_cache`, `connections/`) and `/api/v1/semantic_view/` (bulk POST, PUT, DELETE, `<pk>/structure`) | `superset/semantic_layers/api.py:257-276,375-656,819-1606` |
| Flag semantics | APIs are **always registered**; flag checked at runtime (404 when off); `superset init` must run to register permissions | `initialization/__init__.py:327-328`; `UPDATING.md:401-414` |
| DAO / commands | `superset/daos/semantic_layer.py`, `superset/commands/semantic_layer/{create,update,delete}.py` | VIC |
| UI | `superset-frontend/src/features/semanticLayers/SemanticLayerModal.tsx` (JSON-Schema-driven form), `features/semanticViews/{AddSemanticViewModal,SemanticViewEditModal}.tsx`; semantic views listed with datasets; datasource type `semantic_view` | `superset/utils/core.py:272`; `docs/docs/using-superset/semantic-layer-connections.mdx` |
| Query path | `superset/semantic_layers/mapper.py` (QueryObject -> `SemanticQuery`), `execution.py`, provider HTTP via host `ProviderTransport` (SSRF/budget controlled, `transport.py`) | VIC |
| Limits | No Samples, no drill-to-detail (`models.py:343-347`); feature opt-ins `ADHOC_COLUMN_EXPRESSIONS`, `ADHOC_EXPRESSIONS_IN_ORDERBY`, `GROUP_LIMIT`, `GROUP_OTHERS`, `ROW_OFFSET` (`superset_core/semantic_layers/view.py:33-44`); only `ExecutionMethod.CONNECTION` (shared service credentials, guests' row rules refused) | `extension-points/semantic-layers.md:210-222` |
| MCP | `list_semantic_views`, `list_metrics`, `get_table` span datasets + semantic views | `superset/mcp_service/app.py:203-208` |
| Import/export | Bundles carry only **references** (`datasource_ref: {type: semantic_view, uuid}`); layer/view config and credentials are never exported | `docs/admin_docs/configuration/importing-exporting-datasources.mdx:115-145`; `superset/semantic_layers/import_export.py` |

**In-tree implementations: none for production.** The registry is an empty dict (`superset/semantic_layers/registry.py:24`) filled only by `@semantic_layer`. The only decorated classes in the repo are test fixtures: `superset-core/tests/semantic_layers/example_provider.py:109` and `tests/e2e_extensions/semantic_stub/dist/backend/src/superset_e2e_semantic_stub/__init__.py:236` ("Never ship"). Registration is **only** through the extensions loader (backend entrypoint importing a decorated class) - there is no Python entry-point group and no config list for providers (VIC: grep for `entry_points` finds only DB engine specs / SQLAlchemy dialects). Hence a provider requires `ENABLE_EXTENSIONS` + `SEMANTIC_LAYERS`.

Provider contract (VIC, `superset-core/src/superset_core/semantic_layers/layer.py:80-244`, `view.py:47-254`): `SemanticLayer.from_configuration(configuration, *, cache_token, context, transport, credentials=None)`, `get_configuration_schema`, `get_runtime_schema`, `get_semantic_views`, `get_semantic_view`; `SemanticView.uid/get_dimensions/get_metrics/get_values/get_table/get_row_count/get_compatible_metrics/get_compatible_dimensions` returning Arrow-backed `SemanticResult`. The 303-line stub is the smallest working reference. Docs repeatedly flag churn: "The unreleased SDK ...", "will be unified before any `superset-core` release" (`extension-points/semantic-layers.md:186,255-256`), plus several breaking SDK entries in `UPDATING.md:144-168,364-374`.

Cube / dbt MetricFlow / Snowflake semantic views / Malloy: **no in-tree integration and no documented one**. Mentions are illustrative only: docs sentence "such as dbt Semantic Layer or Cube" (`docs/docs/using-superset/creating-your-first-dashboard.mdx:201-202`), decorator docstring examples "snowflake"/"dbt" (`superset_core/semantic_layers/decorators.py:28-37`), MetricFlow-shaped comments in the UI (`AddSemanticViewModal.tsx:766,921`, `jsonFormsHelpers.tsx:272-283,370`). No "malloy", "wren" or Cube engine spec anywhere (grep). Out-of-tree providers may exist (UNV).

### 3.2 Native semantic layer (datasets) - STABLE, the demo path

| Capability | Evidence | Status |
|---|---|---|
| Saved metrics (`SqlMetric.expression`, `d3format`, `currency`, `warning_text`, `extra`) | `superset/connectors/sqla/models.py:1741-1761` | STABLE |
| Calculated columns (`TableColumn.expression`), temporal flags | `models.py:1360-1389` | STABLE |
| Certification (`CertificationMixin` on columns and metrics) | `models.py:1360,1741`; `creating-your-first-dashboard.mdx:165` | STABLE |
| Virtual (SQL) datasets, `fetch_values_predicate`, `template_params` | `models.py:1958,1981` | STABLE |
| Jinja in SQL/metrics | `ENABLE_TEMPLATE_PROCESSING` stable, default off (`config.py:1004`) | STABLE (opt-in) |
| Dataset folders (`SqlaTable.folders`) | `models.py:1985`; flag `DATASET_FOLDERS` development (`config.py:751-753`), on in docker dev config | EXPERIMENTAL |
| `is_managed_externally` / `external_url` (read-only-in-UI marker for assets owned by code) | `models.py:390-396` | STABLE |
| MCP `query_dataset` over saved metrics/dimensions | `superset/mcp_service/app.py:203` | see MCP research file |

### 3.3 Cube today without the new API

Cube Core exposes a Postgres-wire SQL API (`CUBEJS_PG_SQL_PORT`, commonly 15432, credentials `CUBEJS_SQL_USER`/`CUBEJS_SQL_PASSWORD`) - DOC: https://docs.cube.dev/reference/core-data-apis/sql-api . Superset connects with its ordinary PostgreSQL engine spec (`postgresql://<user>:<pass>@cube:15432/<db>`), each cube/view becomes a physical dataset, and measures are wrapped as saved metrics (e.g. `MEASURE(orders.count)` or a matching aggregate). No Superset code is Cube-specific (VIC: grep). Behavioural limits of Cube's SQL API with Superset-generated SQL (joins, subqueries, time grains) are UNV here.

## 4. Assets as code / versioning

| Item | Finding | Evidence |
|---|---|---|
| Bundle format | ZIP of YAML: `metadata.yaml` (`version`, `type`, `timestamp`) + `databases/`, `datasets/`, `charts/`, `dashboards/`, `queries/`, `annotation_layers/`, `themes/`, tags | `superset/commands/export/assets.py:42-97`; `commands/importers/v1/assets.py:88-96` |
| CLI (click normalizes `_`/`-`, both spellings work: `superset/cli/main.py:35-58`) | `export-dashboards [-f]`, `export-datasources [-f]`, `import-dashboards -p <zip> [-u]`, `import-datasources -p <zip> [-u]`, `import-directory <dir> [-o/--overwrite] [-f/--force] [-u]`, legacy `legacy-export-dashboards`, `legacy-import-dashboards`, `legacy-export-datasources`, `legacy-import-datasources`, `legacy-export-datasource-schema` | `superset/cli/importexport.py:36-419` |
| REST | `GET /api/v1/assets/export/`, `POST /api/v1/assets/import/` (form fields `bundle`, `passwords`, `ssh_tunnel_*`, `sparse`, `overwrite`); per-resource `/api/v1/{dashboard,chart,dataset,database,saved_query}/{export,import}/` | `superset/importexport/api.py:53-223` |
| Overwrite semantics | Assets import: `overwrite` defaults **true** ("will overwrite everything"); with `overwrite=false` any existing UUID is a validation error. Dashboard import: `overwrite` updates the dashboard only; related charts/datasets/databases are overwritten **only with `overwrite_all=true`**. CLI `import-dashboards` hard-codes `overwrite=True` without `overwrite_all`, so existing charts/datasets are NOT refreshed. `import-directory --overwrite` uses the examples importer (no saved queries/tags). | `importexport/api.py:203-206`; `commands/importers/v1/assets.py:81-86,302-340`; `commands/dashboard/importers/v1/__init__.py:81-97,178-180,248-252`; `dashboards/api.py:3298-3312`; `cli/importexport.py:176`; `importing-exporting-datasources.mdx:88-91` |
| Doc/code mismatch | Docs say the dashboard "overwrite" option replaces charts (`importing-exporting-datasources.mdx:106-113`); code requires `overwrite_all` since #34880 (2026-07-20). Trust the code. | VIC vs DOC |
| UUID stability | Assets keyed by UUID across environments; POST responses return `uuid` | `importing-exporting-datasources.mdx:169-181` (DOC) + UUID lookup in `assets.py:320-340` (VIC) |
| Secrets | DB passwords are masked on export and supplied at import through the `passwords` JSON map | `importexport/api.py:125-160` |
| Soft-delete interaction | Importing a UUID that matches a soft-deleted dashboard restores it even without `overwrite` | `dashboards/api.py:3197-3204` |
| Version history | Chart + dashboard history panels, dataset history via API; `GET /api/v1/{chart,dashboard,dataset}/<uuid>/versions/`, `.../activity/`, `POST .../versions/<version_uuid>/restore`; SQLAlchemy-Continuum shadow tables; `ENABLE_VERSIONING_CAPTURE` (default true), `VERSION_HISTORY_RETENTION_DAYS` (default 30), restore refused for `is_managed_externally`; edit-gated | `config.py:814-820,1915-1941`; `docs/docs/using-superset/version-history.mdx:28-58`; `UPDATING.md:973-985,1365,1549,1939-1964`; migration `2026-05-28_19-50_56cd24c07170_add_versioning_tables.py` (in 7.0.0rc1+) |
| Git sync | **None** in this repo (grep `git_sync|git-sync` in `superset/` = 0 hits). Git workflow = export ZIP/unzipped YAML in a repo + CI calling `/api/v1/assets/import/` or `import-directory`. | VIC |
| Limitations | No diff/plan/dry-run; no deletion of assets absent from the bundle; roles, users, RLS rules, alerts/reports, semantic layer/view configs are not in the bundle; `import-directory` skips saved queries and tags | VIC/DOC as above |

## 5. Multi-tenancy

| Mechanism | Exists? | Evidence / note |
|---|---|---|
| Roles + FAB permissions (Admin/Alpha/Gamma/sql_lab/Public, custom roles) | Yes, STABLE | `docs/admin_docs/security/security.mdx:10-64,585-625` |
| Subjects (user / group / role) as editors and viewers | Yes; `ENABLE_VIEWERS`, `ASSIGN_CREATOR_GROUPS_AS_VIEWERS` are testing/off | `security.mdx:169-190`; `config.py:956,965` |
| Datasource / schema / catalog permissions | Yes, STABLE | `superset/security/manager.py:336,2701-2763` |
| Row Level Security (regular/base filters, group keys, role/subject scoped) | Yes, STABLE; `RLS_IN_SQLLAB` testing/off | `connectors/sqla/models.py:3443-3455`; `security.mdx:627-640`; `config.py:892` |
| Guest-token RLS for embedding | Yes (`EMBEDDED_SUPERSET` stable/off) | `config.py:1000,3432-3475` |
| DB user impersonation (`Database.impersonate_user`), OAuth2 per-user DB credentials | Yes | `superset/models/core.py:290`; `config.py:3094-3130` |
| Per-tenant hooks | `DB_CONNECTION_MUTATOR`, `SQL_QUERY_MUTATOR`, `GET_FEATURE_FLAGS_FUNC`, `VERSIONING_CAPTURE_PREDICATE`, callable `SEMANTIC_LAYER_CACHE_NAMESPACE` (comments explicitly anticipate tenant-aware hosts) | `config.py:110-113,1924-1929,2534,2789` |
| Sub-path deployment | Yes: `SUPERSET_APP_ROOT` env / `APPLICATION_ROOT` / `create_app(superset_app_root=...)`; `FAB_API_SWAGGER_UI_SUPERSET_APP_ROOT` for Swagger | `superset/app.py:59-94`; `docs/admin_docs/configuration/configuring-superset.mdx:369-420`; `config.py:539-544` |
| Workspaces / organizations / tenant column on assets / per-tenant metadata isolation | **No** | No model or doc; "workspace" in `config.py` only describes a host concept for cache namespaces. Hard isolation = one deployment (metadata DB + cache prefix) per tenant, optionally under different app roots. |

## 6. Future integration opportunities (documentation only - nothing to build)

| Target | Integration point on this commit | Effort | Maturity / risk |
|---|---|---|---|
| Cube Core (A) | Database connection to Cube's Postgres-wire SQL API; datasets + saved metrics wrapping Cube measures | Low (config + dataset YAML) | Superset side STABLE; Cube SQL-API quirks UNV |
| Cube Core (B) | Backend-only extension registering `@semantic_layer` provider that calls Cube REST (`/meta`, `/load`) through `ProviderTransport` | High (full `SemanticLayer`/`SemanticView` contract, filters, grains, caching identity) | EXPERIMENTAL x2 (`ENABLE_EXTENSIONS` + `SEMANTIC_LAYERS`), SDK unreleased and breaking between commits |
| Wren | Same two shapes: SQL endpoint as a database if Wren exposes a wire-compatible one (UNV), otherwise `@semantic_layer` provider or MCP-to-MCP composition | Medium-High | UNV on Wren's side; Superset side as above |
| Schema-Sense | Push descriptions, certification, metrics into native datasets via `PUT /api/v1/dataset/<id>` or assets YAML import; optionally an extension REST endpoint / MCP tool for lookups | Low-Medium | Native dataset API STABLE; extension route EXPERIMENTAL; product capabilities UNV |
| Custom NxtBI semantic layer | Phase 1: compile NxtBI models to dataset YAML (metrics, calculated columns, folders) and import as managed-externally assets. Phase 2: `@semantic_layer` provider extension once the SDK is released | Phase 1 Low-Medium; Phase 2 High | Phase 1 STABLE primitives; Phase 2 EXPERIMENTAL |

## 7. Unverified items

- Extensions actually loading inside the standalone MCP service process (not traced).
- Runtime behaviour of the hello extension on Windows/Docker Desktop (nothing was run); FAB permission names generated for extension APIs.
- SIP-151 as the extensions SIP number (seen only in a search snippet); out-of-tree providers for dbt/Cube/Snowflake.
- Cube SQL-API compatibility with Superset-generated SQL; Wren and Schema-Sense interfaces.
