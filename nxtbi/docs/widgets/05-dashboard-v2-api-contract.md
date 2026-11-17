# 05 - Dashboard V2 document API: HTTP contract

Backend source: `superset/dashboard_v2/{api,document,schemas,feature}.py`, `superset/commands/dashboard_v2/{get,save,exceptions}.py`. Tests: `tests/unit_tests/dashboard_v2/`.

## 1. Feature flag

Everything below exists only while the feature flag `DASHBOARD_V2` is on (default `False`). While it is off, every route of these four views answers **404** before authentication, for signed-in and anonymous callers alike:

| View | Routes |
|---|---|
| `DashboardV2RestApi` | `/api/v1/dashboard_v2/*` |
| `WidgetControlsRestApi` | `/api/v1/widgets/*` |
| `SavedWidgetRestApi` | `/api/v1/widget/*` |
| `DashboardBuilderV2View` | `/dashboard/v2/new/`, `/dashboard/v2/<pk>/` |

The gate is `register_dashboard_v2_gate` (`superset/dashboard_v2/feature.py`), installed in `superset/initialization/__init__.py`. The flag is resolved per request.

## 2. Resource

```jsonc
// "result" of every successful response
{
  "id": 12,
  "uuid": "6f0c...",
  "dashboard_title": "Sales",
  "changed_on": "2026-01-01T10:00:00",
  "revision": 3,                       // integer, see section 4
  "document": {
    "version": 1,
    "nodes": {
      "root":   { "type": "grid", "layout": { "columns": 24 }, "children": ["node_1"] },
      "node_1": { "type": "markdown", "props": { "content": "# hi" } }
    }
  },
  "embedded": { "uuid": "...", "allowed_domains": ["https://host.example"] }  // or null
}
```

- `revision` travels **beside** `document`, never inside it. A `revision` key sent inside `document` is ignored.
- `embedded.allowed_domains` is omitted for embedded guests.
- Every successful response also carries the revision as a header: `ETag: "3"`. The body field is the one to rely on; reading the header cross-origin needs `ETag` in the CORS `expose_headers`.

## 3. Endpoints

All routes need a session or JWT (`@protect()`), plus the permission in the table. CSRF applies to POST and PUT.

| Method and path | Permission | Object-level check | Success |
|---|---|---|---|
| `POST /api/v1/dashboard_v2/` | `can write on Dashboard` | caller becomes editor | `201 {id, result}` at revision 1 |
| `PUT /api/v1/dashboard_v2/<int:pk>` | `can write on Dashboard` | `raise_for_editorship` | `200 {id, result}` at base revision + 1 |
| `GET /api/v1/dashboard_v2/<ref>` | `can read on Dashboard` | `Dashboard.raise_for_access` | `200 {result}` |
| `GET /api/v1/dashboard_v2/embedded/<uuid>` | `can read on Dashboard` | `Dashboard.raise_for_access` (guest token must name the dashboard) | `200 {result}` |

`<ref>` is an embedded uuid, a dashboard uuid, a slug or an integer id. The `embedded/<uuid>` route resolves an embedded uuid and nothing else.

There is no V2 delete route: a V2 dashboard is deleted through `DELETE /api/v1/dashboard/<pk>` with its existing checks.

### POST body

```json
{ "dashboard_title": "Sales", "document": { "version": 1, "nodes": { } } }
```

`dashboard_title`: required, 1-500 characters. `document`: required. Unknown top-level fields are a 400.

### PUT body

```json
{ "document": { "version": 1, "nodes": { } }, "dashboard_title": "Sales", "base_revision": 3 }
```

`document` is required and replaces the stored document as a whole. `dashboard_title` is optional. The base revision is required, see section 4.

## 4. Revision semantics (optimistic concurrency)

- Create stores revision **1**. Each successful PUT stores `base revision + 1`. A document stored before revisions existed reads as revision **0**.
- A PUT must name the revision it was based on, in either form:
  - header `If-Match: "3"` (`W/"3"` and a bare `3` are accepted), or
  - body field `"base_revision": 3` (a JSON integer, not a string).
  If both are sent they must agree.
- If the stored revision differs from the base, nothing is written and the answer is **409**:

  ```json
  { "message": "The dashboard was changed by someone else. Reload it before saving again.", "current_revision": 4 }
  ```

  with `ETag: "4"`. The client has to reload (`GET`), merge or discard its changes, and save again on the new revision. A base revision ahead of the stored one is also a 409.
- The check is made again while the dashboard row is locked (`SELECT ... FOR UPDATE`), so of two saves racing from the same base exactly one is stored.
- Client rule: keep the `revision` of the last successful GET, POST or PUT for the dashboard on screen and send it with the next PUT. Never reuse a revision across dashboards, and do not save before the load of that dashboard has finished.

## 5. Status codes

| Status | When | Body |
|---|---|---|
| 200 / 201 | success | `{id?, result}` + `ETag` |
| 400 | body is not strict JSON (malformed, not an object, duplicate object keys such as two nodes with one id, `NaN`/`Infinity`, nesting deeper than the value-depth limit + 8); schema error (missing `document`/`dashboard_title`, unknown field, non-integer `base_revision`); malformed `If-Match` (`*`, lists, non-numeric); `If-Match` and `base_revision` disagree | `{message}` |
| 401 | not authenticated | |
| 403 | no route permission; no access to the dashboard (GET); not an editor (PUT). Editorship is checked before the revision. | `{message}` |
| 404 | flag off; no such dashboard; the dashboard is not visible to the caller (PUT); the dashboard has no V2 document | `{message}` |
| 409 | stale or unknown base revision | `{message, current_revision}` + `ETag` |
| 413 | request body larger than `DASHBOARD_V2_MAX_DOCUMENT_BYTES` | `{message}` |
| 422 | the document is invalid (section 6) | `{message}`; for widget props also `{errors: {<node id>: [{loc, message}]}}` |
| 428 | PUT without `If-Match` and without `base_revision` | `{message}` |

## 6. Document validation (422)

Applied on every POST and PUT, server-side, with an iterative walk (no recursion):

- `document.nodes` is an object; `document.version`, when present, is `1`.
- A `root` node exists and has a `children` array.
- Node ids match `^[A-Za-z0-9_-]{1,64}$`.
- Each node is an object with a non-empty string `type` (at most 128 characters). `layout`, `props` and `style`, when present, are objects. Other node keys are dropped.
- `children`, when present, is an array of distinct ids of existing nodes.
- The nodes form one tree rooted at `root`: no cycle or self-reference, no node under two parents, no node unreachable from `root`.
- Node types: `grid` (must have `children`) or a type registered in the widget registry (`GET /api/v1/widgets/types`). Anything else is rejected, containers included.
- Props of every non-`grid` node pass that widget type's `validate_control_values`.
- `layout`/`props`/`style` hold plain JSON only: string keys, finite numbers.
- Limits, each a config key with a default:

| Config key | Default | Meaning |
|---|---|---|
| `DASHBOARD_V2_MAX_NODES` | 500 | nodes per document, root included |
| `DASHBOARD_V2_MAX_DEPTH` | 16 | distance of the deepest node from the root |
| `DASHBOARD_V2_MAX_DOCUMENT_BYTES` | 1048576 | request body (413) and stored document (422) |
| `DASHBOARD_V2_MAX_VALUE_DEPTH` | 32 | nesting inside one `layout`/`props`/`style` value |

A `v2_document` that arrives inside `json_metadata` through the classic dashboard API or an import gets the structural part of this validation (tree shape, ids, limits, JSON values), not the widget-type, props or revision checks.

## 7. Frontend checklist

1. `fetchDashboardV2` returns `result.revision`; store it with the loaded dashboard id.
2. `saveDashboardV2` on update sends `base_revision` (or `If-Match`) and replaces the stored revision with `result.revision` from the response. On create, take `result.revision` (1) from the 201.
3. On 409: do not retry blindly. Tell the user, reload, and keep `current_revision` only as information.
4. On 422 show `message`; if `errors` is present, map each key to its node.
5. Hide the menu entry and the routes when the `DashboardV2` flag is off; the backend returns 404 regardless.
