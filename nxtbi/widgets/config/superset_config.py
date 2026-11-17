# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""Configuration of the isolated Widget Framework stack (compose project "nxtbi-widgets").

Loaded as the ``superset_config`` module (mounted at /app/pythonpath). It uses documented
configuration hooks only.

Sections
    1. Core, metadata database, Redis
    2. Feature flags (DASHBOARD_V2, EMBEDDED_SUPERSET, optional ENABLE_EXTENSIONS)
    3. Authentication: database login, or the main demo's Keycloak OIDC settings
    4. Embedding: guest role, guest token validation, CORS
    5. Languages
    6. MCP service (bearer-token authentication)

Switches (environment of the containers, set in nxtbi/widgets/.env)
    NXTBI_WIDGETS_AUTH=db|keycloak        login method, see section 3
    NXTBI_WIDGETS_DASHBOARD_V2=on|off     the DASHBOARD_V2 feature flag
    NXTBI_WIDGETS_EXTENSIONS=on|off       the ENABLE_EXTENSIONS feature flag
    NXTBI_WIDGETS_CORS_ORIGINS=a,b        origins of host applications
"""

from __future__ import annotations

import importlib.util
import logging
import os
from datetime import timedelta
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import quote_plus

from flask_appbuilder.security.manager import AUTH_DB
from flask_caching.backends.rediscache import RedisCache
from redis import Redis

from superset.config import CeleryConfig as _CoreCeleryConfig
from superset.config import CORS_OPTIONS as _CORE_CORS_OPTIONS

_log = logging.getLogger("nxtbi.widgets.config")


def _env(name: str, default: str | None = None) -> str:
    """A required environment variable; the generated .env supplies all of them."""
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise RuntimeError(f"nxtbi-widgets: environment variable {name} is required")
    if value == "__GENERATE__":
        raise RuntimeError(
            f"nxtbi-widgets: {name} still holds the template placeholder. Create "
            "nxtbi/widgets/.env with `python nxtbi/widgets/scripts/gen_env.py`."
        )
    return value


def _flag(name: str, default: bool = False) -> bool:
    """An on/off environment switch."""
    value = os.environ.get(name, "on" if default else "off").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _list(name: str, default: str = "") -> list[str]:
    """A comma-separated environment variable as a list without empty entries."""
    return [
        item.strip()
        for item in os.environ.get(name, default).split(",")
        if item.strip()
    ]


# =====================================================================================
# 1. Core, metadata database, Redis
# =====================================================================================
SECRET_KEY = _env("SUPERSET_SECRET_KEY")
SUPERSET_PUBLIC_URL = os.environ.get(
    "SUPERSET_PUBLIC_URL", "http://localhost:8089"
).rstrip("/")

_DB_HOST = os.environ.get("DATABASE_HOST", "db")
_DB_PORT = os.environ.get("DATABASE_PORT", "5432")
SQLALCHEMY_DATABASE_URI = (
    f"postgresql+psycopg2://{_env('POSTGRES_USER')}:{quote_plus(_env('POSTGRES_PASSWORD'))}"
    f"@{_DB_HOST}:{_DB_PORT}/{_env('POSTGRES_DB')}"
)
SQLALCHEMY_EXAMPLES_URI = (
    f"postgresql+psycopg2://examples:{quote_plus(_env('EXAMPLES_PASSWORD'))}"
    f"@{_DB_HOST}:{_DB_PORT}/examples"
)

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
# Redis database layout: 0 broker, 1 celery results, 2 caches, 3 SQL Lab results,
# 4 web sessions, 5 rate limiting.
_REDIS = f"redis://{REDIS_HOST}:{REDIS_PORT}"


def _redis_cache(prefix: str, timeout: int) -> dict[str, object]:
    """A Flask-Caching configuration on the stack's own Redis."""
    return {
        "CACHE_TYPE": "RedisCache",
        "CACHE_DEFAULT_TIMEOUT": timeout,
        "CACHE_KEY_PREFIX": prefix,
        "CACHE_REDIS_HOST": REDIS_HOST,
        "CACHE_REDIS_PORT": REDIS_PORT,
        "CACHE_REDIS_DB": 2,
    }


CACHE_CONFIG = _redis_cache("nxtbi_widgets_meta_", 300)
# Short on purpose: the end-to-end checks compare what different principals read from
# the same dataset, and a long-lived data cache would only make failures harder to read.
DATA_CACHE_CONFIG = _redis_cache("nxtbi_widgets_data_", 60)
RESULTS_BACKEND = RedisCache(
    host=REDIS_HOST, port=REDIS_PORT, db=3, key_prefix="nxtbi_widgets_results_"
)
RATELIMIT_STORAGE_URI = f"{_REDIS}/5"


class CeleryConfig(_CoreCeleryConfig):
    """Core task imports with Redis instead of the sqlite defaults.

    The stack runs no worker; the broker only has to be a valid address.
    """

    broker_url = f"{_REDIS}/0"
    result_backend = f"{_REDIS}/1"
    broker_connection_retry_on_startup = True


CELERY_CONFIG = CeleryConfig

SUPERSET_WEBSERVER_TIMEOUT = 120
ROW_LIMIT = 10000
FAB_API_SWAGGER_UI = True  # /swagger/v1 and /api/v1/_openapi

# =====================================================================================
# 2. Feature flags
# =====================================================================================
# DASHBOARD_V2 gates every Widget Framework route: with it off, /api/v1/dashboard_v2/*,
# /api/v1/widgets/*, /api/v1/widget/* and /dashboard/v2/* answer 404 before
# authentication. The compose service "superset-flag-off" runs with the switch off.
FEATURE_FLAGS: dict[str, bool] = {
    "DASHBOARD_V2": _flag("NXTBI_WIDGETS_DASHBOARD_V2", True),
    "EMBEDDED_SUPERSET": True,  # guest tokens
    "ENABLE_EXTENSIONS": _flag("NXTBI_WIDGETS_EXTENSIONS", False),
}

# =====================================================================================
# 3. Authentication
# =====================================================================================
# NXTBI_WIDGETS_AUTH=db (default)
#     Username/password login against the metadata database. The init job creates an
#     Admin and a Gamma demo user with the passwords of nxtbi/widgets/.env, so
#     Playwright, the end-to-end script and the guest-token broker can sign in.
#
# NXTBI_WIDGETS_AUTH=keycloak
#     The Keycloak OIDC settings of the main demo (nxtbi/config/superset_config.py) are
#     imported unchanged: the same provider definition, group -> role mapping, security
#     manager and logout view. This proves the Widget Framework runs with the Keycloak
#     integration intact. The main demo's Keycloak client is not altered from here, so
#     before a browser login works on this stack someone has to add to that client:
#         redirect URI              <SUPERSET_PUBLIC_URL>/oauth-authorized/keycloak
#         post-logout redirect URI  <SUPERSET_PUBLIC_URL>/login/
#     (http://localhost:8089 by default). Until then Keycloak refuses the redirect and
#     only the API login of the local accounts works, which the main demo's settings
#     keep open through AUTH_API_LOGIN_ALLOW_MULTIPLE_PROVIDERS. The organisation roles
#     named by the group mapping (nxt_org_*) do not exist on this stack; FAB skips
#     roles it cannot find, so an organisation user arrives with the built-in roles.
NXTBI_WIDGETS_AUTH = os.environ.get("NXTBI_WIDGETS_AUTH", "db").strip().lower()

# Names the main demo configuration defines for its Keycloak login. They are copied as
# they are; nothing is recomputed here.
_KEYCLOAK_SETTINGS = (
    "AUTH_TYPE",
    "AUTH_USER_REGISTRATION",
    "AUTH_ROLES_SYNC_AT_LOGIN",
    "AUTH_API_LOGIN_ALLOW_MULTIPLE_PROVIDERS",
    "OAUTH_PROVIDERS",
    "AUTH_ROLES_MAPPING",
    "CUSTOM_SECURITY_MANAGER",
    "KEYCLOAK_BROWSER_URL",
    "KEYCLOAK_INTERNAL_URL",
    "KEYCLOAK_REALM",
    "KEYCLOAK_CLIENT_ID",
    "NXTBI_ORGS",
)
# Variables the main demo configuration requires for parts this stack does not use
# (its demo warehouse connection). They get a placeholder so the module can be loaded.
_MAIN_CONFIG_UNUSED_ENV = ("NXTBI_DEMO_RO_PASSWORD",)


def _load_main_demo_config() -> ModuleType:
    """Load the main demo's configuration module under a private name."""
    path = Path(
        os.environ.get("NXTBI_MAIN_CONFIG", "/app/nxtbi-main-config/superset_config.py")
    )
    if not path.is_file():
        raise RuntimeError(
            f"nxtbi-widgets: NXTBI_WIDGETS_AUTH=keycloak needs the main demo "
            f"configuration at {path} (mounted from nxtbi/config)"
        )
    _env("KEYCLOAK_CLIENT_SECRET")  # a clear error instead of the main module's
    for name in _MAIN_CONFIG_UNUSED_ENV:
        os.environ.setdefault(name, "unused-on-the-widgets-stack")
    spec = importlib.util.spec_from_file_location("nxtbi_main_demo_config", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"nxtbi-widgets: cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if NXTBI_WIDGETS_AUTH == "keycloak":
    _main = _load_main_demo_config()
    for _name in _KEYCLOAK_SETTINGS:
        globals()[_name] = getattr(_main, _name)
    _log.info("authentication: Keycloak OIDC settings imported from the main demo")
elif NXTBI_WIDGETS_AUTH == "db":
    AUTH_TYPE = AUTH_DB
    AUTH_USER_REGISTRATION = False
else:
    raise RuntimeError(
        f"nxtbi-widgets: NXTBI_WIDGETS_AUTH must be 'db' or 'keycloak', "
        f"not {NXTBI_WIDGETS_AUTH!r}"
    )

# Session posture for local http. Cookies on localhost are shared across ports, so the
# cookie has its own name and never collides with the main demo's session.
SESSION_COOKIE_NAME = "nxtbi_widgets_session"
# Lax: the standalone example app on http://localhost:5173 is the same site as
# http://localhost:8089, so its credentialed API calls carry the cookie. A host on
# another site cannot use the session and needs guest tokens.
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = False
PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
SESSION_SERVER_SIDE = True
SESSION_TYPE = "redis"
SESSION_REDIS = Redis(host=REDIS_HOST, port=REDIS_PORT, db=4)
SESSION_KEY_PREFIX = "nxtbi_widgets_session:"

# =====================================================================================
# 4. Embedding: guest role, guest token validation, CORS
# =====================================================================================
GUEST_TOKEN_JWT_SECRET = _env("GUEST_TOKEN_JWT_SECRET")
GUEST_TOKEN_JWT_EXP_SECONDS = 300
# A purpose-built role instead of Public or Gamma. The init job creates it and keeps
# it at exactly the permissions listed in bootstrap/widgets_bootstrap.py
# (GUEST_ROLE_PERMISSIONS): what the widget endpoints check, nothing else.
GUEST_ROLE_NAME = "WidgetGuest"


def _datasets_named_by(body: dict[str, Any]) -> set[int]:
    """Dataset ids a guest token request would let the guest read through widgets."""
    # pylint: disable=import-outside-toplevel
    from superset.daos.saved_widget import SavedWidgetDAO

    dataset_ids = {
        item
        for item in body.get("datasets") or []
        if isinstance(item, int) and not isinstance(item, bool)
    }
    for resource in body.get("resources") or []:
        kind, ref = str(resource.get("type")), str(resource.get("id"))
        if kind == "dataset" and ref.isdigit():
            # The explicit grant for inline widget definitions against one dataset.
            dataset_ids.add(int(ref))
        elif kind == "widget":
            widget = SavedWidgetDAO.find_by_uuid(ref)
            if widget is not None and widget.dataset_id is not None:
                dataset_ids.add(int(widget.dataset_id))
    return dataset_ids


def _datasets_with_rls(dataset_ids: set[int]) -> set[int]:
    """The subset of ``dataset_ids`` that has at least one row-level-security rule."""
    # pylint: disable=import-outside-toplevel
    from superset import db
    from superset.connectors.sqla.models import RowLevelSecurityFilter

    if not dataset_ids:
        return set()
    # A deployment has a handful of rules; reading them all keeps this independent of
    # how the rule-to-table association is mapped.
    rules = db.session.query(RowLevelSecurityFilter).all()
    return {
        table.id for rule in rules for table in rule.tables if table.id in dataset_ids
    }


def nxtbi_widgets_guest_token_validator(body: dict[str, Any]) -> bool:
    """Refuse a guest token that would read an RLS-protected dataset unfiltered.

    Role-based row-level security does not apply to a guest: the guest role is in no
    rule's subject list. A token for a dataset that carries RLS rules must therefore
    bring a rule of its own, either scoped to that dataset or global. Without this
    check a host could hand every visitor the rows the rules exist to separate.
    Any error fails closed.
    """
    try:
        protected = _datasets_with_rls(_datasets_named_by(body))
        if not protected:
            return True
        rules = [
            rule
            for rule in body.get("rls") or []
            if str(rule.get("clause", "")).strip()
        ]
        if any(rule.get("dataset") is None for rule in rules):
            return True
        covered = {rule.get("dataset") for rule in rules}
        missing = sorted(protected - covered)
        if missing:
            _log.warning("guest token refused: no rls rule for datasets %s", missing)
        return not missing
    except Exception:  # pylint: disable=broad-except
        _log.exception("guest token validation failed; the token is refused")
        return False


GUEST_TOKEN_VALIDATOR_HOOK = nxtbi_widgets_guest_token_validator

# CORS for host applications that render widgets (the standalone React example runs on
# http://localhost:5173). The origins and exposed headers of Superset's own default are
# repeated, because setting CORS_OPTIONS replaces that default as a whole.
#   supports_credentials  session mode sends the login cookie
#   X-GuestToken          guest mode
#   X-CSRFToken           session mode posts
#   If-Match / ETag       Dashboard V2 revision of a save and of every response
#   max_age               lets the browser reuse a preflight answer for ten minutes.
#                         Every widget data call is a POST with a JSON body and, for
#                         guests, a custom header, so without it each one costs two
#                         requests.
ENABLE_CORS = True
CORS_OPTIONS: dict[str, Any] = {
    **_CORE_CORS_OPTIONS,
    "origins": [
        *_CORE_CORS_OPTIONS.get("origins", []),
        *_list(
            "NXTBI_WIDGETS_CORS_ORIGINS", "http://localhost:5173,http://localhost:5174"
        ),
    ],
    "resources": [r"/api/*"],
    "supports_credentials": True,
    "allow_headers": ["Content-Type", "X-GuestToken", "X-CSRFToken", "If-Match"],
    "expose_headers": sorted({*_CORE_CORS_OPTIONS.get("expose_headers", []), "ETag"}),
    "max_age": 600,
}

# The application-wide rate limit counts per client address ("50 per second" by
# default, active because SUPERSET_ENV is production). A host page with a few dozen
# widgets passes that on its first load: observed with the standalone example, whose
# 27 widgets each send a preflight and a data request. Behind Docker's port mapping
# every caller also shares one address. Raised for this stack; a deployment that embeds
# widget-heavy pages has to size this limit, or key it by something better than the
# address, the same way.
RATELIMIT_APPLICATION = "400 per second"

# =====================================================================================
# 5. Languages
# =====================================================================================
# Arabic strings exist only in an image built with BUILD_TRANSLATIONS=true. Without the
# language pack the interface stays English, and the page direction still follows the
# locale (this fork's direction architecture).
LANGUAGES = {
    "en": {"flag": "us", "name": "English"},
    "ar": {"flag": "sa", "name": "العربية"},
}
BABEL_DEFAULT_LOCALE = "en"

# =====================================================================================
# 6. MCP service (separate process: `superset mcp run`, compose profile "mcp")
# =====================================================================================
# HS256 bearer tokens signed with MCP_JWT_SECRET. The end-to-end script mints one for
# the admin account; every tool call then runs with that user's roles and RLS.
MCP_SERVICE_URL = os.environ.get("MCP_SERVICE_URL", "http://localhost:5009")
MCP_AUTH_ENABLED = True
MCP_JWT_ALGORITHM = "HS256"
MCP_JWT_SECRET = _env("MCP_JWT_SECRET")
MCP_JWT_ISSUER = "nxtbi-widgets"
MCP_JWT_AUDIENCE = "nxtbi-widgets-mcp"
# List every tool in tools/list instead of the search_tools/call_tool proxy.
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
