# NxtBI Copilot

The Copilot SDK lives in `superset-frontend/packages/nxtbi-copilot`. The
React chat consumes AG-UI streams, validates A2UI 1.0 activity snapshots, and
keeps editable state in the mounted conversation. Hosts supply a request
transport, page context, locale, theme tokens, and optional actions and catalog
components. Use `@nxtbi/copilot/a2ui-core` for the framework-independent
contracts and reducer. The SDK has no Superset imports.

The native Superset Chat extension in `nxtbi/copilot/superset-extension`
registers the trigger and panel through `chat.registerChat`. Superset provides
floating and docked placement. The adapter supplies page and accessible entity
IDs, renders inline previews using the Widget SDK, and handles authorized
dashboard navigation. The independent React host uses the same SDK and
validates A2UI snapshots through a registered CopilotKit v2 activity renderer.
[A2UI 1.0 schemas](https://a2ui.org/specification/v1.0/schemas/) ·
[CopilotKit components and surfaces](https://docs.copilotkit.ai/ag2/generative-ui/components)

The FastAPI service uses PydanticAI and its AG-UI adapter. It streams text,
typed tool activity, and versioned A2UI operations. The model can compose a
bounded declarative graph using the registered catalog. The client validates
components, data bindings, and actions again. Explicit renderer actions send
the resolved form context back on the next AG-UI run.
[PydanticAI AG-UI adapter](https://ai.pydantic.dev/ui/ag-ui/)

## CSV imports in Copilot

Open Copilot and select **Choose CSV files**, then **Import CSV files**.
Each UTF-8 CSV with a header becomes a separate Superset dataset. The file
limit is 10 MiB or the instance's lower configured limit. Choose an imported
dataset and select **Draft dashboard from dataset** for a preview, or type an
analysis request to use GovAI. **Review and save** is the same approval flow as
for other Copilot dashboards. Publishing remains a builder action.

Superset writes files through its native uploader using the signed-in actor
and the **Database → can upload** permission. The configured destination must
allow file uploads, and its schema must pass the native access checks. Copilot
uses the single eligible destination. Administrators can narrow the selection
with the optional `NXTBI_COPILOT_CSV_DATABASE` database name and
`NXTBI_COPILOT_CSV_SCHEMA` in Superset configuration. The main demo uses its
existing upload-enabled `examples` database.

An import registers row count and suitable numeric metrics. The one-click
draft uses registered metrics, observed coverage and useful low-cardinality
breakdowns without a model request. Copilot sends the selected dataset ID in
chat context. The file goes to Superset, which imports its rows. Model-assisted
queries use the same permission and aggregation controls as other datasets.
Related files remain independent datasets until their relationships are modeled.

## Authorization and dashboard approval

Superset authenticates the browser through its normal session and sends a
short-lived, audience-bound capability to the agent. The server filters
the tool list to supported operations and uses a short-lived MCP token for
the initiating user. MCP enforces its existing role, object, and metadata
checks. Widget reads use the browser principal and the existing Widget
REST permissions and row-level security.

The Superset catalog provides a `SupersetWidgetPreview` component. The
agent checks each saved Widget UUID under the signed actor before emitting a
component. The browser rechecks access through the Widget REST API when the
component loads its definition and data.

The model proposes registered widget types and references to existing
datasets, metrics, and columns. Superset validates those references before
returning a proposal. The user can edit the proposal and explicitly confirm
the save in the trusted panel. Approval revalidates permissions and uses
Dashboard V2’s UUID idempotency to make a retry return the same dashboard.
The model receives no dashboard write tool, SQL execution tool, or approval
capability.

After approval, Copilot shows **Dashboard saved** with an **Open dashboard**
button. Dashboard lists and recent activity link to the V2 builder for saved
V2 documents. Classic ID and slug bookmarks redirect there after the normal
access checks. For example, the demo's `/dashboard/test/` opens the saved
**Demo Sales Dashboard** at `/dashboard/v2/49/`.

For a classic **Big Number Total** chart with one saved metric and no active
filters, the chart's **Share → Embed with Widget SDK** action exports a React
`MetricTile` using the viewer's Superset session. Other chart configurations
can be built as native V2 widgets, then shared from **Embed widget**.

## Start with the existing NxtBI stack

Run from the repository root. Use the existing demo environment and keep the
model settings and signing material in the ignored `nxtbi/copilot/.env`.
Copy `nxtbi/copilot/.env.example` for a new configuration. Configure an
OpenAI-compatible endpoint and tool-capable model,
`NXTBI_COPILOT_SHARED_SECRET` with at least 32 characters, and the standalone
example’s Basic-auth password. The Docker overlay uses the authenticated
NxtBI MCP sidecar in HS256 mode. The web service and agent run on the Compose
network. Only the example and existing Superset ports bind to localhost.

```bash
npm ci --prefix superset-frontend
npm --prefix nxtbi/copilot/superset-extension/frontend run build
python nxtbi/copilot/superset-extension/package_bundle.py

docker compose -p nxtbi-superset \
  --env-file nxtbi/.env --env-file nxtbi/copilot/.env \
  -f nxtbi/docker-compose.yml -f nxtbi/copilot/docker-compose.yml \
  --profile copilot-example build superset copilot-agent copilot-example

docker compose -p nxtbi-superset \
  --env-file nxtbi/.env --env-file nxtbi/copilot/.env \
  -f nxtbi/docker-compose.yml -f nxtbi/copilot/docker-compose.yml \
  --profile copilot-example up -d --wait
```

The Superset image overlay defaults to the verified upstream-sync base image
referenced in [Git state](git-state.md). Build that base locally first or
set `NXTBI_COPILOT_SUPERSET_BASE_IMAGE` to the corresponding packaged fork
image. Rebuild the base from this checkout to include changes to the classic
chart share menus. The Copilot feature flag is off in the base deployment.
The overlay enables Dashboard V2 and Extensions in the initializer and web
service. The native initializer synchronizes the extension permissions. When refreshing
web only on a stack that enables Extensions for the first time, run
`superset init` inside the feature-enabled web container to sync permissions.

Open Superset on port 8088, sign in through Keycloak, and open the Copilot
from the app header. The standalone example is at
[http://localhost:5186](http://localhost:5186) and uses the demo-only credentials
in the Copilot environment file. Both hosts send user prompts to the
configured model endpoint. Superset tool results sent to that endpoint are
limited to authorized metadata and bounded aggregate results. The analysis
tools run with the signed-in user’s dataset permissions and row-level security.
They return row counts, column coverage and date bounds, or at most ten groups
for a saved metric. The browser fetches live widget data directly through
Superset.

## Dataset analysis and dashboard proposals

Copilot checks accessible datasets for populated groupings and usable time
coverage, then queries saved metrics to substantiate its recommendations. For
annual snapshots, the proposal carries the verified year into each point-in-time
KPI and breakdown. The line chart queries the temporal dimension in ascending
order. Percentage tiles take their precision from the saved metric format.
The proposal editor shows each fixed filter and offers a chart style selector.
Approval validates the filters, metrics, and dimensions again before saving.
Readiness rankings cover the datasets Copilot inspected. Proposals can bind
one fixed equality filter per widget and use existing saved metrics. Dataset
and metric authoring continue through Superset’s data modeling tools.

The chat and History display assistant replies using the same Markdown
renderer. Headings, lists, tables, links and code remain legible in both
directions. Embedded HTML displays as text and remote images are omitted.

## Coverage and limits

The verification stack ran Superset at [port 18088](http://localhost:18088)
and the independent app at [port 5186](http://localhost:5186) with the same
GovAI `qwen-3.8-27b-fp8` agent. Chromium passed all seven Superset checks.
The Planning user signed in through Keycloak, discovered authorized data,
edited a proposal with live widgets, approved it once across retries, and
reopened the saved dashboard. An actual model-authored A2UI tree rendered a
saved Widget. The suite also exercised an A2UI navigation action, Arabic RTL,
and a separate Statistics user denied access to Planning data and dashboards.

Chromium passed all six standalone checks,
including authentication, streamed forms and tables, an edited field
round trip, Arabic RTL, cancellation, and recovery without page errors.

The built Superset image passed 409 focused pytest tests. The agent passed
20 protocol and gateway tests. The SDK passed nine Jest tests, and the
compiled Superset extension passed 14 focused tests and TypeScript. Native
PydanticAI spans use the host OpenTelemetry provider and omit user and tool
content. A synthetic exporter verified the content exclusion.

Restarting the isolated web, agent, and example containers preserved the
PostgreSQL, Redis, MCP, and Keycloak container identities and start times.
An authenticated GovAI form run completed in 5.14 seconds after the restart.

Re-run the browser checks with the isolated stack running and Python
Playwright configured.

```bash
python nxtbi/copilot/tests/superset_e2e.py
python nxtbi/copilot/tests/standalone_e2e.py
```

Verification logs are under the ignored `nxtbi/out/copilot/` directory.

Open **History** in the Superset Copilot panel to resume a recent conversation
after closing the panel or navigating to a dashboard. Copilot shows the ten
most recently updated conversations for the signed-in account. It stores chat
text and saved dashboard links encrypted in Superset's metadata database.
Interactive previews and unsaved proposals are session state. The original panel
held conversations from before history was enabled in memory. Saved dashboards
persist in the metadata database. Available host context
depends on the installed Superset extension API. Filter interactions use the
Widget preview provider and native dashboard controls. Classic dashboard
filter state is outside the Copilot adapter. The standalone app uses a
separate demonstration identity and catalog. GovAI was the verified model
provider. An optional Ollama smoke run reached the agent time limit.

## Main demo Copilot update

The Copilot update on port 8088 used `nxtbi/superset-fork:copilot-demo-polish-20261118`
with image digest `sha256:b040b8d394231aadb25dbdf29099d2848ca9c33560e5032c9a9b5b79e5620d7b`.
The rollout recreated only the web container. The database fingerprints,
service settings and mounts matched the snapshot from before rollout.
The previous image is tagged `nxtbi/superset-fork:main-demo-pre-copilot-polish`.
The matching extension manifest is in the ignored
`nxtbi/out/copilot/demo-polish-rollback-manifest.json` on the demo host.

The final image passed all 34 live smoke checks. Chromium verified the
original saved dashboard and its six widgets, a new Copilot save and retry,
history in a fresh signed-in session, English desktop and Arabic mobile,
and a Widget SDK snippet from **Allocated Budget** in the classic dashboard
and in Explore.

The Dashboard V2 toolbar update used `nxtbi/superset-fork:dashboard-v2-toolbar-20261118` at
`sha256:5aa8fa12f21820366b4c16ac841e3327a6f4c240bf88f50b76e4762f025a63d4`.
The Copilot update image is the rollback tag for this version. The builder
exposes Undo and Redo for in-session edits, History for saved changes, and
Publish and Unpublish for the saved dashboard. The live browser test kept
dashboard 49 in Draft and exercised both publication actions on a temporary
dashboard. The focused checks passed 151 frontend and 93 backend tests.

## Dashboard workflow and card previews

The Copilot starter actions help find authorized datasets and dashboards or
begin a proposal. In the proposal editor, pick a dataset, saved metric, and
grouping column by name. Changing datasets clears the previous bindings.
Refresh the widget previews, then review and save a draft. Open it in the
builder and use **Publish** once the saved version is ready to share.

The NxtBI demo uses `DASHBOARD_LAYOUT_THUMBNAILS` for immediate previews based
on saved widget placement. Classic cards load a screenshot when available.
V2 uses its layout preview. These layout previews contain no query results.

The workflow update uses `nxtbi/superset-fork:copilot-workflow-20261118` and
`nxtbi/copilot-agent:workflow-20261118`. The preceding web and agent images
are `nxtbi/superset-fork:dashboard-v2-toolbar-20261118` and
`nxtbi/copilot-agent:before-workflow-20261118`. The matching rollback extension
manifest is in `nxtbi/out/copilot/workflow-rollback-manifest.json` on the demo host.

On the final images, Chromium verified that the Planning user could discover
datasets, edit metric and grouping selections, load real widget previews,
approve a draft, reopen it through History, and publish it across a reload.
Dashboard V2 read validators include publication and permission metadata,
while writes keep their document revision precondition. The focused backend
suite passed 102 tests and the agent suite passed 20 tests.

## Evidence-based Copilot rollout

The evidence-based rollout on the main demo used
`nxtbi/superset-fork:copilot-analysis-polished-20261118` and
`nxtbi/copilot-agent:analysis-polished-20261118`.
The image digests are `sha256:e07f0e8aa0fd39aab67e2734fcf6fa39f5c971b11fc6ad762946c00be9d33089`
and `sha256:5b08164a65ba417dc23d48dcb405e03cd130a734c95b563538c09ed6a0b8e109`, respectively.
Rollback uses `nxtbi/superset-fork:copilot-analysis-20261118`,
`nxtbi/copilot-agent:analysis-verified-20261118`, and the matching manifest
saved at `nxtbi/out/copilot/analysis/before-polished-manifest.json` on the demo
host. The workflow images and `rollback-manifest.json` remain available for
the pre-analysis version.

All 34 live smoke checks passed. The rollout preserved the fingerprints of
existing data, mounts, environment, and shared services. Chromium reopened
the original population conversation with formatted Markdown and confirmed
its stored text was unchanged. The original population dashboard is still
an unpublished draft.

Live GovAI runs profiled four candidate datasets, and an independent replay
also queried four saved metrics. Some runs returned the profiles alone.
The follow-up proposed a temporary population draft. Chromium saved and
reopened it through the approval flow. Its KPIs used the 2026 snapshot, with
10,155,391 total, 48.7% female share, 32.1% youth share, and 13.0% senior share. The trend
contained 12 chronological points. In October 2026 budget data, Energy had
the lowest execution rate at 77.96%, and Infrastructure had the largest
unspent balance at 5,564,682.09. Both use the synthetic demo data.

On the polished images, a fresh GovAI proposal passed the browser save and
reopen checks. Chromium verified readable dates on the trend canvas and
the table's saved title. Test drafts were removed through the standard
dashboard API.

Intermittent TLS connection timeouts to GovAI interrupted some live replays.
After connectivity recovered, the final images passed a complete replay of
the original opening question, its population-dashboard follow-up, and the
independent budget comparison. The application kept its provider settings.

The focused Copilot and widget backend checks passed 100 tests, the agent
passed 25, and the Copilot and Widget SDKs passed 173 Jest tests. Full
Superset, the Chat extension, and the standalone example built successfully.
The broader Dashboard V2, Widgets, and Copilot backend run passed 622 of 655
tests. All 33 failures reproduced on the previous image. The Dashboard V2
fixtures lack an authenticated Flask user, and one widget schema test hits a
timezone dependency error during MCP registration in the test environment.

## Markdown quote rollout

The quote rollout on the main demo used
`nxtbi/superset-fork:copilot-4558abd734` at
`sha256:7b7ad5f10e7fe14b3dcfc74a0cc95f124c7239aa1172bce8d0fcb48ac252b56b`.
The image includes Copilot commit `4558abd734`. The rollout replaced only
the web container. Database fingerprints, settings, mounts, and dependent
container identities matched the pre-rollout snapshot. Chromium opened the
same saved conversation and verified that the deployed stylesheet draws the
1px quote border on the leading edge in both reading directions.
All 34 live smoke checks passed on this image.

The previous web image is `nxtbi/superset-fork:copilot-analysis-polished-20261118`.
Its manifest and the web-only rollback script are in
`nxtbi/out/copilot/quote-rollout-4558abd734/` on the demo host.

## CSV import rollout

The main demo at [port 8088](http://localhost:8088) runs
`nxtbi/superset-fork:copilot-csv-20261119` at
`sha256:9e41fcc75bf45c6cdb735369b936c730f851b0f37ad41d5872aa0e1387e696ec`
and `nxtbi/copilot-agent:csv-20261119` at
`sha256:a4f63e97d15ecfbd124c5876401ae3d204f9ac9ae5750607277279055140fb08`.
The prior web and agent tags are `copilot-4558abd734` and
`analysis-polished-20261118`. The previous extension manifest and rollback
script are in `nxtbi/out/copilot/csv-upload-20261119/` on the demo host.

Chromium imported the synthetic `orders.csv` and `payments.csv` from
`E:/Work_Lab/test_datasets/01_easy_ecommerce`. A repeated upload returned its
existing dataset. The selected Orders dataset produced a draft with 2,000
records, a saved order-total sum of 6,439,445.27, and a chart by order status.
The browser changed a widget title, refreshed the preview, approved the save,
and reopened the draft. The test also verified upload permissions and dataset
visibility. The test dashboard and imported tables were cleaned up.

The rollout's before and after snapshots matched for data and settings.
The examples database table inventory matched again after cleanup. During
the browser checks, the existing Superset worker issued five chart updates
independently of the CSV workflow.

All 34 main-demo smoke checks passed, along with 16 Copilot backend tests,
35 agent tests, 18 extension tests, and 175 SDK and Widget Jest tests.
GovAI timed out during verification. The one-click draft completed live
through Superset, and agent tests covered the normal model-assisted route.

## Copilot and Dashboard V2 lifecycle

Uploaded-data and snapshot drafts show an **Evidence used** card with the
source, saved measure, query scope, and up to five checked comparison groups.
The evidence describes the original draft. Edited chart previews remain
available for review before approval. Completed interactive replies keep their
own state while the chat is open. Copilot history stores the text transcript
and saved dashboard link. Publishing is a separate Dashboard V2 action after
saving the draft. Dashboard V2 history records the document that the successful
save replaced so a retry can attribute the right widget change. Floating
Copilot stays below the builder's modal dialogs.

Run the lifecycle against locally built backend and agent images. Install
Python `requests` and `playwright`, and run `python -m playwright install
chromium` before the first run. Use the repository's pinned Node version and
run from the repository root.

```bash
npm ci --prefix superset-frontend
npm ci --prefix superset-frontend/packages/superset-widgets/example
npm --prefix nxtbi/copilot/superset-extension/frontend run build
python nxtbi/copilot/superset-extension/package_bundle.py
docker build --target superset --build-arg BUILD_TRANSLATIONS=true -t nxtbi/superset-fork:copilot-lifecycle .
docker build --target agent -f nxtbi/copilot/Dockerfile -t nxtbi/copilot-agent:copilot-lifecycle .
python nxtbi/copilot/tests/lifecycle_fixture/run.py --superset-image nxtbi/superset-fork:copilot-lifecycle --agent-image nxtbi/copilot-agent:copilot-lifecycle
```

The runner starts fresh PostgreSQL, Superset, authenticated MCP, and a Widget
SDK example on loopback. The web process handles the open stream and its
signed agent callbacks concurrently. The test creates and publishes a dashboard
from synthetic data and tears down its own services afterward. Logs and screenshots
are written under `nxtbi/out/copilot-lifecycle/`. If Docker's default address
pools are full, pass an unused private IPv4 CIDR with `--subnet`. Use `--provider-env
nxtbi/copilot/.env --run-model-probe` to include the natural-language check
when the model endpoint is reachable. That check sends only a request about
the synthetic fixture.

The one-click CSV planner skips a raw date series that would exceed the
100-point widget limit. Monthly rollups require matching time-grain support
across preview, Dashboard V2, and the Widget SDK. The sample datasets reviewed
have 399–664 occupied dates and 23–36 occupied months.

The draft's evidence uses the A2UI catalog and data returned by authorized
queries. [A2UI 1.0 schema](https://a2ui.org/specification/v1.0/schemas/)
[Looker Conversational Analytics](https://docs.cloud.google.com/looker/docs/conversational-analytics-overview)

### November 26 lifecycle verification

The disposable Chromium run passed against Superset
`nxtbi/superset-fork:copilot-lifecycle-verified`
(`sha256:d0639c7a0ecee37e268551c7340bd242d079ce56a5d05444ada3af6d8dc34179`),
agent `nxtbi/copilot-agent:copilot-lifecycle`
(`sha256:ec463842ab7c0496c5da74f0c6975abc78bd1316fd76104d12d944bd203f7fa0`),
and packaged extension archive SHA-256
`fd59a5b0cb6947173babe98bdf93bfce0c16e4e43c8db5ffa53c1e07911123b7`.

The run applied fresh PostgreSQL migrations and used authenticated MCP.
Chromium imported the CSV, checked native A2UI values, changed a widget title
and refreshed the live preview, and approved the draft. Dashboard V2 persisted
an item edit through undo, redo, save, history, publish and reopen. The same
Widget SDK host rendered revenue 550 for the session user and 250 for both
North-scoped guest embeds. The Arabic Copilot shell rendered in RTL.

Focused checks passed 344 Copilot and dashboard frontend tests, 14 ChatHost
Jest tests, 38 agent tests, 27 Dashboard V2 command tests, and 18 extension
tests. Extension TypeScript and the compiled bundles passed. On Windows,
the mypy hook reports Linux-only signal attributes in the baseline. The
pinned mypy check targeting Linux passed for all nine changed Python paths.

A synthetic GovAI streaming request timed out before receiving HTTP. This
run verifies the one-click CSV workflow. Natural-language generation against
GovAI and live Keycloak SSO remain outside this run's verified coverage.

## Localized generated dashboards

Choose **Dashboard format** and **Dashboard language** in Copilot before
requesting a draft. Both **Classic (V1)** and **Dashboard (V2)** support English
and Arabic. Use **Preview language** to review the dashboard title and each
widget title in either language. Edit the captions if needed, refresh the
preview, then approve the dashboard once. The dataset, metrics, dimensions,
and filters are shared by both languages.

Open the saved dashboard and choose English or Arabic in Superset's language
menu. The same URL displays the translated dashboard and chart captions with
LTR or RTL layout. In Dashboard V2, select **Edit dashboard** to work with
canonical names and **Preview** to return to the translated viewer. After a
canonical caption changes, its old translation falls back to the new source
text. Translations apply to the dashboard's generated captions. Names and
values originating from data remain as stored.

Classic approval saves native charts and their dashboard in a single
transaction. It requires permission to create both charts and dashboards.
Dashboard V2 stores captions on the grid root by widget ID. The Classic viewer
loads language-specific dashboard titles using ETags with the same entity
version prefix, so switching the app language also refreshes the title.

The disposable Chromium run used `nxtbi/superset-fork:copilot-localization-verified`
and `nxtbi/copilot-agent:localization`. It approved both formats from one CSV,
retried the Classic approval, and opened the same saved ID in each locale. Both
formats showed the translated captions and the same revenue KPI of 550. V2
edit history, publishing and scoped widget embedding passed again. Focused
checks passed 38 agent tests, 51 backend tests, 18 SDK tests and 18 extension
checks. Linux-target mypy passed for all 17 changed Python files.

The browser run used the built-in CSV draft. The agent tests cover the
model-assisted proposal path. The first localization scope is dashboard and
widget captions. Classic copies that duplicate charts require new chart-caption
mappings, and standalone chart titles and embeds use their own title settings.

### Copilot translation suggestions

While reviewing a Classic or V2 draft, select **Suggest translations in
Arabic** or **Suggest translations in English**. Copilot proposes captions for
the other language. Compare current and suggested captions, then apply or
dismiss the suggestions. Applying opens the translated preview. Review and save
the dashboard as usual.

The request sends the source dashboard and widget captions to a tool-free
translation agent. The draft remains available while suggestions are pending.
You can cancel the request or edit the draft to discard stale suggestions.
When a model cannot provide a translation, the agent suggests captions covered
by its English and Arabic glossary. Unrecognized captions stay editable.

The disposable Docker lifecycle used the compiled Copilot extension and
`nxtbi/copilot-agent:localization-assist`. Chromium applied suggestions to both
dashboard formats, confirmed the same revenue value of 550, and verified the
accepted Arabic widget captions after save and reopen. All 20 SDK tests and 51
agent tests passed. The browser run used the glossary fallback. A test model
covered structured translations because the GovAI endpoint timed out during
the connectivity check.
