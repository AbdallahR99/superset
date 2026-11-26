# NxtBI semantic layer research lab

**Baseline** `lab/nxtbi-semantic-layer` started from fork `15ba60ccff`
and Apache baseline `2c58859901`. Reviewed November 26, 2026 using the
workspace’s `chatgpt-research.md` and the earlier `nxtbi-semantic-layer` lab.

**Recommendation** Use a backend-only Superset semantic provider over one
approved Dremio-backed model in an isolated workspace. Keep Dremio responsible
for execution and data policies. Reuse the old lab’s model, evidence, approval
and validation. Use its Cube/PostgreSQL implementation as a comparison on the
same fixtures before taking on a second serving engine.

The first workflow should accept a property-market question in Arabic or
English, resolve an approved measure and grain, show compatible dimensions,
and draft editable charts with traceable totals. “Average property price”
should trigger a choice between average transaction price and price per square
meter. Display the definition, currency, scope, freshness and model version
alongside the answer.

## Superset’s existing capabilities

| Surface | What the pinned source supports | Lab implication |
|---|---|---|
| Provider | A backend package registers via `@semantic_layer`. Pydantic schemas drive the stock forms. A `SemanticView` supplies discovery, members, compatibility, value suggestions, Arrow data and counts. | Reuse the extension API and SDK conformance kit. Implement ordering before limits, required NULL/OR filter semantics, honest counts and explicit refusal for unsupported operations. |
| Explore and Classic | Explore supports a typed semantic-view source. Chart queries map to `SemanticQuery`. Native dashboard filters also distinguish semantic views. | Verify a native Explore chart, filter, saved chart, dashboard reload and the schema-generated forms under the configured CSP. |
| MCP | Standard routing lists semantic views and metrics, resolves compatible members, and runs typed table requests. Configured SQL-dataset routing excludes external views. | Reuse the native tools after verifying the actual MCP profile. |
| Copilot and V2 Widgets | The picker and approval gateway use `SqlaTable` integer IDs. The widget query path uses a native table reference. | Add a typed source binding with stable provider, view and member IDs plus model version. Route through the host’s data access check. Leave this for after Classic proves the provider. |

[Provider contract](../docs/developer_docs/extensions/extension-points/semantic-layers.md) ·
[Native semantic connections](../docs/docs/using-superset/semantic-layer-connections.mdx) ·
[MCP contract](../docs/developer_docs/extensions/mcp.md) ·
[Copilot gateway](../superset/copilot/services.py) · [Widget data path](../superset/widgets/data.py)

Upstream defaults both `SEMANTIC_LAYERS` and `ENABLE_EXTENSIONS` to off.
The NxtBI Copilot overlay enables Extensions. Semantic layers remain
independently opt-in. The public docs are marked **Next** and the release
listing includes a 7.0 candidate. Pin the SDK to the actual fork build.
[Upstream flags](../superset/config.py) · [NxtBI overlay](../nxtbi/config/superset_config.py) ·
[Superset releases](https://github.com/apache/superset/releases)

## Reuse the old lab

The prototype has a canonical Pydantic model, versioned drafts, deterministic
proposal generation, approval, and data checks for null keys, duplicates,
join coverage and cardinality. It emits Cube and Wren definitions and serves
actor-filtered `/meta` and `/query` APIs. Its labelled ecommerce, null/decimal
and service fixtures can test multiple engines against the same cases.

The prototype’s local Git repository has no commits or remote. Pin a reviewed
source snapshot before using it as a dependency. Its source contract targets
uploaded CSVs and local PostgreSQL. Warehouse registration, separate migration
and runtime principals, concurrent registry changes and Cube model-cache
lifecycle still need qualification.

Reference paths in the old workspace are `docs/CONTRACT.md`,
`src/nxtbi_sl/canonical.py`, `src/nxtbi_sl/generation/generator.py`,
`src/nxtbi_sl/validation/engines.py`, `src/nxtbi_sl/api/query.py` and `fixtures/`.

The local `references/schema-sense` checkout already includes native composite
key scoring and join-preservation diagnostics. Its optional Desbordante
adapter uses Spider for **single-column** sample inclusion, alongside
SmartJoin and Valentine. The old lab's `all` extra enables the latter two.
Keep Schema-Sense as the candidate and evidence source. Compare Desbordante
only for the extra dependency checks that could change the decision.
The source paths are `src/schema_sense/engines/desbordante_engine.py`
and `scripts/eval.py` in that reference workspace.

## Tools and communities

| Tool | Reuse decision and verification gate |
|---|---|
| Dremio | First execution path over approved views. The supplied research names Enterprise 25.2.14. Check the exact server and Flight/driver versions, authentication, grain parity and query plans. [Superset connector](https://docs.dremio.com/current/client-applications/superset/) · [25.x policies](https://docs.dremio.com/25.x/reference/sql/commands/row-column-policies/) |
| Schema-Sense, Valentine, SmartJoin | Keep the prior candidate pipeline. Combine column-match and joinability evidence with actual tuple coverage, uniqueness and fanout checks. [Valentine](https://github.com/delftdata/valentine) · [SmartJoin](https://github.com/tbrus/smartjoin) |
| Desbordante | Use as a lab comparator for inclusion and functional dependencies. Exact inclusion still needs a parent-key uniqueness check. The pinned package lists AGPL-3.0-only. Review licensing before any distribution or hosted adoption. [Project](https://github.com/Desbordante/desbordante-core) · [Package](https://pypi.org/project/desbordante/2.5.0/) |
| Cube Core | Compare joins, aggregates, policy and cache behavior using the old PostgreSQL lab. Its catalog lists Dremio and Dremio ODBC as third-party drivers. Measure the actual driver, identity propagation, cache isolation and benefit over Dremio before adoption. [Driver catalog](https://docs.cube.dev/admin/connect-to-data/data-sources) · [Security context](https://docs.cube.dev/docs/data-modeling/access-control/context) |
| Wren Semantic Core | Evaluate the open core for semantic planning. The old lab already emits MDL. Verify the exact package and compiler version. Direct Dremio execution and delegation remain unverified. [Core SDK](https://github.com/Canner/WrenAI/tree/main/core/wren-core/core) · [Connectors](https://github.com/Canner/WrenAI/blob/main/docs/core/guides/connect.md) |
| MetricFlow | Reuse the open compiler and CLI where dbt owns the definitions. The hosted dbt semantic service is separate and lists no Dremio connection. [Open engine](https://github.com/dbt-labs/metricflow) · [Hosted setup](https://docs.getdbt.com/docs/use-dbt-semantic-layer/setup-sl) |
| Apache Ossie | Test one pinned interchange schema for approved measures, dimensions and relationships. Run a round-trip with a loss report. Keep versioned review and policy in the registry. Ossie is incubating. [Project](https://ossie.apache.org/) · [Specification](https://github.com/apache/ossie/blob/main/core-spec/spec.md) |
| DataHub or OpenMetadata | Compare one catalog when shared glossary, ownership, lineage or quality data is needed. DataHub documents Dremio ingestion. Confirm coverage and access before catalog replication. [DataHub connector](https://archive.docs.datahub.com/docs/1.8.0/generated/ingestion/sources/dremio) · [OpenMetadata](https://github.com/open-metadata/OpenMetadata) |
| sqlctx and NVIDIA Auto Ontology | Try sqlctx on synthetic migration cases and Auto Ontology on optional business-context experiments. Check sqlctx’s AGPL-3.0 terms, conversion fidelity and the intended deployment boundary. Confirm a supported connector and review flow before exposing warehouse data to ontology extraction. [sqlctx](https://github.com/sidequery/sqlctx) · [Auto Ontology](https://github.com/NVIDIA/auto-ontology) |

SQLGlot can parse reviewed SQL for lineage. Its community Dremio dialect
still needs result parity checks. Superset NL Explorer is a source of
integration patterns for the existing Copilot.
[SQLGlot](https://github.com/tobymao/sqlglot) ·
[Superset NL Explorer](https://github.com/mitodl/superset-nl-explorer)

Start upstream conversations with SIP-182, the Polaris/Ossie integration
discussion and the Ossie Metrics & Querying working group.
[Superset SIP-182](https://github.com/apache/superset/issues/35003) ·
[Polaris/Ossie integration discussion](https://github.com/apache/superset/discussions/46271) ·
[Ossie community](https://ossie.apache.org/community/)

## Execution and quality gates

The pinned host enables **connection credential execution**. Its
`SemanticExecutionContext` carries host principal and role metadata and
supplies no delegated warehouse token. Superset checks semantic view
or layer grants. External views do not inherit SQL-dataset RLS. Applicable
guest row rules cause the semantic request to be refused. The first trial
needs an isolated, restricted read-only connection with the same upstream
catalog and row scope for every authorized user. Before widening that
scope, prove supported user delegation and cache isolation across metadata,
queries, asynchronous jobs, exports, MCP and proposed embeddings.
[Execution contract](../docs/developer_docs/extensions/extension-points/semantic-layers.md) ·
[Cache contract](../docs/developer_docs/semantic-layer-cache-clear.md) · [Threat model](../SECURITY.md)

1. Build a synthetic property dataset with a composite property key, duplicate
   parent candidate, orphan, NULL category, two role-playing dates and
   amounts with different denominators. Use two personas and a viewer without
   permissions. Preserve original member IDs with bilingual labels and aliases.
2. Load the packaged provider, run the SDK conformance suite against independently
   calculated Arrow tables, then verify Explore, filters, save/reload and MCP.
   Compare reference values for weighted ratios, distinct counts, time grain and
   fanout. Record cold and warm latency on the same approved workload.
3. For relationship discovery, record duplicate, unmatched and null counts,
   direction, scope and metric totals before and after the join. Keep inferred
   suggestions separate from approved definitions. Measure precision and recall
   on labelled positive and negative pairs before using the proposed 95%
   precision threshold for high-confidence suggestions.
4. Connect Copilot using only approved metric and dimension IDs and typed
   filters. Check an ambiguous bilingual request, an editable dashboard
   with exact reference values, and no cross-scope results. Select charts using
   time coverage, grain, cardinality and units. Show source, version and scope.
5. Extend to the original target of 10–15 tables and 20–30 metrics after this
   slice works. Add a V2/Widget typed source and a visual model review page
   when the user workflow needs them.

[Provider conformance](../docs/developer_docs/semantic-layer-provider-testing.md) ·
[Classic host test](../superset-frontend/playwright/tests/semantic-view/semantic-view-dashboard.spec.ts) ·
[Existing zero-code workflow](zero-code-bi.md)

## Property-market lab

The backend-only `nxtbi.property-market-lab` extension exposes
`property_transactions` through Superset’s native semantic-layer registry.
The bundled SQLite fixture uses transaction grain, a composite property
lookup, and a left join that preserves unmatched transactions. Its data
contains a reused property ID in a comparison market, one orphan, a missing
area, and independent sale and registration dates.

| Approved metric | All transactions |
|---|---:|
| Transaction count | 6 |
| Distinct properties, including the unmatched ID | 4 |
| Average transaction price | AED 400,000 |
| Weighted price per square meter | AED 3,737.70 per m² |

The weighted measure divides AED 2,280,000 by 610 m². Both components
use the same five transactions with positive area. The average transaction
price uses all six. The approved labels, definitions and aliases are bilingual.
The lab resolver returns both interpretations for **average property price**
or **متوسط سعر العقار** and a single stable metric for an explicit match.

The lab uses a fixed catalog and parameterized filters. It supports the
pinned SDK’s OR/NULL filters, day and month grouping for each date role,
complete dimension values, and exact counts of the requested result window.

[Provider](../nxtbi/semantic_lab/property_market/dist/backend/src/nxtbi_property_market/__init__.py) ·
[Approved model](../nxtbi/semantic_lab/property_market/dist/backend/src/nxtbi_property_market/model.py) ·
[Bilingual catalog lookup](../nxtbi/semantic_lab/property_market/dist/backend/src/nxtbi_property_market/metric_search.py)

Run the proof from the repository root with Docker, a local pinned Superset
image, and Playwright Chromium installed. Use `--image` to select a
matching fork image if the default tag is unavailable.

~~~bash
python -m pip install playwright
python -m playwright install chromium
python -X utf8 -u nxtbi/semantic_lab/host/run.py --mcp
~~~

The runner creates a fresh metadata database and loopback server, registers
the extension, saves the chart and dashboard, verifies the native filter,
runs the optional MCP check, and removes its container. The logs and
screenshot go under `nxtbi/out/semantic-lab/`.

For an interactive preview, set `NXTBI_SEMANTIC_LAB_PASSWORD` in the
current shell and run `python -X utf8 -u nxtbi/semantic_lab/host/run.py --serve`.
The runner provisions the same dashboard, prints its loopback dashboard
list, and waits. Sign in as `lab_admin` using the chosen password.
Ctrl+C disposes of the preview.

The proof exercises Superset’s authenticated browser/API path and native
MCP using FastMCP’s in-process transport under the disposable lab principal.
Live Dremio driver and identity delegation, and remote MCP authentication remain separate lab work.
The provider is scoped to local synthetic data.

## Draft semantic dashboards in Copilot

Open NxtBI Copilot in the semantic lab and choose **Semantic catalog**.
Select Classic or Dashboard V2, choose a language, then enter
**average property price** or **متوسط سعر العقار**. Copilot asks which approved
definition you mean. Choose average transaction price or weighted price per
square meter, review the total and property-type breakdown, then select
**Save dashboard**. For V2, open the draft from the receipt and choose
**Publish** in Dashboard V2. Use each widget's **Embed widget** menu to save
it and copy the SDK example for signed-in users.

The lab uses the same approved semantic view for previews and native
chart queries. Each dashboard saves an editable KPI and table with a stable
semantic datasource binding. It stores Arabic and English dashboard and
chart captions. The breakdown column headers use the creation language.
Query values and selections remain the same when captions switch.

The feature requires the lab's `NXTBI_COPILOT_SEMANTIC_LAB` setting, an
installed Property Market provider and access to its registered view. The
author needs the native Chart and Dashboard permissions. Approval is
signed for the active actor, view, metric, model version and locale, then
rechecked before an atomic save. The catalog tool resolves approved aliases
and runs native queries without a model call.

Dashboard V2 saves a native metric tile and table bound to the semantic
view UUID and approved member names. The builder can edit presentation
settings. Use Copilot's catalog to choose the source and measures. Dashboard
and widget captions follow the viewing language. Table headers retain the
authoring language, and dimension values come from the view.

Semantic widgets use the viewer's Superset session and native semantic-view
grants, including when rendered in a separate SDK host. Configure
credentialed CORS for that host's exact origin. Semantic widget queries and
semantic dashboard documents require a signed-in session. Saved semantic
widgets are listed for their owners and admins, and a user with the view
grant can open a shared widget directly by UUID.

Use the repository's Node version and installed frontend dependencies
to build and run the browser proof from the repository root. The Dockerfile
uses the lab's cached Linux asset-builder and Superset runtime images.
Install the Widget SDK example's dependencies once with
`npm --prefix superset-frontend/packages/superset-widgets/example ci`.

~~~bash
npm --prefix nxtbi/copilot/superset-extension/frontend run build
python nxtbi/copilot/superset-extension/package_bundle.py
docker build -f nxtbi/semantic_lab/host/Dockerfile -t nxtbi/superset-fork:semantic-lab-v2 .
python -X utf8 -u nxtbi/semantic_lab/host/run.py --copilot --image nxtbi/superset-fork:semantic-lab-v2
~~~

The runner mounts the compiled extension and the branch's Superset server
packages read-only, uses the cached `nxtbi/copilot-agent:zero-code-bi` image
on a private Docker bridge, and starts a fresh lab database. It seeds the
native view and runs Classic and V2 browser checks, including the separate
Vite SDK host. Evidence goes under `nxtbi/out/semantic-lab/`. The runner
removes its containers and network and stops the widget host.

### Copilot browser evidence

On November 26, 2026, the lab ran against
`nxtbi/superset-fork:copilot-localization-verified` and a newly packaged
`nxtbi.ai-copilot-0.1.0.supx` with SHA-256
`69a9907bd8b0eab80506e4caca294bd2c64fafe589de240e47ebaefda4895e2d`.
The archive manifest carries the canonical extension ID required by
Superset's packaged extension loader.

Chromium clarified both requests, previewed their exact totals and
property-type breakdowns, and saved two Classic dashboards through Copilot.
The English dashboard saved average transaction price at AED 400,000.
The Arabic dashboard saved weighted price at AED 3,737.70 per m² and reopened
in RTL. Opening the same Arabic dashboard in an English session switched its
dashboard and chart captions to English and preserved the semantic chart
bindings and values.

The Copilot SDK passed 23 tests, the extension passed 27 tests and
TypeScript checking, and the Superset Copilot backend passed 30 tests.
The lab and semantic SDK suite passed 240 tests with four capability skips.
Screenshots and logs are in
`nxtbi/out/semantic-lab/nxtbi-semantic-lab-fd8376fc95a9/`.

### Dashboard V2 and widget SDK evidence

On November 26, 2026, Chromium passed the full bilingual workflow on the
disposable lab image `nxtbi/superset-fork:semantic-lab-v2`
(`sha256:6223a6a5eff612a593d069a03629dcd6b988c8b9a3c638f16155b441c4cfc456`)
with the branch's Python packages mounted read-only and the packaged
Copilot bundle at SHA-256
`b3aed1c5ce36b35f49bd92c17af191ebc59ae01af0d2197be463fb8ac6e17c56`.

| Locale | Approved metric | Native KPI | Direction |
|---|---|---:|---|
| English | Average transaction price | AED 400,000.00 | LTR |
| Arabic | Area-weighted price per square meter | AED 3,737.70/m² | RTL |

Both requests clarified the metric, returned exact preview values, and
saved native V2 drafts through approval. Chromium published each draft
through the V2 toolbar, saved both widget IDs, and reopened the persisted
dashboard. The actual SDK example on a separate origin rendered both
KPI and property-type tables using the signed-in session. The test
checked the exact displayed values and both individual and combined SDK
snippets. A Gamma user had ordinary access denied before receiving the
native view grant. The same user could then open both published dashboards
read-only and render both sets of embedded widgets. The same run also
passed the Classic browser regression and its language-switch check.

The combined Copilot, Dashboard V2, Widgets, semantic-layer, and selected
guest-access pytest suites passed **3,399 tests** with one capability skip.
The scoped frontend Jest suites passed **752 tests** in 65 suites. The
Copilot extension passed **29 tests** and TypeScript checking. The browser
log and screenshots are in
`nxtbi/out/semantic-lab/nxtbi-semantic-lab-cde786527d52/`.

## Evidence from this lab

The integrated browser run passed on
`nxtbi/superset-fork:copilot-localization-verified`
(`sha256:402562bbe1be6bdb317a5ec953f1ca89359fbfa794818eed0432ffcc1323d732`).
It registered the extension through `LOCAL_EXTENSIONS`, rendered three
property types in Explore, and persisted and reopened a published Classic
dashboard. The Villa filter returned two transactions, one distinct property,
AED 570,000 average transaction price, and AED 2,714.29 per m².
The view did not appear in the ungranted Gamma viewer’s datasource list.
Native in-process MCP found the same view, its four metrics and all four
compatible dimension names, and returned the exact full-model aggregates.

The combined suite passed **240 tests** with four SDK capability skips,
including **25 new lab tests**. The browser run saved its screenshot and
logs under `nxtbi/out/semantic-lab/nxtbi-semantic-lab-8da8509c6b05/`.

The pinned SDK suite under `superset-core/tests/semantic_layers` passed
**215 tests**, with four skips for a query shape or capabilities the stub
does not support. The conformance subset passed **156 tests** with the same
four skips. **138 host unit tests** passed in a disposable Superset container.
They cover the runtime flag, transport wiring, provider boundaries and guest
RLS handling. They used the mounted fork source and local synthetic fixtures.
[SDK conformance commands](../docs/developer_docs/semantic-layer-provider-testing.md) ·
[Host semantic tests](../tests/unit_tests/semantic_layers) ·
[Guest RLS tests](../tests/unit_tests/security/semantic_guest_rls_test.py)

The earlier prototype passed **123 offline tests** for canonical models,
static validation, generation, registry diff and security-cache behavior
with its installed dependencies and Python 3.12. This pass did not start the
old Compose stack or query a live warehouse.

The local Schema-Sense ecommerce suite passed **20 tests**, with five
SmartJoin cases skipped because the optional engine was unavailable. The
native engine found the six labelled canonical foreign keys across five
sampling settings and the suite checked known aggregate preservation.
That ground truth covers single-column foreign keys. The composite probe
below covers a separate question.

The synthetic relationship probe used Desbordante 2.5.0 and independent
Python key-count checks in Ubuntu WSL. The cases were prescribed non-null composite
candidates. This measures verification behavior on these cases.

| Case | Exact tuple inclusion | Duplicate parent keys | Orphan child rows | Eligible |
|---|---|---:|---:|---|
| Valid composite key | Yes | 0 | 0 | Yes |
| Duplicated parent | Yes | 1 | 0 | No |
| Orphan composite tuple | No | 0 | 1 | No |

Run on Linux from the repository root.

~~~bash
uv run --no-project --with desbordante==2.5.0 python -B nxtbi/semantic_lab/relationship_probe.py
~~~

[Probe source](../nxtbi/semantic_lab/relationship_probe.py)

## Business-case acceptance

Use a common, independently calculated fixture to compare authoring quality,
dashboard correctness, saved publication and the resulting business decision.
Count each requested visual as delivered with correct data, intentionally
excluded with a reason, or failed. Compare latency after correctness and
role-scoped access pass.

| Case | What the fixture distinguishes |
|---|---|
| Property market by sale and registration date | Different month populations for the same transactions, repeat property sales, a composite join key, missing area, and four approved measures. April has zero sales and one registration. A transaction with unknown property type remains in the breakdown and contributes no weighted price when its area is missing. |
| Supplier delivery exceptions | One decision per eligible order line despite duplicate receipt events, partial deliveries, and repeated IDs across suppliers and workspaces. The independent benchmark expects 3 of 7 lines late (42.86%) against an unweighted mean supplier rate of 58.33%. It checks the exact exception, assigned owner, action, and due date, including an inclusive 50% escalation boundary. |
| Sales and returns across facts | Keep the older prototype's separately aggregated and full-outer-joined facts as a comparison. Compare the aggregate-before-join result to the independent fixture and make unmatched groups and zero denominators visible. |

The supplier test is a standalone SQLite acceptance fixture. The property
browser test saves a multi-metric document through the native V2 API, then
uses the builder and the Widget SDK. Multi-metric Copilot generation
still needs its own acceptance test.

From the repository root with the lab image and Widget SDK example
dependencies already installed.

~~~bash
python -X utf8 -u nxtbi/semantic_lab/host/run.py --business-cases --image nxtbi/superset-fork:semantic-lab-v2
~~~

On November 26, 2026, Chromium passed this run for English and Arabic on
`nxtbi/superset-fork:semantic-lab-v2`. Each dashboard showed four live KPI
tiles and both date-role breakdown tables, then published and reopened. A
signed-in SDK host on a separate origin rendered the saved registration
widget for each locale. The test checked the date-role scope through the
live widget API. The provider and Apache semantic SDK suites passed
**247 tests** with four capability skips, including the supplier cases.
Browser output and screenshots are in
`nxtbi/out/semantic-lab/nxtbi-semantic-lab-77906cdc5293/`.

### Reuse order for the warehouse pilot

The standard SQLAlchemy Flight connection is the first qualification
target. The lab image has PyArrow 26.0.1 and no Dremio dialect. PyPI's
`sqlalchemy-dremio==3.0.5` requires `pyarrow~=20.0.0`, while the lab's
base requires `pyarrow>=26.0.1,<27`. The resolver reproduced the
incompatibility. An isolated Apache Superset 6.1.0 compatibility check
resolved with Flight connector 3.0.4, SQLAlchemy 1.4.54, and PyArrow
18.1.0. That check establishes dependency resolution. The live
warehouse test remains open.

Use an isolated stable lane to qualify the first approved Dremio view.
If the pinned lab needs live warehouse execution sooner than a compatible
dialect becomes available, qualify the already installed Apache PyArrow
Flight client and the existing provider seam against the same exact
fixture. This still needs a supported authentication and policy path.
[Dremio Superset connector guide](https://docs.dremio.com/current/client-applications/superset/) ·
[Published connector packages](https://pypi.org/project/sqlalchemy-dremio/) ·
[Dremio Arrow Flight client guide](https://docs.dremio.com/current/developer/arrow-flight/)

1. Give data engineers ownership of approved Dremio views and of each
   metric's grain, eligible population, time role, unit, and version. Use
   Dremio grants and policies at the warehouse. Use the standard SQLAlchemy
   Flight connection and a native Superset SQL dataset for the first governed
   view. Add dbt data tests where an existing dbt project owns the model.
   Confirm the Dremio-maintained adapter supports the deployed versions
   before using it. [Superset connection](https://docs.dremio.com/current/client-applications/superset/) ·
   [Dremio access control](https://docs.dremio.com/current/security/rbac/) ·
   [dbt data tests](https://docs.getdbt.com/docs/build/data-tests) ·
   [Dremio adapter support](https://docs.getdbt.com/docs/local/connect-data-platform/dremio-setup)
2. Keep discovery evidence, owner approval, registry versioning, and golden
   check patterns from the old semantic-layer lab. Use Schema Sense for
   relationship candidates. Verify composite key uniqueness, fan-out and
   orphan rates against the serving warehouse before approving a model.
   [Dremio constraint behavior](https://docs.dremio.com/25.x/reference/sql/commands/alter-table/)
3. Use the pinned Superset external semantic provider only when a use case
   needs typed metric and dimension compatibility beyond the reviewed
   dataset. Treat the upstream Next provider API and fork V2 support as
   versioned lab dependencies. Use Apache's SDK conformance checks for
   adapter behavior and compare results to independent business fixtures.
   [Superset provider API](https://superset.apache.org/developer-docs/extensions/extension-points/semantic-layers/) ·
   [Conformance guide](../docs/developer_docs/semantic-layer-provider-testing.md)
4. For a real cross-fact case that the approved Dremio views cannot serve,
   evaluate Cube's native multi-fact planner first. Compare it to the old
   lab's separately aggregated results. Require matching values, warehouse
   pushdown, and tenant isolation with the actual driver before adopting it.
   Wren and MetricFlow have no verified Dremio execution path here.
   [Cube multi-fact views](https://github.com/cube-js/cube/blob/master/docs-mintlify/docs/data-modeling/multi-fact-views.mdx)

For the first Dremio verification, use one approved nonproduction fixture and
a scoped read-only connection with certificate verification. Check the
warehouse principal, exact aggregate and raw-source denial. Then exercise
two intended reader scopes through the actual BI query and cache path
before publishing tenant-sensitive data. A fixed warehouse credential
executes on behalf of that principal even when the UI authenticates viewers
individually. [Dremio principal function](https://docs.dremio.com/current/reference/sql/sql-functions/functions/QUERY_USER/)

## Live Dremio and generation comparison

The live read-only probe uses the official ADBC Flight SQL driver 1.13.0,
certificate verification, and the already configured HTTPS route for the
development warehouse. `SELECT 1, QUERY_USER()` passed and the effective
user matched the provided account. Direct TCP timed out. The account
received access denials for `sys.version` and `sys.options`, including
the read scoped to `exec.impersonation.inbound_policies`. Flight SQL
version metadata was also unavailable. The separately pinned
`sqlalchemy-dremio==3.0.4` dialect loaded and compiled SQL but its live
connection raised `FlightInternalError` before executing a query.

Run with `adbc-driver-flightsql==1.13.0`,
`adbc-driver-manager==1.13.0`, `python-dotenv`, and PyArrow available.
Use the existing local connection file containing `DREMIO_HOST`,
`DREMIO_PORT`, `DREMIO_USER`, and `DREMIO_PASSWORD`.

~~~bash
python nxtbi/semantic_lab/dremio_connection_probe.py --env-file <local-config> --configured-proxy
~~~

Use `--configured-proxy` where the workstation already has an explicit
HTTPS route for the endpoint. Output reports only the authentication
check and metadata visibility. Delegation status remains unknown.
End-to-end
delegation and RLS need the deployed Dremio version, two approved
warehouse viewer identities, the governed test view, and expected rows
for each identity. Then compare fresh sessions with `QUERY_USER()` and
the same bounded fixture query.
[Dremio inbound impersonation](https://docs.dremio.com/current/security/rbac/inbound-impersonation/) ·
[OAuth impersonation](https://docs.dremio.com/current/reference/api/oauth-token/#exchange-a-pat-with-user-impersonation) ·
[Flight JDBC compatibility](https://docs.dremio.com/current/release-notes/arrow-flight-sql-jdbc/)

### Same-input generation

Both applications used the same synthetic six-row CSV, English prompt,
and live OpenAI-compatible model. The request asked for four headline
measures, two distinct date-role tables with three measures each, and the
April comparison. The test used freshly generated results and recorded
semantic gaps before making any edits.

- **BinxtGen** generated a plan and published version 2. Nine reader
  visual queries returned successfully. The AED 400,000 arithmetic
  mean was correct. Records per property (1.5) replaced transaction
  count (6), distinct property count (4) was missing, and the AED
  456,000 mean of eligible prices replaced AED 3,737.70/m². The tables
  kept both distinct date roles, the Unknown row, and April's zero
  sales versus one registration. Their rows were unsorted and they used
  the substitute count and weighted measures.
- **Copilot** ran the exact request against native CSV upload and again
  against the same data with approved saved measures. The latter
  returned the four exact headline values in authenticated tool results.
  Both AG-UI streams ended before a proposal could be saved. The
  generic proposal contract accepts one measure and one optional group-by
  per table, so it cannot represent the exact two requested tables.
- **Copilot reduced control** generated four KPI tiles and two count-only
  date tables with a separate English-only prompt. Native approval,
  publication and a fresh Chromium reopen succeeded. All six chart
  requests returned HTTP 200 and the four raw KPI values matched the
  fixture. The weighted display rounded to 3,738. Dates were rendered
  as epoch milliseconds, neither table was chronological, and both
  omitted the requested property-type and multi-measure breakdown. The
  first reduced attempt rejected the model's string-encoded optional
  translations. The successful retry omitted that optional argument.

The artifacts, input hashes, and individual run outcomes are under
`nxtbi/out/semantic-lab/generation-parity/`. The published fixture was
synthetic. Warehouse viewer delegation remains a separate live check.

### Compound Dashboard V2 proposal

Copilot can propose a native V2 table with up to six saved measures and four
grouping columns in the order requested. The gateway checks every selected
field on the authorized dataset and rechecks the references on approval.
Tables sort by their grouping columns and display dates through the native
UTC formatter while keeping query values and nulls intact. The preview
carries the same fields, saved labels and fixed KPI precision. Optional
summaries are persisted as native Markdown. A validated compound proposal
ends the run after its approval event and tool result. Saving still requires
explicit approval. Scalar proposals and their existing Classic path remain
available.

The lab image is built with `nxtbi/semantic_lab/host/Dockerfile`. It includes
the current Copilot gateway and widget validators alongside the compiled
host assets. Build the agent target from `nxtbi/copilot/Dockerfile` and
package the Copilot extension with the existing commands in this lab.
The live benchmark uses the original CSV and English prompt under
`nxtbi/out/semantic-lab/generation-parity/` and the four approved measures
registered on the disposable upload.

The live model generated all four KPIs and both grouped tables from the exact
benchmark prompt. Chromium reviewed and approved the unchanged proposal,
published Dashboard V2 revision 1, and reopened it in a fresh session. All
six native queries returned HTTP 200 and matched the independent CSV
calculation. The dashboard showed six transactions, four distinct properties,
an AED 400,000 arithmetic mean, and AED 3,737.70/m² weighted price. Each table
showed six groups in chronological order, three metrics, and a blank weighted
price for `Unknown`. The persisted note explained April's zero sales and one
registration. The browser rerun corrected a locator that assumed the grid
cell was an immediate child of a row. No dashboard edits were needed.

The final loopback preview is `http://127.0.0.1:60418/dashboard/v2/1/`. The
`copilot/nxtbi-lifecycle-b77976e33b6d4aa6bd60be46ce46a180/` benchmark folder
contains `full-exact-prompt-verified.json`, the published screenshot, and
local sign-in and cleanup files.

The BinxtGen preview and its disposable database were stopped. Dremio
delegation remains deferred. The available configuration establishes
one warehouse principal, and the verified server denied reads of its
version and inbound impersonation settings. Two sanctioned warehouse
test viewers and their governed test scope are still unavailable.

### Analytical dashboards

Natural-language requests against an uploaded dataset use the authorized
evidence tools before making a proposal. The explicit draft action still
offers a quick overview. For an open analytical brief, Copilot checks
comparable saved measures, chooses charts that answer different questions,
and leads with a measured finding, an applicable caveat, and a decision.
When the request specifies the layout, Copilot preserves the requested
widgets and fields. Chart-bearing V2 dashboards group the findings and
charts in the order proposed, with the finding above the first chart.
Ranked comparisons use an opt-in horizontal bar style. Both query paths
order by the saved metric before applying the 12-category limit. Missing
values remain blank. Ordinary bars retain their vertical layout and
100-row limit. Chronological charts show points and preserve gaps for null
observations. The preview uses the same native widgets and query bindings
as the saved dashboard.

The lab image copies the semantic dashboard and widget authoring, query,
and reader-access code already mounted by the business-case runner. This
keeps the standalone image aligned with the checked-out branch.

The live pricing benchmark used the same six synthetic transactions and
saved measures. After querying both measures, Copilot generated two ranked
charts and explained the reversal. Villas averaged AED 570,000 per
transaction against AED 380,000 for apartments. Apartments averaged
AED 6,000/m² on an area-weighted basis against AED 2,714.29/m² for villas.
The proposal recommended using price per square meter for area-based
pricing and gathering more area-complete transactions before setting rates.
The Unknown category kept its blank weighted result.

Chromium approved and published the unchanged proposal, then reopened it in a
new session. Both native queries matched the CSV oracle. Their SQL sorted by
the saved metric descending before the limit. Canvas checks verified the
displayed ranking in both charts. The pricing dashboard is at
`http://127.0.0.1:57525/dashboard/v2/1/`. The benchmark artifacts, screenshot,
and local sign-in details are under
`copilot/nxtbi-lifecycle-8df4956ed11747a79c3a1f0a28f2d32e/`.

Both final browser benchmarks ran Superset image
`sha256:8c75bb4f15e759fc5a0804402e75e1ee2ece3868034813f2fb06222de0dea6ae`,
agent image
`sha256:d6f1638930647d524a322ad717c98cd9ba3dd8886fc6208b6a441e848ce9a717`,
and extension entry `remoteEntry.9d949975784bde7a0ecd.js`. The MCP service
passed its port 5008 readiness probe. The fixture inherits a web-port health
check for the MCP container, where that port is unused.

Regression checks passed for 731 Superset Python tests, 762 frontend Jest
tests, 34 extension tests, and 80 agent tests. The extension type check and
the repository's changed-file checks passed.
