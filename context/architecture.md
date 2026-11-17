# Architecture

## 1. NxtBI demo (`nxtbi/`)

- `docker-compose.yml`: project `nxtbi-superset`. Services: `db` (Postgres 17), `redis`, one-shot
  `superset-init`, `superset` (gunicorn), `superset-worker`, `superset-beat`, `superset-mcp`.
- `config/superset_config.py`: mounted as `superset_config`. Keycloak OIDC (`AUTH_OAUTH`), a custom
  security manager that maps Keycloak groups (`/orgs/<org>/<admin|editor|viewer>`) to Superset roles at
  every login, Redis caches, Celery, feature flags, theme, languages.
- `bootstrap/`: init script: migrations, warehouse seed, example dashboards, NxtBI dashboards, data
  grants, row-level security per organisation.
- `scripts/`: `gen_env.py`, `keycloak_setup.py`, `smoke_test.py`, `browser_check.py`, `rtl_audit.py`,
  `rtl_e2e.py`, `mcp_token.py`.
- Keycloak is external: container `ld-shared-keycloak-1`, realm `nxtbi`, client `nxtbi-superset`.

## 2. Arabic and RTL

Direction is a property of the locale, fixed per page load.

| Layer | Where |
|---|---|
| Server derives direction from Babel CLDR, renders `<html lang dir>`, puts `common.direction` in bootstrap; `RTL_LAYOUT_ENABLED` switch | `superset/translations/utils.py`, `superset/views/base.py`, `superset/embedded/view.py`, `superset/templates/superset/spa.html` |
| `SupersetThemeProvider({direction})`: one Emotion cache per direction; the RTL cache runs `@mui/stylis-plugin-rtl`; antd `ConfigProvider direction` | `superset-frontend/packages/superset-core/src/theme/Theme.tsx`, `direction.ts` |
| Opt-outs: `LtrIsolate` / `DirectionProvider` (subtree stays LTR via the `dir` attribute), `noFlip` (one rule) | `packages/superset-core/src/theme/LtrIsolate.tsx` |
| Popup placement mirrored inside the shared wrappers (Tooltip, Popover, Dropdown, Popconfirm, DatePicker, Drawer); callers pass LTR values | `packages/superset-ui-core/src/components/*` |
| Charts: `ChartMetadata.direction` (`'ltr'` for plots, `'inherit'` for tables, pivot, big number), decided in `SuperChartCore` | `packages/superset-ui-core/src/chart` |
| Icons: `mirrorInRtl` prop; RTL-only global rules keyed on `theme.direction === 'rtl'` | `GlobalStyles.tsx`, icon components |
| Arabic catalogue (5,951 entries) | `superset/translations/ar/LC_MESSAGES/messages.po` |

Code, SQL, identifiers and URLs stay LTR. User-authored text uses `dir="auto"`.
Test helper: `render(ui, { direction: 'rtl' })` in `spec/helpers/testing-library.tsx`.

## 3. Dashboard V2 and widgets

Everything is gated by `DASHBOARD_V2` (an app-level `before_request` gate that runs before CSRF and
answers 404; frontend routes and menu entries are flag-gated).

**Backend**

| Piece | Where |
|---|---|
| Document API `GET/POST/PUT /api/v1/dashboard_v2/` | `superset/dashboard_v2/` (`api.py`, `schemas.py`, `document.py` validation, `node_types.py`, `storage.py` compare-and-swap, `access.py` read rule, `feature.py` gate), `superset/commands/dashboard_v2/` |
| Widget registry, control schemas, data and filter values, saved widgets | `superset/widgets/` (`api.py`, `builtin.py`, `controls.py`, `data.py`, `safety.py`), `superset/commands/widget/`, `superset/daos/saved_widget.py`, migration `3c9e1a7b5d2f_add_saved_widgets` |
| Guest tokens: `widget` and `dataset` resource types | `superset/security/guest_token.py`, `api.py`, `manager.py` |
| MCP read-only widget tools | `superset/mcp_service/widgets/` |

The V2 document is stored in `dashboards.json_metadata` under `v2_document`, with its `revision`
inside. Classic metadata updates preserve the document observed in the current
row, including the first revision written by a concurrent import. This uses
the existing dashboards table and compare-and-swap.

**Frontend**

| Piece | Where |
|---|---|
| Embeddable package `@apache-superset/widgets` (`SupersetProvider`, `Widget`, built-in widgets, sanitizers, extension host) and its standalone example app | `superset-frontend/packages/superset-widgets/` (`example/`) |
| Shared contracts `@apache-superset/core/widgets`, `/dashboard` | `packages/superset-core/src/widgets`, `src/dashboard` |
| Document store and save session (revision, conflict, reconcile) | `superset-frontend/src/core/dashboard/` (`DashboardProvider.ts`, `documentTree.ts`, `session.ts`, `persistence.ts`) |
| Builder page (gridstack canvas, palette, inspector, JSON-schema control forms) | `superset-frontend/src/pages/DashboardBuilderV2/` |
| Playwright specs | `superset-frontend/playwright/tests/dashboard-v2/` |

Isolated runtime: `nxtbi/widgets/` (compose project `nxtbi-widgets`, own config, bootstrap, scripts).
API contract: `nxtbi/docs/widgets/05-dashboard-v2-api-contract.md`.
