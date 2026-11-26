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

"""Exercise the pilot portal with a disposable, local identity fixture."""

from __future__ import annotations

import json  # noqa: TID251 - The portal runs without a Superset runtime.
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from authlib.integrations.flask_client import FlaskOAuth2App
from flask import Flask
from flask.testing import FlaskClient
from jinja2 import DictLoader

from ..portal.app import create_app  # noqa: TID252 - Keep standalone mypy paths scoped.

ISSUER = "http://identity.localhost:8180/realms/pilot"
PUBLIC_URL = "http://portal.localhost:8090"
ALPHA_GROUP = "/nxt/alpha/viewer"
BETA_GROUP = "/nxt/beta/viewer"


@pytest.fixture
def portal_inventory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Configure the portal without the test ever contacting the issuer."""
    inventory = tmp_path / "tenants.json"
    inventory.write_text(
        json.dumps(
            [
                {
                    "id": str(uuid4()),
                    "slug": "alpha",
                    "name": "North Coast",
                    "base_url": "http://alpha.localhost:18091/bi",
                    "group": ALPHA_GROUP,
                    "state": "active",
                },
                {
                    "id": str(uuid4()),
                    "slug": "beta",
                    "name": "South Coast",
                    "base_url": "https://beta.example.test",
                    "group": BETA_GROUP,
                    "state": "active",
                },
            ]
        ),
        encoding="utf-8",
    )
    for suffix, value in {
        "PORTAL_SECRET": "unit-test-secret-" * 4,
        "INVENTORY": str(inventory),
        "OIDC_ISSUER": ISSUER,
        "OIDC_BACKEND": "http://keycloak:8080/realms/pilot",
        "OIDC_CLIENT_ID": "portal-test",
        "OIDC_CLIENT_SECRET": "client-fixture-only",
        "PUBLIC_URL": PUBLIC_URL,
    }.items():
        monkeypatch.setenv(f"NXTBI_SAAS_{suffix}", value)
    return inventory


@pytest.fixture
def portal(portal_inventory: Path) -> Flask:
    """Use a minimal template to test the rendering contract independently."""
    app = create_app()
    app.testing = True
    app.jinja_loader = DictLoader(
        {
            "index.html": (
                "{{ lang }} {{ direction }} {{ signed_in }} {{ login_url }}\n"
                "{% for tenant in tenants %}{{ tenant.name }}\n{% endfor %}"
            )
        }
    )
    return app


def sign_in(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch, groups: list[str]
) -> None:
    """Return verified-claim-shaped data at the Authlib callback boundary."""
    redirect_url = client.get("/login?lang=ar").location
    assert redirect_url
    nonce = parse_qs(urlsplit(redirect_url).query)["nonce"][0]
    monkeypatch.setattr(
        FlaskOAuth2App,
        "authorize_access_token",
        lambda _app, **_kwargs: {
            "access_token": "discard-me",
            "id_token": "discard-me-too",
            "userinfo": {
                "iss": ISSUER,
                "sub": "actor-subject",
                "exp": int(time.time()) + 300,
                "nonce": nonce,
                "groups": groups,
            },
        },
    )
    callback = client.get("/oidc/callback")
    assert callback.status_code == 302
    assert callback.location == "/?lang=ar"


def test_portal_lists_only_membership_and_checks_direct_open(
    portal: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = portal.test_client()
    assert client.get("/health").status_code == 200
    assert client.get("/open/alpha").location == "/login"
    sign_in(client, monkeypatch, [ALPHA_GROUP])

    html = client.get("/?lang=ar").get_data(as_text=True)

    assert "ar rtl True" in html
    assert "North Coast" in html
    assert "South Coast" not in html
    assert client.get("/open/alpha").location == (
        "http://alpha.localhost:18091/bi/dashboard/list/"
    )
    assert client.get("/open/beta").status_code == 404
    with client.session_transaction() as stored:
        data = json.dumps(dict(stored))
        assert "actor-subject" in data
        assert "discard-me" not in data


def test_portal_checks_current_inventory_on_each_open(
    portal: Flask, portal_inventory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = portal.test_client()
    sign_in(client, monkeypatch, [ALPHA_GROUP, BETA_GROUP])
    assert client.get("/open/beta").location == (
        "https://beta.example.test/dashboard/list/"
    )
    entries = json.loads(portal_inventory.read_text(encoding="utf-8"))
    entries[1]["state"] = "suspended"
    portal_inventory.write_text(json.dumps(entries), encoding="utf-8")

    assert client.get("/open/beta").status_code == 404
    assert "South Coast" not in client.get("/").get_data(as_text=True)


def test_portal_login_pins_callback_and_requires_oidc_state(portal: Flask) -> None:
    client = portal.test_client()
    response = client.get("/login", headers={"Host": "unrelated.localhost"})
    assert response.location
    redirect = urlsplit(response.location)
    assert redirect.netloc == "identity.localhost:8180"
    query = parse_qs(redirect.query)
    assert query["redirect_uri"] == [f"{PUBLIC_URL}/oidc/callback"]
    assert query["scope"] == ["openid"]
    assert query["code_challenge_method"] == ["S256"]
    assert query.get("nonce")
    assert query.get("state")
    assert client.get("/oidc/callback?state=unknown&code=unused").status_code == 401


@pytest.mark.parametrize(
    "url",
    [
        "http://external.example.test",
        "//external.example.test",
        "https://user@external.example.test",
        "https://external.example.test/dashboard?next=bad",
        "https://external.example.test/one/../two",
        "http://bad.localhost:99999",
    ],
)
def test_portal_rejects_invalid_destination(portal_inventory: Path, url: str) -> None:
    entries = json.loads(portal_inventory.read_text(encoding="utf-8"))
    entries[0]["base_url"] = url
    portal_inventory.write_text(json.dumps(entries), encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid|HTTPS|Port out of range"):
        create_app()
