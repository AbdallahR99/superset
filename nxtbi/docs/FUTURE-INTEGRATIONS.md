# NxtBI Future Integrations (documentation only, nothing is built)

Source: `nxtbi/docs/research/02`, `03`, `04`, `06`, `07` (R02..R07). Labels: V = verified in code, D = docs-claimed, U = unverified. Maturity labels are copied from the research. No integration below was prototyped or executed. Effort values are rough estimates from R04 s6 unless stated.

## Local context

A separate NxtBI semantic-layer PoC with Cube Core v1.8 and Schema-Sense exists in the sibling folder `nxtbi-semantic-layer` (Keycloak realm `nxtbi-sl` on `127.0.0.1:8190`, Cube on port 4000). It was deliberately left out of scope for this demo; no file in it was read or changed.

## 1. Semantic-layer candidates

| Candidate | Integration point in Superset | Effort | Maturity / risk | Prerequisites | Prototype first |
|---|---|---|---|---|---|
| Cube Core (A) | Plain PostgreSQL database pointing at Cube's Postgres-wire SQL API (`postgresql://<user>:<pass>@cube:15432/<db>`, port from `CUBEJS_PG_SQL_PORT`); each cube/view becomes a physical dataset; measures wrapped as saved metrics (for example `MEASURE(orders.count)`) | Low (config + dataset YAML) | Superset side STABLE; no Cube-specific code in Superset (V grep); behaviour of Superset-generated SQL (joins, subqueries, time grains) on Cube is U | Cube SQL API enabled and reachable from the Superset containers; user/password; `PREVENT_UNSAFE_DB_CONNECTIONS` is not an issue for Postgres | One cube with 3 measures and a time dimension, exposed as a dataset; one bar chart; confirm time-grain SQL |
| Cube Core (B) | Backend-only extension registering a `@semantic_layer` provider that calls Cube REST (`/meta`, `/load`) through the host `ProviderTransport` | High (full `SemanticLayer`/`SemanticView` contract, filters, grains, caching identity) | EXPERIMENTAL twice: `ENABLE_EXTENSIONS` and `SEMANTIC_LAYERS`; SDK called "unreleased" and changed between commits (R04 s3.1) | Both flags on; extension loaded via `LOCAL_EXTENSIONS`; a pinned Superset commit | Not before (A); then read-only provider listing views and metrics, modelled on the 303-line test stub |
| Wren | Same two shapes: SQL endpoint as a database if Wren exposes a wire-compatible one (U), otherwise a `@semantic_layer` provider, or MCP-to-MCP composition next to the Superset MCP server | Medium-High | U on the Wren side; Superset side as for Cube | Confirm Wren's interface first | Check whether Wren offers a Postgres- or MySQL-compatible endpoint; if yes, treat as Cube (A) |
| Schema-Sense | Push descriptions, certification and metrics into native datasets via `PUT /api/v1/dataset/<id>` or assets YAML import; optionally an extension REST route or MCP tool for lookups | Low-Medium | Native dataset API STABLE; extension route EXPERIMENTAL; Schema-Sense capabilities U | Schema-Sense output format; service account with dataset write | Generate dataset YAML (`description`, `certified_by`, metrics) from Schema-Sense output and import it |
| Custom NxtBI semantic layer | Phase 1: compile NxtBI models to dataset YAML (metrics, calculated columns, folders) and import as `is_managed_externally` assets. Phase 2: `@semantic_layer` provider extension once the SDK is released | Phase 1 Low-Medium; Phase 2 High | Phase 1 uses STABLE primitives (`DATASET_FOLDERS` is EXPERIMENTAL); Phase 2 EXPERIMENTAL | Model schema; stable UUID scheme (for example `uuid5` per asset key) | Phase 1 only: one model compiled to YAML, imported via `/api/v1/assets/import/` |

Other hooks usable by any candidate (all V in R04 s2, R02 s4):

| Hook | Use | Maturity |
|---|---|---|
| Jinja macros (`JINJA_CONTEXT_ADDONS`) with `ENABLE_TEMPLATE_PROCESSING` | Pass user/org context into SQL sent to Cube or Wren; there is no `current_user_groups()`, only roles, username, email | STABLE, off by default (SSTI warning) |
| `CUSTOM_SECURITY_MANAGER` / claims | Carry Keycloak `groups` into roles and RLS; the same org claim can drive Cube security context | STABLE hook, own code |
| `DB_CONNECTION_MUTATOR`, `SQL_QUERY_MUTATOR` | Per-user or per-tenant connection or statement rewriting (for example tag queries for Cube) | STABLE hooks |
| Extension MCP tools (`@tool`) | Expose semantic lookups to MCP clients under `extensions.<org>.<ext>.` | EXPERIMENTAL |
| MCP semantic tools (`list_semantic_views`, `list_metrics`, `get_table`) | Already work on native datasets; external views need a provider | TESTING (beta) tools over EXPERIMENTAL layer |

Limits of the experimental semantic-layer path today (R04 s3.1): no Samples, no drill-to-detail, only `ExecutionMethod.CONNECTION` (shared service credentials, guest row rules refused), import bundles carry only references (credentials and layer config never exported).

## 2. Per-user Keycloak token path for REST and MCP

| Surface | What exists | What would need custom code | Maturity |
|---|---|---|---|
| Browser login | FAB `AUTH_OAUTH` with Keycloak; roles from group claims at each login (R02 s2, s6) | Split-hostname config, deny-by-default and RP logout are NxtBI code | STABLE recipe, own code |
| REST with Keycloak bearer | Not supported: `request_loader` verifies Superset's own JWT then loads user by `sub` (V `superset/security/manager.py:2462-2471`) | Override `request_loader` to verify the Keycloak JWT with `PyJWKClient` (issuer + audience checks), map `preferred_username` to a user; only effective where `allow_browser_login=True` | NOT AVAILABLE; custom path EXPERIMENTAL |
| REST service identity | `POST /api/v1/security/login` with provider `db` works under OAuth; CSRF token + cookie needed for writes; FAB API keys (`sst_...`) | Change the default `admin` password; keep service users local | STABLE; API keys EXPERIMENTAL |
| MCP with Keycloak | Native: `MCP_AUTH_ENABLED`, `MCP_JWKS_URI`, `MCP_JWT_AUDIENCE` (mandatory), `MCP_USER_RESOLVER` (default `preferred_username`) | Audience mapper; client scopes literally named `superset:read` / `superset:write` (otherwise every tool is denied); issuer pinned to the host the MCP client used; the user must already exist from a prior OIDC login | TESTING (beta) |
| Identity propagation to the data source | DB impersonation (`impersonate_user`), `CACHE_IMPERSONATION`, Jinja `current_username()`, RLS | Mapping Keycloak identity to Cube/Wren security context | Core STABLE; two flags TESTING (beta) |

Keycloak access tokens have a 300 s lifetime in the research realm (R02 s2); refresh handling for long MCP sessions is U. Role changes reach Superset only at next login.

## 3. Embedding with guest tokens

- Flag `EMBEDDED_SUPERSET` (STABLE, default off). Production refuses the default `GUEST_TOKEN_JWT_SECRET`. Token expiry 300 s by default (V `superset/config.py:998-1000,3431-3438`).
- Minting needs `can_grant_guest_token` (Admin-only): call `POST /api/v1/security/guest_token/` from a trusted NxtBI backend using a service account, never from the browser (R02 s5).
- Body: `{"user": {...}, "resources": [{"type": "dashboard", "id": "<embedded uuid>"}], "rls": [{"clause": "...", "dataset": <id>}]}`; `rls` and `resources` required; since the 7.0 line RLS rules accept only `dataset` and `clause` keys (R03 s6, R07 s3).
- Client: `@superset-ui/embedded-sdk` 0.4.0, `embedDashboard({id, supersetDomain, mountPoint, fetchGuestToken, ...})`; per-dashboard allowed domains, CSP `frame-ancestors` and CORS must be set (R03 s6).
- Tenant isolation for embeds is a per-token `rls` clause (for example `org_code = '<org>'`) built by the NxtBI backend from the Keycloak identity. This is STABLE but limited to dataset-level RLS.
- Guest tokens also work on MCP (`MCP_EMBEDDED_GUEST_AUTH_ENABLED`, TESTING (beta)), limited to 8 read tools.
- Open issue: #39682 (embedding broken after 6.0 upgrade; check `ENABLE_PROXY_FIX`, allowed domains, referrer policy) (R07 s5). `GUEST_TOKEN_REVOCATION_ENABLED` is opt-in; `EMBEDDED_CREDENTIAL_FALLBACK` is TESTING (beta) and master-only.

## 4. Suggested order

1. Cube Core (A) Postgres-wire dataset (days, config only), after confirming Superset-generated SQL works against it.
2. Schema-Sense or custom-model output compiled to dataset YAML (Phase 1), reusing the assets-import pipeline.
3. Keycloak bearer on MCP, then optional REST `request_loader` override.
4. Provider extension (Cube B, Wren, NxtBI Phase 2) only after Superset releases a stable semantic SDK and a version is pinned; until then treat it as a research item.

## 5. What not to claim

- No Cube, dbt MetricFlow, Snowflake or Malloy provider ships in Superset; mentions in docs and UI comments are illustrative only (R04 s3.1). There is no Python entry-point group or config list for providers: registration is only through the extensions loader.
- No built-in LLM, text-to-SQL or chat panel; the chat contribution point exists but no chat extension ships (R03 s7).
- No Keycloak bearer on REST without custom code; no automatic back-channel logout.
- External semantic views are unavailable to multi-tenant guests (guest row rules are refused under `ExecutionMethod.CONNECTION`).

## 6. Open questions to settle before building

| Question | Why it matters | Label |
|---|---|---|
| Does Cube's SQL API accept the SQL Superset generates (joins, subqueries, time grains)? | Decides whether option (A) is viable | U (R04 s3.3) |
| Does Wren expose a wire-compatible SQL endpoint? | Decides database vs provider shape | U (R04 s6) |
| What does Schema-Sense output, and can it map to dataset YAML? | Decides Phase 1 effort | U (R04 s7) |
| Do extensions load inside the standalone MCP process? | Extension MCP tools depend on it | U (R04 s7) |
| Which commit will be pinned, given the semantic SDK changes weekly on master? | Provider code breaks between commits | R07 s4 |
| Will a Keycloak token refresh strategy be needed for long MCP sessions? | 300 s access token in the research realm | U |
