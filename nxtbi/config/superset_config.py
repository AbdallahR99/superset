"""NxtBI Superset demo configuration.

Loaded as the ``superset_config`` module (mounted at /app/pythonpath). It only uses
documented configuration hooks: no upstream file is modified.

Sections
    1. Core, metadata database, Redis, Celery
    2. Feature flags (stable ones on; experimental ones opt-in via NXTBI_EXPERIMENTAL_FLAGS)
    3. Keycloak OIDC login, group -> role mapping, RP-initiated logout
    4. Branding, theme, languages
    5. Alerts & reports, thumbnails, embedding
    6. MCP service (bearer-token authentication)
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta
from urllib.parse import quote_plus, urlencode

from flask import jsonify, redirect, request, session
from flask_appbuilder import expose
from flask_appbuilder.security.manager import AUTH_OAUTH
from flask_appbuilder.security.views import AuthOAuthView
from flask_caching.backends.rediscache import RedisCache
from redis import Redis

from superset.config import CeleryConfig as _CoreCeleryConfig
from superset.security import SupersetSecurityManager
from superset.tasks.types import FixedExecutor

_log = logging.getLogger("nxtbi.config")


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise RuntimeError(f"NxtBI Superset: environment variable {name} is required")
    if value == "__GENERATE__":
        raise RuntimeError(
            f"NxtBI Superset: {name} still holds the template placeholder. "
            "Create nxtbi/.env with `python nxtbi/scripts/gen_env.py` instead of copying .env.example."
        )
    return value


def _flag(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


# =====================================================================================
# 1. Core, metadata database, Redis, Celery
# =====================================================================================
SECRET_KEY = _env("SUPERSET_SECRET_KEY")
SUPERSET_PUBLIC_URL = os.environ.get("SUPERSET_PUBLIC_URL", "http://localhost:8088").rstrip("/")

_DB_HOST = os.environ.get("DATABASE_HOST", "db")
_DB_PORT = os.environ.get("DATABASE_PORT", "5432")
SQLALCHEMY_DATABASE_URI = (
    f"postgresql+psycopg2://{_env('POSTGRES_USER')}:{quote_plus(_env('POSTGRES_PASSWORD'))}"
    f"@{_DB_HOST}:{_DB_PORT}/{_env('POSTGRES_DB')}"
)
SQLALCHEMY_EXAMPLES_URI = (
    f"postgresql+psycopg2://examples:{quote_plus(_env('EXAMPLES_PASSWORD'))}@{_DB_HOST}:{_DB_PORT}/examples"
)
# Read-only connection used by the "NxtBI Demo" database entry (consumed by the bootstrap).
NXTBI_DEMO_SQLALCHEMY_URI = (
    f"postgresql+psycopg2://nxtbi_ro:{quote_plus(_env('NXTBI_DEMO_RO_PASSWORD'))}@{_DB_HOST}:{_DB_PORT}/nxtbi_demo"
)

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
# Redis database layout: 0 broker, 1 celery results, 2 caches, 3 SQL Lab results,
# 4 web sessions, 5 rate limiting.
_REDIS = f"redis://{REDIS_HOST}:{REDIS_PORT}"


def _redis_cache(prefix: str, timeout: int) -> dict[str, object]:
    return {
        "CACHE_TYPE": "RedisCache",
        "CACHE_DEFAULT_TIMEOUT": timeout,
        "CACHE_KEY_PREFIX": prefix,
        "CACHE_REDIS_HOST": REDIS_HOST,
        "CACHE_REDIS_PORT": REDIS_PORT,
        "CACHE_REDIS_DB": 2,
    }


CACHE_CONFIG = _redis_cache("nxtbi_meta_", 300)
DATA_CACHE_CONFIG = _redis_cache("nxtbi_data_", int(timedelta(hours=1).total_seconds()))
THUMBNAIL_CACHE_CONFIG = _redis_cache("nxtbi_thumb_", int(timedelta(days=7).total_seconds()))
# FILTER_STATE_CACHE_CONFIG / EXPLORE_FORM_DATA_CACHE_CONFIG keep the metastore default.
RESULTS_BACKEND = RedisCache(host=REDIS_HOST, port=REDIS_PORT, db=3, key_prefix="nxtbi_results_")
RATELIMIT_STORAGE_URI = f"{_REDIS}/5"


class CeleryConfig(_CoreCeleryConfig):
    """Core task imports and beat schedule, with Redis instead of the sqlite defaults."""

    broker_url = f"{_REDIS}/0"
    result_backend = f"{_REDIS}/1"
    broker_connection_retry_on_startup = True


CELERY_CONFIG = CeleryConfig

SUPERSET_WEBSERVER_TIMEOUT = 120
SQLLAB_TIMEOUT = 120
SQLLAB_ASYNC_TIME_LIMIT_SEC = int(timedelta(minutes=10).total_seconds())
ROW_LIMIT = 10000
FAB_API_SWAGGER_UI = True  # /swagger/v1 and /api/v1/_openapi

# =====================================================================================
# 2. Feature flags
# =====================================================================================
FEATURE_FLAGS: dict[str, bool] = {
    # stable
    "ENABLE_TEMPLATE_PROCESSING": True,  # Jinja in SQL Lab, virtual datasets and RLS clauses
    "EMBEDDED_SUPERSET": True,           # embedded SDK + guest tokens
    "THUMBNAILS": True,                  # dashboard/chart thumbnails (Playwright in the worker)
    # testing (beta) - enabled on purpose and called out in the docs
    "ALERT_REPORTS": True,
    "RLS_IN_SQLLAB": True,               # tenant isolation also for ad-hoc SQL
}
# development-lifecycle flags are opt-in: NXTBI_EXPERIMENTAL_FLAGS=SEMANTIC_LAYERS,DATASET_FOLDERS
for _name in filter(None, (f.strip() for f in os.environ.get("NXTBI_EXPERIMENTAL_FLAGS", "").split(","))):
    FEATURE_FLAGS[_name] = True
if FEATURE_FLAGS.get("FAB_API_KEY_ENABLED"):
    FAB_API_KEY_ENABLED = True

if os.environ.get("NXTBI_COPILOT_ENABLED") == "true":
    FEATURE_FLAGS.update(
        {"NXTBI_AI_COPILOT": True, "DASHBOARD_V2": True, "ENABLE_EXTENSIONS": True}
    )
    NXTBI_COPILOT_AGENT_URL = _env("NXTBI_COPILOT_AGENT_URL")
    NXTBI_COPILOT_MCP_URL = _env("NXTBI_COPILOT_MCP_URL")
    NXTBI_COPILOT_SHARED_SECRET = _env("NXTBI_COPILOT_SHARED_SECRET")
    LOCAL_EXTENSIONS = [_env("NXTBI_COPILOT_LOCAL_EXTENSION")]

# =====================================================================================
# 3. Keycloak OIDC login, group -> role mapping, RP-initiated logout
# =====================================================================================
# Keycloak runs with a dynamic hostname: the URLs it emits follow the Host header of the
# request. The browser and the container reach it under different names, so the endpoints
# are split explicitly instead of using discovery:
#   browser hops (authorize, logout)  -> KEYCLOAK_BROWSER_URL
#   back channel (token, jwks)        -> KEYCLOAK_INTERNAL_URL
# Verified against this Keycloak 26.4: the "iss" of issued tokens is fixed when the browser
# starts the login, so it is the BROWSER url even when the code is exchanged over the back
# channel. For the same reason userinfo answers 401 on the back-channel host; identity is
# therefore read from the signature-checked id_token only.
KEYCLOAK_BROWSER_URL = os.environ.get("KEYCLOAK_BROWSER_URL", "http://localhost:8180").rstrip("/")
KEYCLOAK_INTERNAL_URL = os.environ.get("KEYCLOAK_INTERNAL_URL", "http://host.docker.internal:8180").rstrip("/")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "nxtbi")
KEYCLOAK_CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "nxtbi-superset")
_KC_PROVIDER = "keycloak"  # callback path: /oauth-authorized/keycloak
_KC_FRONT = f"{KEYCLOAK_BROWSER_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect"
_KC_ISSUER = f"{KEYCLOAK_BROWSER_URL}/realms/{KEYCLOAK_REALM}"
_KC_BACK = f"{KEYCLOAK_INTERNAL_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect"
# "openid groups" works on every NxtBI realm variant. The stub realm that is live on the
# shared dev Keycloak has no profile/email scopes (asking for them is an invalid_scope
# error); keycloak_setup.py adds client-level mappers so the id_token still carries
# preferred_username, email, given_name and family_name.
_KC_SCOPE = os.environ.get("KEYCLOAK_SCOPE", "openid groups")
_ID_TOKEN_KEY = "nxtbi_id_token"
_POST_LOGOUT_URL = f"{SUPERSET_PUBLIC_URL}/login/"  # must be listed in the client's post-logout URIs

_SERVICE_USER = os.environ.get("SUPERSET_SERVICE_USERNAME", "nxtbi-service")

AUTH_TYPE = AUTH_OAUTH
AUTH_USER_REGISTRATION = False   # no public /register/ form; users are provisioned at first SSO login
AUTH_ROLES_SYNC_AT_LOGIN = True  # Keycloak groups are the source of truth on every login
# FAB refuses POST /api/v1/security/login with provider "db" when AUTH_TYPE is OAuth unless
# this is set. Only the local service account has a password, so this opens exactly one
# machine identity for REST automation; browsers still get Keycloak only.
AUTH_API_LOGIN_ALLOW_MULTIPLE_PROVIDERS = True
OAUTH_PROVIDERS = [
    {
        "name": _KC_PROVIDER,
        "icon": "fa-key",
        "token_key": "access_token",
        "remote_app": {
            "client_id": KEYCLOAK_CLIENT_ID,
            "client_secret": _env("KEYCLOAK_CLIENT_SECRET"),
            "authorize_url": f"{_KC_FRONT}/auth",
            "access_token_url": f"{_KC_BACK}/token",
            "api_base_url": f"{_KC_BACK}/",
            # The next three entries become Authlib server metadata (id_token validation).
            "jwks_uri": f"{_KC_BACK}/certs",
            "issuer": _KC_ISSUER,
            "id_token_signing_alg_values_supported": ["RS256"],
            "client_kwargs": {
                "scope": _KC_SCOPE,
                "code_challenge_method": "S256",
                "default_timeout": 10,
            },
        },
    }
]

NXTBI_ORGS = [o.strip() for o in os.environ.get("NXTBI_ORGS", "ministry-of-planning,statistics-bureau").split(",") if o.strip()]
_PLATFORM_ADMINS = {u.strip().lower() for u in os.environ.get("NXTBI_PLATFORM_ADMINS", "").split(",") if u.strip()}
_ADMIN_KEY = "nxtbi:platform-admin"
# Neither Alpha nor Admin for organisation users: both see every tenant's data.
_CAPABILITY = {"admin": ["Gamma", "sql_lab"], "editor": ["Gamma"], "viewer": ["Gamma"]}


def nxtbi_org_role(org: str) -> str:
    """Name of the Superset role that carries one organisation's data access."""
    return f"nxt_org_{org}"


AUTH_ROLES_MAPPING: dict[str, list[str]] = {_ADMIN_KEY: ["Admin"]}
for _org in NXTBI_ORGS:
    for _level, _roles in _CAPABILITY.items():
        # nxt_org_* roles are created by the bootstrap. Workspace groups
        # (/nxt/<org>/<workspace>/<level>) are deliberately NOT mapped: the demo has no
        # workspace-scoped data, and mapping them to the organisation role would widen access.
        AUTH_ROLES_MAPPING[f"/nxt/{_org}/{_level}"] = [*_roles, nxtbi_org_role(_org)]


class NxtbiOAuthView(AuthOAuthView):
    """Adds OIDC RP-initiated logout: ending the Superset session also ends the Keycloak one."""

    @expose("/logout/", methods=["GET", "POST"])
    def logout(self):  # type: ignore[no-untyped-def]
        id_token = session.get(_ID_TOKEN_KEY)
        super().logout()  # flask_login.logout_user() + audit hook
        session.clear()
        params = {"client_id": KEYCLOAK_CLIENT_ID, "post_logout_redirect_uri": _POST_LOGOUT_URL}
        if id_token:
            params["id_token_hint"] = id_token  # skips Keycloak's confirmation page
        return redirect(f"{_KC_FRONT}/logout?{urlencode(params)}")


class NxtbiSecurityManager(SupersetSecurityManager):
    """Keycloak groups -> Superset roles, deny-by-default, just-in-time user provisioning."""

    authoauthview = NxtbiOAuthView

    def set_oauth_session(self, provider, oauth_response):  # type: ignore[no-untyped-def]
        # FAB's default stores the access token in the session; it is never read again.
        session["oauth_provider"] = provider
        session[_ID_TOKEN_KEY] = oauth_response.get("id_token")

    def oauth_user_info(self, provider, response=None):  # type: ignore[no-untyped-def]
        if provider != _KC_PROVIDER:
            return self.get_oauth_user_info(provider, response)
        # id_token claims, already verified by Authlib (signature, iss, aud, exp, nonce).
        # Keycloak omits "groups" entirely for a user without groups: that means none.
        claims = dict((response or {}).get("userinfo") or {})
        username = (claims.get("preferred_username") or "").strip()
        groups = sorted(g for g in claims.get("groups") or [] if isinstance(g, str))
        role_keys = [g for g in groups if g.startswith("/nxt/") and g in AUTH_ROLES_MAPPING]
        if username.lower() == _SERVICE_USER.lower():
            # The local machine account must never be reachable through SSO.
            _log.warning("OIDC login rejected: %s is reserved for the local service account", username)
            username, role_keys = "", []
        elif username.lower() in _PLATFORM_ADMINS:
            role_keys.append(_ADMIN_KEY)
        _log.info("OIDC login user=%s groups=%s mapped=%s", username, groups, role_keys)
        return {
            "username": username,
            "email": claims.get("email", ""),
            "first_name": claims.get("given_name", ""),
            "last_name": claims.get("family_name", ""),
            "role_keys": role_keys,
            "groups": groups,
        }

    def auth_user_oauth(self, userinfo):  # type: ignore[no-untyped-def]
        username = userinfo.get("username")
        if not username or not userinfo.get("role_keys"):
            _log.warning("OIDC login rejected, no mapped NxtBI group: user=%s", username)
            session.pop(_ID_TOKEN_KEY, None)
            existing = self.find_user(username=username) if username else None
            if existing is not None and username.lower() != _SERVICE_USER.lower():
                # The user had access before and lost every NxtBI group: drop the roles
                # and end the sessions that are still open in other browsers.
                from superset.security.session_invalidation import invalidate_sessions_for_user

                existing.roles = []
                self.session.commit()
                invalidate_sessions_for_user(existing.id)
                _log.warning("OIDC: revoked roles and sessions of %s", username)
            return None  # FAB flashes "Invalid login" and returns to /login/
        if not self.find_user(username=username):
            created = self.add_user(
                username=username,
                first_name=userinfo.get("first_name") or username.split("@")[0],
                last_name=userinfo.get("last_name") or "-",
                email=userinfo.get("email") or f"{username}@email.notfound",
                role=self._oauth_calculate_user_roles(userinfo),
            )
            if not created:
                return None
        return super().auth_user_oauth(userinfo)  # role sync + login stats + on_user_login


CUSTOM_SECURITY_MANAGER = NxtbiSecurityManager

# Session posture for local http. For https set SESSION_COOKIE_SECURE=True, ENABLE_PROXY_FIX=True
# behind a proxy and a Talisman config with force_https.
SESSION_COOKIE_SAMESITE = "Lax"  # the OAuth callback is a top-level GET
SESSION_COOKIE_SECURE = False
SESSION_COOKIE_NAME = "nxtbi_superset_session"  # cookies on localhost are shared across ports
# Absolute lifetime (not sliding): group changes in Keycloak take effect at the next login,
# so a session must not be kept alive forever just by being used.
PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
SESSION_REFRESH_EACH_REQUEST = False
# Server-side sessions keep the id_token out of the browser cookie and avoid the cookie
# race that caused intermittent "mismatching_state" errors (apache/superset#45587).
SESSION_SERVER_SIDE = True
SESSION_TYPE = "redis"
SESSION_REDIS = Redis(host=REDIS_HOST, port=REDIS_PORT, db=4)
SESSION_KEY_PREFIX = "nxtbi_session:"



def FLASK_APP_MUTATOR(app):  # type: ignore[no-untyped-def]
    """Request guard for a row-level-security bypass found while testing this build.

    With RLS_IN_SQLLAB on, POST /api/v1/sqllab/execute/ with an empty-string catalog runs
    the query WITHOUT the caller's RLS predicates (the access check falls back to the
    default catalog, the RLS rewrite does not). Reproduced over HTTP on fork commit
    f3f3d10d5c as a tenant user. Until that is fixed upstream, an empty catalog is refused.
    """

    @app.before_request
    def _nxtbi_reject_blank_sqllab_catalog():  # type: ignore[no-untyped-def]
        if request.method == "POST" and request.path.startswith("/api/v1/sqllab/"):
            body = request.get_json(silent=True)
            if isinstance(body, dict) and isinstance(body.get("catalog"), str) and not body["catalog"].strip():
                return jsonify(message="catalog must be omitted or name an existing catalog"), 400
        return None


# =====================================================================================
# 4. Branding, theme, languages
# =====================================================================================
APP_NAME = "NxtBI"
FAVICONS = [{"href": "/static/nxtbi/nxtbi-favicon.svg", "type": "image/svg+xml"}]
_NXT_FONT = "'IBM Plex Sans Arabic', 'Noto Sans Arabic', Inter, 'Segoe UI', Helvetica, Arial, sans-serif"
_NXT_BRAND = {
    "brandAppName": "NxtBI",
    "brandLogoAlt": "NxtBI",
    "brandLogoHref": "/",
    "brandLogoHeight": "28px",
    "brandLogoMargin": "14px 0",
    # Loaded by the browser from Google Fonts (already on Superset's CSP allow-list).
    "fontUrls": [
        "https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@300;400;500;600;700&display=swap"
    ],
    "fontFamily": _NXT_FONT,
    "colorInfo": "#2563A8",
    "colorSuccess": "#1E9E6A",
    "colorWarning": "#D9911A",
    "colorError": "#D4374A",
    "borderRadius": 6,
}
THEME_DEFAULT = {
    "algorithm": "default",
    "token": {
        **_NXT_BRAND,
        "brandLogoUrl": "/static/nxtbi/nxtbi-logo.svg",
        "colorPrimary": "#0F766E",
        "colorLink": "#0F766E",
        "colorTextBase": "#0F2A43",
        "colorEditorSelection": "#CDEDEA",
    },
}
THEME_DARK = {
    "algorithm": "dark",
    "token": {
        **_NXT_BRAND,
        "brandLogoUrl": "/static/nxtbi/nxtbi-logo-dark.svg",
        "colorPrimary": "#2DD4BF",
        "colorLink": "#2DD4BF",
        "colorBgBase": "#0B1F33",
        "colorEditorSelection": "#1D4E63",
    },
}
THEME_DEFAULT_MODE = "default"
# A theme saved in the UI as "system default" would silently override the two above.
ENABLE_UI_THEME_ADMINISTRATION = _flag("NXTBI_UI_THEME_ADMIN", False)

EXTRA_CATEGORICAL_COLOR_SCHEMES = [
    {
        "id": "nxtbiColors",
        "description": "NxtBI categorical palette",
        "label": "NxtBI",
        "isDefault": True,
        "colors": [
            "#0F766E", "#2563A8", "#D9911A", "#7C4DBB", "#D4374A",
            "#14B8A6", "#5B9BD5", "#E7B755", "#A98BD9", "#F08A8F",
            "#0F2A43", "#64748B",
        ],
    }
]

# The image is built with BUILD_TRANSLATIONS=true, so the Arabic language pack exists.
# Layout stays left-to-right: Superset has no RTL support (see nxtbi/docs/I18N-RTL.md).
LANGUAGES = {
    "en": {"flag": "us", "name": "English"},
    "ar": {"flag": "sa", "name": "العربية"},
}
BABEL_DEFAULT_LOCALE = "en"

# =====================================================================================
# 5. Alerts & reports, thumbnails, embedding
# =====================================================================================
WEBDRIVER_BASEURL = os.environ.get("WEBDRIVER_BASEURL", "http://superset:8088/")
WEBDRIVER_BASEURL_USER_FRIENDLY = f"{SUPERSET_PUBLIC_URL}/"
ALERT_REPORTS_EXECUTORS = [FixedExecutor(_SERVICE_USER)]
# THUMBNAIL_EXECUTORS keeps the upstream default (the current user). Rendering thumbnails
# as a fixed Admin account would show every tenant the same unfiltered picture.
DASHBOARD_LAYOUT_THUMBNAILS = True
ALERT_REPORTS_NOTIFICATION_DRY_RUN = False
EMAIL_REPORTS_SUBJECT_PREFIX = "[NxtBI] "
SMTP_HOST = os.environ.get("SMTP_HOST", "host.docker.internal")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "1025"))
SMTP_STARTTLS = False
SMTP_SSL = False
SMTP_USER = ""
SMTP_PASSWORD = ""
SMTP_MAIL_FROM = os.environ.get("SMTP_MAIL_FROM", "nxtbi-superset@nxtbi.local")
EMAIL_NOTIFICATIONS = True

GUEST_TOKEN_JWT_SECRET = _env("GUEST_TOKEN_JWT_SECRET")
# GUEST_ROLE_NAME keeps the upstream default ("Public", no permissions). Give embedded
# guests a purpose-built role before embedding anything for real.
GUEST_TOKEN_JWT_EXP_SECONDS = 300

# =====================================================================================
# 6. MCP service (separate process: `superset mcp run`)
# =====================================================================================
# NXTBI_MCP_AUTH selects how MCP callers are identified:
#   local-jwt (default)  HS256 bearer tokens signed with MCP_JWT_SECRET. Mint one for any
#                        existing Superset user with `python nxtbi/scripts/mcp_token.py`;
#                        every tool call then runs with that user's roles and RLS.
#   keycloak             RS256 access tokens of the NxtBI realm (designed, not tested).
#   dev                  no authentication; every call runs as MCP_DEV_USERNAME. The
#                        port is reachable by every local process and container.
MCP_SERVICE_URL = os.environ.get("MCP_SERVICE_URL", "http://localhost:5008")
NXTBI_MCP_AUTH = os.environ.get("NXTBI_MCP_AUTH", "local-jwt").strip().lower()
if NXTBI_MCP_AUTH == "dev":
    MCP_AUTH_ENABLED = False
    MCP_DEV_USERNAME = os.environ.get("MCP_DEV_USERNAME", _SERVICE_USER)
elif NXTBI_MCP_AUTH == "keycloak":
    MCP_AUTH_ENABLED = True
    MCP_JWT_ALGORITHM = "RS256"
    MCP_JWKS_URI = f"{_KC_BACK}/certs"
    MCP_JWT_ISSUER = os.environ.get("MCP_JWT_ISSUER", _KC_ISSUER)
    MCP_JWT_AUDIENCE = os.environ.get("MCP_JWT_AUDIENCE", KEYCLOAK_CLIENT_ID)
else:
    MCP_AUTH_ENABLED = True
    MCP_JWT_ALGORITHM = "HS256"
    MCP_JWT_SECRET = _env("MCP_JWT_SECRET")
    MCP_JWT_ISSUER = "nxtbi-superset-demo"
    MCP_JWT_AUDIENCE = "nxtbi-superset-mcp"
if _flag("NXTBI_MCP_NATIVE_TOOL_LIST", True):
    # List every tool in tools/list instead of the default search_tools/call_tool proxy.
    MCP_TOOL_SEARCH_CONFIG = {
        "enabled": False,
        "strategy": "bm25",
        "max_results": 5,
        "always_visible": ["health_check", "get_instance_info"],
        "search_tool_name": "search_tools",
        "call_tool_name": "call_tool",
        "compact_schemas": True,
        "max_description_length": 300,
        "include_schemas": True,
    }
