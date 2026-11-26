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
"""Superset policy for one viewer-only SaaS pilot tenant."""

from __future__ import annotations

import hashlib
import os
import re
from datetime import timedelta
from time import time
from typing import Any, cast
from urllib.parse import urlsplit

from flask import Flask, session
from flask_appbuilder.const import AUTH_OAUTH
from flask_appbuilder.security.sqla.models import User
from flask_login import logout_user
from redis import Redis

from superset.commands.database.exceptions import DatabaseInvalidError
from superset.config import CeleryConfig as SupersetCeleryConfig
from superset.databases.utils import make_url_safe
from superset.security import SupersetSecurityManager
from superset.security.session_invalidation import (
    invalidate_sessions_for_user,
    SESSION_LOGIN_AT_KEY,
)


def required(name: str) -> str:
    """Read a required setting without including its value in errors."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing {name}")
    return value


def postgres_uri(name: str, database: str, users: set[str]) -> str:
    """Keep each connection on its configured database and purpose-built role."""
    value = required(name)
    try:
        url = make_url_safe(value)
    except DatabaseInvalidError:
        raise RuntimeError(f"{name} must be a valid PostgreSQL URI") from None
    if (
        url.get_backend_name() != "postgresql"
        or url.database != database
        or url.username not in users
    ):
        raise RuntimeError(f"{name} requires a PostgreSQL {database} role")
    return value


def public_origin(name: str) -> str:
    """Allow only an HTTPS origin or plain HTTP on a local test host."""
    parsed = urlsplit(required(name))
    if not (
        parsed.hostname
        and not parsed.username
        and not parsed.password
        and parsed.path in ("", "/")
        and not parsed.query
        and not parsed.fragment
        and (
            parsed.scheme == "https"
            or (parsed.scheme == "http" and parsed.hostname.endswith(".localhost"))
        )
    ):
        raise RuntimeError(f"{name} must be HTTPS or a local .localhost origin")
    return parsed.geturl().rstrip("/")


NXTBI_SAAS_TENANT_SLUG = required("NXTBI_SAAS_TENANT_SLUG")
if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", NXTBI_SAAS_TENANT_SLUG):
    raise RuntimeError("Invalid NXTBI_SAAS_TENANT_SLUG")
NXTBI_SAAS_TENANT_GROUP = required("NXTBI_SAAS_TENANT_GROUP")
NXTBI_SAAS_VIEWER_ROLE = "NxtbiTenantViewer"

SECRET_KEY = required("NXTBI_SAAS_TENANT_SECRET")
if len(SECRET_KEY) < 32:
    raise RuntimeError("NXTBI_SAAS_TENANT_SECRET must have at least 32 characters")

SQLALCHEMY_DATABASE_URI = postgres_uri(
    "NXTBI_SAAS_METADATA_URI", "nxtbi_metadata", {"nxtbi_migrator", "nxtbi_runtime"}
)
NXTBI_SAAS_WAREHOUSE_URI = postgres_uri(
    "NXTBI_SAAS_WAREHOUSE_URI", "nxtbi_warehouse", {"nxtbi_reader"}
)
REDIS_URL = required("NXTBI_SAAS_REDIS_URL")
CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_REDIS_URL": REDIS_URL,
    "CACHE_DEFAULT_TIMEOUT": 300,
    "CACHE_KEY_PREFIX": f"{NXTBI_SAAS_TENANT_SLUG}:metadata:",
}
DATA_CACHE_CONFIG = {
    **CACHE_CONFIG,
    "CACHE_KEY_PREFIX": f"{NXTBI_SAAS_TENANT_SLUG}:data:",
}
RATELIMIT_STORAGE_URI = REDIS_URL


class TenantCeleryConfig(SupersetCeleryConfig):
    """Keep queued work and its results on the tenant's Redis service."""

    broker_url = REDIS_URL
    result_backend = REDIS_URL


CELERY_CONFIG = TenantCeleryConfig
SESSION_SERVER_SIDE = True
SESSION_TYPE = "redis"
SESSION_REDIS = Redis.from_url(REDIS_URL)
SESSION_KEY_PREFIX = f"{NXTBI_SAAS_TENANT_SLUG}:session:"
SESSION_COOKIE_NAME = f"nxtbi_{NXTBI_SAAS_TENANT_SLUG}_session"
SESSION_COOKIE_DOMAIN = None
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_HTTPONLY = True
SESSION_PERMANENT = True
SESSION_REFRESH_EACH_REQUEST = False
PERMANENT_SESSION_LIFETIME = timedelta(minutes=5)
SESSION_COOKIE_SECURE = public_origin("NXTBI_SAAS_PUBLIC_URL").startswith("https://")

APP_NAME = required("NXTBI_SAAS_TENANT_NAME")
LOGO_TARGET_PATH = public_origin("NXTBI_SAAS_PORTAL_URL")
LOGO_TOOLTIP = "Return to NxtBI workspaces"


def configure_tenant_session(app: Flask) -> None:
    """Keep the login deadline fixed even when a request updates its session."""

    @app.before_request
    def expire_tenant_session() -> None:
        """Let native routes handle a stale session as an anonymous request."""
        if "_user_id" not in session:
            return
        login_at = session.get(SESSION_LOGIN_AT_KEY)
        if (
            not isinstance(login_at, (int, float))
            or time() - login_at >= PERMANENT_SESSION_LIFETIME.total_seconds()
        ):
            logout_user()
            session.clear()


FLASK_APP_MUTATOR = configure_tenant_session


_provider = "keycloak"
_issuer = required("NXTBI_SAAS_OIDC_ISSUER").rstrip("/")
_backend = required("NXTBI_SAAS_OIDC_BACKEND").rstrip("/")
_client_id = required("NXTBI_SAAS_OIDC_CLIENT_ID")

AUTH_TYPE = AUTH_OAUTH
AUTH_USER_REGISTRATION = False
AUTH_API_LOGIN_ALLOW_MULTIPLE_PROVIDERS = False
AUTH_ROLES_SYNC_AT_LOGIN = True
AUTH_ROLES_MAPPING = {NXTBI_SAAS_TENANT_GROUP: [NXTBI_SAAS_VIEWER_ROLE]}
PUBLIC_ROLE_LIKE = None
OAUTH_AUTO_REDIRECT_SINGLE_PROVIDER = False
OAUTH_PROVIDERS = [
    {
        "name": _provider,
        "icon": "fa-key",
        "token_key": "access_token",
        "remote_app": {
            "client_id": _client_id,
            "client_secret": required("NXTBI_SAAS_OIDC_CLIENT_SECRET"),
            "authorize_url": f"{_issuer}/protocol/openid-connect/auth",
            "access_token_url": f"{_backend}/protocol/openid-connect/token",
            "jwks_uri": f"{_backend}/protocol/openid-connect/certs",
            "issuer": _issuer,
            "id_token_signing_alg_values_supported": ["RS256"],
            "client_kwargs": {
                "scope": "openid",
                "code_challenge_method": "S256",
                "default_timeout": 10,
            },
        },
    }
]


class TenantSecurityManager(SupersetSecurityManager):
    """Admit only identities holding this tenant's exact verified group."""

    def set_oauth_session(self, provider: str, oauth_response: dict[str, Any]) -> None:
        """Record the provider without retaining OAuth credentials in the session."""
        session["oauth_provider"] = provider

    def oauth_user_info(
        self, provider: str, response: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Use Authlib's verified ID token claims as the identity source."""
        claims = (response or {}).get("userinfo")
        if provider != _provider or not claims or claims.get("iss") != _issuer:
            return {}
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            return {}
        identity = hashlib.sha256(f"{_issuer}\0{subject}".encode()).hexdigest()
        groups = claims.get("groups")
        admitted = isinstance(groups, list) and NXTBI_SAAS_TENANT_GROUP in groups
        return {
            "username": f"oidc_{identity}",
            "email": f"{identity}@oidc.invalid",
            "first_name": claims.get("given_name") or "Workspace",
            "last_name": claims.get("family_name") or "Viewer",
            "role_keys": [NXTBI_SAAS_TENANT_GROUP] if admitted else [],
        }

    def auth_user_oauth(self, userinfo: dict[str, Any]) -> User | None:
        """Provision admitted viewers and drop prior sessions after a denied login."""
        username = userinfo.get("username")
        if not username:
            return None

        user = self.find_user(username=username)
        if userinfo.get("role_keys") != [NXTBI_SAAS_TENANT_GROUP]:
            if user is not None:
                user.roles = []
                self.session.commit()
                invalidate_sessions_for_user(user.id)
            return None

        role = self.find_role(NXTBI_SAAS_VIEWER_ROLE)
        if role is None:
            return None
        if user is None:
            user = self.add_user(
                username=username,
                first_name=userinfo["first_name"],
                last_name=userinfo["last_name"],
                email=userinfo["email"],
                role=[role],
            )
            if not user:
                return None
        return cast("User | None", super().auth_user_oauth(userinfo))


CUSTOM_SECURITY_MANAGER = TenantSecurityManager
FEATURE_FLAGS = {
    "ALERT_REPORTS": False,
    "DASHBOARD_V2": False,
    "EMBEDDED_SUPERSET": False,
    "ENABLE_API_KEYS": False,
    "ENABLE_EXTENSIONS": False,
    "ENABLE_TEMPLATE_PROCESSING": False,
    "GLOBAL_ASYNC_QUERIES": False,
    "NXTBI_AI_COPILOT": False,
    "THUMBNAILS": False,
}
ENABLE_CORS = False
SCARF_ANALYTICS = False
WEBSOCKET_ENABLE = False
