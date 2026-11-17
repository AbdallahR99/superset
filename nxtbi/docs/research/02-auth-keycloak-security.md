# 02 - Authentication, authorization and Keycloak OIDC (NxtBI Superset Demo)

Scope: fork @ `f3f3d10d5c` (2026-11-16). Labels: **V** = VERIFIED-IN-CODE, **D** = DOCS-CLAIMED, **U** = UNVERIFIED. FAB = Flask-AppBuilder tag `v5.3.0`, Authlib = tag `v1.6.12`, KC = Keycloak tag `26.4.0` (all read at source on GitHub). Secrets are referenced by variable name only.

## 1. Versions and moving parts

| Item | Fact | Evidence |
|---|---|---|
| FAB | `flask-appbuilder==5.3.0` (pyproject `>=5.3.0,<6.0.0`) | V `requirements/base.txt:123`, `pyproject.toml:56` |
| Authlib | `authlib==1.6.12`, **dev-only** (via `fastmcp-slim`), **absent from `requirements/base.txt`** -> add `Authlib==1.6.12` to the image or `AUTH_OAUTH` fails on `from authlib...` | V `requirements/development.txt:68-69`; FAB `security/manager.py:298-299` |
| Related pins | flask-login 0.6.3, flask-jwt-extended 4.7.1, flask-session 0.8.0, flask-talisman 1.1.0, flask-wtf 1.3.0, pyjwt 2.15.1 | V `requirements/base.txt:135-154,306` |
| Official recipe | Repo ships a complete Keycloak example (PKCE, group mapping, RP logout): STABLE, config-only pattern | D `docs/admin_docs/security/oauth.mdx:107-307` |
| Routes | `SupersetAuthView` (`route_base="/login"`) renders the SPA at `/login/`; FAB `AuthOAuthView` is also registered and serves `/login/<provider>`, `/oauth-authorized/<provider>`, `/logout/` | V `superset/views/auth.py:34-50`, `superset/security/manager.py:7288-7289,7329`; FAB `security/views.py:668-776`, `security/manager.py:929-938` |
| Login page | Under `AUTH_OAUTH`: provider buttons only ("Sign in with Keycloak" -> `/login/keycloak?next=`), **no password form** | V `superset-frontend/src/pages/Login/index.tsx:94,186-206`, `superset/views/base.py:650-659` |
| Callback | `url_for(".oauth_authorized", provider, _external=True)` -> `http://<request-host>/oauth-authorized/keycloak` | V FAB `security/views.py:705-709` |
| Extension points | `CUSTOM_SECURITY_MANAGER`, `FLASK_APP_MUTATOR` (zero upstream edits) | V `superset/config.py:255,2397` |

## 2. FAB 5.3.0 OAuth flow (V unless noted)

| Step | Behaviour | Evidence (FAB / Authlib) |
|---|---|---|
| Register | `oauth.register(name, **remote_app)`; unknown kwargs become **server metadata** (`issuer`, `jwks_uri`, `userinfo_endpoint`) | `security/manager.py:298-315`; `base_client/sync_app.py:206,225-226` |
| Authorize | PKCE verifier when `client_kwargs.code_challenge_method` is set; `nonce` when scope has `openid`; `authorize_url` overrides metadata | `sync_app.py:272-294,341-343` |
| Token | `authorize_access_token()` calls `access_token_url`, then **validates the id_token** (JWKS signature, `iss` == `metadata["issuer"]`, aud, exp, nonce) and stores claims in `token["userinfo"]` | `flask_client/apps.py:82-121`; `base_client/sync_openid.py:36-79` |
| User info | view calls `sm.set_oauth_session(provider, resp)` then `sm.oauth_user_info(provider, resp)`; a subclass method named `oauth_user_info` wins (default assigned only when falsy) | `security/views.py:735-736`; `security/manager.py:162,310-311` |
| Built-in `keycloak` | `.get("openid-connect/userinfo")` relative to `api_base_url`; `role_keys = data.get("groups", [])` | `security/manager.py:809-822` |
| Session token | `session["oauth"] = (access_token, "")`; only reader is legacy `_oauth_tokengetter`, never used by Authlib (it reads `g._oauth_token_<name>`) -> safe to drop | `security/manager.py:133-139,703-715`; `flask_client/apps.py:15-32` |
| Roles | with `AUTH_ROLES_SYNC_AT_LOGIN`: `user.roles` = roles of each `AUTH_ROLES_MAPPING` key present in `role_keys` (+ `AUTH_USER_REGISTRATION_ROLE` every time, only if registration is on). Unknown role names are skipped with a warning | `security/manager.py:360-384,1547-1577,1610-1613` |
| Groups (first-class) | `ab_group` (name `String(100)` unique) M2M users + roles. `AUTH_GROUPS_SYNC_AT_LOGIN` sets `user.groups` from `userinfo["groups"]` (fallback `role_keys`) by **exact group name**; `AUTH_AUTO_CREATE_GROUPS` creates missing ones | `security/manager.py:242-243,386-424,1615-1629`; `security/sqla/models.py:240-292` |
| Login hook | `auth_user_oauth` -> `update_user_auth_stat` -> `on_user_login` -> Superset stamps `session["_login_at"]` | `security/manager.py:1100-1102`; `superset/security/manager.py:2421-2431` |
| Logout | `GET /logout/`: `logout_user()` + `on_user_logout`, redirect to `LOGOUT_REDIRECT_URL` or index; does **not** clear the session or call the IdP | `security/views.py:605-615` |
| Self-registration | `AUTH_USER_REGISTRATION=True` under `AUTH_OAUTH` also publishes a public `/register/` form + e-mail activation that creates a user with the registration role | V `superset/security/manager.py:7296-7303`, `superset/views/auth.py:85-106`; D `UPDATING.md:815-822` |

Realm facts (V, read-only from `D:/DDWork/nxtdash-w4-int/docker/keycloak/realm-nxtbi.json`): `groups` scope mapper `oidc-group-membership-mapper` has `full.path=true` and `id.token.claim = access.token.claim = userinfo.token.claim = true`, so the claim is e.g. `["/nxt/ministry-of-planning/admin"]` everywhere. `groups` is **not** a realm default scope (defaults: `role_list saml_organization profile email roles web-origins acr basic`) -> the new client must list it. `defaultSignatureAlgorithm=RS256`; access token 300 s; SSO idle 1800 s / max 36000 s. Seed users sit only in `/nxt/<org>/admin` or `/nxt/<org>/editor`; `unaffiliated@` has no group; nobody is in a `viewer` or workspace group. NxtDash uses `http://localhost:8180` in the browser and redirect URIs on ports 3000/8080 (no clash with 8088); the multi-value separator for post-logout URIs is `##`.

## 3. Split-hostname design

Problem: with `KC_HOSTNAME_STRICT=false` and no `KC_HOSTNAME`, every URL Keycloak emits, including token `iss`, comes from the `Host` of the request that produced it (V KC `TokenManager.java:520`, `UserInfoEndpoint.java:288`; D keycloak.org/server/hostname). Discovery fetched from the container advertises an `authorization_endpoint` the browser cannot reach, and vice versa.

**Recommended: explicit split endpoints, no `server_metadata_url`, issuer pinned to the back-channel host.**

| Leg | Caller | Base URL | Reason |
|---|---|---|---|
| `authorize_url`, end-session | browser | `KEYCLOAK_BROWSER_URL` = `http://localhost:8180` (same host NxtDash uses -> shared SSO cookie) | the only front-channel hops |
| `access_token_url`, `jwks_uri`, `userinfo_endpoint`, `api_base_url` | Superset container | `KEYCLOAK_INTERNAL_URL` = `http://host.docker.internal:8180` | back-channel |
| `issuer` (metadata kwarg) | Authlib check | `{KEYCLOAK_INTERNAL_URL}/realms/{realm}` | Superset chooses the token-endpoint host, so the id_token `iss` is deterministically this value; `iss` validation stays **on** |

Why it is correct: (1) the auth code is not host-bound; (2) `iss` equals the pinned value by construction; (3) the access token is only presented back to the host that minted it (userinfo enforces `realmUrl`, V `UserInfoEndpoint.java:186-187`); (4) RP logout works cross-host: `id_token_hint` is checked by **signature + token type only**, no issuer check (V `LogoutEndpoint.java:182-183`, `TokenManager.java:510-516`), and with a matching `client_id` there is no confirmation page (V `LogoutEndpoint.java:199-210`); (5) realm signing keys are host-independent. `sslRequired=external` passes because Keycloak sees private bridge addresses (U; symptom if wrong: `HTTPS required` on the token call).

**Fallback (env only, same code):** join external network `ld-shared_default` and set `KEYCLOAK_INTERNAL_URL=http://keycloak:8080` (issuer `http://keycloak:8080/realms/nxtbi`); costs a start-up dependency on another compose project. Rejected: `claims_options` to skip `iss` (weakens validation); one hostname via `keycloak.localhost` + `extra_hosts` (changes the browser URL, loses the SSO cookie shared with NxtDash); browser on `host.docker.internal` (Keycloak is published on host loopback only). Production: fixed `KC_HOSTNAME=https://sso...` gives one issuer, both env vars become equal and `server_metadata_url` is viable.

## 4. Role model and tenant isolation

Built-in roles (V `superset/security/manager.py:3718-3738,3835-3954`; D `docs/admin_docs/security/security.mdx:22-66`):

| Role | Real permission set on this commit |
|---|---|
| Admin | every non-user-defined PVM; fully trusted; edits users/RLS; sees all data |
| Alpha | all but admin-only and SQL-Lab-only PVMs; **includes `all_datasource_access` + `all_database_access`** (`:2235-2239`) and dataset write |
| Gamma | Alpha minus alpha-only menus/perms, minus writes on `Dataset`/`Database`/`SemanticView`/`Theme`/`CssTemplate`, minus `can_export_data/image`; data only via explicit `datasource_access`/`schema_access`; **can still create charts and dashboards** |
| sql_lab | SQL Lab PVMs only (`:2250-2288`); no database access by itself |
| Public | empty unless `PUBLIC_ROLE_LIKE` is set (`superset/config.py:580`) |

Recommended mapping (deny by default: no mapped group -> login rejected, no user row):

| Keycloak group path | Superset roles | Note |
|---|---|---|
| `/nxt/<org>/admin`, `/nxt/<org>/<ws>/admin` | `Gamma`, `sql_lab`, `nxt_org_<org>` | **not** Alpha/Admin: both cross tenants |
| `/nxt/<org>[/<ws>]/editor` and `.../viewer` | `Gamma`, `nxt_org_<org>` | no built-in read-only role; optional custom `nxt_viewer` for viewers |
| env allow-list `NXTBI_PLATFORM_ADMINS` | `Admin` | realm has no platform group; production: dedicated KC group |

`nxt_org_<org>` roles must be created by the bootstrap **before first login** (FAB `POST /api/v1/security/roles/`, Admin only; `FAB_ADD_SECURITY_API=True` V `config.py:2428`) and granted `datasource_access` on the demo datasets (perm name `[db].[dataset](id:N)`, V `manager.py:2525-2530`). Optional mirror: `AUTH_GROUPS_SYNC_AT_LOGIN` + `AUTH_AUTO_CREATE_GROUPS` create FAB groups named after the full Keycloak path; Subject rows follow via FAB signals (V `superset/subjects/hooks.py:47-82`; repair: `superset sync-subjects`).

RLS (STABLE, no feature flag; V `manager.py:6295-6365`, `connectors/sqla/models.py:1178-1215,3443-3481`): filters bind **datasets** to **Subjects** (user / role / group, role-via-group included, V `superset/subjects/utils.py:33-80`); `Regular` applies to matching subjects, `Base` to everyone **except** the listed subjects; equal `group_key` -> OR, otherwise AND; the clause is Jinja-rendered. API: `POST /api/v1/rowlevelsecurity/` `{name, filter_type:"Regular"|"Base", tables:[dataset_id], subjects:[subject_id], group_key, clause}` (V `row_level_security/schemas.py:125-170`, `api.py:76-80`, `utils/core.py:459-461`); subject ids from `GET /api/v1/security/subject/?q=(filters:!((col:role_id,opr:eq,value:<id>)))` (Admin only, D `security.mdx:239-262`). `roles` was replaced by `subjects` (D `UPDATING.md:2233-2246`).

Demo recipe: shared datasets carry `org_code`. R1 `Regular`, subject role `nxt_org_ministry-of-planning`, `group_key="org"`, clause `org_code = 'ministry-of-planning'`; R2 same for `statistics-bureau`; R3 `Base`, clause `1 = 0`, exempt subjects = `Admin` + both org roles. Jinja: `current_username()`, `current_user_email()`, `current_user_roles()` (includes group-derived roles), `current_user_rls_rules()` exist (V `jinja_context.py:228-334,1335-1348`); there is **no** `current_user_groups()`; custom macros via `JINJA_CONTEXT_ADDONS` need `ENABLE_TEMPLATE_PROCESSING` (STABLE, default off, `config.py:1002-1004`). Prefer static per-role clauses: their text is in the cache key (V `manager.py:6489-6498`).

Multi-tenancy limits (say so in the demo): one metadata DB and one role namespace; RLS protects datasets, not tables, so anyone with dataset write + database access (Alpha, Admin) can build an unfiltered dataset; SQL Lab bypasses RLS unless `RLS_IN_SQLLAB` (BETA-TESTING, "may ... allow RLS bypass", `config.py:889-892`) so `nxt_org_*` must only carry org-private schema access; user/role lists are instance-global; dashboard viewers `ENABLE_VIEWERS` is BETA-TESTING (`config.py:954-956`); role changes apply at next login only (no back-channel logout or introspection); a new org needs config + role + RLS rule.

## 5. API authentication under `AUTH_OAUTH`

| Mechanism | Status | Finding |
|---|---|---|
| `POST /api/v1/security/login` `{"provider":"db"}` | STABLE | **Works regardless of `AUTH_TYPE`**: no auth-type gate before `auth_user_db` (V FAB `security/api.py:101-103`, `security/manager.py:1106-1147`); HS256 JWT, `sub` = user id. `fab create-admin` works under OAuth (V FAB `cli.py:59-100`). **`docker/docker-init.sh:38-49` creates `admin` with default `ADMIN_PASSWORD=admin` -> API-reachable Admin unless overridden** |
| CSRF | STABLE | Superset REST APIs are not CSRF-exempt (V `superset/views/base_api.py:341`, `config.py:387-395`): mutations need `GET /api/v1/security/csrf_token/` + `X-CSRFToken` + the cookie from that call, even with Bearer or API key (D `UPDATING.md:271-283`) |
| Keycloak access token on REST | not supported | `request_loader` runs `verify_jwt_in_request()` (Superset key) then `load_user(int(sub))` (V `manager.py:2462-2471`; FAB `manager.py:2647-2659`). Possible custom `request_loader` override (PyJWT `PyJWKClient`, issuer + audience checks) = EXPERIMENTAL own code, only effective where `allow_browser_login=True` (V FAB `security/decorators.py:122-124`) |
| FAB API keys (`sst_...`) | EXPERIMENTAL (`@lifecycle: development`) | config `FAB_API_KEY_ENABLED=True` + feature flag of the same name; checked before JWT in `protect()`; `ApiKey` perms Admin-only (V `config.py:758-761,2433-2438`, `manager.py:2188-2189`; FAB `decorators.py:103-121`; D `security.mdx:522-583`) |
| MCP service | own auth stack | `MCP_AUTH_ENABLED`, `MCP_JWKS_URI`, `MCP_JWT_ISSUER`, `MCP_JWT_AUDIENCE` (**mandatory**), `MCP_JWT_ALGORITHM` (RS256), `MCP_REQUIRED_SCOPES`, `MCP_USER_RESOLVER` (default `preferred_username` -> `username` -> `email` -> `sub`); `MCP_DEV_USERNAME` is refused when auth is on (V `mcp_service/mcp_config.py:638-667,871-972`). Keycloak tokens work here; the user must already exist (first OIDC login); `MCP_JWT_ISSUER` must equal the host the MCP client used to obtain its token, JWKS may be fetched internally; needs the audience mapper of section 7 |
| Guest tokens / embedded SDK | STABLE (`EMBEDDED_SUPERSET`, default off, `config.py:998-1000`) | `POST /api/v1/security/guest_token/` needs `can_grant_guest_token` (Admin-only, V `manager.py:2216`, `security/api.py:207-213`) -> mint with the service account; per-token `rls`; `GUEST_ROLE_NAME="Public"`, replace `GUEST_TOKEN_JWT_SECRET`, 300 s expiry (V `config.py:3431-3438`) |

## 6. Ready-to-paste `superset_config.py` block

```python
# ===== NxtBI: Keycloak OIDC login, group->role mapping, RP-initiated logout =====
# Needs Authlib==1.6.12 in the image (not part of requirements/base.txt).
import logging
import os
from datetime import timedelta
from urllib.parse import urlencode

from flask import redirect, session
from flask_appbuilder import expose
from flask_appbuilder.security.manager import AUTH_OAUTH
from flask_appbuilder.security.views import AuthOAuthView
from superset.security import SupersetSecurityManager

_log = logging.getLogger("nxtbi.auth")
KEYCLOAK_BROWSER_URL = os.environ.get("KEYCLOAK_BROWSER_URL", "http://localhost:8180").rstrip("/")
KEYCLOAK_INTERNAL_URL = os.environ.get("KEYCLOAK_INTERNAL_URL", "http://host.docker.internal:8180").rstrip("/")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "nxtbi")
KEYCLOAK_CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "nxtbi-superset")
_KC_SECRET = os.environ["KEYCLOAK_CLIENT_SECRET"]  # no default: fail fast at start-up
SUPERSET_PUBLIC_URL = os.environ.get("SUPERSET_PUBLIC_URL", "http://localhost:8088").rstrip("/")
_KC_PROVIDER = "keycloak"  # callback path = /oauth-authorized/keycloak
_KC_FRONT = f"{KEYCLOAK_BROWSER_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect"  # browser hops only
_KC_ISSUER = f"{KEYCLOAK_INTERNAL_URL}/realms/{KEYCLOAK_REALM}"  # == iss of tokens minted for Superset
_KC_BACK = f"{_KC_ISSUER}/protocol/openid-connect"
_ID_TOKEN_KEY = "nxtbi_id_token"
_POST_LOGOUT_URL = f"{SUPERSET_PUBLIC_URL}/login/"  # must match post.logout.redirect.uris exactly

AUTH_TYPE = AUTH_OAUTH
AUTH_USER_REGISTRATION = False   # keeps the public /register/ form closed; JIT provisioning is done below
AUTH_ROLES_SYNC_AT_LOGIN = True  # Keycloak groups are the source of truth on every login
OAUTH_PROVIDERS = [{
    "name": _KC_PROVIDER, "icon": "fa-key", "token_key": "access_token",
    "remote_app": {
        "client_id": KEYCLOAK_CLIENT_ID,
        "client_secret": _KC_SECRET,
        # No server_metadata_url on purpose: Keycloak derives every URL (and iss) from the request Host.
        "authorize_url": f"{_KC_FRONT}/auth",
        "access_token_url": f"{_KC_BACK}/token",
        "api_base_url": f"{_KC_BACK}/",
        "jwks_uri": f"{_KC_BACK}/certs",  # this and the next three kwargs become Authlib server metadata
        "userinfo_endpoint": f"{_KC_BACK}/userinfo",
        "issuer": _KC_ISSUER,
        "id_token_signing_alg_values_supported": ["RS256"],
        "client_kwargs": {"scope": "openid profile email groups", "code_challenge_method": "S256", "default_timeout": 10},
    },
}]
_ORGS = [o for o in os.environ.get("NXTBI_ORGS", "ministry-of-planning,statistics-bureau").split(",") if o]
_WORKSPACES = [w for w in os.environ.get("NXTBI_WORKSPACES", "example-workspace").split(",") if w]
_PLATFORM_ADMINS = {u.strip().lower() for u in os.environ.get("NXTBI_PLATFORM_ADMINS", "").split(",") if u.strip()}
_ADMIN_KEY = "nxtbi:platform-admin"
_CAPABILITY = {"admin": ["Gamma", "sql_lab"], "editor": ["Gamma"], "viewer": ["Gamma"]}
AUTH_ROLES_MAPPING = {_ADMIN_KEY: ["Admin"]}
for _org in _ORGS:
    for _level, _roles in _CAPABILITY.items():
        _mapped = [*_roles, f"nxt_org_{_org}"]  # nxt_org_* roles are created by the bootstrap
        AUTH_ROLES_MAPPING[f"/nxt/{_org}/{_level}"] = _mapped
        for _ws in _WORKSPACES:
            AUTH_ROLES_MAPPING[f"/nxt/{_org}/{_ws}/{_level}"] = _mapped

class NxtbiOAuthView(AuthOAuthView):
    @expose("/logout/", methods=["GET", "POST"])
    def logout(self):
        id_token = session.get(_ID_TOKEN_KEY)
        super().logout()  # flask_login.logout_user() + sm.on_user_logout() audit event
        session.clear()   # FAB leaves oauth/_login_at/id_token keys behind
        params = {"client_id": KEYCLOAK_CLIENT_ID, "post_logout_redirect_uri": _POST_LOGOUT_URL}
        if id_token:
            params["id_token_hint"] = id_token  # skips Keycloak's confirmation page
        return redirect(f"{_KC_FRONT}/logout?{urlencode(params)}")  # OIDC RP-initiated logout

class NxtbiSecurityManager(SupersetSecurityManager):
    authoauthview = NxtbiOAuthView

    def set_oauth_session(self, provider, oauth_response):  # FAB default also stores the unused access token
        session["oauth_provider"] = provider
        session[_ID_TOKEN_KEY] = oauth_response.get("id_token")

    def oauth_user_info(self, provider, response=None):
        if provider != _KC_PROVIDER:
            return self.get_oauth_user_info(provider, response)
        claims = dict((response or {}).get("userinfo") or {})  # id_token claims verified by Authlib
        if not claims.get("preferred_username") or "groups" not in claims:
            resp = self.oauth_remotes[provider].get("userinfo")  # relative to api_base_url
            resp.raise_for_status()
            claims.update(resp.json())
        username = (claims.get("preferred_username") or claims.get("email") or "").strip()
        groups = sorted(g for g in claims.get("groups", []) if isinstance(g, str))
        role_keys = [g for g in groups if g in AUTH_ROLES_MAPPING]
        if username.lower() in _PLATFORM_ADMINS:
            role_keys.append(_ADMIN_KEY)
        _log.info("OIDC login user=%s mapped=%s", username, role_keys)
        return {"username": username, "email": claims.get("email", ""), "role_keys": role_keys, "groups": groups,
                "first_name": claims.get("given_name", ""), "last_name": claims.get("family_name", "")}

    def auth_user_oauth(self, userinfo):
        username = userinfo.get("username")
        if not username or not userinfo.get("role_keys"):  # deny by default: no mapped /nxt/... group
            _log.warning("OIDC login rejected, no mapped group: %s", username)
            session.pop(_ID_TOKEN_KEY, None)
            return None  # FAB flashes "Invalid login" and returns to /login/
        if not self.find_user(username=username):  # JIT provisioning without AUTH_USER_REGISTRATION
            if not self.add_user(username=username, first_name=userinfo["first_name"], last_name=userinfo["last_name"],
                                 email=userinfo["email"] or f"{username}@email.notfound",
                                 role=self._oauth_calculate_user_roles(userinfo)):
                return None
        return super().auth_user_oauth(userinfo)  # role sync + login stats + on_user_login

CUSTOM_SECURITY_MANAGER = NxtbiSecurityManager

# --- session / cookie posture for local http://localhost:8088 ---
# Keep the defaults SESSION_COOKIE_HTTPONLY=True, WTF_CSRF_ENABLED=True, TALISMAN_ENABLED=True (force_https False).
SESSION_COOKIE_SAMESITE = "Lax"  # OAuth callback is a top-level GET: Lax is required and sufficient
SESSION_COOKIE_SECURE = False    # True as soon as Superset is served over https
PERMANENT_SESSION_LIFETIME = timedelta(hours=10)  # realm ssoSessionMaxLifespan = 36000 s
ENABLE_PROXY_FIX = False         # True behind a TLS-terminating proxy (else redirect_uri is http://)
# Recommended (keeps the id_token out of the browser cookie), flask-session 0.8.0:
# from redis import Redis; SESSION_SERVER_SIDE = True; SESSION_TYPE = "redis"
# SESSION_REDIS = Redis(host=os.environ.get("REDIS_HOST", "redis"), port=6379, db=4)
```

Notes: only UPPERCASE names reach `app.config`. `add_user(role=<list>)` mirrors FAB's own call (V FAB `security/manager.py:1630-1637`). Zero-code logout fallback: `LOGOUT_REDIRECT_URL = "{front}/logout?client_id=...&post_logout_redirect_uri=..."` (V FAB `security/views.py:613`), accepting Keycloak's confirmation page (no `id_token_hint`). Compose env for `superset`, `worker`, `superset-mcp`: the five `KEYCLOAK_*` vars, `SUPERSET_PUBLIC_URL`, `NXTBI_PLATFORM_ADMINS`, `extra_hosts: ["host.docker.internal:host-gateway"]`.

## 7. Keycloak client representation (`nxtbi-superset`)

`__KEYCLOAK_CLIENT_SECRET__` is substituted by the script from the env var; never commit the value.

```json
{
  "clientId": "nxtbi-superset",
  "name": "NxtBI Superset Demo",
  "description": "Apache Superset (NxtBI demo). Managed by nxtbi/scripts, do not edit by hand.",
  "enabled": true, "protocol": "openid-connect",
  "publicClient": false, "clientAuthenticatorType": "client-secret", "secret": "__KEYCLOAK_CLIENT_SECRET__",
  "standardFlowEnabled": true, "implicitFlowEnabled": false, "directAccessGrantsEnabled": false,
  "serviceAccountsEnabled": false, "consentRequired": false, "frontchannelLogout": false, "fullScopeAllowed": false,
  "rootUrl": "http://localhost:8088", "baseUrl": "/",
  "redirectUris": ["http://localhost:8088/oauth-authorized/keycloak", "http://127.0.0.1:8088/oauth-authorized/keycloak"],
  "webOrigins": ["http://localhost:8088", "http://127.0.0.1:8088"],
  "attributes": {
    "pkce.code.challenge.method": "S256",
    "post.logout.redirect.uris": "http://localhost:8088/login/##http://127.0.0.1:8088/login/",
    "backchannel.logout.session.required": "true", "backchannel.logout.revoke.offline.tokens": "false"
  },
  "defaultClientScopes": ["web-origins", "acr", "roles", "profile", "basic", "email", "groups"],
  "optionalClientScopes": ["offline_access", "organization"],
  "protocolMappers": [{
    "name": "audience-nxtbi-superset", "protocol": "openid-connect", "protocolMapper": "oidc-audience-mapper",
    "config": {"included.client.audience": "nxtbi-superset", "access.token.claim": "true", "id.token.claim": "false", "introspection.token.claim": "true"}
  }]
}
```

Idempotent apply (admin token via `admin-cli` + `KC_BOOTSTRAP_ADMIN_*`, from the host at `http://127.0.0.1:8180`): `GET /admin/realms/nxtbi/clients?clientId=nxtbi-superset` -> empty: `POST /admin/realms/nxtbi/clients`; else `PUT /admin/realms/nxtbi/clients/{uuid}`; then always `PUT /admin/realms/nxtbi/clients/{uuid}/default-client-scopes/{groupsScopeId}` (id from `GET /admin/realms/nxtbi/client-scopes`) because scope lists may be ignored on update (U). kcadm: `kcadm.sh create clients -r nxtbi -f client.json` / `kcadm.sh update clients/{uuid} -r nxtbi -f client.json`. Re-run after every recreate of `ld-shared-keycloak-1` (no data volume). Never touch `nxtbi-web` or the realm import file.

## 8. Verification checklist

1. Dynamic issuer: `curl -s http://localhost:8180/realms/nxtbi/.well-known/openid-configuration | jq -r .issuer` -> `http://localhost:8180/realms/nxtbi`; `docker compose exec superset curl -s $KEYCLOAK_INTERNAL_URL/realms/nxtbi/.well-known/openid-configuration` -> `issuer` is exactly `$KEYCLOAK_INTERNAL_URL/realms/nxtbi`.
2. Authorize redirect: `curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' http://localhost:8088/login/keycloak` -> `302 http://localhost:8180/realms/nxtbi/protocol/openid-connect/auth?...client_id=nxtbi-superset&redirect_uri=http%3A%2F%2Flocalhost%3A8088%2Foauth-authorized%2Fkeycloak...&code_challenge_method=S256&nonce=...`.
3. Browser login as `planning.admin@nxtbi.local` -> welcome page; `http://localhost:8088/api/v1/me/roles/` lists `Gamma`, `sql_lab`, `nxt_org_ministry-of-planning` (V route `superset/views/users/api.py:132`).
4. `stats.editor@nxtbi.local` -> `Gamma`, `nxt_org_statistics-bureau`. `unaffiliated@nxtbi.local` -> back on `/login/` with a warning, log `OIDC login rejected`, no `ab_user` row. `http://localhost:8088/register/` is not served (expected `404`, U).
5. Role sync: a user listed in `NXTBI_PLATFORM_ADMINS` gets `Admin`; remove it, restart, log in again -> `Admin` gone.
6. RLS: the same dashboard as a planning and as a stats user shows disjoint `org_code` rows; as Admin `GET /api/v1/rowlevelsecurity/?q=(filters:!((col:tables,opr:rel_m_m,value:<dataset_id>)))` lists R1-R3.
7. Logout: click Logout; network tab shows `/logout/` -> `302 http://localhost:8180/realms/nxtbi/protocol/openid-connect/logout?client_id=nxtbi-superset&post_logout_redirect_uri=http%3A%2F%2Flocalhost%3A8088%2Flogin%2F&id_token_hint=...` -> `302 http://localhost:8088/login/`, no confirmation page. `http://localhost:8088/login/keycloak` then shows the Keycloak credential form again; NxtDash in the same browser is signed out too (expected single logout). Session cookie is `HttpOnly`, `SameSite=Lax`, well under 4 KB.
8. Service API: `curl -s -X POST http://localhost:8088/api/v1/security/login -H 'Content-Type: application/json' -d "{\"username\":\"$SVC_USER\",\"password\":\"$SVC_PASSWORD\",\"provider\":\"db\",\"refresh\":true}"` -> `access_token`; `curl -s -c jar -H "Authorization: Bearer $T" http://localhost:8088/api/v1/security/csrf_token/` -> `result`; mutate with `-b jar -H "X-CSRFToken: $CSRF" -H "Authorization: Bearer $T"`.
9. Negative: the same login call with `admin` / `admin` returns `401`; a Keycloak access token as `Authorization: Bearer` on `/api/v1/me/` returns `401`; a tampered `state` on the callback returns to `/login/`.

## 9. Production deltas and future work

- Keycloak: fixed `KC_HOSTNAME=https://...` (dynamic hostname makes the issuer spoofable through `Host`), no `start-dev`, persistent DB, client in realm-as-code, secret rotation; `sslRequired` then requires https redirect and post-logout URIs.
- Superset: https; `SESSION_COOKIE_SECURE=True`; `TALISMAN_CONFIG` with `force_https` and `session_cookie_secure` True (V defaults False, `config.py:3195-3196`); `ENABLE_PROXY_FIX=True` behind a proxy (D `oauth.mdx:101-105`); `SESSION_SERVER_SIDE=True` + Redis and an 8 h lifetime (D `securing_superset.mdx:59-88`); `SECRET_KEY` and `GUEST_TOKEN_JWT_SECRET` from a secret store; platform admins from a dedicated Keycloak group; local break-glass account with a rotated password.
- Future, document only: Keycloak organizations/workspaces mirrored as FAB groups + `ENABLE_VIEWERS`; issuer-aware `MCP_USER_RESOLVER`; Keycloak bearer on REST via a custom `request_loader`; Cube / Wren / Schema-Sense / NxtBI semantic layer consuming the same org claims.
