# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""Verify portal membership, SSO and native chart data in a real browser."""

from __future__ import annotations

import re
from pathlib import Path
from time import monotonic
from typing import Any, TYPE_CHECKING
from urllib.parse import urlsplit

from playwright.sync_api import Error, expect, sync_playwright

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page, Response

WORKSPACES = {"alpha": ("North Coast", 101), "beta": ("Cedar Works", 202)}
DASHBOARD = "/dashboard/workspace-overview/"
TIMEOUT = 45_000


def _fetch_json(page: Page, url: str) -> tuple[int, dict[str, Any] | None]:
    """Check an API from its own browser origin without following redirects."""
    status, payload = page.evaluate(
        """async url => {
            if (new URL(url).origin !== location.origin) {
                throw new Error('API check requires the current page origin');
            }
            const response = await fetch(url, {
                credentials: 'same-origin',
                headers: { Accept: 'application/json' },
                redirect: 'manual',
                cache: 'no-store',
                signal: AbortSignal.timeout(5000),
            });
            if (response.status === 0 && response.type !== 'opaqueredirect') {
                throw new Error('API returned an unreadable response');
            }
            return [response.status, response.ok
                ? await response.json().catch(() => null)
                : null];
        }""",
        url,
    )
    return status, payload


def _portal_login(page: Page, portal: str, username: str, password: str) -> None:
    """Use the portal's normal Keycloak sign-in with the synthetic account."""
    page.goto(f"{portal}/")
    page.locator('a[href*="/login"]').click()
    try:
        page.locator("#username").fill(username)
        password_field = page.locator("#password")
        if not password_field.is_visible():
            page.locator("#kc-login").click()
        password_field.fill(password)
        page.locator("#kc-login").click()
        page.wait_for_url(f"{portal}/**", timeout=TIMEOUT)
    except Error:
        # A Playwright fill error can include its argument in the call log.
        raise AssertionError(f"Portal sign-in failed for {username}.") from None


def _assert_menu(page: Page, allowed: set[str]) -> None:
    """Check that only authorized workspace cards appear."""
    cards = page.locator(".workspace-card")
    expect(cards).to_have_count(len(allowed))
    for slug, (name, _) in WORKSPACES.items():
        expect(cards.filter(has_text=name)).to_have_count(int(slug in allowed))


def _keycloak_provider(page: Page) -> Locator:
    """Find the provider action on the native Superset login page."""
    keycloak = re.compile("keycloak", re.IGNORECASE)
    return (
        page.get_by_role("link", name=keycloak)
        .or_(page.get_by_role("button", name=keycloak))
        .first
    )


def _tenant_session(page: Page, base: str, username: str, slug: str) -> str:
    """Wait for native SSO and return the resulting tenant-local identity."""
    deadline = monotonic() + TIMEOUT / 1000
    provider_clicked = False
    provider = _keycloak_provider(page)
    tenant = urlsplit(base)
    while monotonic() < deadline:
        native = urlsplit(page.url)
        if (native.scheme, native.netloc) != (tenant.scheme, tenant.netloc):
            if page.locator("#username").is_visible():
                raise AssertionError(f"{slug}: native SSO asked for credentials again.")
            page.wait_for_timeout(250)
            continue
        try:
            status, identity = _fetch_json(page, f"{base}/api/v1/me/")
        except Error:
            # The native or identity-provider redirect can replace the document.
            page.wait_for_timeout(250)
            continue
        if status == 200:
            assert identity is not None, f"{slug}: invalid current-user API payload."
            user = identity["result"]
            native_username = user.get("username")
            assert isinstance(native_username, str), (
                f"{slug}: the current-user API omitted the native username."
            )
            assert re.fullmatch(r"oidc_[0-9a-f]{64}", native_username), (
                f"{slug}: native session did not use the hashed OIDC identity."
            )
            assert user.get("first_name") == username.partition("-")[0].capitalize(), (
                f"{slug}: native SSO established a different identity."
            )
            return native_username
        if (
            not provider_clicked
            and native.path.rstrip("/").endswith("/login")
            and provider.is_visible()
        ):
            provider.click()
            provider_clicked = True
        page.wait_for_timeout(250)
    raise AssertionError(f"{slug}: Superset did not establish the native SSO session.")


def _native_chart_response(response: Response, base: str) -> bool:
    """Identify the native chart data POST on the selected tenant origin."""
    actual = urlsplit(response.url)
    tenant = urlsplit(base)
    return (
        (actual.scheme, actual.netloc) == (tenant.scheme, tenant.netloc)
        and actual.path == f"{tenant.path}/api/v1/chart/data"
        and response.request.method == "POST"
    )


def _verify_dashboard(page: Page, base: str, slug: str) -> None:
    """Open the published dashboard and verify the actual native POST result."""
    with page.expect_response(
        lambda response: _native_chart_response(response, base), timeout=TIMEOUT
    ) as captured:
        page.goto(f"{base}{DASHBOARD}")
    chart = captured.value
    assert chart.ok, f"{slug}: native chart data returned HTTP {chart.status}."
    expected = WORKSPACES[slug][1]
    values = [
        row["workspace_value"]
        for result in chart.json().get("result", [])
        for row in result.get("data", [])
        if "workspace_value" in row
    ]
    assert values == [expected], f"{slug}: native chart returned an unexpected value."
    expect(page.get_by_text("Workspace overview", exact=True).first).to_be_visible()
    expect(page.get_by_text("Workspace value", exact=True).first).to_be_visible()
    expect(page.get_by_text(str(expected), exact=True).first).to_be_visible()


def _open_workspace(
    page: Page, portal: str, base: str, username: str, slug: str
) -> str:
    """Follow the portal card to a tenant's own native session and chart."""
    page.goto(f"{portal}/")
    page.locator(".workspace-card").filter(has_text=WORKSPACES[slug][0]).click()
    identity = _tenant_session(page, base, username, slug)
    _verify_dashboard(page, base, slug)
    return identity


def _verify_denial(page: Page, portal: str, base: str, slug: str) -> None:
    """Verify both portal and native denial using the same signed-in browser."""
    page.goto(f"{portal}/")
    portal_status, _ = _fetch_json(page, f"{portal}/open/{slug}")
    assert portal_status == 404, f"{slug}: portal did not deny the workspace."
    page.goto(f"{base}{DASHBOARD}")
    expect(page).to_have_url(re.compile(rf"^{re.escape(base)}/login/?(?:\?|$)"))
    callback = f"{base}/oauth-authorized/keycloak"
    with page.expect_response(
        lambda response: response.url.partition("?")[0] == callback, timeout=TIMEOUT
    ) as captured:
        _keycloak_provider(page).click()
    assert captured.value.status in {302, 303}, (
        f"{slug}: native peer SSO callback did not return a login redirect."
    )
    expect(
        page.get_by_text(re.compile(r"\binvalid login\b", re.IGNORECASE))
    ).to_be_visible()
    expect(page).to_have_url(re.compile(rf"^{re.escape(base)}/login/?(?:\?|$)"))
    identity_status, _ = _fetch_json(page, f"{base}/api/v1/me/")
    assert identity_status in {0, 401, 403, 404}, (
        f"{slug}: the outside account gained a native session (HTTP {identity_status})."
    )
    dashboard_status, _ = _fetch_json(
        page, f"{base}/api/v1/dashboard/workspace-overview"
    )
    assert dashboard_status in {0, 401, 403, 404}, (
        f"{slug}: native dashboard API did not deny access (HTTP {dashboard_status})."
    )
    expect(page.get_by_text("Workspace overview", exact=True)).to_have_count(0)


def verify_browser(
    portal_url: str,
    tenant_urls: dict[str, str],
    passwords: dict[str, str],
    artifact_dir: Path,
) -> None:
    """Exercise two single memberships and one dual membership in Chromium."""
    portal = portal_url.rstrip("/")
    bases = {slug: tenant_urls[slug].rstrip("/") for slug in WORKSPACES}
    artifact_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        channel = (
            "chromium"
            if Path(playwright.chromium.executable_path).is_file()
            else "chrome"
        )
        browser = playwright.chromium.launch(
            channel=channel, args=["--host-resolver-rules=MAP *.localhost 127.0.0.1"]
        )
        try:
            for username, allowed in (
                ("alpha-viewer", {"alpha"}),
                ("beta-viewer", {"beta"}),
                ("shared-viewer", {"alpha", "beta"}),
            ):
                with browser.new_context(
                    viewport={"width": 1280, "height": 850}
                ) as context:
                    context.set_default_timeout(TIMEOUT)
                    page = context.new_page()
                    _portal_login(page, portal, username, passwords[username])
                    _assert_menu(page, allowed)
                    if len(allowed) == 1:
                        slug = next(iter(allowed))
                        outside = "beta" if slug == "alpha" else "alpha"
                        _open_workspace(page, portal, bases[slug], username, slug)
                        _verify_denial(page, portal, bases[outside], outside)
                    else:
                        page.goto(f"{portal}/?lang=ar")
                        expect(page.locator("html")).to_have_attribute("lang", "ar")
                        expect(page.locator("html")).to_have_attribute("dir", "rtl")
                        _assert_menu(page, allowed)
                        page.screenshot(path=artifact_dir / "workspaces-rtl.png")
                        identities = set()
                        for slug in ("alpha", "beta", "alpha", "beta"):
                            identities.add(
                                _open_workspace(
                                    page, portal, bases[slug], username, slug
                                )
                            )
                        assert len(identities) == 1, (
                            "Shared OIDC identity differed across tenant cells."
                        )
                        page.screenshot(path=artifact_dir / "cedar-works.png")
        finally:
            browser.close()
    print("Browser verified memberships, shared SSO, chart values and Arabic RTL.")
