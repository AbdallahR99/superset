<!--
Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
-->

# Widgets host example

A Vite + React app that renders `@apache-superset/widgets` in its own layout.
It stands in for a host application and shows, top to bottom:

| On the page                          | What it demonstrates                                                                                                                                           | Source                                 |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| Embed one widget (session mode only) | The smallest integration: a provider and a chart.                                                                                                              | `src/MinimalEmbed.tsx`                 |
| Host filter chips                    | A filter the host owns, passed declaratively as `<SupersetProvider filters>`.                                                                                  | `src/HostFilterBar.tsx`, `src/App.tsx` |
| Inline widgets                       | Filter, metric tile, bar, pie, table and markdown defined in the page, cross-filtering each other.                                                             | `src/App.tsx`                          |
| Saved widgets                        | Widgets stored in Superset, rendered by uuid (`<Widget id>`).                                                                                                  | `src/App.tsx`                          |
| Events and errors (side panel)       | `useWidgetEvent` and `<SupersetProvider onError>`.                                                                                                             | `src/EventLog.tsx`, `src/ErrorLog.tsx` |
| Two independent providers            | Two `SupersetProvider`s side by side, each with its own filter, bus and (in guest mode) token via `guestTokenKey`. Filtering one does not refetch the other.   | `src/Isolation.tsx`                    |
| Component gallery                    | One example per component and prop, including two providers that share a `bus` on purpose.                                                                     | `src/Gallery.tsx`                      |
| Header toggles                       | Dark mode, the structure overlay, and **العربية (RTL)**, which switches every provider to `direction="rtl"` (tables and controls mirror; chart axes stay LTR). | `src/App.tsx`                          |

It runs in one of two modes:

- **session** (default): no backend. Widgets call Superset with the viewer's
  own Superset login, so that user's permissions and RLS apply.
- **guest**: widgets use guest tokens from `server.mjs`, a local token broker
  that plays the host application's backend.

## 1. Prepare Superset

In `superset_config.py` (in this fork: the nxtbi overrides):

```python
FEATURE_FLAGS = {
    "DASHBOARD_V2": True,       # the widget APIs answer 404 without it
    "EMBEDDED_SUPERSET": True,  # guest mode only
}
ENABLE_CORS = True
CORS_OPTIONS = {
    "origins": ["http://localhost:5173"],
    "resources": [r"/api/*"],
    # session mode sends the login cookie and a CSRF token:
    "supports_credentials": True,
    "allow_headers": ["Content-Type", "X-GuestToken", "X-CSRFToken"],
}
# guest mode only: the role every guest token acts with. It needs
# `can read on Chart` and nothing else.
GUEST_ROLE_NAME = "WidgetGuest"
```

Then, depending on the mode:

- **session:** log in to Superset in the same browser. `localhost:5173` and
  `localhost:8088` are the same site, so the session cookie reaches Superset;
  a host on another site needs guest mode instead. Your user needs `can read
  on Chart` and access to the dataset.
- **guest:**
  1. Create the role named by `GUEST_ROLE_NAME` with only `can read on Chart`.
  2. Create (or pick) a service account for the broker with `can grant guest
     token on SecurityRestApi` and read access to every dataset and saved
     widget the page uses. Superset checks each grant against this account.
  3. If a dataset carries row-level security rules, set `BROKER_RLS_A` /
     `BROKER_RLS_B` (step 3): Superset refuses to grant it to a guest without
     a token rule that covers it.

An extension's widget (`EMBED_EXTENSION_WIDGET`) additionally needs
`ENABLE_EXTENSIONS` and, in guest mode, `EMBEDDED_EXTENSION_ASSETS_PUBLIC =
True`, since its bundle loads as a plain `<script>`.

## 2. Install

```bash
cd superset-frontend
npm install            # once: this app resolves react, antd, emotion, echarts here
cd packages/superset-widgets/example
npm install
```

## 3. Configure

```bash
cp .env.example .env
```

`.env.example` documents every variable. The ones that matter first:

- `SUPERSET_URL`: where Superset is.
- **The dataset.** Defaults describe Superset's `birth_names` example. For
  other data, set `FILTER_DATASET_TABLE` (and `FILTER_DATASET_ID`), the
  dimension `FILTER_COLUMN` with a few `FILTER_VALUES`, the saved metric
  `EMBED_METRIC`, and the `EMBED_CATEGORY` / `EMBED_LABEL` /
  `EMBED_METRIC_COLUMN` columns.
  - In session mode these are a preference: the app finds the dataset by table
    name, and replaces any column or metric the dataset does not have.
  - In guest mode a guest cannot read the dataset API, so every value is used
    as written. Look the id up first:
    `GET /api/v1/dataset/?q=(filters:!((col:table_name,opr:eq,value:<name>)))`.
- `EMBED_B_*`: the dataset of the second provider in "Two independent
  providers". Empty means the same dataset as the first.
- `EMBED_WIDGET_IDS`: uuids of saved widgets (`GET /api/v1/widget/`, or "Embed
  widget" on a widget in the Dashboard v2 builder). Empty hides nothing: the
  section explains what to set.
- `EMBED_MISSING_WIDGET_ID`: a uuid no saved widget has. Set it to show the
  gallery's `renderError` demo, which asks for that widget and draws the 404.
  Empty hides the demo, so a default run makes no request that fails.
- Guest mode: `EMBED_AUTH=guest`, `SUPERSET_USERNAME`, `SUPERSET_PASSWORD`
  (the service account; no defaults, and never sent to the browser).

Only variables starting with `SUPERSET_URL`, `EMBED_` or `FILTER_` are
compiled into the browser bundle. Credentials and `BROKER_*` settings are read
by `server.mjs` alone.

## 4. Run

```bash
npm run dev        # http://localhost:5173

# guest mode: also start the broker, in a second terminal
npm run broker     # http://127.0.0.1:3001, proxied by Vite at /api/guest-token
```

`npm run typecheck` type-checks the app together with the package sources it
consumes; `npm run build` does that and bundles.

## The token broker (`server.mjs`)

The page never asks for a resource. It asks for a token for an **audience**
(`POST /api/guest-token?audience=a|b`), and the broker decides what a token
for that audience may read:

| Audience | Used by                       | `resources` it requests                                                                               | `rls`          |
| -------- | ----------------------------- | ----------------------------------------------------------------------------------------------------- | -------------- |
| `a`      | the main provider, provider A | `{type: "widget", id}` for each of `EMBED_WIDGET_IDS`, and `{type: "dataset", id: FILTER_DATASET_ID}` | `BROKER_RLS_A` |
| `b`      | provider B                    | `{type: "dataset", id: EMBED_B_DATASET_ID}` (defaults to `FILTER_DATASET_ID`)                         | `BROKER_RLS_B` |

- A `widget` resource grants one saved widget and the dataset it is bound to
  when the token is minted.
- A `dataset` resource is the explicit grant for inline, SQL-free widget
  definitions against that dataset. Nothing else grants them; the `datasets`
  claim only narrows a dashboard token and is not sent here.

The broker reads credentials from the environment only (a `.env` file is
loaded into the environment at start), binds to `127.0.0.1`, answers only
`POST` from `BROKER_ALLOWED_ORIGIN`, sends tokens with `Cache-Control:
no-store`, and never logs a token or a Superset response body that contains
one. A failure is logged with Superset's reason on the broker's console; the
browser only learns that it failed.

What it leaves out, and a real broker must do: authenticate the host
application's own user before minting, and derive the `rls` clause from that
user rather than from the environment.

## Troubleshooting

| Symptom                                          | Check                                                                                                                                                                                                                         |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Every widget: `Failed to fetch`, CORS in console | `ENABLE_CORS`, the origin `http://localhost:5173`, and the headers in `CORS_OPTIONS`. Restart Superset after changing them.                                                                                                   |
| 404 on `/api/v1/widget/...`                      | `DASHBOARD_V2` is off.                                                                                                                                                                                                        |
| 401 in session mode                              | Not logged in to Superset in this browser, or the cookie is not sent (different site).                                                                                                                                        |
| Broker exits: `SUPERSET_USERNAME is not set`     | Fill in `.env`.                                                                                                                                                                                                               |
| Broker logs `Guest token failed: 400 …` or `403` | Read Superset's reason in the log. Usual causes: the service account lacks `can grant guest token` or cannot read a granted dataset or widget; a saved widget uuid is wrong; the dataset has RLS and `BROKER_RLS_*` is empty. |
| Broker logs `Superset login failed …`            | `SUPERSET_URL`, `SUPERSET_USERNAME` or `SUPERSET_PASSWORD` is wrong (the broker signs in with the `db` auth provider).                                                                                                        |
| 403 on an inline widget in guest mode            | `FILTER_DATASET_ID` / `EMBED_B_DATASET_ID` is not the id of the dataset the page queries (guest mode does not look it up).                                                                                                    |
| Empty charts, `invalid` errors                   | A column or metric in `.env` does not exist on the dataset (guest mode uses them as written).                                                                                                                                 |
| The errors panel shows the failure too           | That is `onError`: every failure a widget shows is also reported to the host.                                                                                                                                                 |
