# 01 - Upstream record: PR #44471, SIP-231/232, and what happened after

Collected 2026-11-17, read-only. Sources: GitHub API (apache/superset), `git` in the two checkouts.
Notation: **PR** = `E:/Work_Lab/nxtbi-superset-pr44471` (detached at `71be990689`), **FORK** = `E:/Work_Lab/nxtbi-superset` at ref `master` (`f3f3d10d5c`).
"claims" = PR text; "code" = verified in the checkout. Anything not verified is marked **UNVERIFIED**.

## 0. Headline facts (read these first)

| # | Fact | Evidence |
|---|---|---|
| H1 | PR #44471 is an **open, unmerged POC** against the `dashboard-v2` feature branch, not `master`. Last push 2026-09-25, last activity 2026-09-30. No author reply to review, no commits after the review. | PR API: `state=open`, `merged=false`, `base.ref=dashboard-v2`, `updated_at=2026-09-30T11:17:24Z` |
| H2 | Upstream **abandoned the `dashboard-v2` line** in favour of **Canvas + Widget Framework**: SIP-231 (#44875, 2026-10-01) and SIP-232 (#44989, 2026-10-05), new long-lived branch `canvas`, umbrella draft PR #44998, prototype PR #45022. `dashboard-v2` head is still `ce0934a4cb` (2026-09-03): zero new commits. | `git ls-remote --heads upstream`: `canvas=522629ebb8`, `dashboard-v2=ce0934a4cb`, `msyavuz/feat/canvas=48d511f691`, `msyavuz/feat/canvas-v2=8dbb6d663a` |
| H3 | **Nothing of the widget framework is in master `f3f3d10d5c`.** No `superset/widgets`, `superset/dashboard_v2`, `superset/mcp_oauth`, `superset/commands/widget`, `superset/mcp_service/widgets`, `superset-frontend/packages/superset-widgets`, `superset-frontend/src/pages/DashboardBuilderV2`, `superset-frontend/src/core/dashboard`, `superset-core/src/superset_core/widgets`, `tests/unit_tests/widgets`. No `CANVAS`/`DASHBOARD_V2` flag. | `git ls-tree -d master -- <path>` = empty for all; `git grep` on `master:superset/config.py` finds only `ENABLE_EXTENSIONS` (:788), `EMBEDDABLE_CHARTS` (:990), `EMBEDDED_SUPERSET` (:1000) |
| H4 | The **embedding layer of #44471 exists nowhere else upstream** (`SupersetProvider`, `<Widget>`, `@apache-superset/widgets`, guest-token `widget` resource, MCP OAuth server, extension-widget embedding). SIP-231 §10 defers a "Widget SDK" to a *follow-up SIP* that has not been filed. | GitHub search `SupersetProvider` in apache/superset = 1 hit (#44471); search `"Widget SDK"` = #44875, #44998 only |
| H5 | All four human review findings are on the PR **head** commit and **unresolved**; one of them (shared `active` context) was *introduced* by the head commit `71be990689`. | review threads `is_resolved=false`, `is_outdated=false`, `commit_id=71be990689` |
| H6 | CI on the head is red on Python only: `unit-tests`, `pre-commit`, `test-postgres`, `test-mysql`, `test-sqlite`. All frontend jobs are green. CI ran on the merge with `dashboard-v2` (July base), so it says nothing about master. | check-runs API, section 3 |
| H7 | Dry merge of the PR head into master has **9 textual conflicts** only; the real cost is semantic drift (2688 commits). | `git merge-tree --write-tree master upstream/pr-44471` exit 1, tree `61efe9e637`, section 7 |

## 1. PR #44471 as filed

| Field | Value |
|---|---|
| Title | `feat(dashboard-v2): embeddable widgets for host apps, artifacts and extensions` |
| URL | https://github.com/apache/superset/pull/44471 |
| Author | `msyavuz` (Mehmet Salih Yavuz, MEMBER), head `msyavuz/feat/dashboard-v2-embedding` @ `71be990689` |
| Base | `dashboard-v2` @ `ce0934a4cb` |
| State | open, not draft, `mergeable_state=unstable` (mergeable, checks failing) |
| Size (vs base) | 13 commits, 188 files, +19949 / -2013 |
| Labels | `risk:db-migration`, `size/XXL`, `preset-io`, `api`, `doc`, `dependencies:npm`, `packages` |
| Requested reviewers | mistercrunch, rusackas, betodealmeida, eschutho, kgabryje, villebro, geido, michael-s-molina (none reviewed) |
| Created / updated | 2026-09-21 / 2026-09-30 |

### 1.1 What the description claims (verbatim essentials)

- "POC for initiative 3.13: the **widget**, not the dashboard, is the unit of embedding. A host app renders Superset widgets as React components, and every query still runs on the server from a stored definition or a validated inline spec, so a guest never sends SQL."
- `@apache-superset/core/widgets`: the contract (bus, data client, widget props, query-constraint vocabulary).
- `@apache-superset/widgets`: the implementation; builder and host app render the same components.
- Saved widgets + `POST /api/v1/widget/data`; guest tokens gain a `widget` resource type and a `datasets` allowlist for inline specs.
- Dashboards persist as node documents (`/api/v1/dashboard_v2`), with view/edit modes in the builder.
- Claude artifacts: widgets read the viewer's Superset MCP connector; `MCP_OAUTH_ENABLED` adds an authorization server (code + PKCE, dynamic registration).
- Extension widgets embed too: type `extensions.<publisher>.<name>.<type>`, page loads that extension's remote entry.
- "Six commits, one concern each; review them in order." **Code: there are 13 commits** (6 feature commits + 7 follow-ups).
- Checklist: migrations "only create new tables"; "Confirm DB migration upgrade and downgrade tested: **No** - not exercised yet"; "Runtime estimates: **No**".
- No architecture diagram in the PR. The only code sample:

```tsx
<SupersetProvider supersetDomain="https://superset.example.com" fetchGuestToken={mintToken}>
  <Chart dataBinding={{ datasetId: 17, metrics: ['sum__num'], dimensions: ['state'] }} chartType="bar" />
  <Widget id="cedf0501-fa36-4e19-9f84-e9da6d657dcc" />
  <Widget type="extensions.acme.widgets.funnel" props={{ dataBinding }} />
</SupersetProvider>
```

### 1.2 How the author says to run it

| Step | Command / setting | Source |
|---|---|---|
| Backend tests | `pytest tests/unit_tests/widgets tests/unit_tests/dashboard_v2 tests/unit_tests/extensions tests/unit_tests/mcp_oauth tests/unit_tests/mcp_service` | PR body. All five dirs exist in PR |
| Frontend tests | `cd superset-frontend && npm run test -- packages/superset-widgets` | PR body |
| Standalone example | `cd superset-frontend/packages/superset-widgets/example && npm install && npm run dev`, open http://localhost:5173 logged in to Superset | PR body; PR `superset-frontend/packages/superset-widgets/example/README.md` |
| Example prerequisite | `cd superset-frontend && npm install` first: the example resolves `react`, `antd`, emotion, echarts from there | example `README.md` Setup step 2 |
| Example config | `cp .env.example .env`; keys `SUPERSET_URL`, `EMBED_AUTH=session\|guest`, `EMBED_WIDGET_IDS`, `EMBED_EXTENSION_WIDGET`, `EMBED_DATASETS`, `FILTER_DATASET_TABLE/ID`, `FILTER_COLUMN`, `FILTER_VALUES`, `EMBED_METRIC`, `EMBED_SECOND_METRIC`, `EMBED_METRIC_COLUMN`, `EMBED_CATEGORY`, `EMBED_CATEGORY_VALUES`, `EMBED_LABEL`, broker `SUPERSET_USERNAME/PASSWORD`, `BROKER_PORT=3001` | PR `example/.env.example` |
| Guest mode | `npm run broker` (terminal 1, `server.mjs`) + `npm run dev` (terminal 2) | example `README.md` Run |
| Superset config for the example | `ENABLE_CORS=True`; `CORS_OPTIONS={"origins":["http://localhost:5173"],"resources":[r"/api/*"],"supports_credentials":True,"allow_headers":["Content-Type","X-GuestToken"]}`; guest mode: `FEATURE_FLAGS={"EMBEDDED_SUPERSET": True}`, `GUEST_ROLE_NAME="Gamma"` | example `README.md` Setup step 1 |
| Dashboard V2 builder | open `/dashboard/v2/new/` (menu entry) or `/dashboard/v2/<id>/`; widget menu -> *Embed widget* saves it and prints snippet + guest-token claims | PR body; PR `superset-frontend/src/features/home/RightMenu.tsx:258`, `src/views/routePaths.ts:30-31`, `src/core/dashboard/EmbedWidgetModal.tsx` |

### 1.3 Feature flags and config keys

| Key | Kind | Default | Added by | Where (PR) |
|---|---|---|---|---|
| `EMBEDDED_SUPERSET` | feature flag | False | pre-existing | `superset/config.py:906` |
| `ENABLE_EXTENSIONS` | feature flag | False | pre-existing | `superset/config.py:733` |
| `EMBEDDED_EXTENSION_ASSETS_PUBLIC` | config | False | **PR** | `superset/config.py:3086` (publishes extension frontend bundles unauthenticated) |
| `MCP_OAUTH_ENABLED` | config | False | **PR** | `superset/config.py:384` |
| `MCP_OAUTH_ISSUER`, `MCP_OAUTH_RESOURCES`, `MCP_OAUTH_PRIVATE_KEY`, `MCP_OAUTH_SCOPES`, `MCP_OAUTH_ACCESS_TOKEN_TTL`, `MCP_OAUTH_REFRESH_TOKEN_TTL`, `MCP_OAUTH_AUTHORIZATION_CODE_TTL`, `MCP_OAUTH_ALLOWED_REDIRECT_URIS` | config | see file | **PR** | `superset/config.py:386-398` |
| `MCP_WIDGETS_BUNDLE_URL` | MCP config | None | **PR** | `superset/mcp_service/mcp_config.py:105` |
| *(none)* for Dashboard V2 itself | - | - | - | **Code: the V2 builder, `/api/v1/dashboard_v2`, `/api/v1/widget*` are not behind any feature flag.** View `superset/views/dashboard/views.py:136-157` (`@has_access`, permission `Dashboard`), routes `superset-frontend/src/views/routes.tsx:217-218` unconditional |

## 2. Commits

### 2.1 The 13 PR commits (`upstream/dashboard-v2..upstream/pr-44471`), oldest first

| SHA | Date | Subject | Files +/- | What it adds |
|---|---|---|---|---|
| `6afb5f5843` | 09-21 | refactor(dashboard-v2): move the widgets into @apache-superset/widgets | 55, +1923/-1043 | New package; widgets, event bus, data-client contract, filter vocabulary leave `src/core/dashboard` |
| `637805854a` | 09-21 | feat(dashboard-v2): persist dashboards as documents | 23, +1519/-122 | `/api/v1/dashboard_v2`, `superset/dashboard_v2/*`, `superset/commands/dashboard_v2/*`, view/edit modes, load by id |
| `c9deadfe6f` | 09-21 | feat(dashboard-v2): add saved widgets and the widget data API | 20, +2175/-21 | `saved_widgets` table + migration `3c9e1a7b5d2f`, `POST /api/v1/widget/`, `POST /api/v1/widget/data`, guest-token `widget` resource + `datasets` claim |
| `98caf39499` | 09-21 | feat(dashboard-v2): render widgets in host apps and artifacts | 46, +9364 | `SupersetProvider`, `Widget`, hooks, `SupersetArtifactProvider`, `createSession`, the `example/` app |
| `134f0c5956` | 09-21 | feat(mcp): serve widget data over MCP, and an OAuth server to reach it | 27, +3400/-6 | MCP tools `get_saved_widget`, `get_widget_data`, `get_widget_values`, prompt `build_widget_artifact`, `superset/mcp_oauth/*`, migration `8f2d4c6a1b3e` |
| `0769398090` | 09-21 | feat(dashboard-v2): embed widgets contributed by extensions | 9, +1134/-7 | `embed/extensionHost.tsx`, `embed/extensionLoader.ts`, `EMBEDDED_EXTENSION_ASSETS_PUBLIC`, extension builds use `publicPath: "auto"` |
| `801ee8b5d9` | 09-21 | refactor(dashboard-v2): move the widget contract into @apache-superset/core | 18, +248/-133 | `packages/superset-core/src/widgets/index.ts` (types only) |
| `0252cde0ff` | 09-21 | fix(mcp): make the OAuth service's writes units of work | 1, +9/-5 | `@transaction` on 4 of 5 OAuth writes |
| `77170bc63f` | 09-21 | feat(dashboard-v2): stop shipping balloons as a built-in widget | 7, +8/-480 | Removes frontend balloons widget; backend `@widget` stays as test fixture |
| `d502195445` | 09-21 | fix(dashboard-v2): keep the widgets example app out of the root tsc program | 1, +6/-1 | `tsconfig.json` exclude (fixes `npm run type` in CI) |
| `6e99023802` | 09-24 | fix(dashboard-v2): report a bad widget query as 400, and unhardcode the example | 8, +147/-82 | `ChartDataQueryFailedError` -> 400; example dataset shape from `.env` |
| `888263bc1f` | 09-24 | fix(dashboard-v2): drive the example's ad hoc aggregate from config too | 3, +9/-4 | `EMBED_METRIC_COLUMN` |
| `71be990689` | 09-25 | fix: widgets | 14, +278/-380 | No message body. Touches example, `extensionHost.tsx`, `extensionLoader.ts`, `WidgetView.tsx`, `resolveWidgetView.ts`, `superset/widgets/builtin.py`, `controls.py`, 3 test files. **Introduces defect D3** |

### 2.2 The 10 `dashboard-v2` commits (`6856d0fc67..upstream/dashboard-v2`)

| SHA | Date | Author | Subject | Files +/- | Main area |
|---|---|---|---|---|---|
| `ab59385427` | 08-03 | M. S. Molina | First milestone | 33, +3081/-31 | `src/core/dashboard` (17), route + `DashboardBuilderV2View` |
| `116142e57f` | 08-07 | E. Martellucci | editing UI and layout modes (#42865) | 35, +5242/-70 | `src/pages/DashboardBuilderV2` (16), `src/core/dashboard` |
| `46be6a032d` | 08-11 | M. S. Molina | Initial design of containers (#43065) | 30, +2628/-569 | `src/core/dashboard` |
| `368aa3df87` | 08-13 | M. S. Molina | Use gridstack for the layout (#43096) | 24, +2835/-694 | gridstack dep, playwright experimental tests |
| `df3c616ea4` | 08-19 | V. Brofeldt | progressive widget schema disclosure (#43262) | 77, +4208/-787 | `superset_core/widgets`, `superset/mcp_service/widgets/tool`, backend registry |
| `ae0dc90f59` | 08-21 | M. S. Molina | Add support for filters (#43400) | 32, +3217/-119 | event bus, `superset/widgets/controls.py` |
| `12854abbee` | 09-03 | E. Martellucci | dataset-aware widget editing controls (#43588) | 55, +8102/-354 | builder controls, enrichment |
| `4716bbf0ee` | 09-03 | J. Park | fix(playwright): palette tab selector after Widgets rename (#43487) | 2 | playwright |
| `8e60d3abc4` | 09-03 | J. Park | fix(playwright): match palette tab selector (#43833) | 1 | playwright |
| `ce0934a4cb` | 09-03 | J. Park | feat(extensions): client-side MCP tools API for chat (#43093) | 21, +1271/-8 | `src/core/clientTools` (11), `src/core/chat` (3). **Chat piece - out of scope for us**, but shares `src/extensions/ExtensionsStartup.tsx`, `ExtensionsLoader.ts`, `packages/superset-core/src` |

Still open against `dashboard-v2`: #43070 `feat(dashboard-v2): theme a building block's chart` (msyavuz, 17 files, `mergeable_state=clean`, updated 2026-10-25) - not part of #44471.

## 3. CI on head `71be990689` (2026-09-25, merge ref `76f1ad6594`)

| Check | Result | Note |
|---|---|---|
| `unit-tests (current)` / `unit-tests-required` | **failure** | workflow Python-Unit, step "Python unit tests", exit 1 |
| `test-postgres (current)` / `test-postgres-required` | **failure** | exit 1 |
| `test-mysql` | **failure** | exit 1 |
| `test-sqlite` | **failure** | exit 1 |
| `pre-commit (current)` | **failure** | exit 1 (5 min run) |
| `test-postgres-presto`, `test-postgres-hive`, `test-load-examples` | success | |
| `frontend-build`, `lint-frontend`, `validate-frontend`, `sharded-jest-tests (1-8)`, `test-storybook` | success | |
| `playwright-tests (chromium)`, `playwright-tests-experimental` (x2), `cypress-matrix` (x2) | success | |
| `Check DB migration conflict`, `check-python-deps`, `python-dependency-liccheck`, `License Check`, `dependency-review`, `zizmor`, `babel-extract`, `frontend-check-translations`, `test-superset-extensions-cli-package` | success | |
| Codecov | patch coverage 41.65 %, 943 lines missing | worst: `superset/mcp_oauth/service.py` 23.9 %, `superset/widgets/data.py` 24.7 %, `superset/mcp_oauth/views.py` 36.1 %, `superset/commands/widget/data.py` 32.3 %, `superset/security/manager.py` 20.5 % |

**Failing error output: UNVERIFIED.** Job logs require a signed-in GitHub session (`gh` token on this machine is invalid; check-run annotations only say "Process completed with exit code 1"). Which tests/hooks fail must be reproduced locally. Hypotheses, none confirmed: (i) the head commit `71be990689` rewrote `superset/widgets/builtin.py`/`controls.py` and three test files together, so a test/implementation mismatch in `tests/unit_tests/widgets` is plausible; (ii) all three DB integration jobs failing together while presto/hive pass points to a shared integration test (permission/API inventory assertions for the new `Widget`/`DashboardV2`/OAuth views) rather than a dialect problem; (iii) `pre-commit` red with `lint-frontend` green points to a Python hook (mypy/ruff/pylint).

## 4. Reviews, comments and bot findings on #44471 (complete)

| Who | Date | Kind | Content |
|---|---|---|---|
| `bito-code-review[bot]` | 09-21 | comment | "Bito Automatic Review Skipped - Branch Excluded". **No findings.** |
| `netlify[bot]` | 09-21 | comment | docs preview ready (commit `0769398090`) |
| `codecov[bot]` | 09-21 | comment | coverage table (section 3) |
| `rusackas` (MEMBER) | 09-29 | comment | "CI's currently failing on unit-tests, pre-commit, and all three DB backends on the latest push, and the migration upgrade/downgrade testing box in the description is still unchecked. Not a huge blocker..." |
| `sadpandajoe` (MEMBER) | 09-30 | review `COMMENTED`, empty body, 4 inline threads on `71be990689` | R1-R4 below |

No CodeAnt, Copilot, Korbit or Cursor Bugbot output exists on this PR. No approvals, no change requests. The brief's defect classes (a)-(d) are exactly sadpandajoe's four threads; (e) is rusackas' comment plus CI.

| ID | Thread (verbatim) | Anchor |
|---|---|---|
| R1 | "Saving before this fetch returns writes the current singleton document to the requested dashboard, so opening B and clicking Save can overwrite it with a blank tree or dashboard A's tree. Can the editor block saves and clear/reset state until the requested document has loaded?" | `superset-frontend/src/pages/DashboardBuilderV2/index.tsx:188` |
| R2 | "This accepts a node as its own child (or any cycle), which is then persisted and recursively rendered when the dashboard is opened. Can validation reject cycles before saving the document?" | `superset/dashboard_v2/document.py:93` |
| R3 | "`active` is shared by every rendered extension widget, so after B renders, a query initiated by A uses B's instance ID, filters, and potentially B's data client. Can this context be scoped to the calling widget instead of module-global state?" | `superset-frontend/packages/superset-widgets/src/embed/extensionHost.tsx:250` |
| R4 | "This reuses the legacy embed modal, whose SDK route renders the legacy dashboard rather than the V2 document. Can the V2 embed action point to a renderer that loads the saved V2 widgets before exposing this flow?" | `superset-frontend/src/pages/DashboardBuilderV2/DashboardHeader.tsx:331` |

## 5. Confirmed defect classes, located in the PR checkout

### (a) Save/load races and stale-state overwrites
- **Where.** Load: PR `src/pages/DashboardBuilderV2/index.tsx:187-201` (`fetchDashboardV2(dashboardId).then(r => provider.loadDocument(r.document.nodes))`). Save: PR `DashboardHeader.tsx:242-262` (`saveDashboardV2({ id: dashboardId, nodes: provider.getDocument() })`). The tree is a process-wide singleton: PR `src/core/dashboard/DashboardProvider.ts:486-502` (`loadDocument` / `getDocument`).
- **Manifestations (code-verified).** (1) R1: the Save button (`DashboardHeader.tsx:321-329`) is enabled as soon as the route has an id; nothing tracks "loaded", so Save during the fetch PUTs the previous dashboard's tree (or a blank root) onto dashboard B. (2) On fetch failure (`index.tsx:194-197`) only a toast is shown; the old tree stays and remains saveable under the new id. (3) First save does `history.push('/dashboard/v2/<id>/')` (`DashboardHeader.tsx:254-256`), which changes `dashboardId`, re-runs the effect and replaces the in-memory tree with the server copy; edits made between the POST and that GET are dropped, contradicting the comment at `:251-252`. (4) Backend is last-write-wins: `UpdateDashboardV2Command.run` (`superset/commands/dashboard_v2/save.py`) overwrites `json_metadata["v2_document"]` with no revision / `If-Match` / `changed_on` check, so two tabs or an agent plus a human silently clobber each other. (5) No in-flight save guard beyond the button spinner; a slow first POST followed by a second click creates two dashboards.
- **Reviewer's fix.** Block saves and clear/reset state until the requested document has loaded.
- **Complete fix.** Key state by dashboard id (`loadedId`), reset the provider on id change, disable Save unless `loadedId === dashboardId` and no request is in flight, skip the refetch after create, and add optimistic concurrency server-side (revision column or `changed_on` precondition -> 409). SIP-231 §5 mandates `revision` "exposed as an ETag and checked on update".
- **Fixed later in PR?** No.

### (b) Recursive / cyclic document trees
- **Where.** PR `superset/dashboard_v2/document.py:70-101` (`normalize_document`). The only structural check is `:93` "children exist in `nodes`".
- **Manifestations.** A node listed as its own child, a longer cycle, a node with two parents, `root` as somebody's child, and unreachable orphan nodes are all accepted and stored. The builder renders children recursively, so a cyclic document recurses until the tab dies. Also at `:93`: a non-string child (`{}` or `[]`) makes `child not in nodes` raise `TypeError: unhashable type`, which is a 500, not a 400 (own analysis, not in review). No depth or node-count bound. PR `tests/unit_tests/dashboard_v2/test_document.py` has no cycle case. Frontend `DashboardProvider.loadDocument` (`:486-497`) only checks that `root` exists.
- **Reviewer's fix.** Reject cycles before saving.
- **Complete fix.** In `normalize_document`: children must be strings; walk from `root` with a visited set; reject any node reached twice (cycle or multi-parent), `root` as child, and unreachable nodes; cap depth and node count. Mirror the same guard in `loadDocument` and make the renderer cycle-safe for already-stored documents.
- **Fixed later in PR?** No.

### (c) Shared mutable widget context / cross-widget leakage
- **Where.** PR `packages/superset-widgets/src/embed/extensionHost.tsx:125` (`let active: { id, bus, client } | undefined`), written during render at `:250`, read by `fetchQueryData` at `:171-183`. Sibling module-level state: `instances` (`:111`), `buses` (`:127`), `subscriptions` (`:135`), `registeredViews` (`:268`).
- **Manifestation.** `dashboard.fetchQueryData(binding)` carries no node id, so it uses whichever extension widget rendered last. With widgets A and B (or two providers with different guest tokens / RLS), A's effect-time fetch runs with B's `instanceId` (so B's own filter is excluded instead of A's), B's bus filters and B's `WidgetDataClient` (i.e. B's token). The code comment at `:114-124` says the pointer is "deliberately not cleared".
- **History.** Commit `71be990689` replaced `currentInstanceId` + per-instance lookup (`instances.get(id).client/bus`) with this global holding bus and client. The earlier code was wrong for effect-time calls (the id was cleared on unmount); the "fix" traded a thrown error for silent cross-attribution. See `git show 71be990689 -- .../extensionHost.tsx`.
- **Reviewer's fix.** Scope the context to the calling widget instead of module-global state.
- **Complete fix.** Give each extension instance its own scoped `dashboard` facade (closure over `instanceId`, bus, client) delivered through React context or a per-instance core object from `createExtensionCore` (`:321`); keep `fetchQueryData(binding)` source-compatible by binding it per instance; reject calls that cannot be attributed. Add a two-widget, two-provider test to `extensionHost.test.tsx`.
- **Fixed later in PR?** No - introduced by the last commit.

### (d) Incorrect legacy embedding route
- **Where.** PR `DashboardHeader.tsx:39` imports `src/dashboard/components/EmbeddedModal`; rendered at `:330-336`, button at `:305-313`.
- **Manifestation.** The modal calls `/api/v1/dashboard/<id>/embedded` (PR `src/dashboard/components/EmbeddedModal/index.tsx:70`) and hands out an embedded-SDK uuid. The SDK iframe loads `/embedded/<uuid>` (PR `superset/embedded/view.py:36`), whose entry `src/embedded/index.tsx:99-131` mounts the legacy `DashboardPage`. A V2 dashboard keeps its content in `json_metadata["v2_document"]` and has an empty `position_json`, so the embed shows an empty legacy dashboard. A V2 reader endpoint exists (`GET /api/v1/dashboard_v2/embedded/<uuid>`, PR `superset/dashboard_v2/api.py:216-255`) but nothing in the embedded entry point consumes it.
- **Reviewer's fix.** Point the V2 embed action at a renderer that loads the saved V2 widgets before exposing the flow.
- **Complete fix.** Either hide the header Embed button, or add a V2 branch to the embedded entry (detect `v2_document`, render the V2 view-mode grid with guest-token data client) and test it. Per-widget embedding via `EmbedWidgetModal.tsx` is the supported path in this PR.
- **Fixed later in PR?** No.

### (e) Failed tests, broken builds, migration issues
| Item | Status | Evidence |
|---|---|---|
| Python unit, pre-commit, postgres/mysql/sqlite suites red on head | open; root cause **UNVERIFIED** | section 3 |
| Migration upgrade/downgrade never exercised | open | PR body checklist; rusackas 09-29 |
| `3c9e1a7b5d2f.down_revision = "e5f6a7b8c9d0"` creates a **second alembic head on master** | must rebase | on master `e5f6a7b8c9d0` already has children `d3b9a1f6c204` and merge `0be4b8f436f2`; master single head is `b8f3a2c91d64` (408 revisions); PR chain is `e5f6a7b8c9d0 -> 3c9e1a7b5d2f -> 8f2d4c6a1b3e` |
| `saved_widgets.dataset_id` is a bare `Integer` with no FK to `tables.id` | design gap (own analysis) | PR `superset/migrations/versions/2026-09-15_12-00_3c9e1a7b5d2f_add_saved_widgets.py:46` |
| Root `tsc` swept up the example app | **fixed in PR** by `d502195445` | commit message |
| Bad widget query returned 500 | **fixed in PR** by `6e99023802` | commit message |
| pylint `consider-using-transaction` in OAuth service | **fixed in PR** by `0252cde0ff` | commit message |
| Patch coverage 41.65 % | open | Codecov |

## 6. SIP-231 and SIP-232

| | SIP-231 | SIP-232 |
|---|---|---|
| Issue | #44875 "[SIP-231] Proposal for Charts v2 aka Widget Framework" | #44989 "[SIP-232] Proposal for Canvas, the document that places widgets" |
| Author / date | villebro, 2026-10-01 (body last edited 10-05) | msyavuz, 2026-10-05 (updated 11-13) |
| Status | **open, under discussion**; label `sip`; 6 heart reactions, 6 comments | open; labels `sip`, `preset-io`; 8 comments |
| Vote | No vote recorded on the issue. A dev@ mailing-list vote: **UNVERIFIED** (not searched) | rusackas 10-20: "I don't see any blockers here... about ready to give my +1"; no formal vote on the issue |
| Prototype named | `dashboard-v2` branch (#43262, #43588, #43400). **#44471 is not cited.** | `msyavuz/feat/canvas` (#45022) |

SIP-231 in one paragraph: a widget is a backend Python class (`@widget`, `Widget`, optional `QueryMixin` with `build_queries` / `transform_data`) plus a React renderer; props are a Pydantic model whose JSON Schema drives the property panel and agent disclosure; instances are **persisted** (`widgets` table with `id`, `uuid`, `widget_type`, `name`, `description`, `schema_version`, `props`, `revision`, editors/viewers) or **inline** on a Canvas placement; edits may go through drafts with JSON Patch; data is fetched **by instance** (`POST /api/v1/widget/{uuid}/data`, body = additive `runtime_filters` only) as a JSON manifest + Arrow IPC, async via the Global Task Framework and SIP-227 realtime; everything sits behind one `CANVAS` flag (routes 404 when off); new `Widget` permission resource. Milestones M1 Framework, M2 Parity, M3 Convergence (Slice migration), M4 Removal.

Discussion points that matter to us: michael-s-molina 10-05 "the event bus behind widgets is generic, it accepts any type of event... `dashboard-v2` prototype has this generic event bus concept" (accepted); villebro 10-05 "storing widgets as KV entries is not an option" (dedicated table); villebro on dynamic group-by: "a bit of a security concern... start with just additive filters"; open question whether edits are grouped by an explicit commit.

### 6.1 Where PR #44471 differs from what the SIPs decided

| Topic | SIP-231 / SIP-232 | PR #44471 (code) |
|---|---|---|
| Storage of saved widgets | table `widgets`, int `id` + `uuid`, `schema_version`, `revision`, `name`/`description`, `widget_editors`/`widget_viewers` | table `saved_widgets`, `uuid` PK, `title`, `props`, `dataset_id`; no revision, no schema version, no editors/viewers (PR `superset/models/saved_widget.py:35`) |
| Dashboard document | `canvases` table, placements with readable ids, ops, drafts, versions, op log | flat node map in `dashboards.json_metadata["v2_document"]`, whole-document PUT |
| Data endpoint | `POST /api/v1/widget/{uuid}/data`; "The query definition always comes from storage"; caller sends only `runtime_filters` | `POST /api/v1/widget/data` accepts a saved id **or a caller-supplied inline spec**; guests limited by `datasets` claim and SIMPLE metrics/filters |
| Transport | JSON manifest + Arrow IPC, async tasks, realtime | synchronous JSON through the chart-data pipeline |
| Type API | `/api/v1/widget_type/{type}/control-schema\|field-options\|validate` | `/api/v1/widgets/types`, `/api/v1/widgets/type/<type>/control-schema\|validate` (PR `superset/widgets/api.py:66,78,112,249`) |
| Permissions | new `Widget` and `Canvas` resources | reuses `Chart` (PR `superset/widgets/api.py:70,360`) and `Dashboard` (PR `superset/dashboard_v2/api.py:53`) |
| Feature flag | single `CANVAS`, routes 404 when off, MCP tools removed | none for the builder/APIs (section 1.3) |
| Concurrency | `revision` + ETag / `If-Match` -> 409 | last write wins (defect a) |
| Drafts / JSON Patch | optional drafts, `patch_widget_draft`, strict commit | none |
| Query building | backend `QueryMixin` -> `SemanticQuery` over a `SemanticView` adapter | `dataBinding` props mapped onto the chart-data query context |
| Frontend contract | hooks `useWidgetData`, `useRuntimeFilters`, `emitFilter` in `@apache-superset/core` | `WidgetBus`, `WidgetDataClient`, `WidgetProps` in `@apache-superset/core/widgets`; host hooks `useSupersetFilter`, `useWidgetEvent` in `@apache-superset/widgets` |
| Embedding outside Superset | "A Widget SDK, specified in a follow-up SIP"; §10 sketches `<Widget id="..." />` and inline type+props | **implemented**: `SupersetProvider`, `<Widget id>`, `<Widget type props>`, `SupersetArtifactProvider`, `createSession` |
| Guest tokens | SIP-232 §12 (M2): `{"type": "canvas", "id": "<uuid>"}` resource | `{"type": "widget", "id}` resource + `datasets` allowlist (PR `superset/security/guest_token.py:123,157`) |
| MCP OAuth authorization server | not in either SIP | `superset/mcp_oauth/*`, 3 tables |
| Reference extension widget | W7: balloons as a real extension | balloons removed from the package (`77170bc63f`), backend fixture kept |

Related SIPs cited by SIP-231: SIP-182 (semantic layer, source of `SemanticQuery`), SIP-151 (extensions), SIP-211 (Node sidecar, rejected), SIP-219 #41779 (uniform built-in extensions, open), SIP-207 (Zustand/TanStack), SIP-227 #44174 (async + realtime, a dependency), SIP-220 #41854 (extension storage, closed). PR #44471 itself cites only SIP-59 (migration process).

## 7. After 2026-09-25: successors and overlap with master

| Item | State (2026-11-17) | Relevance |
|---|---|---|
| `dashboard-v2` branch | frozen at `ce0934a4cb` | PR base is dead; nothing to pull |
| #44998 `feat: Canvas and the Widget Framework` (villebro) | open **draft**, base `master`, head `canvas` @ `522629ebb8`, 41 files +2628, 2 commits | Umbrella. Only **W1** merged: `widgets` table + `widget_editors`/`widget_viewers` (migration `06373bc38605`), `superset_core.widgets` model/DAO, REST `/api/v1/widget/` with `ETag`/`If-Match`, MCP `list_widgets`/`get_widget_info`, `CANVAS` flag (`upstream/canvas:superset/config.py:700`). W2-W11 and C1-C7 "Planned". Ref `upstream/canvas` is present in FORK |
| #45022 `feat(canvas): Canvas... (SIP prototype)` (msyavuz) | open, base `master`, head `msyavuz/feat/canvas` @ `48d511f691`, 92 commits, 293 files, +69766/-9135 | Active prototype; reviewed by alexandrusoare (10-28 security pass, 11-13 correctness pass: "the `place` crash, the draft-write race and the changes-feed race look like real correctness bugs") |
| Child PRs into `msyavuz/feat/canvas` | #45090 drag/resize (merged 11-12), #45826 draft fixes (merged 11-02), #46111 MCP error typing (merged 11-13), #46119 versioned widget discovery (merged 11-13), #46250 "align query errors and clear stale widget state" (open 11-16) | Same problem space as defects (a) and (c), different code |
| `msyavuz/feat/canvas-v2` @ `8dbb6d663a` | branch exists, no PR found | **UNVERIFIED** content |
| Widget SDK / host embedding | no successor anywhere | #44471 stays the only implementation |
| Chat / A2UI / client tools (**not ours**) | master has `superset-frontend/src/core/chat`; `src/core/clientTools` exists only on `dashboard-v2`/PR (#43093); #45392 `feat(extensions): adopt client tool API and implement SQL Lab tools` open; #46130, #46135, #45991 extension API PRs open | Shared files: `src/extensions/ExtensionsStartup.tsx`, `ExtensionsLoader.ts`, `packages/superset-core/src/*`, `App.tsx` chat hosts referenced from `DashboardBuilderV2/index.tsx:159-177` |
| Embedded / guest-token hardening merged to master since the merge-base | #43111, #43151, #43391, #43834, #43896, #44987, #45273, #45452, #45816, #45869, #45870, #45890, plus MCP guest tokens #43637, #45346, #45639 (FastMCP 4) | `master:superset/security/guest_token.py` enum is at line 253 (PR: line 121) and still has only `DASHBOARD`; the PR's `WIDGET` type and `datasets` claim must be re-applied on top of the hardened file and validators |
| Embedded SDK | #44470 re-auth after navigation, #35754 `setDataMask`, #45957 tests + JSDoc, TS7/Babel 8 (#43702) | iframe SDK only; no widget mode |

Textual conflicts of `git merge-tree --write-tree master upstream/pr-44471` (9 files): `superset-core/src/superset_core/semantic_layers/config.py`, `superset-frontend/package-lock.json`, `superset-frontend/package.json`, `superset-frontend/playwright/tests/experimental/README.md`, `superset-frontend/src/views/routes.tsx`, `superset-frontend/tsconfig.json`, `superset/config.py`, `superset/mcp_service/mcp_config.py`, `superset/security/manager.py`. Semantic drift on files that merge cleanly is not covered by this number. Already-compatible: the PR uses the subjects model (`populate_subjects`, `raise_for_editorship`), both present on master (`superset/commands/utils.py:215`, `superset/security/manager.py:6987`).

## 8. Defects to fix (implementer checklist)

| ID | Class | Location (PR checkout) | Fix | Fixed upstream? |
|---|---|---|---|---|
| D1 | a - save before load | `superset-frontend/src/pages/DashboardBuilderV2/index.tsx:187-201`; `DashboardHeader.tsx:242-262,321-329` | Track `loadedId`; reset provider on id change; disable Save until loaded and while a request is in flight | No (R1 open) |
| D2 | a - load failure keeps old tree | `index.tsx:194-197` | Reset to an error state; block Save | No |
| D3 | a - refetch after first save clobbers edits | `DashboardHeader.tsx:251-256` + `index.tsx:187-201` | Mark the new id as already loaded; do not reload after create | No |
| D4 | a - last-write-wins update | `superset/commands/dashboard_v2/save.py` (`UpdateDashboardV2Command.run`); `superset/dashboard_v2/schemas.py:34` | Revision or `changed_on` precondition, 409 on mismatch; client sends it | No (canvas W1 does it for `widgets` only) |
| D5 | b - cycles, multi-parent, root-as-child, orphans | `superset/dashboard_v2/document.py:70-101` (check at `:93`) | Reachability walk from `root` with visited set; reject; depth/size caps; tests in `tests/unit_tests/dashboard_v2/test_document.py` | No (R2 open) |
| D6 | b - non-string child -> 500 | `superset/dashboard_v2/document.py:93` | Validate child type before membership test | No |
| D7 | b - client accepts cyclic doc | `superset-frontend/src/core/dashboard/DashboardProvider.ts:486-497`; recursive render in `src/core/dashboard/WidgetView.tsx` | Same guard in `loadDocument`; cycle-safe render | No |
| D8 | c - module-global `active` | `packages/superset-widgets/src/embed/extensionHost.tsx:125,171-183,250` | Per-instance scoped `dashboard` facade; no global attribution | No (R3 open; introduced by `71be990689`) |
| D9 | c - other module-level maps shared across providers | `extensionHost.tsx:111,127,135,268` | Key by provider/session or move into provider context; verify `resetExtensionHost` (`:357`) coverage | No |
| D10 | d - header Embed uses legacy modal | `DashboardHeader.tsx:39,305-313,330-336`; `superset-frontend/src/embedded/index.tsx:99-131` | V2-aware embedded renderer, or remove the button | No (R4 open) |
| D11 | e - Python unit tests red | `tests/unit_tests/widgets/*` and others, **UNVERIFIED** which | Reproduce with the PR's pytest command; fix | No |
| D12 | e - pre-commit red | **UNVERIFIED** hook | `pre-commit run --all-files` | No |
| D13 | e - integration suites red on 3 DBs | **UNVERIFIED** test | Reproduce | No |
| D14 | e - alembic second head on master | `superset/migrations/versions/2026-09-15_12-00_3c9e1a7b5d2f_add_saved_widgets.py:26` | Re-parent onto master head `b8f3a2c91d64` (re-check at implementation time); re-date files | No |
| D15 | e - upgrade/downgrade untested | both PR migrations | Run upgrade -> downgrade -> upgrade on Postgres (and SQLite) | No |
| D16 | e - `dataset_id` without FK | same migration `:46`; `superset/models/saved_widget.py` | Decide FK + `ondelete`, or document | No |
| D17 | gating - no feature flag | `superset/views/dashboard/views.py:136-157`; `superset-frontend/src/views/routes.tsx:217-218`; `src/features/home/RightMenu.tsx:258`; `superset/initialization/__init__.py:265,469` | Add a flag; APIs 404 when off; hide menu | n/a (canvas uses `CANVAS`) |
| D18 | drift - guest token on hardened master | `superset/security/guest_token.py:121-160`; `superset/security/manager.py` (conflict) | Re-apply `WIDGET` resource and `datasets` claim over master's validators; port `tests/unit_tests/widgets/test_saved_widget_security.py` | n/a |
| D19 | coverage | `superset/mcp_oauth/service.py`, `superset/widgets/data.py`, `superset/commands/widget/data.py` | Raise patch coverage; access-path tests with non-admin and guest principals | No |

## 9. Review themes maintainers will care about

1. **Green CI and a tested migration** before anything else (rusackas 09-29).
2. **State isolation and races** in the editor and in embedded widgets (sadpandajoe R1, R3; alexandrusoare on #45022: "draft-write race", "changes-feed race").
3. **Server-side validation that cannot be bypassed**: tree invariants, props schema, "a canvas can't be left broken" (R2; SIP-232).
4. **Optimistic concurrency**: revision + ETag / `If-Match` / 409 is the upstream standard since canvas W1.
5. **Security tests on the real access path**, not fakes: alexandrusoare 10-28 "My main ask is tests rather than code... both fixtures pin `is_admin=True`, so the data endpoint never walks the access path - no non-reader case, no guest case." `SECURITY.md` capability-matrix rows for every new guest/viewer capability.
6. **The query definition comes from storage**; callers may only add filters (SIP-231 §8). The PR's inline-spec path for guests is the part most at odds with this and will be scrutinised.
7. **One flag, off by default, routes 404 when off** (`CANVAS` model).
8. **A dedicated `Widget` permission resource** instead of borrowing `Chart`/`Dashboard`.
9. **Embedding must render what it says** (R4) and unauthenticated asset exposure (`EMBEDDED_EXTENSION_ASSETS_PUBLIC`) must be explicit and opt-in.
10. **Generic event bus shared by core and extension widgets** (michael-s-molina 10-05), types in `@apache-superset/core`, no heavy runtime in the shared singleton.
11. **Scope**: "quite the scope on this one" (rusackas). One concern per commit / small child PRs is the accepted working mode on `canvas`.
12. **Naming alignment with the SIPs** (`widgets` table, `widget_type`, `/api/v1/widget/{uuid}`) to keep a later convergence with upstream cheap.
