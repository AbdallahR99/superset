# 04 - Git integration strategy for the Widget Framework (apache/superset PR #44471)

Read-only analysis, 2026-11-17. Nothing was built, installed or run except read-only git and two throwaway scripts in the session scratchpad.
Legend: **PR** = `E:/Work_Lab/nxtbi-superset-pr44471` (detached `71be990689`), **FORK** = `E:/Work_Lab/nxtbi-superset` at ref `master` (`f3f3d10d5c`) unless another ref is named. `BASE` = merge-base `6856d0fc67`. "UNVERIFIED" = not checked by a command.

## 0. Ref facts (measured)

| Ref | SHA | Note |
|---|---|---|
| `master` | `f3f3d10d5c` | = `upstream/master` today (`git ls-remote upstream`) |
| `nxtbi-demo` | `976e975e99` | master + 2 commits, 45 files, all under `nxtbi/` (purely additive) |
| `feature/nxtbi-arabic-rtl` | `976e975e99` | **same commit as nxtbi-demo**: the RTL work is 100 % uncommitted (18 modified + 8 untracked paths) |
| `upstream/dashboard-v2` | `ce0934a4cb` | unchanged upstream since 2026-09-03 |
| `upstream/pr-44471` | `71be990689` | `refs/pull/44471/head` still this SHA upstream (no update since 2026-09-25); `refs/pull/44471/merge` exists, so the PR is open against `dashboard-v2`, not master |
| `BASE` | `6856d0fc67` | 2026-07-27; PR = BASE + 10 (dashboard-v2) + 13 (PR); master = BASE + 2688 |

`git diff BASE upstream/pr-44471`: 287 files, +46108/-90 = **240 added (A), 47 modified (M), 0 deleted, 0 renamed**.
None of the PR numbers #42865 #43065 #43096 #43262 #43400 #43588 #43487 #43833 #43093 #44471 appears in `git log master --grep` (0 hits each). Master has no `src/core/dashboard`, `src/core/clientTools`, `packages/superset-widgets`, `superset/widgets`, `superset/dashboard_v2`, `superset/mcp_oauth`. **Nothing of dashboard-v2 has landed on master.**

## 1. The 23 commits

A/M/D = files added/modified/deleted versus the commit's parent. Class: **DV2** dashboard v2 builder, **WF** widget framework, **MCP** MCP server side, **AI** chat / agent / Claude-artifact only, **MIX** mixed.

| # | SHA | Subject (author) | A/M/D | Class | Main areas |
|---|---|---|---|---|---|
| 1 | `ab59385427` | First milestone (Molina) | 19/14/0 | DV2 | `src/core/dashboard` 17, superset-core 4, routes, RightMenu, `ExtensionsStartup.tsx`+`Namespaces.ts` (adds `dashboard` namespace), `initialization`, `views/dashboard/views.py`, package.json+lock |
| 2 | `116142e57f` | editing UI and layout modes #42865 (Martellucci) | 22/13/0 | DV2 | `src/core/dashboard` 15, `pages/DashboardBuilderV2` 16, `AntdEnhanced.tsx` |
| 3 | `46be6a032d` | containers #43065 (Molina) | 7/21/1 | DV2 | `src/core/dashboard` 24, pages 6 |
| 4 | `368aa3df87` | gridstack layout #43096 (Molina) | 7/17/0 | DV2 | `gridstack` dep, jest mock, 6 playwright files |
| 5 | `df3c616ea4` | progressive widget schema disclosure #43262 (Brofeldt) | 28/32/0 | **MIX** WF+MCP | `superset/widgets/*`, `superset_core/widgets`, `core_api_injection.py`; MCP: `mcp_service/widgets` 5, `mcp_service/app.py`, 3 MCP tests |
| 6 | `ae0dc90f59` | filters #43400 (Molina) | 9/23/0 | WF/DV2 | `src/core/dashboard` 20, `jsonFormsHelpers`, builtin/controls |
| 7 | `12854abbee` | dataset-aware editing controls #43588 (Martellucci) | 25/30/0 | **MIX** WF+MCP | pages 18, `semantic_layers/config.py`, `DatasetSelect.tsx`; MCP: `mcp_service/widgets` 4 + app.py |
| 8 | `4716bbf0ee` | playwright selector #43487 (JUST.in DO IT) | 0/2/0 | DV2 test | playwright |
| 9 | `8e60d3abc4` | playwright selector #43833 (JUST.in DO IT) | 0/1/0 | DV2 test | playwright |
| 10 | `ce0934a4cb` | **client-side MCP tools API for chat #43093** (JUST.in DO IT) | 12/9/0 | **AI** (2 DV2 hunks) | `src/core/clientTools` 11, `src/core/chat` 3, `packages/superset-core/src/chat/index.ts`, `ExtensionsLoader.ts(+test)`, `ExtensionsStartup.tsx` |
| 11 | `6afb5f5843` | move widgets into `@apache-superset/widgets` (Yavuz) | 14/27/2 | WF | new package 24, tsconfig, jest, package.json+lock, `check-custom-rules.js` |
| 12 | `637805854a` | persist dashboards as documents (Yavuz) | 14/9/0 | DV2 (contaminated) | `superset/dashboard_v2/*`, `commands/dashboard_v2`, routes; **also registers `MCPOAuthView` in `initialization`** |
| 13 | `c9deadfe6f` | saved widgets + widget data API (Yavuz) | 12/8/0 | WF (contaminated) | `commands/widget`, `daos|models/saved_widget.py`, `widgets/data.py`, `security/manager.py`, `guest_token.py`, migration `3c9e1a7b5d2f`; **also adds `MCP_OAUTH_*` keys + mcp_oauth CSRF exemptions to `config.py`** |
| 14 | `98caf39499` | render widgets in host apps and artifacts (Yavuz) | 46/0/0 | **MIX** WF+AI | widgets `src/embed/*`, `example/*` (22); AI: `artifact/*` 6, `src/mcp/*` 3, `SupersetArtifactProvider`, `session.tsx` |
| 15 | `134f0c5956` | widget data over MCP + OAuth server (Yavuz) | 23/4/0 | **MCP/AI** | `superset/mcp_oauth/*` 5, `mcp_service/auth_oauth.py`, `mcp_config.py`, `server.py`, `app.py`, `mcp_service/widgets` 8, migration `8f2d4c6a1b3e`, 9 tests |
| 16 | `0769398090` | embed widgets contributed by extensions (Yavuz) | 5/4/0 | WF | `extensionHost|extensionLoader`, `superset/extensions/api.py`, cli webpack template, docs |
| 17 | `801ee8b5d9` | widget contract into `@apache-superset/core` (Yavuz) | 1/17/0 | WF | superset-core 4, widgets 10 |
| 18 | `0252cde0ff` | fix(mcp) OAuth writes as units of work (Yavuz) | 0/1/0 | **AI/MCP** | `mcp_oauth/service.py` only |
| 19 | `77170bc63f` | stop shipping balloons widget (Yavuz) | 0/6/1 | WF | widgets 3, core/dashboard 2, pages 2 |
| 20 | `d502195445` | keep example out of root tsc (Yavuz) | 0/1/0 | WF build | `tsconfig.json` |
| 21 | `6e99023802` | bad widget query = 400, unhardcode example (Yavuz) | 0/8/0 | WF | `commands/widget`, example |
| 22 | `888263bc1f` | example ad hoc aggregate from config (Yavuz) | 0/3/0 | WF example | example |
| 23 | `71be990689` | fix: widgets (Yavuz) | 0/14/0 | WF | widgets 7, `builtin.py`, `controls.py`, 3 tests |

**The 13 PR commits are not individually importable**: #12 imports `superset.mcp_oauth.views` (`git log -S MCPOAuthView -- superset/initialization/__init__.py` -> `637805854a`) but that module is only added by #15. The split was made after the fact, so per-commit bisecting is worthless.

### 1.1 Exclusion map (user scope: no AI / agents / CopilotKit / A2UI)

| Tier | Paths (PR) | Evidence / what the framework still needs |
|---|---|---|
| **AI-only, drop** | `superset-frontend/src/core/clientTools/**` (11); PR changes to `src/core/chat/{ChatProvider.ts,ChatProvider.test.ts,index.ts}`, `packages/superset-core/src/chat/index.ts` (+181), `src/extensions/ExtensionsLoader.ts(+test)` | Only `ce0934a4cb` touches them. Master has not changed any of these files since BASE, so "drop" = keep master's version. |
| **Mixed file** | `src/extensions/ExtensionsStartup.tsx` | Keep the `dashboard` namespace lines (commit #1); drop `import getCoreClientTools from 'src/core/clientTools'` and the `chat.registerClientTools(...)` block (PR:ExtensionsStartup.tsx:37,51,79-90). |
| **Needed from the AI commit** | `packages/superset-core/src/dashboard/index.ts:135` (`getDashboardId` declaration), `src/core/dashboard/index.ts:59-65` (implementation), `src/core/dashboard/getDashboardId.test.ts` | `packages/superset-widgets/src/embed/extensionHost.tsx:187` implements `getDashboardId: () => undefined` against that type. Keep these 3. |
| **AI-only, drop (Claude artifacts)** | `packages/superset-widgets/artifact/**` (6), `src/mcp/{client.ts,client.test.ts,errors.ts}`, `src/embed/SupersetArtifactProvider.tsx(+test)`, `src/embed/session.tsx(+test)`, exports at `src/index.ts:69-91`, `AGENTS.md` | Leaf code: nothing under `superset-frontend/src` imports it (grep: 0 hits). Whether `session.tsx` has a non-MCP mode: UNVERIFIED. |
| **Agent connectivity, drop** | `superset/mcp_oauth/**` (5), `superset/mcp_service/auth_oauth.py`, OAuth hunks of `mcp_config.py`/`server.py`, migration `8f2d4c6a1b3e`, `tests/unit_tests/mcp_oauth/**`, `tests/unit_tests/mcp_service/test_auth_oauth.py`, `MCP_OAUTH_*` + 2 CSRF entries in `config.py`, 3 lines in `initialization`, commit #18 | An OAuth authorization server "for MCP clients such as claude.ai custom connectors" (PR:superset/config.py comment). New unauthenticated, CSRF-exempt endpoints `/oauth/mcp/register|token`. Uses `fastmcp.server.auth.RemoteAuthProvider` (FastMCP 3 API; master pins `fastmcp>=4.1.4`): UNVERIFIED on master. |
| **MCP widget tools, optional (phase 2)** | `superset/mcp_service/widgets/{tool/**,schemas.py,utils.py,data_utils.py,node_store.py}`, `prompts/build_widget_artifact.py` (drop, artifact), `mcp_service/app.py` +9, `tests/unit_tests/mcp_service/widgets/**`, `MCP_WIDGETS_BUNDLE_URL` | Not required by REST/embedding: `git grep 'mcp_service|mcp_oauth|fastmcp'` over `superset/widgets`, `commands/widget`, `commands/dashboard_v2`, `dashboard_v2`, `daos|models/saved_widget.py` = 0 hits. Already broken on master: imports `superset.mcp_service.utils.sanitize_for_llm_context`, which no longer exists anywhere on master. |

## 2. Simulated merge (`git merge-tree --write-tree --name-only --messages`)

| Target | Result tree | Exit | Conflicted paths |
|---|---|---|---|
| `master` x `upstream/pr-44471` | `61efe9e637` | 1 | 9 |
| `nxtbi-demo` x `upstream/pr-44471` | `b408e04cc9` | 1 | 9, identical set and messages (nxtbi-demo only adds `nxtbi/`) |

Classification of the 287 PR paths against master:

| Bucket | Count | How measured |
|---|---|---|
| Pure additions (path absent on master) | **240** | `git cat-file -e master:<path>` fails for all 240 |
| Modified by PR, untouched on master since BASE (PR version taken as is) | **18** | `git diff -M --name-status BASE master -- <47 paths>` |
| Modified on both sides, auto-merged | **20** | merge-tree messages |
| Content conflicts | **8** | below |
| Modify/delete conflict | **1** | below |
| Renamed on master | **0** | `-M` shows 28 M + 1 D, no R |

| Conflicted path | Type | Hunks | Reason / resolution |
|---|---|---|---|
| `superset-frontend/package.json` | content | 1 | Adjacent lines: master bumped `google-auth-library` ^11.1.0, added `html2canvas`, `immer` ^11.1.21; PR adds `gridstack ^13.0.2`. Take master + add `gridstack`. The `@apache-superset/widgets` line auto-merges. |
| `superset-frontend/package-lock.json` | content | 3 | Master lock moved +9078/-11451 since BASE; PR delta is +36/-24. Never merge by hand: take master's lock, regenerate. |
| `superset-frontend/tsconfig.json` | content | 1 | Both rewrote `exclude` (master: node_modules/lib/esm globs; PR: `./packages/superset-widgets/example`). Union. |
| `superset-frontend/src/views/routes.tsx` | content | 2 | Master replaced `lazy` with `lazyWithRetry` and added `mobileSupported`; PR adds the `DashboardBuilderV2` import and 2 routes. Keep master, add the V2 routes **before** `DASHBOARD`, with `lazyWithRetry`. |
| `superset/config.py` | content | 1 | Both append to `WTF_CSRF_EXEMPT_LIST` (master: `superset.datasource.api.query`; PR: `widgets.api.data|values` + 2 mcp_oauth). Union, minus mcp_oauth. The `MCP_OAUTH_*` block auto-merges: delete it by hand. |
| `superset/security/manager.py` | content | 2 | (a) `raise_for_access`: master has `_semantic_layer_grant_allows` and `allow_editorship and self.is_editor(...)`; PR adds `or widget_context_grants_data_access(...)`. Keep master's lines + add the PR line. (b) PR extracted the guest dataset allowlist into `_raise_for_guest_dataset_allowlist`; **master's inline version gained `datasource.type != DatasourceType.TABLE`** which the PR helper lacks. Port that condition into the helper or semantic-view datasources bypass the allowlist. |
| `superset/mcp_service/mcp_config.py` | content | 3 | All three are the OAuth provider vs master's `MCP_DEV_USERNAME` refusal and HMAC hardening. With OAuth excluded: take master's file unchanged. |
| `superset-core/src/superset_core/semantic_layers/config.py` | content | 2 | Master added `SemanticCredentialReadiness(Enum)`; PR added `_iter_nested_models`, `_resolve_field_order`, `_reorder` at the same spot. Keep both, union the imports. |
| `superset-frontend/playwright/tests/experimental/README.md` | modify/delete | - | Master deleted `tests/experimental/` (only other file moved: `explore/results-tab-reuse.spec.ts` R087 -> `tests/explore/`) and removed the `INCLUDE_EXPERIMENTAL` gate from `playwright.config.ts`. Delete the README; move the 5 PR specs to `playwright/tests/dashboard-v2/` and fix `../../../pages/DashboardV2Page`. |

Auto-merged files that still need a human look (git-clean is not build-clean): `jest.config.js`, `packages/superset-core/package.json`, `theme/Theme.tsx` (master +105/-24), `translation/types/index.ts`, `AntdEnhanced.tsx`, `check-custom-rules.js`, `DatasetSelect.tsx`, `RightMenu.tsx` (master +184/-39), `jsonFormsHelpers.tsx(+test)` (master +222/-71), `routePaths.ts`, `query_context.py`, `dashboards/schemas.py`, `extensions/api.py`, `initialization/__init__.py` (master +500/-74), `mcp_service/app.py`, `mcp_service/server.py`, `security/guest_token.py` (master +132), `views/dashboard/views.py`, `docs/.../development.md`. The 8 auto-merged Python files pass `ast.parse` from the merge tree; nothing more is proven.

Known drift not visible as a conflict:
- `packages/superset-widgets/tsconfig.json` uses `"baseUrl": "../.."`. Master (TypeScript **7.0.2**, PR was 5.4.5) removed `baseUrl` from package tsconfigs and declares explicit relative `paths` (FORK:`packages/superset-core/tsconfig.json`). Rewrite the widgets tsconfig the same way.
- Import check of the 48 PR-added Python modules against master (142 `superset.*`/`superset_core.*` imports): only `sanitize_for_llm_context` is missing. Signature/behaviour drift (SQLAlchemy 1.4.54 -> 2.0.55, Flask 2.3.3 -> 3.1.3, flask-sqlalchemy 2.5.1 -> 3.1.1, FAB 5.2.2 -> 5.3.0, pydantic 2.13 -> 2.14) is UNVERIFIED.

## 3. Strategies

Extra measurement for B: sequential cherry-pick of the 23 commits onto master, simulated with `merge-tree --merge-base=<parent>` + `commit-tree` (objects only): **7 of 23 commits conflict, 12 file-events**, the lock file three times (#1, #4, #11). Skipping #10, #15, #18 leaves 6 of 20 conflicting, and the OAuth wiring still arrives through #12 and #13.

| | A. merge PR head | B. cherry-pick/rebase 23 | C. squash-port (one patch) | D. vendor + rewrite glue |
|---|---|---|---|---|
| Conflict work | 9 paths, once | 7 commits, 12 events, lock x3 | same 9 paths, once | none in git, all by hand |
| Authorship | full (5 authors, 23 SHAs are ancestors) | per commit, new SHAs | lost (only `Co-authored-by` trailers) | lost |
| Review | `git show --remerge-diff <merge>` shows exactly the 9 resolutions; verbatim content is proven by ancestry | 23 rewritten commits, each broken against master (TS 7, SA 2, FastMCP 4) | import commit must be verified with `git diff upstream/pr-44471 HEAD -- <paths>` | largest review, no upstream reference |
| Later PR updates | `git merge upstream/pr-44471` again (works while upstream appends) | `git cherry-pick <new range>` | `git diff 71be990689..<new> | git apply -3` (works for verbatim files, same blob ids) | manual |
| AI exclusion | explicit follow-up `git rm` commit (auditable, revertable) | cannot be done by dropping commits (#12/#13 contaminated) | never imported | never imported |
| Intermediate states | not needed | none importable (#12 before #15) | n/a | n/a |
| Risk | AI code present in history (not in tree) | highest effort, no benefit | provenance only in prose | diverges from upstream, glue is only 47 files anyway |

**Recommendation: A**, a real `--no-ff` merge of `upstream/pr-44471` into a new branch `feature/nxtbi-widgets` cut from `nxtbi-demo`, in a separate worktree, followed by small ordered commits (section 8). Reasons: measured conflict cost is low (9 paths, all small), it is the only option that keeps authorship and a machine-checkable link to the PR, and exclusions become one reviewable commit instead of an invisible omission. Use C only if the fork owner insists on linear history; D is not worth it (it degenerates into C). If upstream later rebases the PR onto master, no strategy merges cleanly: re-port from `git range-diff`.

### 3.1 RTL branch overlap and topology

RTL working tree (uncommitted) vs PR paths: `comm` of `git diff --name-only HEAD` + untracked against the 287 PR paths = **5 files**.

| RTL-touched path | PR touches it? | 3-way result (RTL working copy x BASE x PR, `git merge-file -p` in scratch) |
|---|---|---|
| `packages/superset-core/src/theme/Theme.tsx` | yes (+9/-2: `withGlobalStyles` prop on `SupersetThemeProvider`) | **2 conflict hunks caused by RTL** (signature: RTL adds `direction`; JSX: RTL uses `getEmotionCache(direction)` + `ConfigProvider direction`). Resolution: keep RTL's version and add the `withGlobalStyles` prop + `{withGlobalStyles && <GlobalStyles />}`. |
| `superset-frontend/package.json` | yes | RTL adds `@mui/stylis-plugin-rtl 9.5.0`, `stylis 4.2.0`, `@types/stylis 4.2.7`; no RTL-specific conflict (the 1 hunk is the master-vs-PR one) |
| `superset-frontend/package-lock.json` | yes | regenerate once more when the branches meet |
| `packages/superset-core/package.json` | yes (`./dashboard`, `./widgets` exports) | clean (0 conflicts) |
| `superset/config.py` | yes | RTL adds `RTL_LAYOUT_ENABLED` near line 623; no RTL-specific conflict |
| `theme/index.tsx`, `theme/types.ts`, `direction.ts`, `LtrIsolate.tsx`, `SuperChartCore.tsx`, `ChartMetadata.ts`, `ThemedAgGridReact/index.tsx`, `useLocale.ts`, `preamble.ts`, `src/theme/ThemeProvider.tsx`, `bootstrapTypes.ts`, `spa.html`, `views/base.py`, `embedded/view.py`, `translations/utils.py` | **no** | - |

Semantic coupling beyond text: `packages/superset-widgets/src/embed/SupersetProvider.tsx:159-176` builds its own `Theme.fromConfig(...)` and renders `<SupersetThemeProvider withGlobalStyles={false}>`; the widgets also import `@superset-ui/core/components/ThemedAgGridReact` (RTL-modified). Gridstack and the builder panels under `dir="rtl"`: UNVERIFIED.

**Topology: parallel, not stacked.** The RTL branch has no commits to stack on, and stacking would make widgets depend on WIP. Cut `feature/nxtbi-widgets` from `nxtbi-demo` in its own worktree; whichever branch lands second merges the other and resolves `Theme.tsx` (2 hunks) + lock regeneration. Do the combined build/demo on an integration branch (`nxtbi-demo` after both merges).

## 4. Dependencies and build wiring

| Item | PR change | State on master / action |
|---|---|---|
| npm (root) | `gridstack ^13.0.2` (lock 13.0.2), `@apache-superset/widgets: file:packages/superset-widgets` | add both; lock regen in a Linux Node 24 / npm 11 container |
| npm (package) | `packages/superset-widgets/package.json`: peerDeps `@apache-superset/core *`, `@superset-ui/core *`, `@emotion/react ^11.4.1`, `antd ^6.5.1`, `echarts ^6.1.0`, `react|react-dom ^18.3.0`; scripts `build` = `tsc --build` | master has antd ^6.6.8, echarts ^6.1.0, react ^18.3.0: ranges satisfied |
| npm (example) | own `package.json` + `package-lock.json`: `vite ^6.3.5`, `@vitejs/plugin-react ^4.5.0`, `vite-plugin-svgr ^4.3.0`, `typescript ^5.9.3`; **not** a workspace | resolves react/antd/emotion/echarts from `superset-frontend/node_modules` (example/README.md step 2) |
| Workspaces | none needed | FORK:`package.json:34-38` `"workspaces": ["packages/*","plugins/*","src/setup/*"]` picks the package up |
| tsconfig | paths `@apache-superset/widgets(/*)`, reference `./packages/superset-widgets`, exclude example | paths/reference auto-merge, exclude conflicts; package tsconfig needs the TS 7 rewrite |
| Jest | `moduleNameMapper` for `@apache-superset/widgets` and `gridstack` -> `spec/__mocks__/gridstackMock.ts` | auto-merged (merge tree `jest.config.js:62-67`) |
| Webpack | none | alias is automatic for every `@apache-superset/*` `file:` dependency with a `src/` (FORK:`webpack.config.js:624-636`); Module Federation `shared` lists only `@apache-superset/core` (`:206`), same as the PR |
| superset-core exports | `./dashboard`, `./widgets` in `packages/superset-core/package.json` | auto-merged |
| Lint | `check-custom-rules.js` ignores `/example/` | auto-merged; oxlint replaced eslint on master, the PR code was never linted with oxlint 1.92: UNVERIFIED |
| Python deps | **none** (`pyproject.toml`, `requirements/`, `superset-core/pyproject.toml` untouched) | - |
| Python package | `superset-core/src/superset_core/widgets/{__init__,base,composites,decorators,enrichment}.py` | shipped by `-e ./superset-core` (FORK:`requirements/base.txt:3`, `Dockerfile:304`), `packages.find where=["src"]` |
| Dockerfile | **none** | no change needed: `COPY superset-frontend` + manifest stage keep every `package.json` (`Dockerfile:50-54`), `npm ci` links workspaces (`:102-108`, needs an in-sync lock), `COPY superset superset` (`:316`). `tests/` and `docs/` are in `.dockerignore`. |
| CI workflows | **none added** (`git diff --stat BASE PR -- .github Dockerfile docker` empty) | `npm run core:cover` (FORK:`package.json:51`) enforces 100 % coverage on `packages/**` except superset-core: the new package would fail it if that job is ever run in the fork |
| Extensions CLI | `webpack.config.js.j2`: `publicPath: "auto"` | master untouched since BASE; applies as is |

## 5. Database migrations

Heads computed from `git grep '^(revision|down_revision)' <ref> -- superset/migrations/versions` (throwaway script, no alembic).

| Ref | Revisions | Head(s) |
|---|---|---|
| BASE | 363 | `e5f6a7b8c9d0` (`2026-07-07_12-00_e5f6a7b8c9d0_add_extension_storage_table.py`) |
| PR | 365 | `8f2d4c6a1b3e` |
| master / nxtbi-demo | 409 | **`b8f3a2c91d64`** (`2026-10-29_00-00_b8f3a2c91d64_migrate_databricks_connector_uri.py`, down `f72b6e9c104a`), single head |

| PR migration file | revision | down_revision | Content |
|---|---|---|---|
| `2026-09-15_12-00_3c9e1a7b5d2f_add_saved_widgets.py` | `3c9e1a7b5d2f` | `e5f6a7b8c9d0` | table `saved_widgets` (uuid PK `UUIDType(binary=True)`, widget_type, title, props, dataset_id, audit columns, 2 FKs to `ab_user`), index `ix_saved_widgets_created_by_fk` |
| `2026-09-15_18-00_8f2d4c6a1b3e_add_mcp_oauth_tables.py` | `8f2d4c6a1b3e` | `3c9e1a7b5d2f` | `mcp_oauth_clients`, `mcp_oauth_authorization_codes`, `mcp_oauth_refresh_tokens` |

On master `e5f6a7b8c9d0` already has two children (`d3b9a1f6c204`, `0be4b8f436f2`); an unedited merge yields **two heads** (`b8f3a2c91d64`, `8f2d4c6a1b3e`) and `superset db upgrade` aborts. Required: in `3c9e1a7b5d2f` set `down_revision = "b8f3a2c91d64"` and the `Revises:` docstring line, rename the file with a current date prefix, keep the revision id. Drop `8f2d4c6a1b3e` together with `superset/mcp_oauth` (or keep it chained on `3c9e1a7b5d2f` if OAuth is kept). Both files use only `create_table|drop_table|create_index|drop_index` from `superset.migrations.shared.utils`, all present on master with the same signatures (FORK:`shared/utils.py:259,281,434,479`).

Test plan on a disposable Postgres (never the compose project `nxtbi-superset` or its volumes). Quick pre-check without rebuilding: the migration imports nothing from the PR, so it can be bind-mounted into the existing master image.

```bash
docker network create wf-mig
docker run -d --name wf-mig-pg --network wf-mig -e POSTGRES_USER=superset -e POSTGRES_PASSWORD=superset -e POSTGRES_DB=superset postgres:17
mkdir -p /tmp/wf-mig && cat > /tmp/wf-mig/superset_config.py <<'EOF'
SECRET_KEY = "wf-migration-test-only-0123456789abcdef0123456789abcdef"
SQLALCHEMY_DATABASE_URI = "postgresql+psycopg2://superset:superset@wf-mig-pg:5432/superset"
EOF
W=E:/Work_Lab/nxtbi-superset-widgets/superset/migrations/versions   # widgets worktree
M=<new file name>_3c9e1a7b5d2f_add_saved_widgets.py
run() { docker run --rm --network wf-mig -v /tmp/wf-mig:/app/pythonpath:ro "$@"; }
run nxtbi/superset-fork:local superset db upgrade                      # baseline -> b8f3a2c91d64
run nxtbi/superset-fork:local superset db current
run -v "$W/$M:/app/superset/migrations/versions/$M:ro" nxtbi/superset-fork:local superset db heads     # exactly 1 head: 3c9e1a7b5d2f
run -v "$W/$M:/app/superset/migrations/versions/$M:ro" nxtbi/superset-fork:local superset db upgrade
docker exec wf-mig-pg psql -U superset -c '\d saved_widgets'
run -v "$W/$M:/app/superset/migrations/versions/$M:ro" nxtbi/superset-fork:local superset db downgrade b8f3a2c91d64
docker exec wf-mig-pg psql -U superset -c '\dt saved_widgets'           # no relation
run -v "$W/$M:/app/superset/migrations/versions/$M:ro" nxtbi/superset-fork:local superset db upgrade   # re-apply
docker rm -f wf-mig-pg && docker network rm wf-mig
```
Repeat the upgrade/downgrade/upgrade cycle with the final image `nxtbi/superset-fork:widgets`. `nxtbi/superset-fork:local` being built from master, and psycopg2 being in the `superset` target: taken from `nxtbi/docker-compose.yml:24-31`, not re-verified.

## 6. Test and tooling inventory (Definition of Done)

| Layer | Files (PR paths) | Command | Where |
|---|---|---|---|
| pytest, framework | `tests/unit_tests/widgets/` (10 test files + conftest), `tests/unit_tests/dashboard_v2/test_document.py`, `tests/unit_tests/extensions/test_api.py`, `tests/unit_tests/semantic_layers/config_test.py` | `pytest tests/unit_tests/widgets tests/unit_tests/dashboard_v2 tests/unit_tests/extensions/test_api.py tests/unit_tests/semantic_layers/config_test.py` | Unit tests use `sqlite://` (FORK:`tests/unit_tests/conftest.py:66,164`). `tests/` is not in the image: build the Dockerfile `dev` target and mount `tests/` + `pytest.ini`, or a Windows venv with `requirements/development.txt` (UNVERIFIED on Windows) |
| pytest, MCP (optional) | `tests/unit_tests/mcp_service/widgets/**` (4 test files) | `pytest tests/unit_tests/mcp_service/widgets` | same; expected red until ported to FastMCP 4 |
| pytest, excluded | `tests/unit_tests/mcp_oauth/**`, `tests/unit_tests/mcp_service/test_auth_oauth.py` | removed with the OAuth server | - |
| Regression guard | existing security and guest-token suites | `pytest tests/unit_tests/security` | because `raise_for_access` and `validate_guest_token_resources` change |
| Jest, framework | `packages/superset-widgets` (12 test files, 3 of them artifact/MCP), `src/core/dashboard` (15), `src/pages/DashboardBuilderV2` (13), `src/core/navigation/index.test.ts`, `src/features/semanticLayers/jsonFormsHelpers.test.ts` | `cd superset-frontend && npm run test -- packages/superset-widgets src/core/dashboard src/pages/DashboardBuilderV2 src/core/navigation src/features/semanticLayers` | Windows host Node 24 (Jest does not use webpack; UNVERIFIED) or `node:24-trixie-slim` container |
| Jest, excluded | `src/core/chat/ChatProvider.test.ts`, `src/core/clientTools/dashboard/getActiveDashboardId.test.ts`, `src/extensions/ExtensionsLoader.test.ts` (PR additions) | - | - |
| tsc | root program; package project; example | `npm run type` (`tsc --noEmit`, TS 7.0.2); `npx tsc --build packages/superset-widgets`; `cd packages/superset-widgets/example && npm install && npm run typecheck` | host or node container |
| Lint | oxlint, custom rules, ruff, mypy | `npm run lint`; `npm run check:custom-rules`; `pre-commit run --files $(git diff --name-only nxtbi-demo...HEAD)` (hooks: mypy, oxfmt-frontend, oxlint-frontend, custom-rules-frontend, type-checking-frontend) | host |
| Playwright | `playwright/pages/DashboardV2Page.ts` + 5 specs (`empty-canvas`, `filters`, `layout-regressions`, `reposition-and-resize`, `split`) | `PLAYWRIGHT_BASE_URL=http://localhost:<port> PLAYWRIGHT_ADMIN_USERNAME=... PLAYWRIGHT_ADMIN_PASSWORD=... npx playwright test dashboard-v2/` | `global-setup.ts:45-46` logs in with username/password, so it needs a DB-auth stack, **not** the Keycloak demo |
| Bundle | production webpack build | `docker build --target superset -t nxtbi/superset-fork:widgets .` | Linux only (brief: the fork's webpack config only builds on Linux; not re-verified here) |

## 7. Docker / runtime

| Topic | Finding |
|---|---|
| Feature flag for Dashboard V2 | **There is none.** No `FeatureFlag`/`is_feature_enabled` gates the routes, menu entry or APIs (grep over the new backend and frontend dirs: only `FeatureFlag.SemanticLayers` in `schemaControlRenderers.tsx:1252`). After the merge every user with `can_write Dashboard` sees "Dashboard v2" in the + menu (`RightMenu.tsx`), `/dashboard/v2/new/` and `/dashboard/v2/<pk>/` are served, and `/api/v1/dashboard_v2/`, `/api/v1/widgets/*`, `/api/v1/widget/*` are registered unconditionally. |
| Permissions | APIs reuse existing permission names (`class_permission_name = "Chart"` for widgets, `"Dashboard"` for dashboard_v2; `data`/`values` map to `read`), so no new permission-view rows are expected: UNVERIFIED by running `superset init`. |
| Embedding config | Already in the demo: `EMBEDDED_SUPERSET: True` (FORK@nxtbi-demo:`nxtbi/config/superset_config.py:120`), `GUEST_TOKEN_JWT_SECRET` (`:420`). Missing: a `GUEST_ROLE_NAME` with `can read on Chart` (demo keeps `Public` with no permissions, `:421`, so guest calls to `/api/v1/widget/data` will be 403); the PR README uses `Gamma`. |
| CORS | Master default is `ENABLE_CORS = True` with tile-server origins and `expose_headers: ["ETag"]` (FORK:`superset/config.py:1663-1672`). The demo must set `CORS_OPTIONS = {"origins": [<master defaults>, "http://localhost:5173"], "resources": [r"/api/*"], "supports_credentials": True, "allow_headers": ["Content-Type", "X-GuestToken"], "expose_headers": ["ETag"]}`. Overriding the dict replaces master's defaults, so repeat them. |
| CSRF | `superset.widgets.api.data` and `.values` are added to the default `WTF_CSRF_EXEMPT_LIST`; the demo config does not override that list, so it inherits. |
| Extension widgets | `FEATURE_FLAGS["ENABLE_EXTENSIONS"]` plus `EMBEDDED_EXTENSION_ASSETS_PUBLIC = True` (default False) for guest-token pages; this publishes extension bundles unauthenticated. |
| MCP | Nothing needed for the framework. Only if phase 2 is done: port and register the widget tools in `mcp_service/app.py`; the existing `superset-mcp` service on 5008 picks them up. |
| Image / compose | No Dockerfile change. Build under a different tag (`nxtbi/superset-fork:widgets`) and run under a different compose project name and ports (`nxtbi/docker-compose.yml` hardcodes `image: nxtbi/superset-fork:local`, `127.0.0.1:8088`, `127.0.0.1:5008`), otherwise the running demo is replaced. |

Standalone React example (`packages/superset-widgets/example`), host -> `http://localhost:8088`:

| Aspect | Value (evidence) |
|---|---|
| Ports | Vite `5173` strict (`vite.config.ts`), guest-token broker `127.0.0.1:3001` (`server.mjs:33,112`), Vite proxies `/api/guest-token` to it |
| Env | `.env` from `.env.example`: `SUPERSET_URL=http://localhost:8088`, `EMBED_AUTH=session|guest`, `EMBED_WIDGET_IDS`, `EMBED_DATASETS`, `FILTER_DATASET_TABLE=birth_names`, ... The defaults describe the `birth_names` example dataset: point them at a demo dataset |
| Session mode (default) | Browser calls Superset with `credentials: 'include'` (`src/embed/httpClient.ts:75-76`). Log in through Keycloak in the same browser first. `localhost:5173` -> `localhost:8088` is same-site, so the `SameSite=Lax` cookie `nxtbi_superset_session` is sent; requires `supports_credentials` and the exact origin in CORS. |
| Guest mode | `server.mjs` logs in with `POST /api/v1/security/login` (username/password), fetches a CSRF token, then `POST /api/v1/security/guest_token/` with `resources: [{type:"widget", id}]` and `datasets: [...]` (`server.mjs:51-90`). With Keycloak SSO only the local service account has a password (`superset_config.py:160-168`, `AUTH_API_LOGIN_ALLOW_MULTIPLE_PROVIDERS = True`). Whether `nxtbi-service` holds `can_grant_guest_token`: UNVERIFIED. Browser then sends `X-GuestToken` with `credentials: 'omit'`. |
| Running it | `npm ci` in `superset-frontend` first, then `npm install && npm run dev` in the example. Containerising it is awkward: one `SUPERSET_URL` serves both the browser (`localhost`) and the broker (would need `host.docker.internal`). Run it on the host. |

## 8. Runbook (strategy A)

```bash
cd E:/Work_Lab/nxtbi-superset                     # do NOT touch this working tree (RTL WIP)
git fetch upstream "+refs/pull/44471/head:refs/remotes/upstream/pr-44471"
git worktree add -b feature/nxtbi-widgets ../nxtbi-superset-widgets nxtbi-demo
cd ../nxtbi-superset-widgets

# 1. merge (expect exactly the 9 conflicts of section 2)
git merge --no-ff --no-commit upstream/pr-44471
git checkout --ours -- superset-frontend/package-lock.json superset/mcp_service/mcp_config.py
git rm superset-frontend/playwright/tests/experimental/README.md
#   hand-resolve: package.json (+gridstack), tsconfig.json (union exclude), src/views/routes.tsx (lazyWithRetry),
#   superset/config.py (union CSRF list), superset/security/manager.py (2 hunks, keep TABLE-type check),
#   superset-core/.../semantic_layers/config.py (keep both)
git add -A . && git commit   # message: "Merge apache/superset#44471 @71be990689 (base dashboard-v2 @ce0934a4cb) into nxtbi-demo"
git show --remerge-diff HEAD | less      # review: only the resolutions

# 2. one commit each, in this order
#  a. chore(widgets): drop chat client tools, MCP OAuth server, Claude-artifact transport  (section 1.1; keep getDashboardId)
#  b. fix(migrations): re-chain 3c9e1a7b5d2f onto b8f3a2c91d64, drop 8f2d4c6a1b3e
#  c. build(frontend): regenerate package-lock.json
docker run --rm -v "$PWD/superset-frontend:/w" -w /w node:24-trixie-slim npm install --package-lock-only --ignore-scripts
#  d. build(widgets): tsconfig for TypeScript 7 (no baseUrl, explicit paths)
#  e. test(playwright): move dashboard-v2 specs out of tests/experimental
#  f. fix(...): drift repairs until section 6 is green (tsc, oxlint, jest, pytest, mypy)
#  g. feat(nxtbi): CORS / guest role / example .env for the demo, under nxtbi/ only

# 3. verify
python <heads script> HEAD                         # exactly one head: 3c9e1a7b5d2f
git diff upstream/pr-44471 HEAD --stat -- superset-frontend/packages/superset-widgets/src superset/widgets   # only intended deltas
# section 5 (migration cycle), section 6 (tests), then:
docker build --target superset -t nxtbi/superset-fork:widgets .
# 4. later: merge with feature/nxtbi-arabic-rtl on an integration branch; resolve Theme.tsx (2 hunks), regenerate lock again
```

## 9. Risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | Two alembic heads after the merge; and again at every later upstream sync that adds migrations after `b8f3a2c91d64`, once `3c9e1a7b5d2f` is applied in a real DB | re-chain now; later use an alembic merge revision instead of re-chaining an applied revision |
| 2 | Security regression in `raise_for_access` (lost `DatasourceType.TABLE` check, lost `allow_editorship` gating, lost semantic-layer grant) if "theirs" is taken | resolve by hand as in section 2; run `tests/unit_tests/security` and `test_saved_widget_security.py` |
| 3 | 20 auto-merged files and 240 verbatim files were written against TS 5.4 / SA 1.4 / Flask 2.3 / FastMCP 3 / antd 6.5 | budget most of the effort for step 2f; nothing here proves they compile |
| 4 | No feature flag: Dashboard V2 UI and APIs go live for every editor the moment the image is deployed | add a fork-level gate (config key or `FEATURE_FLAGS`) before deploying to the shared demo |
| 5 | Lock file: three sources of change (master, widgets, RTL) | never hand-merge; regenerate in the Linux Node 24 container each time |
| 6 | RTL WIP is uncommitted in the main checkout; any `checkout`/`stash`/`merge` there destroys or entangles it | work only in the new worktree; `git worktree add` does not touch the main working tree |
| 7 | Building the widgets image under the tag `nxtbi/superset-fork:local` or the same compose project replaces the running demo and migrates its database | separate tag, project name, ports, database |
| 8 | Playwright suite and the example's guest broker assume username/password login; the demo is Keycloak-only | disposable DB-auth stack for Playwright; service account for the broker |
| 9 | Upstream may rebase or squash #44471 onto master (it targets `dashboard-v2`, which is 2688 commits behind) | then no strategy merges cleanly; diff the two PR versions with `git range-diff` and re-port |
| 10 | Stray untracked files exist in the main checkout root (`files`, `2026-09-25'`; not created by this analysis) | never `git add -A` in the main checkout |
| 11 | `EMBEDDED_EXTENSION_ASSETS_PUBLIC` and a permissive `GUEST_ROLE_NAME` widen exposure | keep defaults; give guests a purpose-built role |
