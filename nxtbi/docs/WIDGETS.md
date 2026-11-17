# Dashboard V2 and embeddable widgets in the NxtBI Superset fork

Branch `feature/nxtbi-widgets`, stacked on `feature/nxtbi-arabic-rtl`. It merges the widget framework of
upstream PR [apache/superset#44471](https://github.com/apache/superset/pull/44471) (an abandoned proof of
concept on the frozen `dashboard-v2` branch) onto current master, repairs it and makes it run. Everything
is behind the feature flag `DASHBOARD_V2`, which defaults to off: with the flag off every new route
answers 404 and no builder code is loaded.

Research and design notes: [widgets/](widgets/). API contract:
[widgets/05-dashboard-v2-api-contract.md](widgets/05-dashboard-v2-api-contract.md). Security model:
[widgets/03-backend-security.md](widgets/03-backend-security.md) section 5. How to run the stack and the
checks: [../widgets/README.md](../widgets/README.md).

## 1. What works

| Area | State |
|---|---|
| `@apache-superset/widgets` package, `SupersetProvider`, `Widget` | Builds, type-checks; saved and inline widgets render in an external React app with a session or a guest token |
| Built-in widgets | ECharts chart, AG Grid table, metric tile, select filter, filter bar, markdown |
| Dashboard V2 builder | Add, configure, move, save, reload; containers (tabs, collapsible, carousel); conflict dialog; embed dialog |
| Filters | Filter widgets narrow their targets; chart click cross-filters; host-controlled filters through the provider |
| Persistence and REST | `GET/POST/PUT /api/v1/dashboard_v2/`, saved widgets CRUD with paging, server-side widget data and filter values |
| MCP | Five read-only tools: `list_widget_types`, `get_widget_control_schema`, `list_saved_widgets`, `get_saved_widget`, `get_widget_data` |
| Extension widgets | Loaded once per page, started once per provider (`activate(core)`); see limitations |
| Arabic / RTL | Builder and widgets follow the interface direction; charts stay left-to-right |
| Keycloak | The demo's OIDC integration is untouched; the widgets stack can switch to it with `NXTBI_WIDGETS_AUTH=keycloak` |

Not included, by instruction: the AI, agent, chat, CopilotKit and A2UI parts of the PR were removed
(client tools, chat additions, artifact transport, the MCP OAuth server and its migration, widget prompts).

## 2. Defects found and fixed

From the PR review, from two rounds of independent review of this branch, and from running it.

**Save and load**

- Saves carry a revision. A stale save gets 409 with the current revision, a save without a base
  revision 428. The write is a compare-and-swap on the stored value, so two writers cannot both win.
- The revision only moves forward: version restore and import stamp the document with the stored
  revision plus one, so a tab holding an old revision can never match again.
- Every other writer of dashboard metadata (classic update, native filters, colours, chart
  customisations, MCP dashboard tools, copy, export, classic create) keeps or drops the document instead
  of overwriting or disclosing it.
- The client keeps one save in flight, drops writes that arrive after the document was replaced,
  reconciles a save whose answer was lost, and makes creates idempotent with a client uuid.

**Document trees**

- The server validates the whole document: one root, no cycles, no shared or missing children, known
  node types, typed props, limits on nodes (500), depth (16) and size (1 MB). All walkers on both sides
  are iterative. Node ids that collide with JavaScript object members are refused and repaired on load.

**Shared state**

- Widget context, event bus, extension host and node ids are per provider; two providers on one page do
  not see each other's filters or widgets.

**Routes and gating**

- V2 routes are registered ahead of the classic dashboard route; the flag gate runs before CSRF
  protection.

**Security**

- A guest may send an inline widget definition only with a `dataset` resource in the token; the
  `datasets` claim only narrows. A `widget` resource is bound to the dataset recorded when the token was
  minted. The minter must be able to read what it grants.
- Guests can never send SQL, Jinja or free-form expressions. Signed-in users may author SQL expressions
  only for datasets they can read, the same rule as an ad-hoc metric in Explore.
- Row-level security applies to widget data as to charts. A token for an RLS-protected dataset needs a
  covering rule, and a minter restricted by RLS on a dataset cannot grant it
  (`GUEST_TOKEN_WIDGET_RLS_GUARD`, on by default).
- ECharts options and AG Grid column definitions are allowlisted on the server at save time and again
  in the browser at render time; a test keeps the two lists equal.
- Reading a V2 document needs access to every dataset it binds; saving one checks new bindings against
  the author's access.

**Found by running it**

- The builder crashed under the production Content-Security-Policy: the properties form compiled JSON
  schemas with `new Function`. It now uses an interpreting validator; the policy is unchanged.
- A long dashboard scrolled the header and palette away; the "last saved" time was read in the wrong
  zone; the default rate limit (50 requests per second per address) answered 429 to an embedding page
  with about 25 widgets (raised in the widgets stack only).

## 3. Verification

Final run on the image `nxtbi/superset-fork:widgets` built from the branch, compose project
`nxtbi-widgets` (port 8089, its own database), production CSP.

| Check | Result |
|---|---|
| `nxtbi/widgets/scripts/widgets_e2e.py` | 25 passed, 0 failed, 0 skipped |
| Upstream Playwright `dashboard-v2` specs (plus the new stale-save spec) | 20 passed |
| `migration_cycle.sh` on a disposable PostgreSQL | single head `3c9e1a7b5d2f`; upgrade, downgrade, upgrade pass |
| TypeScript (`tsc --build`) | clean |
| oxlint on the widgets paths | clean |
| Jest: widgets package, core, builder, extensions, home, routes | 109 suites, 1,308 tests pass |
| Backend unit suites (dashboard_v2, dashboards, widgets, security, extensions, MCP, versioning, importers, DAOs, translations) | 5,318 tests: 5,302 pass, 2 skipped, 1 fails for a missing BigQuery driver, 13 setup errors in `extensions/test_sqlalchemy.py` (a file this branch does not touch; the test database cannot be created in the read-only test container) |
| ruff check and format on the changed backend paths | clean |

The E2E script covers: build, save and reload a dashboard in the builder; two editors and the conflict
dialog; filter and cross-filter; saved against inline widget data; the standalone React example with a
session and with a guest token (two providers, host filter, RTL switch); guest-token scoping, RLS, SQL
refusal and flag-off 404s; REST validation (14 invalid documents, oversized and malformed bodies); the
Arabic builder; the MCP tools. Browser checks fail on any uncaught page error or CSP violation.

## 4. Known limitations

| Item | Detail |
|---|---|
| Databases | SQLite unit tests exercise compare-and-swap and retries. The [PostgreSQL harness](../widgets/README.md#concurrent-dashboard-v2-saves-on-postgresql) checks overlapping V2 saves and a classic metadata edit on three independent connections. MySQL and MariaDB coverage checks the generated SQL. |
| mypy / pre-commit | Not run; ruff, oxlint, oxfmt and tsc were. |
| Semantic layer forms | Upstream's semantic layer and semantic view dialogs use the same JSON form library without the interpreting validator and are expected to fail under the production CSP. Not part of this work; not reproduced. |
| Extension widgets | Tested against a simulated Module Federation container, not a real extension bundle. An extension that registers only on import and calls the core without naming a node from a timer or event handler cannot be attributed when two providers show its widgets; the call throws. In the builder, an extension's data call without a node id runs unfiltered. |
| Stored definitions | A widget or document saved before the stricter rules (markup in chart strings, `graphic`, custom column types, a stray dataset reference) still loads but must be cleaned before its next save. |
| Guest tokens | Widget tokens minted before the dataset binding must be re-minted. The minting account must be an admin or unrestricted by RLS on what it grants. A virtual dataset whose SQL cannot be parsed is treated as protected. |
| Builder | Palette block names are not translated under Arabic. Parent/child pairing of containers is not enforced by the server. One observed case of a first chart click after clearing a filter not cross-filtering. A conditional-visibility rule on form fields did not hide the field in a unit render. |
| Keycloak on the widgets stack | Verified at configuration level only; a browser login on port 8089 needs its redirect URI added to the client, which was deliberately not changed. |
| Embedding hosts | The default application rate limit is too low for a page with many widgets; size it per deployment. `/static/service-worker.js` answers 404 on this stack. |
| Trash restore, welcome template | Restoring a deleted dashboard and the welcome-dashboard copy write metadata without the compare-and-swap; neither can race an open editor. |

## 5. Run it

```bash
docker build --target superset --build-arg BUILD_TRANSLATIONS=true -t nxtbi/superset-fork:widgets .
python nxtbi/widgets/scripts/gen_env.py
docker compose -f nxtbi/widgets/docker-compose.yml --profile flag-off --profile mcp up -d
python nxtbi/widgets/scripts/example_app.py            # session mode, http://localhost:5173
python nxtbi/widgets/scripts/example_app.py --guest    # guest-token mode, http://localhost:5174
python nxtbi/widgets/scripts/widgets_e2e.py
bash nxtbi/widgets/scripts/run_upstream_playwright.sh
bash nxtbi/widgets/scripts/migration_cycle.sh
```

The builder is at `http://localhost:8089/dashboard/v2/new/`. The main demo (project `nxtbi-superset`,
port 8088) is a separate stack and is not affected.
