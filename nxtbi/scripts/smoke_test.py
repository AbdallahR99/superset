"""End-to-end smoke test for the NxtBI Superset demo. Runs on the host.

    python nxtbi/scripts/smoke_test.py            # all groups
    python nxtbi/scripts/smoke_test.py sso api    # selected groups: stack sso rls api mcp content reports

Needs `requests`. The reports group also needs the Mailpit API (MAILPIT_URL, default
http://localhost:8025) and is skipped when it is unreachable. Reads nxtbi/.env for the
demo credentials; never prints a secret.
Every check is executed against the running stack - nothing is assumed. Results are
written to nxtbi/out/smoke-results.json and the exit code is non-zero on any failure.
"""

from __future__ import annotations

import html
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mcp_token  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


ENV = load_env()
SUPERSET = ENV.get("SUPERSET_PUBLIC_URL", "http://localhost:8088").rstrip("/")
KEYCLOAK = ENV.get("KEYCLOAK_BROWSER_URL", "http://localhost:8180").rstrip("/")
REALM = ENV.get("KEYCLOAK_REALM", "nxtbi")
MCP = ENV.get("MCP_SERVICE_URL", "http://localhost:5008").rstrip("/")
MCP_AUTH = ENV.get("NXTBI_MCP_AUTH", "local-jwt")
PLANNING, STATS = "ministry-of-planning", "statistics-bureau"
DEMO_PW = ENV.get("NXTBI_DEMO_USER_PASSWORD", "")
USERS = {
    "planning.admin@nxtbi.local": (DEMO_PW, {"Gamma", "sql_lab", f"nxt_org_{PLANNING}"}),
    "planning.editor@nxtbi.local": (DEMO_PW, {"Gamma", f"nxt_org_{PLANNING}"}),
    "stats.admin@nxtbi.local": (DEMO_PW, {"Gamma", "sql_lab", f"nxt_org_{STATS}"}),
    "stats.editor@nxtbi.local": (DEMO_PW, {"Gamma", f"nxt_org_{STATS}"}),
    "superset.admin@nxtbi.local": (ENV.get("SUPERSET_SSO_ADMIN_PASSWORD", ""), {"Admin"}),
}
REJECTED_USER = "unaffiliated@nxtbi.local"
DASHBOARD_SLUGS = ["nxtbi-budget-execution", "nxtbi-trade-population", "nxtbi-service-operations"]

# Ad-hoc metric, so the checks do not depend on the names of saved metrics.
COUNT_STAR = {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "rows"}

RESULTS: list[dict[str, Any]] = []


class Skip(Exception):
    """A check that could not run because an optional prerequisite is absent."""


def check(group: str, name: str, fn: Callable[[], Any]) -> Any:
    started = time.time()
    try:
        detail = fn()
        status = "PASS"
    except Skip as exc:
        detail, status = str(exc), "SKIP"
    except AssertionError as exc:
        detail, status = str(exc) or "assertion failed", "FAIL"
    except Exception as exc:  # noqa: BLE001 - a smoke test reports every failure
        detail, status = f"{type(exc).__name__}: {exc}", "FAIL"
    RESULTS.append({"group": group, "check": name, "status": status,
                    "detail": detail if isinstance(detail, (str, int, float, list, dict)) else str(detail),
                    "seconds": round(time.time() - started, 2)})
    print(f"[{status}] {group:8} {name}: {str(detail)[:230]}")
    return detail if status == "PASS" else None


# ------------------------------------------------------------------ SSO helpers
class _BrowserLikeSession(requests.Session):
    """Keycloak marks its cookies Secure even on http. Browsers treat http://localhost as a
    secure context and send them back; python-requests would silently drop them, so the
    flag is cleared on every hop (including redirects)."""

    def send(self, request: Any, **kwargs: Any) -> requests.Response:
        response = super().send(request, **kwargs)
        for cookie in self.cookies:
            cookie.secure = False
        return response


def sso_login(username: str, password: str) -> tuple[requests.Session, requests.Response]:
    """Full OIDC authorization-code flow, exactly as a browser would do it."""
    s = _BrowserLikeSession()
    page = s.get(f"{SUPERSET}/login/keycloak", timeout=30)
    assert urlparse(page.url).netloc == urlparse(KEYCLOAK).netloc, f"expected Keycloak login page, got {page.url}"
    # The realm uses Keycloak's identity-first flow (username page, then password page);
    # a classic single-page form is handled by the same loop.
    for _ in range(3):
        if urlparse(page.url).netloc != urlparse(KEYCLOAK).netloc:
            break
        match = re.search(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"', page.text) or \
            re.search(r'<form[^>]*action="([^"]+)"[^>]*id="kc-form-login"', page.text)
        if not match:
            break
        fields = {"credentialId": ""}
        if 'name="username"' in page.text:
            fields["username"] = username
        if 'name="password"' in page.text:
            fields["password"] = password
        before = page.text
        page = s.post(html.unescape(match.group(1)), data=fields, timeout=30)
        if "password" in fields and urlparse(page.url).netloc == urlparse(KEYCLOAK).netloc \
                and 'name="password"' in page.text and 'name="password"' in before:
            break  # credentials rejected: Keycloak re-rendered the password form
    return s, page


def me_roles(s: requests.Session) -> set[str]:
    r = s.get(f"{SUPERSET}/api/v1/me/roles/", timeout=30)
    assert r.status_code == 200, f"/api/v1/me/roles/ -> {r.status_code}"
    return set(r.json()["result"]["roles"].keys())


def csrf(s: requests.Session) -> dict[str, str]:
    """CSRF headers for a session; fetched once per session (the endpoint is rate limited)."""
    cached = getattr(s, "_nxtbi_csrf", None)
    if cached is None:
        r = s.get(f"{SUPERSET}/api/v1/security/csrf_token/", timeout=30)
        assert r.status_code == 200, f"csrf_token -> {r.status_code}"
        cached = {"X-CSRFToken": r.json()["result"], "Referer": f"{SUPERSET}/"}
        s._nxtbi_csrf = cached  # type: ignore[attr-defined]
    return cached


def dataset_id(s: requests.Session, table: str, headers: dict[str, str] | None = None) -> int | None:
    q = f"(filters:!((col:table_name,opr:eq,value:{table})))"
    r = s.get(f"{SUPERSET}/api/v1/dataset/", params={"q": q}, headers=headers or {}, timeout=30)
    assert r.status_code == 200, f"dataset list -> {r.status_code}"
    ids = [d["id"] for d in r.json()["result"] if d["table_name"] == table and d.get("schema") == "nxtbi"]
    return ids[0] if ids else None


def orgs_visible(s: requests.Session, ds_id: int, headers: dict[str, str] | None = None) -> tuple[int, dict[str, int]]:
    body = {
        "datasource": {"id": ds_id, "type": "table"},
        "force": True,
        "queries": [{"columns": ["org_slug"], "metrics": [COUNT_STAR], "row_limit": 100}],
        "result_format": "json",
        "result_type": "full",
    }
    r = s.post(f"{SUPERSET}/api/v1/chart/data", json=body, headers=headers or {}, timeout=60)
    if r.status_code != 200:
        return r.status_code, {}
    return 200, {row["org_slug"]: row["rows"] for row in r.json()["result"][0]["data"]}


def sql(s: requests.Session, database_id: int, statement: str) -> tuple[int, Any]:
    body = {"database_id": database_id, "sql": statement, "runAsync": False, "schema": "nxtbi",
            "queryLimit": 100, "client_id": f"smoke{int(time.time() * 1000) % 10 ** 6}"}
    r = s.post(f"{SUPERSET}/api/v1/sqllab/execute/", json=body, headers=csrf(s), timeout=90)
    try:
        payload = r.json()
    except ValueError:
        payload = r.text[:200]
    return r.status_code, payload


# ------------------------------------------------------------------ groups
def group_stack() -> None:
    def health() -> str:
        r = requests.get(f"{SUPERSET}/health", timeout=10)
        assert r.status_code == 200 and r.text.strip() == "OK", f"{r.status_code} {r.text[:40]}"
        return "200 OK"

    def asset(path: str, needle: str | None = None) -> Callable[[], str]:
        def run() -> str:
            r = requests.get(f"{SUPERSET}{path}", timeout=20)
            assert r.status_code == 200, f"{path} -> {r.status_code}"
            if needle:
                assert needle in r.text, f"{needle!r} not in {path}"
            return f"200, {len(r.content)} bytes"
        return run

    def arabic_pack() -> str:
        r = requests.get(f"{SUPERSET}/language_pack/ar/", timeout=20)
        assert r.status_code == 200, f"-> {r.status_code}"
        messages = r.json()["locale_data"]["superset"]
        translated = sum(1 for k, v in messages.items() if k and isinstance(v, list) and v and v[0])
        assert translated > 1000, f"only {translated} translated entries"
        return f"{translated} translated UI strings in the Arabic pack"

    def bootstrap_branding() -> str:
        r = requests.get(f"{SUPERSET}/login/", timeout=20)
        assert r.status_code == 200
        text = html.unescape(r.text)
        for needle in ("NxtBI", "nxtbi-logo.svg", "IBM Plex Sans Arabic", "#0F766E", "nxtbiColors"):
            assert needle in text, f"{needle!r} missing from the bootstrap payload"
        arabic_name = "العربية"
        escaped = arabic_name.encode("unicode_escape").decode("ascii")  # bootstrap JSON is ASCII-escaped
        assert '"ar"' in text and (arabic_name in text or escaped in text), "Arabic missing from the language list"
        return "brand name, logo, font, primary colour, palette and ar language present in bootstrap data"

    def login_offers_keycloak_only() -> str:
        text = html.unescape(requests.get(f"{SUPERSET}/login/", timeout=20).text)
        assert '"name": "keycloak"' in text or '"name":"keycloak"' in text, "keycloak provider not offered"
        r = requests.get(f"{SUPERSET}/register/", timeout=20, allow_redirects=False)
        assert r.status_code in (302, 404), f"/register/ -> {r.status_code}"
        return f"provider keycloak offered; /register/ -> {r.status_code}"

    check("stack", "superset /health", health)
    check("stack", "mcp /health", lambda: requests.get(f"{MCP}/health", timeout=10).json())
    check("stack", "NxtBI logo served", asset("/static/nxtbi/nxtbi-logo.svg", "NxtBI"))
    check("stack", "NxtBI favicon served", asset("/static/nxtbi/nxtbi-favicon.svg"))
    check("stack", "Arabic language pack", arabic_pack)
    check("stack", "theme + language bootstrap", bootstrap_branding)
    check("stack", "login page is SSO-only", login_offers_keycloak_only)


def group_sso() -> dict[str, requests.Session]:
    sessions: dict[str, requests.Session] = {}

    def authorize_redirect() -> str:
        r = requests.get(f"{SUPERSET}/login/keycloak", allow_redirects=False, timeout=20)
        assert r.status_code == 302, f"-> {r.status_code}"
        url = urlparse(r.headers["Location"])
        q = parse_qs(url.query)
        assert f"{url.scheme}://{url.netloc}" == KEYCLOAK, f"authorize host {url.netloc}"
        assert q["client_id"] == [ENV.get("KEYCLOAK_CLIENT_ID", "nxtbi-superset")]
        assert q["redirect_uri"] == [f"{SUPERSET}/oauth-authorized/keycloak"], q["redirect_uri"]
        assert q["code_challenge_method"] == ["S256"] and q.get("nonce") and q.get("state")
        assert "groups" in q["scope"][0].split()
        return f"302 to {url.netloc}{url.path} with PKCE S256, nonce, state, scope={q['scope'][0]!r}"

    check("sso", "authorize redirect (PKCE, scopes)", authorize_redirect)

    for username, (password, expected) in USERS.items():
        def login(username: str = username, password: str = password, expected: set[str] = expected) -> str:
            assert password, "no password available in nxtbi/.env for this user"
            s, final = sso_login(username, password)
            assert final.url.startswith(SUPERSET), f"did not return to Superset: {final.url[:80]}"
            me = s.get(f"{SUPERSET}/api/v1/me/", timeout=30)
            assert me.status_code == 200, f"/api/v1/me/ -> {me.status_code}"
            assert me.json()["result"]["username"] == username
            roles = me_roles(s)
            assert roles == expected, f"roles {sorted(roles)} != expected {sorted(expected)}"
            sessions[username] = s
            return f"logged in via Keycloak; roles = {sorted(roles)}"
        check("sso", f"login + role mapping: {username}", login)

    def rejected() -> str:
        assert DEMO_PW, "no demo password available"
        s, final = sso_login(REJECTED_USER, DEMO_PW)
        me = s.get(f"{SUPERSET}/api/v1/me/", timeout=30)
        assert me.status_code == 401, f"user without NxtBI group got /api/v1/me/ {me.status_code}"
        return f"authenticated at Keycloak but refused by Superset (landed on {urlparse(final.url).path}, /api/v1/me/ 401)"
    check("sso", f"deny by default: {REJECTED_USER}", rejected)

    def wrong_password() -> str:
        s, final = sso_login("planning.admin@nxtbi.local", "definitely-not-the-password")
        assert urlparse(final.url).netloc == urlparse(KEYCLOAK).netloc, "wrong password left Keycloak"
        assert s.get(f"{SUPERSET}/api/v1/me/", timeout=30).status_code == 401
        return "stays on the Keycloak form; no Superset session"
    check("sso", "wrong password", wrong_password)

    def logout() -> str:
        assert DEMO_PW, "no demo password available"
        s, _ = sso_login("planning.editor@nxtbi.local", DEMO_PW)
        assert s.get(f"{SUPERSET}/api/v1/me/", timeout=30).status_code == 200
        first = s.get(f"{SUPERSET}/logout/", allow_redirects=False, timeout=30)
        assert first.status_code == 302, f"/logout/ -> {first.status_code}"
        target = urlparse(first.headers["Location"])
        q = parse_qs(target.query)
        assert target.path.endswith("/protocol/openid-connect/logout"), target.path
        assert q.get("id_token_hint") and q["post_logout_redirect_uri"] == [f"{SUPERSET}/login/"]
        end = s.get(first.headers["Location"], timeout=30)
        assert end.url.startswith(f"{SUPERSET}/login"), f"after Keycloak logout landed on {end.url[:80]}"
        assert s.get(f"{SUPERSET}/api/v1/me/", timeout=30).status_code == 401, "Superset session survived logout"
        again = s.get(f"{SUPERSET}/login/keycloak", timeout=30)
        assert "kc-form-login" in again.text, "Keycloak SSO session survived logout (no credential form shown)"
        return "RP-initiated logout with id_token_hint; Superset session and Keycloak SSO session both ended"
    check("sso", "logout (Superset + Keycloak session)", logout)
    return sessions


def group_rls(sessions: dict[str, requests.Session]) -> None:
    admin = sessions.get("superset.admin@nxtbi.local")
    planning = sessions.get("planning.admin@nxtbi.local")
    stats = sessions.get("stats.admin@nxtbi.local")
    editor = sessions.get("stats.editor@nxtbi.local")
    if not (admin and planning and stats and editor):
        check("rls", "prerequisite: SSO sessions", lambda: (_ for _ in ()).throw(AssertionError("SSO logins failed")))
        return
    shared = dataset_id(admin, "service_requests")
    budget = dataset_id(admin, "budget_execution")
    trade = dataset_id(admin, "trade_flows")

    def chart_rows(session: requests.Session, expected: set[str]) -> Callable[[], str]:
        def run() -> str:
            status, orgs = orgs_visible(session, shared)
            assert status == 200, f"chart data -> {status}"
            assert set(orgs) == expected, f"sees {sorted(orgs)} expected {sorted(expected)}"
            return f"service_requests rows by org: {orgs}"
        return run

    check("rls", "Admin sees both organisations", chart_rows(admin, {PLANNING, STATS}))
    check("rls", "planning admin sees only planning rows", chart_rows(planning, {PLANNING}))
    check("rls", "stats admin sees only statistics rows", chart_rows(stats, {STATS}))
    check("rls", "stats editor sees only statistics rows", chart_rows(editor, {STATS}))

    def dataset_denied() -> str:
        status, _ = orgs_visible(planning, trade)
        assert status in (403, 404), f"planning user queried trade_flows -> {status}"
        visible = dataset_id(planning, "trade_flows")
        assert visible is None, "planning user can list the statistics dataset"
        status2, _ = orgs_visible(stats, budget)
        assert status2 in (403, 404), f"stats user queried budget_execution -> {status2}"
        return f"cross-tenant dataset access refused ({status}/{status2}) and hidden from the dataset list"
    check("rls", "datasets of the other organisation are inaccessible", dataset_denied)

    def dashboards_visible() -> str:
        def slugs(session: requests.Session) -> set[str]:
            r = session.get(f"{SUPERSET}/api/v1/dashboard/", params={"q": "(page_size:100)"}, timeout=30)
            assert r.status_code == 200
            return {d["slug"] for d in r.json()["result"] if (d.get("slug") or "").startswith("nxtbi-")}
        p, st, a = slugs(planning), slugs(stats), slugs(admin)
        assert a == set(DASHBOARD_SLUGS), f"admin sees {sorted(a)}"
        assert p == {"nxtbi-budget-execution", "nxtbi-service-operations"}, f"planning sees {sorted(p)}"
        assert st == {"nxtbi-trade-population", "nxtbi-service-operations"}, f"stats sees {sorted(st)}"
        return f"planning: {sorted(p)}; stats: {sorted(st)}; admin: all {len(a)}"
    check("rls", "dashboard visibility per organisation", dashboards_visible)

    def database_id() -> int:
        r = admin.get(f"{SUPERSET}/api/v1/database/", params={"q": "(page_size:100)"}, timeout=30)
        return next(d["id"] for d in r.json()["result"] if d["database_name"] == "NxtBI Demo")

    def sqllab_rls() -> str:
        db_id = database_id()
        status, payload = sql(planning, db_id, "SELECT org_slug, count(*) AS n FROM nxtbi.service_requests GROUP BY 1")
        assert status == 200, f"SQL Lab as planning admin -> {status} {str(payload)[:160]}"
        orgs = {row["org_slug"]: row["n"] for row in payload["data"]}
        assert set(orgs) == {PLANNING}, f"SQL Lab leaked rows: {orgs}"
        return f"RLS_IN_SQLLAB applied to raw SQL: {orgs}"
    check("rls", "SQL Lab: RLS applies to ad-hoc SQL", sqllab_rls)

    def sqllab_blank_catalog() -> str:
        # Regression test for a bypass found on this build: with "catalog": "" Superset
        # runs the statement without the caller's RLS predicates. The demo config refuses
        # such requests (FLASK_APP_MUTATOR in superset_config.py).
        body = {"database_id": database_id(), "catalog": "", "schema": "nxtbi", "runAsync": False,
                "queryLimit": 100, "client_id": f"blank{int(time.time() * 1000) % 10 ** 6}",
                "sql": "SELECT org_slug, count(*) AS n FROM nxtbi.service_requests GROUP BY 1"}
        r = planning.post(f"{SUPERSET}/api/v1/sqllab/execute/", json=body, headers=csrf(planning), timeout=60)
        if r.status_code == 200:
            orgs = {row["org_slug"] for row in r.json().get("data", [])}
            assert orgs <= {PLANNING}, f"RLS bypass through an empty catalog: planning user read {sorted(orgs)}"
            return "empty catalog accepted but RLS still applied"
        assert r.status_code == 400, f"unexpected status {r.status_code}: {r.text[:120]}"
        return "request with an empty catalog is refused (HTTP 400); the upstream bypass is closed"
    check("rls", "SQL Lab: empty-catalog RLS bypass is blocked", sqllab_blank_catalog)

    def thumbnails_per_user() -> str:
        def digest(session: requests.Session) -> str:
            r = session.get(f"{SUPERSET}/api/v1/dashboard/nxtbi-service-operations", timeout=30)
            assert r.status_code == 200, f"dashboard -> {r.status_code}"
            url = r.json()["result"].get("thumbnail_url") or ""
            assert "/thumbnail/" in url, f"no thumbnail url: {url!r}"
            return url.rstrip("/").split("/")[-1]
        p, s, a = digest(planning), digest(stats), digest(admin)
        assert len({p, s, a}) == 3, "thumbnail digest is shared between users with different row access"
        return "thumbnail digests differ for planning, statistics and admin users (rendered per user, not as a fixed account)"
    check("rls", "thumbnails are rendered per user", thumbnails_per_user)

    def sqllab_denied() -> str:
        db_id = database_id()
        status, payload = sql(planning, db_id, "SELECT count(*) FROM nxtbi.trade_flows")
        error_types = [e.get("error_type") for e in payload.get("errors", [])] if isinstance(payload, dict) else []
        assert status != 200 and "TABLE_SECURITY_ACCESS_ERROR" in error_types, \
            f"planning admin read trade_flows through SQL Lab -> {status} {str(payload)[:160]}"
        status2, _ = sql(editor, db_id, "SELECT 1")
        assert status2 in (401, 403, 404), f"editor (no sql_lab role) executed SQL -> {status2}"
        return (f"other tenant's table refused (TABLE_SECURITY_ACCESS_ERROR, HTTP {status}); "
                f"user without the sql_lab role refused (HTTP {status2})")
    check("rls", "SQL Lab: table and role restrictions", sqllab_denied)

    def sqllab_admin() -> str:
        status, payload = sql(admin, database_id(),
                              "SELECT sector_ar, round(sum(spent_amount)) AS spent FROM nxtbi.budget_execution "
                              "GROUP BY 1 ORDER BY 2 DESC LIMIT 3")
        assert status == 200, f"-> {status} {str(payload)[:160]}"
        rows = payload["data"]
        assert len(rows) == 3 and any("؀" <= ch <= "ۿ" for ch in rows[0]["sector_ar"])
        return f"3 rows, Arabic values intact: {[r['sector_ar'] for r in rows]}"
    check("rls", "SQL Lab as Admin (Arabic data round-trip)", sqllab_admin)


def api_login() -> requests.Session:
    s = requests.Session()
    r = s.post(f"{SUPERSET}/api/v1/security/login", timeout=30, json={
        "username": ENV.get("SUPERSET_SERVICE_USERNAME", "nxtbi-service"),
        "password": ENV["SUPERSET_SERVICE_PASSWORD"], "provider": "db", "refresh": True})
    assert r.status_code == 200, f"/api/v1/security/login -> {r.status_code}"
    s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return s


def group_api() -> None:
    holder: dict[str, requests.Session] = {}

    def login() -> str:
        holder["s"] = api_login()
        me = holder["s"].get(f"{SUPERSET}/api/v1/me/", timeout=30).json()["result"]
        return f"JWT issued for local service account {me['username']}"
    check("api", "POST /api/v1/security/login (provider db)", login)
    s = holder.get("s")
    if s is None:
        return

    def openapi() -> str:
        spec = s.get(f"{SUPERSET}/api/v1/_openapi", timeout=60).json()
        return f"OpenAPI {spec.get('openapi')}: {len(spec['paths'])} paths"
    check("api", "OpenAPI spec", openapi)

    def anonymous_denied() -> str:
        codes = {p: requests.get(f"{SUPERSET}{p}", timeout=20).status_code
                 for p in ("/api/v1/dashboard/", "/api/v1/chart/", "/api/v1/dataset/")}
        assert set(codes.values()) == {401}, codes
        bad = requests.post(f"{SUPERSET}/api/v1/security/login", timeout=20,
                            json={"username": "admin", "password": "admin", "provider": "db"}).status_code
        assert bad == 401, f"default admin/admin accepted ({bad})"
        return "anonymous requests 401; default admin/admin credentials rejected"
    check("api", "unauthenticated access refused", anonymous_denied)

    def inventory() -> str:
        counts = {}
        for kind in ("dashboard", "chart", "dataset", "database"):
            counts[kind] = s.get(f"{SUPERSET}/api/v1/{kind}/", params={"q": "(page_size:1)"}, timeout=30).json()["count"]
        assert counts["dashboard"] >= 3 and counts["chart"] >= 20, counts
        return f"{counts}"
    check("api", "asset inventory", inventory)

    def chart_data() -> str:
        ds = dataset_id(s, "budget_execution")
        body = {"datasource": {"id": ds, "type": "table"}, "force": True, "result_format": "json", "result_type": "full",
                "queries": [{"columns": ["sector_en"], "metrics": ["execution_rate"], "row_limit": 20,
                             "orderby": [["execution_rate", False]]}]}
        r = s.post(f"{SUPERSET}/api/v1/chart/data", json=body, timeout=60)
        assert r.status_code == 200, f"-> {r.status_code} {r.text[:200]}"
        rows = r.json()["result"][0]["data"]
        assert len(rows) == 8, f"{len(rows)} sectors"
        return f"headless query on saved metric execution_rate: top {rows[0]['sector_en']} = {rows[0]['execution_rate']:.3f}"
    check("api", "POST /api/v1/chart/data (saved metric)", chart_data)

    def cache_hit() -> str:
        ds = dataset_id(s, "trade_flows")
        body = {"datasource": {"id": ds, "type": "table"}, "result_format": "json", "result_type": "full",
                "queries": [{"columns": ["flow"], "metrics": [COUNT_STAR], "row_limit": 10}]}
        s.post(f"{SUPERSET}/api/v1/chart/data", json={**body, "force": True}, timeout=60)
        second = s.post(f"{SUPERSET}/api/v1/chart/data", json=body, timeout=60).json()["result"][0]
        assert second.get("is_cached") is True, f"second identical query not served from cache: {second.get('is_cached')}"
        return "second identical query served from the Redis data cache (is_cached=true)"
    check("api", "query result caching", cache_hit)

    def export_assets() -> str:
        r = s.get(f"{SUPERSET}/api/v1/assets/export/", timeout=120)
        assert r.status_code == 200 and r.content[:2] == b"PK", f"-> {r.status_code}"
        return f"ZIP bundle of all assets, {len(r.content) // 1024} KiB"
    check("api", "GET /api/v1/assets/export/ (assets as code)", export_assets)

    def guest_token() -> str:
        dash = s.get(f"{SUPERSET}/api/v1/dashboard/nxtbi-service-operations", timeout=30).json()["result"]
        emb = s.post(f"{SUPERSET}/api/v1/dashboard/{dash['id']}/embedded", headers=csrf(s), timeout=30,
                     json={"allowed_domains": ["http://localhost:8088"]})
        assert emb.status_code == 200, f"enable embedding -> {emb.status_code} {emb.text[:160]}"
        embedded_uuid = emb.json()["result"]["uuid"]
        try:
            body = {"user": {"username": "embed-demo", "first_name": "Embed", "last_name": "Demo"},
                    "resources": [{"type": "dashboard", "id": embedded_uuid}],
                    "rls": [{"clause": f"org_slug = '{PLANNING}'"}]}
            r = s.post(f"{SUPERSET}/api/v1/security/guest_token/", json=body, headers=csrf(s), timeout=30)
            assert r.status_code == 200, f"-> {r.status_code} {r.text[:160]}"
            assert r.json()["token"].count(".") == 2
            page = requests.get(f"{SUPERSET}/embedded/{embedded_uuid}", timeout=30,
                                headers={"Referer": "http://localhost:8088/"})
            assert page.status_code == 200, f"/embedded/<uuid> -> {page.status_code}"
        finally:  # leave no dashboard embeddable after the test
            s.delete(f"{SUPERSET}/api/v1/dashboard/{dash['id']}/embedded", headers=csrf(s), timeout=30)
        return ("embedding enabled, guest token minted with an RLS clause, embedded page served, embedding removed "
                "again (rendering inside a host application with the embedded SDK not exercised)")
    check("api", "POST /api/v1/security/guest_token/", guest_token)

    def rls_rules() -> str:
        r = s.get(f"{SUPERSET}/api/v1/rowlevelsecurity/", params={"q": "(page_size:50)"}, timeout=30)
        assert r.status_code == 200
        names = sorted(x["name"] for x in r.json()["result"] if x["name"].startswith("NxtBI"))
        assert len(names) == 3, names
        return f"{names}"
    check("api", "RLS rules present", rls_rules)

    def sqllab_async() -> str:
        dbs = s.get(f"{SUPERSET}/api/v1/database/", params={"q": "(page_size:100)"}, timeout=30).json()["result"]
        db_id = next(d["id"] for d in dbs if d["database_name"] == "NxtBI Demo")
        client_id = f"async{int(time.time()) % 10 ** 6}"
        body = {"database_id": db_id, "runAsync": True, "client_id": client_id, "schema": "nxtbi",
                "sql": "SELECT flow, round(sum(value_usd)) AS usd FROM nxtbi.trade_flows GROUP BY 1 ORDER BY 1"}
        r = s.post(f"{SUPERSET}/api/v1/sqllab/execute/", json=body, headers=csrf(s), timeout=60)
        assert r.status_code == 202, f"-> {r.status_code} {r.text[:160]}"
        query_id = r.json()["query"]["queryId"]
        key = None
        for _ in range(40):
            time.sleep(1.5)
            q = s.get(f"{SUPERSET}/api/v1/query/{query_id}", timeout=30).json()["result"]
            if q["status"] in ("success", "failed", "timed_out", "stopped"):
                assert q["status"] == "success", f"async query {q['status']}: {q.get('error_message')}"
                key = q.get("results_key")
                break
        assert key, "async query did not finish in 60 s (Celery worker?)"
        res = s.get(f"{SUPERSET}/api/v1/sqllab/results/", params={"q": f"(key:'{key}')"}, timeout=30)
        assert res.status_code == 200, f"results -> {res.status_code}"
        return f"async query ran on the Celery worker; results backend returned {len(res.json()['data'])} rows"
    check("api", "SQL Lab async (Celery + results backend)", sqllab_async)


def mcp_bearer(username: str | None = None) -> str:
    return mcp_token.mint(username or ENV.get("SUPERSET_SERVICE_USERNAME", "nxtbi-service"), 600, ENV["MCP_JWT_SECRET"])


def mcp_call(method: str, params: dict[str, Any] | None = None, session_id: str | None = None,
             request_id: int | None = 1, token: str | None = None) -> tuple[Any, str | None]:
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    if token is None and MCP_AUTH == "local-jwt":
        token = mcp_bearer()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        body["id"] = request_id
    if params is not None:
        body["params"] = params
    r = requests.post(f"{MCP}/mcp", headers=headers, json=body, timeout=120)
    sid = r.headers.get("Mcp-Session-Id") or session_id
    if request_id is None:
        return r.status_code, sid
    assert r.status_code == 200, f"MCP {method} -> {r.status_code} {r.text[:200]}"
    if "text/event-stream" in r.headers.get("Content-Type", ""):
        r.encoding = "utf-8"
        payloads = [json.loads(line[5:].strip()) for line in r.text.splitlines() if line.startswith("data:")]
        message = next(p for p in payloads if p.get("id") == request_id)
    else:
        message = r.json()
    assert "error" not in message, f"MCP {method} error: {message['error']}"
    return message["result"], sid


def tool_text(result: dict[str, Any]) -> Any:
    assert not result.get("isError"), f"tool error: {str(result.get('content'))[:300]}"
    if result.get("structuredContent") is not None:
        return result["structuredContent"]
    text = "".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")
    try:
        return json.loads(text)
    except ValueError:
        return text


def group_mcp() -> None:
    state: dict[str, Any] = {}

    def unauthenticated() -> str:
        if MCP_AUTH != "local-jwt":
            raise Skip(f"NXTBI_MCP_AUTH={MCP_AUTH}: bearer-token checks apply to local-jwt only")
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        none = requests.post(f"{MCP}/mcp", headers=headers, json=body, timeout=30).status_code
        forged = mcp_token.mint("nxtbi-service", 600, "not-the-real-secret")
        bad = requests.post(f"{MCP}/mcp", headers={**headers, "Authorization": f"Bearer {forged}"}, json=body, timeout=30).status_code
        assert none == 401 and bad == 401, f"no token -> {none}, forged token -> {bad}"
        return "no token -> 401; token signed with a wrong secret -> 401"
    check("mcp", "unauthenticated and forged requests are refused", unauthenticated)

    def initialize() -> str:
        result, sid = mcp_call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                              "clientInfo": {"name": "nxtbi-smoke", "version": "1.0"}})
        state["sid"] = sid
        mcp_call("notifications/initialized", None, sid, request_id=None)
        info = result["serverInfo"]
        return f"server {info.get('name')} {info.get('version')}, protocol {result['protocolVersion']}"
    check("mcp", "initialize (streamable HTTP)", initialize)

    def tools() -> str:
        result, _ = mcp_call("tools/list", {}, state.get("sid"), 2)
        names = sorted(t["name"] for t in result["tools"])
        state["tools"] = names
        assert len(names) >= 20, f"only {len(names)} tools listed"
        return f"{len(names)} tools, e.g. {names[:6]}"
    check("mcp", "tools/list", tools)

    def call(name: str, arguments: dict[str, Any], rid: int) -> Any:
        result, _ = mcp_call("tools/call", {"name": name, "arguments": arguments}, state.get("sid"), rid)
        return tool_text(result)

    def list_dashboards() -> str:
        data = call("list_dashboards", {"request": {"search": "NxtBI", "page_size": 10}}, 3)
        text = json.dumps(data, ensure_ascii=False)
        found = [slug for slug in DASHBOARD_SLUGS if slug in text]
        assert len(found) == 3, f"MCP list_dashboards found {found}"
        return "all three NxtBI dashboards returned through MCP"
    check("mcp", "tools/call list_dashboards", list_dashboards)

    def execute_sql() -> str:
        dbs = call("list_databases", {"request": {"page_size": 20}}, 4)
        text = json.dumps(dbs, ensure_ascii=False)
        match = re.search(r'"id":\s*(\d+)[^{}]*?"database_name":\s*"NxtBI Demo"', text) or \
            re.search(r'"database_name":\s*"NxtBI Demo"[^{}]*?"id":\s*(\d+)', text)
        assert match, f"NxtBI Demo database not in list_databases: {text[:200]}"
        out = call("execute_sql", {"request": {"database_id": int(match.group(1)), "limit": 5,
                   "sql": "SELECT region_ar, sum(population) AS people FROM nxtbi.population "
                          "WHERE census_year = 2026 GROUP BY 1 ORDER BY 2 DESC"}}, 5)
        text = json.dumps(out, ensure_ascii=False)
        assert "العاصمة" in text, f"unexpected execute_sql output: {text[:240]}"
        return "SQL executed through MCP, Arabic result values returned"
    check("mcp", "tools/call execute_sql", execute_sql)

    def chart_info() -> str:
        charts = call("list_charts", {"request": {"page_size": 5, "search": "NxtBI"}}, 6)
        text = json.dumps(charts, ensure_ascii=False)
        assert '"id"' in text, f"no charts: {text[:200]}"
        return f"list_charts returned {text.count('viz_type')} chart records"
    check("mcp", "tools/call list_charts", chart_info)

    def per_user_identity() -> str:
        if MCP_AUTH != "local-jwt":
            raise Skip(f"NXTBI_MCP_AUTH={MCP_AUTH}")
        token = mcp_bearer("planning.admin@nxtbi.local")  # exists after the SSO checks or any real login
        who, _ = mcp_call("tools/call", {"name": "get_instance_info", "arguments": {"request": {}}}, None, 20, token)
        user = tool_text(who).get("current_user", {})
        assert user.get("username") == "planning.admin@nxtbi.local" and "Admin" not in user.get("roles", []), \
            f"identity: {user}"
        dashboards, _ = mcp_call("tools/call", {"name": "list_dashboards",
                                 "arguments": {"request": {"search": "NxtBI", "page_size": 10}}}, None, 21, token)
        text = json.dumps(tool_text(dashboards), ensure_ascii=False)
        visible = sorted(slug for slug in DASHBOARD_SLUGS if slug in text)
        assert visible == ["nxtbi-budget-execution", "nxtbi-service-operations"], f"planning user sees {visible} through MCP"
        dbs, _ = mcp_call("tools/call", {"name": "list_databases", "arguments": {"request": {"page_size": 20}}}, None, 22, token)
        match = re.search(r'"id":\s*(\d+)[^{}]*?"database_name":\s*"NxtBI Demo"', json.dumps(tool_text(dbs)))
        assert match, "planning user cannot see the NxtBI Demo database through MCP"
        rows, _ = mcp_call("tools/call", {"name": "execute_sql", "arguments": {"request": {
            "database_id": int(match.group(1)), "limit": 10,
            "sql": "SELECT org_slug, count(*) AS n FROM nxtbi.service_requests GROUP BY 1"}}}, None, 23, token)
        rows_text = json.dumps(tool_text(rows), ensure_ascii=False)
        assert PLANNING in rows_text and STATS not in rows_text, f"RLS not applied through MCP: {rows_text[:200]}"
        return ("token for planning.admin: MCP reports that user (no Admin role), lists only the planning "
                "dashboards, and execute_sql returns only planning rows")
    check("mcp", "per-user identity, RBAC and RLS through MCP", per_user_identity)


def group_content() -> None:
    holder: dict[str, Any] = {}

    def dashboards() -> str:
        s = holder.setdefault("s", api_login())
        summary = []
        for slug in DASHBOARD_SLUGS:
            r = s.get(f"{SUPERSET}/api/v1/dashboard/{slug}", timeout=30)
            assert r.status_code == 200, f"{slug} -> {r.status_code}"
            dash = r.json()["result"]
            charts = s.get(f"{SUPERSET}/api/v1/dashboard/{slug}/charts", timeout=30).json()["result"]
            meta = json.loads(dash["json_metadata"])
            filters = meta.get("native_filter_configuration", [])
            assert dash["published"] and len(charts) >= 8 and len(filters) >= 3, (slug, len(charts), len(filters))
            assert meta.get("cross_filters_enabled") is True, f"{slug}: cross filters off"
            holder.setdefault("charts", {})[slug] = charts
            summary.append(f"{slug}: {len(charts)} charts, {len(filters)} native filters")
        return "; ".join(summary)
    check("content", "dashboards imported (charts, native filters, cross-filters)", dashboards)

    def every_chart_returns_data() -> str:
        s = holder["s"]
        ok, failures, types = 0, [], set()
        for slug, charts in holder.get("charts", {}).items():
            for chart in charts:
                form_data = dict(chart["form_data"])
                types.add(form_data.get("viz_type"))
                r = s.post(f"{SUPERSET}/api/v1/explore/form_data", headers=csrf(s), timeout=30, json={
                    "datasource_id": int(str(form_data["datasource"]).split("__")[0]), "datasource_type": "table",
                    "chart_id": chart["id"], "form_data": json.dumps(form_data)})
                if r.status_code not in (200, 201):
                    failures.append(f"{chart['slice_name']}: form_data {r.status_code}")
                    continue
                ok += 1
        assert not failures, failures[:5]
        holder["types"] = sorted(t for t in types if t)
        return f"{ok} charts accepted by Explore; viz types: {holder['types']}"
    check("content", "every chart opens in Explore (form_data round-trip)", every_chart_returns_data)

    def examples() -> str:
        s = holder["s"]
        r = s.get(f"{SUPERSET}/api/v1/dashboard/", params={"q": "(page_size:100)"}, timeout=30).json()
        others = [d["dashboard_title"] for d in r["result"] if not (d.get("slug") or "").startswith("nxtbi-")]
        assert len(others) >= 5, f"only {len(others)} example dashboards"
        return f"{len(others)} Superset example dashboards available, e.g. {others[:4]}"
    check("content", "bundled Superset examples loaded", examples)


def group_reports() -> None:
    """Scheduled e-mail report: Celery beat -> worker -> Playwright screenshot -> SMTP (Mailpit)."""
    mailpit = ENV.get("MAILPIT_URL", "http://localhost:8025")

    def report() -> str:
        try:
            requests.get(f"{mailpit}/api/v1/info", timeout=5).raise_for_status()
        except requests.RequestException as exc:
            raise Skip(f"Mailpit API not reachable at {mailpit} ({type(exc).__name__}); set MAILPIT_URL") from exc
        s = api_login()
        dash = s.get(f"{SUPERSET}/api/v1/dashboard/nxtbi-budget-execution", timeout=30).json()["result"]
        name = f"NxtBI smoke report {int(time.time())}"
        body = {"type": "Report", "name": name, "description": "created by smoke_test.py", "active": True,
                "crontab": "* * * * *", "timezone": "UTC", "dashboard": dash["id"], "report_format": "PNG",
                "creation_method": "alerts_reports", "force_screenshot": True, "working_timeout": 300,
                "log_retention": 7,
                "recipients": [{"type": "Email", "recipient_config_json": {"target": "analyst@nxtbi.local"}}]}
        created = s.post(f"{SUPERSET}/api/v1/report/", json=body, headers=csrf(s), timeout=30)
        assert created.status_code == 201, f"create report -> {created.status_code} {created.text[:160]}"
        report_id = created.json()["id"]
        try:
            message = None
            for _ in range(48):
                time.sleep(5)
                found = requests.get(f"{mailpit}/api/v1/search", params={"query": f'subject:"{name}"'}, timeout=15).json()
                if found.get("messages"):
                    message = found["messages"][0]
                    break
            assert message, "no e-mail arrived in Mailpit within 4 minutes"
            full = requests.get(f"{mailpit}/api/v1/message/{message['ID']}", timeout=15).json()
            images = [a for a in full.get("Inline", []) + full.get("Attachments", []) if a.get("ContentType") == "image/png"]
            assert images and images[0]["Size"] > 20_000, "report e-mail has no dashboard screenshot"
            return f"e-mail '{message['Subject']}' delivered with a {images[0]['Size'] // 1024} KiB PNG screenshot"
        finally:
            s.delete(f"{SUPERSET}/api/v1/report/{report_id}", headers=csrf(s), timeout=30)
    check("reports", "scheduled dashboard report by e-mail", report)


def main(argv: list[str]) -> int:
    groups = {"stack", "sso", "rls", "api", "mcp", "content", "reports"}
    wanted = set(argv[1:]) or groups
    if wanted - groups:
        print(f"unknown group(s): {sorted(wanted - groups)}; choose from {sorted(groups)}", file=sys.stderr)
        return 2
    sessions: dict[str, requests.Session] = {}
    if "stack" in wanted:
        group_stack()
    if wanted & {"sso", "rls"}:
        sessions = group_sso()
    if "rls" in wanted:
        group_rls(sessions)
    if "api" in wanted:
        group_api()
    if "mcp" in wanted:
        group_mcp()
    if "content" in wanted:
        group_content()
    if "reports" in wanted:
        group_reports()
    OUT.mkdir(exist_ok=True)
    (OUT / "smoke-results.json").write_text(json.dumps(RESULTS, indent=2, ensure_ascii=False), encoding="utf-8")
    failed = [r for r in RESULTS if r["status"] == "FAIL"]
    skipped = [r for r in RESULTS if r["status"] == "SKIP"]
    print(f"\n{len(RESULTS) - len(failed) - len(skipped)} passed, {len(failed)} failed, {len(skipped)} skipped "
          f"-> {OUT / 'smoke-results.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv))
