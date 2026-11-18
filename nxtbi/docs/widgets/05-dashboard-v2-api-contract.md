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
  "published": false,
  "can_edit": true,                    // object-level editorship for the caller
  "can_publish": true,                 // editorship and Dashboard write permission
  "changed_on": "2026-01-01T10:00:00+00:00", // UTC with an explicit offset
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
- `changed_on` is the time of the last write in ISO 8601, converted to UTC and sent **with an explicit offset**. The builder still reads a value without a designator as UTC, for answers from a server that predates the offset.
- The builder changes publication via `PUT /api/v1/dashboard/<pk>` with
  `{ "published": true }` or `{ "published": false }`. This uses the existing
  dashboard authorization and leaves the V2 document and revision intact.
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
- A repeat by **the same caller** whose dashboard already exists under that uuid: nothing is written; the answer is `200 {id, result}` with the dashboard **as stored** (its current revision and document, which may be newer than the body that was re-sent). Adopt `id`. Adopt `revision` and continue with an update only when the stored dashboard is still the one this client created (revision 1, or a document this client sent under that uuid); otherwise treat the answer as a conflict and let the author choose between reloading and overwriting, because another session has saved since.
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
- The revision of one dashboard only ever moves forward, and a number is never used for two different documents. The writers other than this API that replace the document (version restore, import with overwrite) store it at `stored revision + 1`, read from the row at the time of their write and written with the same compare-and-swap; none of them removes a document, so the numbering cannot start over (section 6.1). A builder holding a revision from before such a write gets a 409 on its next save.
- A PUT must name the revision it was based on, in either form:
  - header `If-Match: "3"` (`W/"3"` and a bare `3` are accepted), or
  - body field `"base_revision": 3` (a JSON integer, not a string).
  If both are sent they must agree.
- If the stored revision differs from the base, nothing is written and the answer is **409**:

  ```json
  { "message": "The dashboard was changed by someone else. Reload it before saving again.", "current_revision": 4 }
  ```

  with `ETag: "4"`. The client has to reload (`GET`), merge or discard its changes, and save again on the new revision. A base revision ahead of the stored one is also a 409.
- The write is a compare-and-swap: `UPDATE dashboards SET json_metadata = :new WHERE id = :id AND json_metadata = :value_read`, and the save succeeds only when that statement matched one row. Of two saves racing from the same base exactly one is stored; a row lock is taken where the database has one, but correctness rests on the comparison being exact, not on the lock.
  - SQLite and PostgreSQL compare text byte by byte, so the statement is exact as written.
  - MySQL and MariaDB compare text by the column's collation, which by default ignores case, accents and trailing spaces. There the condition is `CAST(CONVERT(json_metadata USING utf8mb4) AS BINARY) = CAST(CONVERT(:value_read USING utf8mb4) AS BINARY)` (`superset/dashboard_v2/storage.py`, `_unchanged_condition`), a byte comparison independent of the column's and the connection's character set.
  - SQLite unit tests cover the swap, retries and metadata writers in section 6.1. The [concurrent save harness](../../widgets/README.md#concurrent-dashboard-v2-saves-on-postgresql) exercises two V2 saves and a classic metadata edit on separate PostgreSQL connections. MySQL and MariaDB coverage checks the generated SQL.
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
| 403 | no route permission; no access to the dashboard (GET); not an editor (PUT). Editorship is checked before the revision, the revision before the document, the document before the authoring rule. | `{message}` |
| 404 | flag off; no such dashboard; the dashboard is not visible to the caller (PUT); the dashboard has no V2 document | `{message}` |
| 409 | stale or unknown base revision; the save lost a database-level race (section 4) | `{message, current_revision?}` + `ETag` when `current_revision` is present |
| 413 | request body larger than `DASHBOARD_V2_MAX_DOCUMENT_BYTES` | `{message}` |
| 422 | the document is invalid (section 6); the caller may not author a data definition the document adds (section 6.2); the `uuid` of a create is taken (section 3.1) | `{message}`; for widget props and refused data definitions also `{errors: {<node id>: [{loc, message}]}}` |
| 428 | PUT without `If-Match` and without `base_revision` | `{message}` |

## 6. Document validation (422)

Applied on every POST and PUT, server-side, with an iterative walk (no recursion):

- `document.nodes` is an object; `document.version`, when present, is `1`.
- A `root` node exists and has a `children` array.
- Node ids match `^[A-Za-z0-9_-]{1,64}$` and are none of the reserved names `__proto__`, `constructor`, `prototype`, `hasOwnProperty`, `isPrototypeOf`, `propertyIsEnumerable`, `toLocaleString`, `toString`, `valueOf`, `__defineGetter__`, `__defineSetter__`, `__lookupGetter__`, `__lookupSetter__` (the member names of JavaScript's `Object.prototype`, under which a client keeping nodes in a plain object would lose the node). `root` and the ids the builder generates (`node_<n>`, `node_<n>_<suffix>`) are unaffected.
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
- Props of a registry widget are validated **only where present**. A required prop that is simply missing (a freshly placed chart without `dataBinding`, a `dataBinding` without `datasetId`, an empty markdown block, `props` absent or `{}`) is not an error, so an unconfigured widget can be saved. A prop that is present with a wrong type or a value the control model refuses is a 422 with per-node `errors`. Props the control model does not know (`collapsed`, `expandedRowSpan`, `title`, ...) are kept as they are, with one exception: a built-in widget names its dataset in one place only, the one its type reads. A `dataBinding` on `filter.select`, a top-level `datasetId` on `echarts` / `metric-tile` / `ag-grid-table`, and either of them on `markdown` / `filter.bar` is a 422 (`"... is not a setting of this widget: its dataset is named in one place only."`); `null` is accepted.
- Free-form JSON of a widget is checked by the control model as well (`03-backend-security.md` section 5.6). Two rules a client is likely to meet: in `echartsOptions`, `link` / `sublink` must be an http(s), mailto or relative link, except `axisPointer.link`, which is a list of axis references; in `columnDefs`, `type` accepts `numericColumn` / `rightAligned` and `cellDataType` accepts `text` / `number` / `boolean` / `date` / `dateString` / `object`, and any other name is a 422.
- `layout`/`props`/`style` hold plain JSON only: string keys, finite numbers.
- Limits, each a config key with a default:

| Config key | Default | Meaning |
|---|---|---|
| `DASHBOARD_V2_MAX_NODES` | 500 | nodes per document, root included |
| `DASHBOARD_V2_MAX_DEPTH` | 16 | distance of the deepest node from the root |
| `DASHBOARD_V2_MAX_DOCUMENT_BYTES` | 1048576 | request body (413) and document (422), both in UTF-8 bytes: the document is measured as its compact JSON serialisation with non-ASCII text unescaped, so a character costs the same in both checks. (The column itself holds the ASCII-escaped form, which can be larger; the limit is not applied to that.) |
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
| Classic `PUT /api/v1/dashboard/<id>` (properties modal, `json_metadata`) | An incoming `v2_document` key is **ignored**. The writer re-reads the row and carries forward the stored document and its revision, including a document an overwrite import added after the writer loaded the dashboard. |
| Classic `POST /api/v1/dashboard/` | An incoming `v2_document` key is **dropped** before anything is stored, by `DashboardPostSchema` and again by `CreateDashboardCommand` for callers that build the properties themselves. The classic create never produces a V2 dashboard. No error is raised. |
| `PUT /api/v1/dashboard/<id>/filters`, `/chart_customizations`, `/colors` | Same compare-and-swap as the classic update (`DashboardDAO.metadata_keeping_v2_document`): the writer changes its own key and the document is taken from the row at write time, so a V2 save made after the writer loaded the dashboard is kept. A writer that keeps losing the swap fails instead of overwriting. |
| MCP `update_dashboard`, `generate_dashboard` (`json_metadata_overrides`) | A `v2_document` key in the overrides is refused by the request schema. `update_dashboard` and `remove_chart_from_dashboard` store through the same compare-and-swap. |
| Copy / "Save as" (`POST /api/v1/dashboard/<id>/copy/`) | The **source's stored** document is copied to the new dashboard at revision 1; a `v2_document` in the request's `json_metadata` is ignored. The metadata the copy is seeded with never holds the document: it is added once, and only for a caller who passes the read rule of section 3.2 (copying needs editorship, which passes it). |
| Export | `metadata.v2_document` is part of the exported dashboard YAML only for a caller who may read the document (section 3.2); for anyone else the key is left out and the rest of the dashboard is exported as usual. The CLI export runs as an admin and always includes it. |
| Restore from the trash (`POST /api/v1/dashboard/<uuid>/restore`) | Rewrites `json_metadata` only to drop filters with missing semantic views; the document is carried through unchanged. The row is invisible to every other writer until the restore commits. |
| Version restore (dashboard `restore_version` route, flag `VERSION_HISTORY`) | Editors only. The other metadata keys go back to the snapshot's. The snapshot's document is stored like a save of it: validated by the rules in force at the time of the restore (section 6), checked against the authoring rule relative to the stored document (section 6.2), and stamped with the **stored revision + 1**, whatever revision the snapshot held, so every open builder gets a 409 on its next save. A snapshot without a document leaves the stored document and revision as they are. A snapshot whose document no longer validates (a widget type uninstalled since, lowered limits, a tightened safety rule) or brings back a data definition the restoring user may not author is **refused as a whole** with `422 {message}` naming the reason, and the dashboard is left unchanged; restore a different version or fix the dashboard in the builder. |
| Import | `metadata.v2_document` goes through the full validation of this section (types, props, limits) and, when the import runs as a user, the authoring rule of section 6.2 (an import without a user, such as the CLI or example loading, is trusted). An invalid or refused document fails the import. A `revision` inside the file is ignored: a new dashboard gets revision 1, an overwritten V2 dashboard gets the revision **stored at the time of the write** + 1, written by compare-and-swap (open builders then get a 409 on their next save). A file **without** `metadata.v2_document` (or with `null`) that overwrites a V2 dashboard leaves the stored document and its revision untouched: an import never removes a document, so the dashboard stays a V2 dashboard and its revision numbers never start over. To replace the document, import one. |
| Legacy import (pre-1.0 JSON format, `superset/commands/dashboard/importers/v0.py`) | The format predates the document: a `v2_document` in the file is dropped, and an overwritten V2 dashboard keeps its stored document and revision (compare-and-swap, as for the classic update). |

### 6.2 Authoring rule for data definitions

A document save is also a save of every widget definition in it, so POST, PUT, import and version restore apply the saved-widget authoring rule (`raise_for_widget_authoring`, `superset/commands/widget/utils.py`; see `03-backend-security.md` section 5) to the data definitions the write **adds**:

- A node is checked when it binds a dataset, as its widget type reads it (`widget_dataset_id`: `props.dataBinding.datasetId`, or `props.datasetId` for `filter.select`), and its definition is not already in the stored document. A definition is the node's `type` together with its `dataBinding`, `datasetId` and `column` props.
- A checked node needs: the dataset exists, the caller can read it, and, when the definition carries SQL, the caller may author SQL against that dataset.
- A definition the stored document already holds is **not** checked again, whichever node carries it. An editor without access to a dataset can therefore keep, move, resize, restyle, retitle and duplicate the widgets bound to it and edit everything around them; what they cannot do is point a widget at that dataset, or change its metrics, dimensions, filters or SQL.
- A create has no stored document, so every binding in it is checked.

A refusal is `422` with the nodes named, in the shape of a widget props error:

```json
{ "message": "You are not allowed to store some of the widget definitions.",
  "errors": { "node_4": [ { "loc": ["dataBinding"], "message": "You don't have access to the dataset this widget reads." } ] } }
```

`loc` is `["dataBinding"]`, or `["datasetId"]` for a node without a `dataBinding` prop. Nothing is written.

## 7. Frontend checklist

1. `fetchDashboardV2` returns `result.revision`; store it with the loaded dashboard id.
2. `saveDashboardV2` on update sends `base_revision` (or `If-Match`) and replaces the stored revision with `result.revision` from the response. On create, take `result.revision` (1) from the 201.
3. On 409: do not retry blindly. Tell the user, reload, and keep `current_revision` only as information.
4. On 422 show `message`; if `errors` is present, map each key to its node.
5. Hide the menu entry and the routes when the `DashboardV2` flag is off; the backend returns 404 regardless.
6. Send a `uuid` with every create of one unsaved document; a `200` adopts the id, and the revision only under the rule in section 3.1.
7. A 409 may come without `current_revision` (section 4); do not require the field.
8. Read the node and depth limits from `bootstrap_data.common.conf` (section 6).
9. Do not send or expect `v2_document` through the classic dashboard API (section 6.1).
10. A 422 with `errors` can be an authoring refusal (section 6.2) as well as a props error; show it on the node the same way.
11. Never generate a reserved node id (section 6).
