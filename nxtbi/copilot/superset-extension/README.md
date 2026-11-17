# NxtBI Copilot for Superset

The extension registers a native Superset chat panel with floating and docked modes. It uses the signed-in user's Superset session for Copilot requests and Widget SDK previews. The gateway revalidates access and the edited dashboard before saving it.

## Build and install

From the repository root, with the Superset frontend dependencies installed, run

```sh
npm --prefix nxtbi/copilot/superset-extension/frontend run build
python nxtbi/copilot/superset-extension/package_bundle.py
```

Install `nxtbi.ai-copilot-0.1.0.supx` under the configured `EXTENSIONS_PATH`, or add the absolute path of `nxtbi/copilot/superset-extension` to `LOCAL_EXTENSIONS`. Enable `ENABLE_EXTENSIONS` for the chat host and `DASHBOARD_V2` for proposals and Widget previews, then configure the Copilot gateway and restart Superset.

## Page context and previews

Copilot reads the current Superset page when the user submits a message. It sends the page type and applicable numeric IDs for dashboards, datasets, and charts. Raw URLs, SQL editor contents, and filter values stay in the browser.

Dashboard proposals render real Metric, Table, and Bar widgets. The user can change the dashboard title, widget type, metric, dimension, and the title of a metric tile or chart. Preview refresh applies those changes before approval. For A2UI integrations, the host catalog `urn:nxtbi:superset-widgets:1.0` also supports `SupersetWidgetPreview` with a single `widgetId` UUID for an existing saved widget. Superset authorizes the referenced widget and its data through the current session.

The host also accepts the A2UI user action `nxtbi.open-dashboard` with a positive numeric `dashboardId`. It resolves Dashboard V2 through the signed-in session and falls back to the same deployment's classic Dashboard route when appropriate. Both routes use Superset's usual access checks.

## Test

```sh
npm --prefix nxtbi/copilot/superset-extension/frontend test
npm --prefix nxtbi/copilot/superset-extension/frontend run typecheck
```
