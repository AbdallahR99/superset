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
Live Dremio driver and identity delegation, remote MCP authentication, and
connection of the bilingual resolver to Copilot remain separate lab work.
The provider is scoped to local synthetic data.

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
