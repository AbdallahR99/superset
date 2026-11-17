# 05 - Dashboard V2 document API: HTTP contract

Backend source: `superset/dashboard_v2/{api,document,node_types,storage,access,schemas,feature}.py`, `superset/commands/dashboard_v2/{get,save,exceptions}.py`. Tests: `tests/unit_tests/dashboard_v2/`.

## 1. Feature flag

Everything below exists only while the feature flag `DASHBOARD_V2` is on (default `False`). While it is off, every route of these four views answers **404** before CSRF protection and before authentication, for signed-in and anonymous callers alike. An anonymous `POST`/`PUT`/`DELETE` without a CSRF token is therefore a 404 as well, not the 400 of the CSRF check:

| View | Routes |
|---|---|
| `DashboardV2RestApi` | `/api/v1/dashboard_v2/*` |
| `WidgetControlsRestApi` | `/api/v1/widgets/*` |
| `SavedWidgetRestApi` | `/api/v1/widget/*` |
| `DashboardBuilderV2View` | `/dashboard/v2/new/`, `/dashboard/v2/<pk>/` |

The gate is `register_dashboard_v2_gate` (`superset/dashboard_v2/feature.py`), installed in `superset/initialization/__init__.py`. The flag is resolved per request.

The gate is the first of the app's `before_request` hooks: it is inserted ahead of the ones registered earlier (CSRF protection, session validation, Flask-AppBuilder's `g.user`). Because it runs before Flask-AppBuilder's hook, it assigns `g.user` the same lazy `current_user` proxy itself when it is not set yet, so a flag function that looks at the caller (`GET_FEATURE_FLAGS_FUNC` / `IS_FEATURE_ENABLED_FUNC`) keeps working. Routes outside the four views are not affected.

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
| `POST /api/v1/dashboard_v2/` | `can write on Dashboard` | caller becomes editor | `201 {id, result}` at revision 1; `200 {id, result}` for a repeated `uuid` (section 3.1) |
| `PUT /api/v1/dashboard_v2/<int:pk>` | `can write on Dashboard` | `raise_for_editorship` | `200 {id, result}` at base revision + 1 |
| `GET /api/v1/dashboard_v2/<ref>` | `can read on Dashboard` | `Dashboard.raise_for_access` + the document read rule (section 3.2) | `200 {result}` |
| `GET /api/v1/dashboard_v2/embedded/<uuid>` | `can read on Dashboard` | `Dashboard.raise_for_access` (guest token must name the dashboard) | `200 {result}` |

`<ref>` is an embedded uuid, a dashboard uuid, a slug or an integer id. The `embedded/<uuid>` route resolves an embedded uuid and nothing else.

There is no V2 delete route: a V2 dashboard is deleted through `DELETE /api/v1/dashboard/<pk>` with its existing checks.

### POST body

```json
{ "dashboard_title": "Sales", "document": { "version": 1, "nodes": { } } }
```

`dashboard_title`: required, 1-500 characters. `document`: required. `uuid`: optional, see 3.1. Unknown top-level fields are a 400.

### 3.1 Idempotent create (`uuid`)

```json
{ "dashboard_title": "Sales", "document": { "version": 1, "nodes": { } }, "uuid": "6f0c2a3e-5b1d-4c8e-9f70-1a2b3c4d5e6f" }
```

- `uuid` is a client-generated UUID that becomes the dashboard's uuid. Generate one per unsaved document and send the same value on every retry of that create.
- First request: `201`, as without a uuid.
- A repeat by **the same caller** whose dashboard already exists under that uuid: nothing is written; the answer is `200 {id, result}` with the dashboard **as stored** (its current revision and document, which may be newer than the body that was re-sent). Adopt `id` and `revision` from it exactly as from a 201.
- The uuid belongs to a dashboard the caller did not create, to one that is not a V2 dashboard, or to one in the trash (soft-deleted, the caller's own included): `422 {message}`. Generate a new uuid.
- Two creates racing on one uuid: one answers 201, the other 200.

### 3.2 Who may read the document

`GET` first applies `Dashboard.raise_for_access` and then a rule on the document itself, because a V2 dashboard has no charts for the classic "published and at least one accessible dataset" fallback to look at:

| Caller | Result |
|---|---|
| Admin, an editor of the dashboard, a viewer of the (published) dashboard | allowed |
| Embedded guest whose token names the dashboard | allowed |
| Anyone else; the document binds datasets (`props.dataBinding.datasetId` or `props.datasetId` on any node) | allowed only with access to **every** bound dataset; a bound dataset that no longer exists counts as inaccessible |
| Anyone else; the document binds no dataset | **403** (editors and viewers only) |

A refused read is `403 {message}`, the same as any other access failure.

The classic `GET /api/v1/dashboard/<id>` does not return the `v2_document` key inside `json_metadata`; the document is served by this API only. The other places a document can leave the server:

| Path | Rule |
|---|---|
| Dashboard export (`GET /api/v1/dashboard/export/`, asset export) | the rule of the table above, applied per dashboard; a caller who fails it gets the dashboard without `metadata.v2_document` (section 6.1) |
| Version history (`/api/v1/dashboard/<uuid>/versions/...`, flag `VERSION_HISTORY`) | editors only (`is_editor`, `superset/versioning/api_helpers.py`), who may read the document anyway; `json_metadata` is a versioned column and is diffed leaf by leaf, `v2_document` included |
| MCP dashboard tools (`get_dashboard_info`, `list_dashboards`) | the serializers never return `json_metadata`; only its size and the extracted native filters |
| Copy | editors only; the copy carries the document |

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
- The write is a compare-and-swap: `UPDATE dashboards SET json_metadata = :new WHERE id = :id AND json_metadata = :value_read`, and the save succeeds only when that statement matched one row. Of two saves racing from the same base exactly one is stored, on SQLite, PostgreSQL and MySQL alike; a row lock is taken where the database has one, but correctness does not depend on it.
- The `revision` (and the whole `result`) of a `200`/`201` is produced inside the transaction that stored it; for a PUT it is always `base revision + 1`, never a later writer's revision. A client may treat `result.revision !== base + 1` as a bug.
- A save the database aborts because of a concurrent transaction (serialization failure, deadlock, lock timeout, `database is locked`) is answered **409** as well. `current_revision` is then the stored revision if it could be read, and is otherwise absent together with the `ETag` header. Handle it like any other 409.
- Changing the title through this PUT bumps the revision like any other save. Changes made through the classic dashboard API (properties modal: title, slug, owners, colours, ...) never change the revision or the document.
- Client rule: keep the `revision` of the last successful GET, POST or PUT for the dashboard on screen and send it with the next PUT. Never reuse a revision across dashboards, and do not save before the load of that dashboard has finished.

## 5. Status codes

| Status | When | Body |
|---|---|---|
| 200 / 201 | success | `{id?, result}` + `ETag` |
| 400 | body is not strict JSON (malformed, not an object, duplicate object keys such as two nodes with one id, `NaN`/`Infinity`, nesting deeper than the value-depth limit + 8); schema error (missing `document`/`dashboard_title`, unknown field, non-integer `base_revision`); malformed `If-Match` (`*`, lists, non-numeric); `If-Match` and `base_revision` disagree | `{message}` |
| 401 | not authenticated | |
| 403 | no route permission; no access to the dashboard (GET); not an editor (PUT). Editorship is checked before the revision. | `{message}` |
| 404 | flag off; no such dashboard; the dashboard is not visible to the caller (PUT); the dashboard has no V2 document | `{message}` |
| 409 | stale or unknown base revision; the save lost a database-level race (section 4) | `{message, current_revision?}` + `ETag` when `current_revision` is present |
| 413 | request body larger than `DASHBOARD_V2_MAX_DOCUMENT_BYTES` | `{message}` |
| 422 | the document is invalid (section 6); the `uuid` of a create is taken (section 3.1) | `{message}`; for widget props also `{errors: {<node id>: [{loc, message}]}}` |
| 428 | PUT without `If-Match` and without `base_revision` | `{message}` |

## 6. Document validation (422)

Applied on every POST and PUT, server-side, with an iterative walk (no recursion):

- `document.nodes` is an object; `document.version`, when present, is `1`.
- A `root` node exists and has a `children` array.
- Node ids match `^[A-Za-z0-9_-]{1,64}$`.
- Each node is an object with a non-empty string `type` (at most 128 characters). `layout`, `props` and `style`, when present, are objects. Other node keys are dropped.
- `children`, when present, is an array of distinct ids of existing nodes.
- The nodes form one tree rooted at `root`: no cycle or self-reference, no node under two parents, no node unreachable from `root`.
- Node types. Every type the builder palette can produce is accepted; anything else is `422 "unknown type"`:

  | Type | Accepted because | `children` | Props checked |
  |---|---|---|---|
  | `grid` | root / grid container | required | plain JSON |
  | `markdown`, `echarts`, `metric-tile`, `ag-grid-table`, `filter.select`, `filter.bar`, and any other type in `GET /api/v1/widgets/types` (includes extension widgets with a backend `@widget`, named `extensions.<publisher>.<name>.<type>`) | widget registry | optional | that widget's control model, present props only (below) |
  | `tabs`, `tab`, `collapsible`, `carousel`, `slide` | built-in structural containers (`superset/dashboard_v2/node_types.py`) | required (may be empty) | `tab`/`slide`: `label` string up to 250 characters; `collapsible`: `collapsed` boolean, `expandedRowSpan` number >= 1; other props are kept |
  | `extensions.<publisher>.<name>.<type>` without a backend `@widget` | the `ENABLE_EXTENSIONS` flag is on and the extension `<publisher>.<name>` is installed and not refused by `EXTENSION_DENYLIST` / `EXTENSION_VERSION_POLICY` | optional | plain JSON only, within the limits below |

  A frontend-only extension widget must therefore register its view under the id `extensions.<publisher>.<name>.<type>`; any other id is unknown to the server.
- Props of a registry widget are validated **only where present**. A required prop that is simply missing (a freshly placed chart without `dataBinding`, a `dataBinding` without `datasetId`, an empty markdown block, `props` absent or `{}`) is not an error, so an unconfigured widget can be saved. A prop that is present with a wrong type or a value the control model refuses is a 422 with per-node `errors`. Props the control model does not know (`collapsed`, `expandedRowSpan`, `title`, ...) are kept as they are.
- `layout`/`props`/`style` hold plain JSON only: string keys, finite numbers.
- Limits, each a config key with a default:

| Config key | Default | Meaning |
|---|---|---|
| `DASHBOARD_V2_MAX_NODES` | 500 | nodes per document, root included |
| `DASHBOARD_V2_MAX_DEPTH` | 16 | distance of the deepest node from the root |
| `DASHBOARD_V2_MAX_DOCUMENT_BYTES` | 1048576 | request body (413) and stored document (422) |
| `DASHBOARD_V2_MAX_VALUE_DEPTH` | 32 | nesting inside one `layout`/`props`/`style` value |

The four limits are declared in `superset/config.py`. The builder reads the two it enforces itself from the bootstrap payload instead of hardcoding them:

| Bootstrap key | Config key |
|---|---|
| `bootstrap_data.common.conf.DASHBOARD_V2_MAX_NODES` | `DASHBOARD_V2_MAX_NODES` |
| `bootstrap_data.common.conf.DASHBOARD_V2_MAX_DEPTH` | `DASHBOARD_V2_MAX_DEPTH` |

Fall back to 500 / 16 when a key is absent.

### 6.1 Other write paths

The Dashboard V2 API is the only writer of the document during normal use.

| Path | What happens to `v2_document` |
|---|---|
| Classic `PUT /api/v1/dashboard/<id>` and `POST /api/v1/dashboard/` (properties modal, `json_metadata`) | An incoming `v2_document` key is **ignored**. The stored document and its revision are carried forward unchanged, re-read from the database at write time. No error is raised, so the modal can keep sending back the `json_metadata` it loaded. |
| `PUT /api/v1/dashboard/<id>/filters`, `/chart_customizations`, `/colors` | Same compare-and-swap as the classic update (`DashboardDAO.metadata_keeping_v2_document`): the writer changes its own key and the document is taken from the row at write time, so a V2 save made after the writer loaded the dashboard is kept. A writer that keeps losing the swap fails instead of overwriting. |
| MCP `update_dashboard`, `generate_dashboard` (`json_metadata_overrides`) | A `v2_document` key in the overrides is refused by the request schema. `update_dashboard` and `remove_chart_from_dashboard` store through the same compare-and-swap. |
| Copy / "Save as" (`POST /api/v1/dashboard/<id>/copy/`) | The **source's stored** document is copied to the new dashboard at revision 1; a `v2_document` in the request's `json_metadata` is ignored. |
| Export | `metadata.v2_document` is part of the exported dashboard YAML only for a caller who may read the document (section 3.2); for anyone else the key is left out and the rest of the dashboard is exported as usual. The CLI export runs as an admin and always includes it. |
| Restore from the trash (`POST /api/v1/dashboard/<uuid>/restore`) | Rewrites `json_metadata` only to drop filters with missing semantic views; the document is carried through unchanged. The row is invisible to every other writer until the restore commits. |
| Version restore (dashboard `restore_version` route, flag `VERSION_HISTORY`) | Editors only. Reverts `json_metadata` as a whole, so the document **and its revision** go back to the snapshot's; this path does not validate the document again or move the revision forward. |
| Import | `metadata.v2_document` goes through the full validation of this section (types, props, limits). An invalid document fails the import. A `revision` inside the file is ignored: a new dashboard gets revision 1, an overwritten V2 dashboard gets its stored revision + 1 (open builders then get a 409 on their next save). |

## 7. Frontend checklist

1. `fetchDashboardV2` returns `result.revision`; store it with the loaded dashboard id.
2. `saveDashboardV2` on update sends `base_revision` (or `If-Match`) and replaces the stored revision with `result.revision` from the response. On create, take `result.revision` (1) from the 201.
3. On 409: do not retry blindly. Tell the user, reload, and keep `current_revision` only as information.
4. On 422 show `message`; if `errors` is present, map each key to its node.
5. Hide the menu entry and the routes when the `DashboardV2` flag is off; the backend returns 404 regardless.
6. Send a `uuid` with every create of one unsaved document and treat `200` like `201` (section 3.1).
7. A 409 may come without `current_revision` (section 4); do not require the field.
8. Read the node and depth limits from `bootstrap_data.common.conf` (section 6).
9. Do not send or expect `v2_document` through the classic dashboard API (section 6.1).
