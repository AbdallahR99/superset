# Zero-code BI in NxtBI

An author can start with a registered dataset or upload a CSV, build a chart
in Superset Explore, and review and publish a dashboard without writing SQL.
The NxtBI authoring guide links those steps. Copilot can also draft a Classic
or V2 dashboard from one registered dataset using saved metrics and
deterministic rules. [Superset's native authoring workflow](https://superset.apache.org/user-docs/using-superset/creating-your-first-dashboard/)

## Capabilities and deployment

| Capability | What an author can use |
|---|---|
| **Native Superset** | Register a table or view on an approved database connection in **Data → Datasets**. In Explore, choose a chart, saved metric, dimensions, and filters. Supported charts also offer simple visual aggregations. Save the chart to a new or existing dashboard, add dashboard filters, and publish when ready. Native CSV uploads require a supported, upload-enabled connection. [Superset authoring](https://superset.apache.org/user-docs/using-superset/creating-your-first-dashboard/) · [Visual exploration and file uploads](https://superset.apache.org/user-docs/using-superset/exploring-data/) |
| **NxtBI Copilot overlay** | The demo configuration enables Copilot, Extensions, and Dashboard V2 together when `NXTBI_COPILOT_ENABLED=true`. This branch adds the **Build a dashboard** guide and an existing-dataset picker alongside CSV import. Both deterministic draft actions use the Superset gateway, agent, and authenticated MCP metadata reads. The actions work without an LLM. The supplied demo Compose overlay still expects model settings for chat. [Demo configuration](../nxtbi/config/superset_config.py#L126) · [Copilot overlay](../nxtbi/copilot/docker-compose.yml) · [Agent](../nxtbi/copilot/agent/app.py) |
| **SaaS pilot** | The isolated tenant fixture is a viewer proof. Its custom viewer role can open the seeded dashboard. Copilot and the extension host are disabled there. An author role needs separate qualification. [Tenant configuration](../nxtbi/saas/tenant/superset_config.py) · [Pilot scope](../nxtbi/saas/README.md) |
| **External semantic views** | Native Explore can use views exposed by an installed provider when `SEMANTIC_LAYERS` and Extensions are enabled. The new Copilot picker and proposal flow are scoped to native SQL-backed dataset IDs. External semantic-view references need a dedicated adapter. [Superset semantic connections](../docs/docs/using-superset/semantic-layer-connections.mdx) · [Copilot query and approval services](../superset/copilot/services.py) · [Widget query binding](../superset/widgets/data.py) |

The visual workflow removes the need for an author to type SQL. Superset
still queries the underlying source and enforces the signed-in actor's
permissions and applicable row-level security. Registering a source, uploading
data, saving charts or dashboards, and enabling SQL Lab each have their own
permissions. Dashboard filters change the view. Tenant isolation depends on
grants and warehouse policy as described in the SaaS plan.
[Superset security configuration](https://superset.apache.org/admin-docs/security/) · [NxtBI tenant boundaries](saas-tenancy-plan.md)

## Native features worth using first

| Stage | Use Superset for | Authoring decision |
|---|---|---|
| Prepare | Physical datasets and existing warehouse views. Register dimensions, time columns, saved measures, and visible descriptions. | Name the business grain and units on the dataset. Use Count for a row count and a saved measure for domain totals, averages, or ratios. Keep repeatable joins and transformations in a curated source. |
| Explore | Saved and simple measures, chart-type controls, filters, previews, and exports. | Start with a KPI plus a bar comparison for a few categories. Add a line chart when the dataset has a meaningful time grain. Use a table for detail and a pivot for comparisons across two dimensions. |
| Compose | Classic native filters, dashboard layout, filter scope, and chart interactions where supported. Dashboard V2 provides registered widgets, edit history, and explicit publishing in the NxtBI build. | Preview changed filters and check that the intended charts respond. Reopen the saved dashboard as a viewer before sharing. |
| Distribute | Published links, permitted chart exports, native dashboard embedding, saved and inline Widget SDK integrations, and configured alerts or scheduled reports. | Treat each delivery method as a separate permission and identity check. Qualify report executors and destinations before enabling customer scheduling. |

[Native chart and dashboard walkthrough](../docs/docs/using-superset/creating-your-first-dashboard.mdx) ·
[Dashboard embedding](../docs/docs/using-superset/embedding.mdx) ·
[Alerts and reports](../docs/admin_docs/configuration/alerts-reports.mdx) ·
[NxtBI Widget SDK](../nxtbi/docs/WIDGETS.md)

## Draft from existing data

1. Open **Build a dashboard** from the navbar. The contributed page requires
   dashboard write permission and links to native Datasets, chart creation,
   and Dashboards. Its **Open Copilot** button appears when the chat is
   registered. The guide follows the app's English or Arabic language and
   direction. [Authoring guide](../nxtbi/copilot/superset-extension/frontend/src/AuthoringGuide.tsx)
2. In Copilot choose a dashboard format and content language, then select
   **Use existing data**. Search or page through the accessible dataset list,
   choose a dataset, and select **Draft from existing dataset**. For a new
   file, use **Choose CSV files → Import CSV files**, select the imported
   dataset, and choose **Draft dashboard from dataset**. The Copilot uploader
   requires upload permission and an authorized destination. Its limit is
   10 MiB per file or the lower configured limit.
   [Dataset picker](../superset-frontend/packages/nxtbi-copilot/src/ExistingDatasetPicker.tsx) · [CSV import](copilot.md#csv-imports-in-copilot)
3. Review the evidence and previews. The deterministic draft prefers an
   existing saved measure over a generic count, tries up to three saved measures,
   profiles up to three fields,
   and adds a comparison or a trend when the observed data supports it.
   Drafts use one dataset, with joins and metric definitions supplied by the
   source model. Sparse data or a long date series may yield only a KPI or
   comparison. A dataset without a saved metric needs one before it can be
   drafted. A user can change the saved
   metric and eligible fields in the proposal editor and refresh previews.
   [Draft planner](../nxtbi/copilot/agent/uploads.py) · [Proposal editor](../nxtbi/copilot/superset-extension/frontend/src/ProposalEditor.tsx)
4. Select **Review and save** and confirm. Superset revalidates dataset
   bindings and permissions before writing. Classic also requires chart write
   permission because it creates native charts. Open the saved draft, check
   its values and filters, then publish and share through the builder. The
   English and Arabic caption variants are reviewed separately from the
   queries. [Approval and localization](copilot.md#localized-generated-dashboards)

## Ranked next steps

1. **Build a guided saved-measure editor.** Start with count or a compatible
   column and an allowlisted aggregate. Show the measure label, format, and
   preview under the current user's RLS. Save only after confirmation with
   native dataset editorship and the additive metric update path.
   [Native additive metric command use](../superset/mcp_service/dataset/tool/create_dataset_metric.py)
2. **Qualify grouping and date grain.** Offer only supported granularities,
   compare observed group count with the chart limit, and keep totals and date
   scope visible. Aggregate with the existing saved definition. Require an
   explicit scope when a point-in-time measure could be summed across periods.
   [Native Explore controls](https://superset.apache.org/user-docs/using-superset/exploring-data/) · [Snapshot draft rules](../nxtbi/copilot/agent/snapshot.py)
3. **Improve Arabic CSV profiling.** Recognize non-ASCII headers, keep original
   display labels, and show inferred types and parse issues before committing.
   Let the author confirm ambiguous dates, numbers, and candidate dimensions.
   The existing uploader and planner currently use English and ASCII naming
   heuristics when choosing measures or comparisons.
   [Upload heuristics](../superset/copilot/upload.py) · [Planner heuristics](../nxtbi/copilot/agent/uploads.py)
4. **Qualify a workspace author role.** In isolated tenant deployments, verify
   author and viewer flows separately. Test permitted data reads, draft and
   publish permissions, upload destinations, and denials from the other tenant
   before enabling Copilot or authoring for a customer.
   [SaaS pilot and evidence gates](saas-tenancy-plan.md)
5. **Add a semantic-view adapter when a shared metric catalog needs it.** Start
   with one installed provider. Verify typed source bindings, compatible
   measures and dimensions, execution identity, preview, and save before
   exposing the new source in the picker.
   [Superset semantic provider contract](https://superset.apache.org/developer-docs/extensions/extension-points/semantic-layers/)

## Tools and extension boundary

The implementation uses the existing runtime and packages. Keep the guide,
picker, and product orchestration in the NxtBI extension and sidecar. Superset owns
session identity, dataset authorization, authoring validation, and writes.
Register future pages and actions through the extension API and use native
commands behind protected endpoints. Use the Superset Extensions CLI when
starting a separate extension bundle.
[Superset contribution points](https://superset.apache.org/developer-docs/extensions/contribution-types/) · [Fork maintenance plan](upstream-maintenance-plan.md)

If several BI tools need consistent definitions across tables, dbt MetricFlow
can define metrics and related dimensions at the model layer. For teams
already using dbt, add source and model tests for required values, uniqueness,
accepted values, and join relationships. Those checks complement the in-app
profile and review. DuckDB is worth evaluating in an isolated staging step
when files need better dialect inference or row-level parse diagnostics.
Keep governed warehouse ingestion and source authorization in place.
[MetricFlow semantic models](https://docs.getdbt.com/docs/build/semantic-models) · [dbt data tests](https://docs.getdbt.com/reference/resource-properties/data-tests) · [DuckDB CSV detection](https://duckdb.org/docs/current/data/csv/auto_detection) · [DuckDB parse diagnostics](https://duckdb.org/docs/2.0/data/csv/reading_faulty_csv_files)

Consider Great Expectations when ingestion teams need standalone validation
reports outside dbt. Evaluate Cube as a semantic provider only when shared
query-time metrics or measured rollup performance justify another service.
[Great Expectations validation](https://docs.greatexpectations.io/docs/core/run_validations/) ·
[Cube semantic modeling](https://cube.dev/docs/product/data-modeling/concepts) ·
[Superset provider extension contract](https://superset.apache.org/developer-docs/extensions/extension-points/semantic-layers/)

## Verified workflow

On November 26, 2026, the isolated lifecycle fixture passed against a fresh
PostgreSQL database, authenticated MCP, the packaged Copilot extension, and
a rebuilt agent. The browser opened the guide, found a registered dataset,
previewed its revenue KPI at 550, and saved and reopened both Classic and V2
drafts. The fixture also seeded a saved measure with no numeric result. Agent
tests verify that the planner can advance to another authorized saved measure
within its query budget.

The browser also verified CSV import, English and Arabic content and
direction, V2 edit history and publishing, and the actual Widget SDK. Both
saved and inline guest widgets returned the RLS-filtered total of 250. The
session widget returned the full synthetic total of 550. The fixture ran with
no model configured and tore down its services.

- Agent pytest passed 66 tests. Extension Node tests passed 20 tests. The
  shared Copilot SDK passed 22 Jest tests across four suites.
- Extension TypeScript and Webpack packaging passed. Scoped Ruff, Oxfmt,
  oxlint, and diff checks passed.
- Superset image `nxtbi/superset-fork:copilot-localization-verified` had digest
  `sha256:402562bbe1be6bdb317a5ec953f1ca89359fbfa794818eed0432ffcc1323d732`.
  Agent image `nxtbi/copilot-agent:zero-code-bi` had digest
  `sha256:a8f26a40b6163385270238111a3c40ebd6bc257b90d5b4fe3187f07e43bf819d`.
  The extension archive SHA-256 was
  `8435c0736d0ea7c6f1aabee3c3e6490f1032b90a7312d948d25a9e8f61024c2d`.
- For build and startup commands, use the
  [Copilot lifecycle instructions](copilot.md#copilot-and-dashboard-v2-lifecycle).
  This run wrote its logs and screenshots to
  `nxtbi/out/copilot-lifecycle/nxtbi-lifecycle-255b925b018f479896938274c8044b00/`.
