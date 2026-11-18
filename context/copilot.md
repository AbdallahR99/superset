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
limited to authorized metadata. Live widget data is fetched through Superset
to the browser.

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

## Main demo update

The demo on port 8088 runs `nxtbi/superset-fork:copilot-demo-polish-20261118`
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
