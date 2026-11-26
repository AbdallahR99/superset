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
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Keycloak sign-in and authorized tenant navigation for the NxtBI pilot."""

from __future__ import annotations

import ipaddress
import json  # noqa: TID251 - The portal runs without a Superset runtime.
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from uuid import UUID

from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.flask_client import OAuth
from flask import (
    abort,
    current_app,
    Flask,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from joserfc.errors import JoseError
from requests.exceptions import RequestException
from werkzeug.wrappers import Response

if TYPE_CHECKING:
    from authlib.integrations.flask_client import FlaskOAuth2App

SESSION_SECONDS = 300
INVENTORY_MAX_BYTES = 64 * 1024
TENANT_LIMIT = 32
TENANT_FIELDS = {"id", "slug", "name", "base_url", "group", "state"}
TENANT_STATES = {"active", "provisioning", "suspended", "deleting"}
SLUG = re.compile(r"[a-z][a-z0-9-]{0,62}\Z")
GROUP = re.compile(r"(?:/[A-Za-z0-9][A-Za-z0-9_-]{0,62}){1,5}\Z")
HOST = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\Z")
URL_PATH = re.compile(r"(?:/[A-Za-z0-9._~-]+)*/?\Z")
REALM_PATH = re.compile(r"/realms/[A-Za-z0-9_-]+\Z")


@dataclass(frozen=True)
class Tenant:
    """A provisioned routing row from the trusted inventory."""

    id: UUID
    slug: str
    name: str
    base_url: str
    group: str
    state: str


def _required(suffix: str) -> str:
    """Read a required deployment setting without echoing its value."""
    name = f"NXTBI_SAAS_{suffix}"
    value = os.environ.get(name, "")
    if not value.strip():
        raise ValueError(f"Missing portal setting {name}")
    return value


def _host_scope(host: str) -> tuple[bool, bool]:
    """Report whether a host is valid and whether it resolves by loopback convention."""
    try:
        return True, ipaddress.ip_address(host).is_loopback
    except ValueError:
        valid = len(host) <= 253 and all(
            HOST.fullmatch(part) for part in host.split(".")
        )
        return valid, host == "localhost" or host.endswith(".localhost")


def _safe_url(value: str, *, internal: bool = False) -> str:
    """Validate an operator-defined destination, preserving an optional path prefix."""
    if not value.isascii() or any(
        char.isspace() or not char.isprintable() for char in value
    ):
        raise ValueError("Invalid portal URL")
    parts = urlsplit(value)
    if not parts.hostname or parts.username is not None or parts.password is not None:
        raise ValueError("Invalid portal URL authority")
    valid_host, loopback = _host_scope(parts.hostname)
    if not valid_host or parts.port == 0 or parts.netloc.endswith(":"):
        raise ValueError("Invalid portal URL host or port")
    if parts.scheme != "https" and not (
        parts.scheme == "http" and (loopback or internal)
    ):
        raise ValueError("Public portal URLs require HTTPS or a local loopback host")
    if (
        "?" in value
        or "#" in value
        or not URL_PATH.fullmatch(parts.path)
        or {".", ".."}.intersection(parts.path.split("/"))
    ):
        raise ValueError("Invalid portal URL path")
    return parts.geturl().rstrip("/")


def _tenant(entry: object) -> Tenant:
    """Validate one inventory row and normalize its redirect destination."""
    if not isinstance(entry, dict) or set(entry) != TENANT_FIELDS:
        raise ValueError("Invalid portal inventory record")
    if not all(isinstance(value, str) for value in entry.values()):
        raise ValueError("Portal inventory fields must be strings")
    tenant_id = UUID(entry["id"])
    slug, name, group, state = (
        entry[key] for key in ("slug", "name", "group", "state")
    )
    if (
        not SLUG.fullmatch(slug)
        or not name.strip()
        or len(name) > 120
        or len(group) > 64
        or not GROUP.fullmatch(group)
        or state not in TENANT_STATES
    ):
        raise ValueError("Invalid portal inventory record")
    return Tenant(tenant_id, slug, name, _safe_url(entry["base_url"]), group, state)


def _read_inventory(path: Path) -> tuple[Tenant, ...]:
    """Read a small, operator-owned inventory with unique routing and group keys."""
    with path.open("rb") as inventory_file:
        contents = inventory_file.read(INVENTORY_MAX_BYTES + 1)
    if len(contents) > INVENTORY_MAX_BYTES:
        raise ValueError("Portal inventory exceeds its size limit")
    values = json.loads(contents)
    if not isinstance(values, list) or len(values) > TENANT_LIMIT:
        raise ValueError("Invalid portal inventory list")
    tenants = tuple(_tenant(entry) for entry in values)
    if any(
        len(values) != len(tenants)
        for values in (
            {tenant.id for tenant in tenants},
            {tenant.slug for tenant in tenants},
            {tenant.group for tenant in tenants},
            {tenant.base_url for tenant in tenants},
        )
    ):
        raise ValueError("Portal inventory contains duplicate tenants or routes")
    return tenants


def _language(value: object) -> str:
    """Choose the requested pilot language."""
    return "ar" if value == "ar" else "en"


def _current_inventory(path: Path) -> tuple[Tenant, ...]:
    """Fail closed if the operator's routing data becomes unavailable."""
    try:
        return _read_inventory(path)
    except (OSError, ValueError, RecursionError):
        current_app.logger.warning("The tenant routing inventory could not be loaded")
        return abort(503)


def _session_groups(issuer: str) -> frozenset[str] | None:
    """Read the verified browser identity within its absolute session window."""
    if session.get("issuer") != issuer or not session.get("subject"):
        return None
    expires = session.get("expires_at")
    if not isinstance(expires, int) or expires <= time.time():
        session.clear()
        return None
    return frozenset(session.get("groups", []))


def _session_claims(
    token: Mapping[str, object], issuer: str
) -> tuple[str, int, list[str]]:
    """Read Authlib's verified ID-token claims and bound the new portal session."""
    claims = token.get("userinfo")
    if not token.get("id_token") or not isinstance(claims, Mapping):
        raise ValueError("A verified ID token is required")
    subject, expires = claims.get("sub"), claims.get("exp")
    groups = claims.get("groups", [])
    now = int(time.time())
    if (
        claims.get("iss") != issuer
        or not claims.get("nonce")
        or not isinstance(subject, str)
        or not subject
        or len(subject) > 255
        or not isinstance(expires, int)
        or expires <= now
        or not isinstance(groups, list)
        or not all(isinstance(group, str) for group in groups)
    ):
        raise ValueError("Invalid verified portal claims")
    return subject, min(expires, now + SESSION_SECONDS), groups


def create_app() -> Flask:
    """Build a portal whose routes use one pinned Keycloak client and inventory."""
    secret = _required("PORTAL_SECRET")
    if len(secret) < 32:
        raise ValueError("NXTBI_SAAS_PORTAL_SECRET must be at least 32 characters")
    inventory = Path(_required("INVENTORY"))
    _read_inventory(inventory)
    issuer = _safe_url(_required("OIDC_ISSUER"))
    backend = _safe_url(_required("OIDC_BACKEND"), internal=True)
    realm = urlsplit(issuer).path
    if not REALM_PATH.search(realm) or urlsplit(backend).path != realm:
        raise ValueError("Expected matching Keycloak realm URLs")
    public_url = _safe_url(_required("PUBLIC_URL"))
    if urlsplit(public_url).path:
        raise ValueError("NXTBI_SAAS_PUBLIC_URL must be an origin")

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=secret,
        SESSION_COOKIE_NAME="nxtbi_saas_portal",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=public_url.startswith("https://"),
        SESSION_REFRESH_EACH_REQUEST=False,
        PERMANENT_SESSION_LIFETIME=SESSION_SECONDS,
    )
    oauth = OAuth(app)
    keycloak = oauth.register(
        "keycloak",
        client_id=_required("OIDC_CLIENT_ID"),
        client_secret=_required("OIDC_CLIENT_SECRET"),
        authorize_url=f"{issuer}/protocol/openid-connect/auth",
        access_token_url=f"{backend}/protocol/openid-connect/token",
        jwks_uri=f"{backend}/protocol/openid-connect/certs",
        issuer=issuer,
        id_token_signing_alg_values_supported=["RS256"],
        client_kwargs={
            "scope": "openid",
            "code_challenge_method": "S256",
            "default_timeout": 10,
        },
    )
    _register_login_routes(app, keycloak, issuer, public_url, inventory)
    _register_tenant_views(app, issuer, inventory)
    return app


def _register_login_routes(
    app: Flask, keycloak: FlaskOAuth2App, issuer: str, public_url: str, inventory: Path
) -> None:
    """Register the browser's short-lived Keycloak sign-in flow."""

    @app.get("/login")
    def login() -> Response:
        """Start the authorization code flow with a fixed public callback URL."""
        lang = _language(request.args.get("lang"))
        session.clear()
        session.permanent = True
        session["login_lang"] = lang
        return keycloak.authorize_redirect(f"{public_url}/oidc/callback")

    @app.get("/oidc/callback")
    def callback() -> Response:
        """Verify the OIDC response and retain only the bounded identity context."""
        try:
            token = keycloak.authorize_access_token(leeway=0)
            subject, expires, groups = _session_claims(token, issuer)
        except RequestException:
            return abort(503)
        except (OAuthError, JoseError, ValueError):
            return abort(401)
        relevant = {
            tenant.group for tenant in _current_inventory(inventory)
        }.intersection(groups)
        lang = _language(session.get("login_lang"))
        session.clear()
        session.permanent = True
        session.update(
            issuer=issuer, subject=subject, groups=sorted(relevant), expires_at=expires
        )
        return redirect(url_for("index", lang=lang))


def _register_tenant_views(app: Flask, issuer: str, inventory: Path) -> None:
    """Register readiness and browser navigation under the same inventory policy."""

    def visible_tenants(groups: frozenset[str]) -> tuple[Tenant, ...]:
        """Apply the same membership and state rule to discovery and direct links."""
        return tuple(
            tenant
            for tenant in _current_inventory(inventory)
            if tenant.state == "active" and tenant.group in groups
        )

    @app.after_request
    def private_pages(response: Response) -> Response:
        """Keep identity-bearing pages and redirects out of caches."""
        if request.endpoint != "static":
            response.cache_control.no_store = True
            response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/health")
    def health() -> dict[str, str]:
        """Report readiness after validating the current local inventory."""
        _current_inventory(inventory)
        return {"status": "ok"}

    @app.get("/")
    def index() -> str:
        """Display only active workspaces for this browser identity."""
        groups = _session_groups(issuer)
        lang = _language(request.args.get("lang"))
        tenants = visible_tenants(groups) if groups is not None else ()
        return render_template(
            "index.html",
            lang=lang,
            direction="rtl" if lang == "ar" else "ltr",
            signed_in=groups is not None,
            tenants=[{"slug": tenant.slug, "name": tenant.name} for tenant in tenants],
            login_url=url_for("login", lang=lang),
        )

    @app.get("/open/<slug>")
    def open_tenant(slug: str) -> Response:
        """Open the dashboard list after reevaluating workspace access."""
        if (groups := _session_groups(issuer)) is None:
            return redirect(url_for("login"))
        if tenant := next(
            (item for item in visible_tenants(groups) if item.slug == slug), None
        ):
            return redirect(f"{tenant.base_url}/dashboard/list/")
        return abort(404)
