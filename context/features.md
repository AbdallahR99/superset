# Implemented features

## Demo stack

- Superset built from this fork; sign-in only through Keycloak (OIDC); roles synced from groups at login.
- Tenant isolation by organisation with row-level security, also in SQL Lab.
- Three NxtBI dashboards on a seeded warehouse, plus the Superset examples.
- REST API with Swagger, MCP server (port 5008), embedded SDK with guest tokens, alerts and reports,
  thumbnails, NxtBI theme, English and Arabic.

## Arabic / RTL

- The whole interface runs right-to-left in Arabic: shell, lists, dashboards, filters, Explore,
  SQL Lab, modals, popups, tables. Charts keep left-to-right axes; table-like charts follow the interface.
- Arabic catalogue fully translated (1 fuzzy entry left, 0 untranslated).
- English output is unchanged.

## Dashboard V2 / widgets (flag `DASHBOARD_V2`)

- Builder: add, configure, move, resize, save, reload; containers (tabs, collapsible, carousel);
  conflict dialog on a stale save; embed dialogs.
- Dashboard editors can undo and redo edits in the open builder and inspect saved
  changes through History. Save the draft before using Publish. Published dashboards
  can be returned to draft using Unpublish.
- Widgets: ECharts chart, AG Grid table, metric tile, select filter, filter bar, markdown.
- Filter widgets, chart cross-filtering, host-controlled filters.
- Saved widgets (CRUD, paged list) and inline definitions; server-side data and filter values.
- Single widgets embedded in an external React app with a session or a guest token; several
  independent providers on one page; RTL in embeds.
- Extension widgets through Module Federation (`activate(core)` contract).
- Five read-only MCP tools: `list_widget_types`, `get_widget_control_schema`, `list_saved_widgets`,
  `get_saved_widget`, `get_widget_data`.

## Deliberately not included

The AI, agent, chat, CopilotKit and A2UI parts of PR 44471 were removed.
