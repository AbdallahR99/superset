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
"""End-to-end checks of the Widget Framework against the stack "nxtbi-widgets".

    python nxtbi/widgets/scripts/widgets_e2e.py                 # every check
    python nxtbi/widgets/scripts/widgets_e2e.py --only f,g      # groups, or name fragments
    python nxtbi/widgets/scripts/widgets_e2e.py --api-only      # no browser (d, f, g, mcp)
    python nxtbi/widgets/scripts/widgets_e2e.py --manage-flag-off
                                                                # start and remove the
                                                                # flag-off web container
    python nxtbi/widgets/scripts/widgets_e2e.py --keep --headed

Every check is independent, has a name and ends as PASS, FAIL or SKIP. A check that
cannot run here (the example app is not started, the MCP profile is not up) is a SKIP
whose message says how to make it run. Each check creates what it needs through the
REST API and deletes it at the end (--keep leaves it).

Groups, following the eight scenarios of the brief:
    a  builder: chart, table, metric, filter and markdown widgets, save, reload
    b  concurrent edit: second save gets the conflict dialog, nothing is overwritten
    c  filter widget and cross-filter narrow the data of other widgets
    d  saved widget and inline widget return the same data
    e  standalone React example: session and guest token, host filter, two providers
    f  security: guest scopes, SQL in definitions, row level security, flag off
    g  REST: saved widget CRUD, Dashboard V2 documents, revisions, invalid documents
    h  Arabic / right-to-left, and the MCP widget tools

Results:  nxtbi/out/widgets-e2e-results.json   (exit code 1 when a check fails)
Failures: nxtbi/out/widgets-e2e/<check>.png    (browser checks, at the moment of failure)

Credentials and URLs come from nxtbi/widgets/.env and are never printed. Requirements
on the host: `pip install requests playwright` and `playwright install chromium`.

Request payloads that two engineers are still shaping (the guest token grant for inline
widgets, the revision of a Dashboard V2 save) are built in one place each: see the
section "payloads under change" below.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable

import requests

WIDGETS_DIR = Path(__file__).resolve().parents[1]
NXTBI_DIR = WIDGETS_DIR.parent
REPO_ROOT = NXTBI_DIR.parent
OUT = NXTBI_DIR / "out"
SHOTS = OUT / "widgets-e2e"
RESULTS_FILE = OUT / "widgets-e2e-results.json"
COMPOSE_FILE = WIDGETS_DIR / "docker-compose.yml"
FRONTEND_SOURCES = [
    REPO_ROOT / "superset-frontend" / "src" / "pages" / "DashboardBuilderV2",
    REPO_ROOT / "superset-frontend" / "src" / "core" / "dashboard",
    REPO_ROOT / "superset-frontend" / "packages" / "superset-widgets" / "src",
    REPO_ROOT / "superset-frontend" / "src" / "pages" / "Login",
]

PREFIX = "widgets-e2e"
RLS_TABLE = "widgets_rls_demo"  # bootstrap/widgets_bootstrap.py
RLS_VISIBLE_REGION = "north"
MCP_ISSUER = "nxtbi-widgets"  # MCP_JWT_ISSUER in config/superset_config.py
MCP_AUDIENCE = "nxtbi-widgets-mcp"  # MCP_JWT_AUDIENCE
SESSION_COOKIE = "nxtbi_widgets_session"  # SESSION_COOKIE_NAME
VIEWPORT = {"width": 1440, "height": 1000}
BUILTIN_TYPES = {"markdown", "echarts", "metric-tile", "ag-grid-table", "filter.select"}


class Skip(Exception):
    """The check cannot run here; the message says why and what to do."""


def expect(condition: Any, message: str) -> None:
    """Fail the running check with ``message`` unless ``condition`` holds."""
    if not condition:
        raise AssertionError(message)


def read_env() -> dict[str, str]:
    """KEY=value pairs of nxtbi/widgets/.env."""
    path = WIDGETS_DIR / ".env"
    if not path.exists():
        sys.exit(f"{path} not found: run python nxtbi/widgets/scripts/gen_env.py")
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


# ------------------------------------------------------------------ payloads under change
# Everything in this section mirrors a request shape defined in
#   superset/security/api.py          GuestTokenCreateSchema
#   superset/security/manager.py      guest_widget_grants_dataset
#   superset/widgets/schemas.py       WidgetSelectorSchema, WidgetDataPostSchema
#   superset/dashboard_v2/api.py      read_base_revision
#   nxtbi/docs/widgets/05-dashboard-v2-api-contract.md
# When one of those changes, this is the only place of the script to adapt.


def guest_token_request(
    *,
    widget_uuids: Iterable[str] = (),
    inline_dataset_ids: Iterable[int] = (),
    dashboard_uuids: Iterable[str] = (),
    dataset_allowlist: Iterable[int] = (),
    rls: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Body of POST /api/v1/security/guest_token/.

    A saved widget is granted as a ``widget`` resource. Inline widget definitions are
    granted per dataset by a ``dataset`` resource whose id is the dataset id written
    as a string. A dashboard is granted as a ``dashboard`` resource naming its
    embedded uuid. ``dataset_allowlist`` becomes the ``datasets`` claim, which only
    narrows a token and grants nothing.
    """
    body: dict[str, Any] = {
        "user": {
            "username": f"{PREFIX}-guest",
            "first_name": "Widgets",
            "last_name": "E2E",
        },
        "resources": [
            *({"type": "widget", "id": ref} for ref in widget_uuids),
            *({"type": "dataset", "id": str(ref)} for ref in inline_dataset_ids),
            *({"type": "dashboard", "id": ref} for ref in dashboard_uuids),
        ],
        "rls": list(rls),
    }
    allowlist = list(dataset_allowlist)
    if allowlist:
        body["datasets"] = allowlist
    return body


# Who may put SQL expressions into a widget definition (user_may_author_widget_sql in
# superset/widgets/data.py): admins, and any signed-in user who can read the dataset,
# the rule Explore applies to an ad-hoc SQL metric. A guest never may. With True the
# Gamma demo user is expected to be served a SQL metric on a dataset it can read; set
# it to False when the rule goes back to "SQL Lab permission or dataset editor only".
DATASET_READERS_MAY_AUTHOR_SQL = True


def guest_rls_rule(dataset_id: int, clause: str) -> dict[str, Any]:
    """One row-level-security rule of a guest token, scoped to a dataset."""
    return {"dataset": dataset_id, "clause": clause}


def saved_selector(widget_uuid: str) -> dict[str, Any]:
    """Names a saved widget in a widget data or values request."""
    return {"id": widget_uuid}


def inline_selector(widget_type: str, props: dict[str, Any]) -> dict[str, Any]:
    """Carries an inline widget definition in a widget data or values request."""
    return {"widget": {"type": widget_type, "props": props}}


def data_request(
    selector: dict[str, Any], filters: Iterable[dict[str, Any]] = ()
) -> dict[str, Any]:
    """Body of POST /api/v1/widget/data."""
    return {**selector, "filters": list(filters)}


def resolved_filter(column: str, operator: str, value: Any) -> dict[str, Any]:
    """One structured filter of a widget data request."""
    return {"column": column, "operator": operator, "value": value}


def v2_create_body(
    title: str, document: dict[str, Any], client_uuid: str | None = None
) -> dict[str, Any]:
    """Body of POST /api/v1/dashboard_v2/; a client uuid makes the create repeatable."""
    body: dict[str, Any] = {"dashboard_title": title, "document": document}
    if client_uuid is not None:
        body["uuid"] = client_uuid
    return body


def v2_update_body(
    document: dict[str, Any], base_revision: int | None, title: str | None = None
) -> dict[str, Any]:
    """Body of PUT /api/v1/dashboard_v2/<pk>; the base revision travels in the body."""
    body: dict[str, Any] = {"document": document}
    if base_revision is not None:
        body["base_revision"] = base_revision
    if title is not None:
        body["dashboard_title"] = title
    return body


def v2_if_match(revision: int) -> dict[str, str]:
    """The base revision of a PUT as a header instead of a body field."""
    return {"If-Match": f'"{revision}"'}


def v2_revision(payload: dict[str, Any]) -> int:
    """The revision in a successful Dashboard V2 response body."""
    return int(payload["result"]["revision"])


def v2_conflict_revision(payload: dict[str, Any]) -> int | None:
    """The stored revision a 409 answer reports."""
    value = payload.get("current_revision")
    return int(value) if value is not None else None


def v2_etag(response: requests.Response) -> str | None:
    """The revision carried by the ETag header, without quotes."""
    value = response.headers.get("ETag")
    return value.strip().removeprefix("W/").strip('"') if value else None


# ------------------------------------------------------------------------------ REST client


class Api:
    """A principal talking to the REST API: a signed-in user, a guest or nobody."""

    def __init__(self, base: str, label: str) -> None:
        self.base = base.rstrip("/")
        self.label = label
        self.session = requests.Session()
        self.headers: dict[str, str] = {}
        self._credentials: tuple[str, str] | None = None

    @classmethod
    def login(cls, base: str, username: str, password: str) -> "Api":
        """Sign in with a database account (bearer token plus CSRF token)."""
        api = cls(base, username)
        api._credentials = (username, password)
        api._sign_in()
        return api

    @classmethod
    def guest(cls, base: str, token: str) -> "Api":
        """A holder of a guest token; no session, no cookies."""
        api = cls(base, "guest")
        api.headers["X-GuestToken"] = token
        return api

    @classmethod
    def anonymous(cls, base: str) -> "Api":
        """No credentials at all."""
        return cls(base, "anonymous")

    def _sign_in(self) -> None:
        assert self._credentials is not None
        username, password = self._credentials
        self.session = requests.Session()
        response = self.session.post(
            f"{self.base}/api/v1/security/login",
            json={
                "username": username,
                "password": password,
                "provider": "db",
                "refresh": False,
            },
            timeout=30,
        )
        expect(
            response.status_code == 200,
            f"API login of {username} at {self.base} -> {response.status_code} {response.text[:200]}",
        )
        self.headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        csrf = self.session.get(
            f"{self.base}/api/v1/security/csrf_token/", headers=self.headers, timeout=30
        )
        expect(
            csrf.status_code == 200, f"CSRF token for {username} -> {csrf.status_code}"
        )
        self.headers["X-CSRFToken"] = csrf.json()["result"]
        self.headers["Referer"] = f"{self.base}/"

    def call(
        self,
        method: str,
        path: str,
        body: Any = None,
        headers: dict[str, str] | None = None,
        raw: bytes | None = None,
    ) -> requests.Response:
        """One request; a signed-in principal signs in again when its token expired."""
        for attempt in (1, 2):
            merged = {**self.headers, **(headers or {})}
            # No redirects: an API answer that points at the login page is a refusal
            # to report, not a page to follow.
            kwargs: dict[str, Any] = {
                "headers": merged,
                "timeout": 120,
                "allow_redirects": False,
            }
            if raw is not None:
                merged.setdefault("Content-Type", "application/json")
                kwargs["data"] = raw
            elif body is not None:
                kwargs["json"] = body
            response = self.session.request(method, f"{self.base}{path}", **kwargs)
            if response.status_code == 401 and self._credentials and attempt == 1:
                self._sign_in()
                continue
            return response
        return response

    def json(
        self,
        method: str,
        path: str,
        body: Any = None,
        allowed: tuple[int, ...] = (200,),
        what: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """A request whose status must be one of ``allowed``; the parsed body."""
        response = self.call(method, path, body, headers)
        need_status(response, allowed, what or f"{method} {path} as {self.label}")
        return response.json() if response.content else {}


def need_status(
    response: requests.Response, allowed: tuple[int, ...], what: str
) -> None:
    """Fail with the request, the expected and the received status."""
    expect(
        response.status_code in allowed,
        f"{what}: expected HTTP {'/'.join(map(str, allowed))}, got {response.status_code} "
        f"{response.text[:300]!r}",
    )


def reachable(url: str) -> bool:
    """Whether an HTTP server answers at ``url`` at all."""
    try:
        requests.get(url, timeout=5)
        return True
    except requests.RequestException:
        return False


# -------------------------------------------------------------------------------- context


class Ctx:
    """Everything the checks share: principals, dataset ids, the lazy browser."""

    def __init__(self, env: dict[str, str], args: argparse.Namespace) -> None:
        self.env, self.args = env, args
        self.base = env.get("SUPERSET_PUBLIC_URL", "http://localhost:8089").rstrip("/")
        self.flag_off_base = env.get(
            "SUPERSET_FLAG_OFF_URL", "http://localhost:8099"
        ).rstrip("/")
        self.mcp = env.get("MCP_SERVICE_URL", "http://localhost:5009").rstrip("/")
        self.example_session = env.get(
            "EXAMPLE_APP_URL", "http://localhost:5173"
        ).rstrip("/")
        self.example_guest = env.get(
            "EXAMPLE_APP_GUEST_URL", "http://localhost:5174"
        ).rstrip("/")
        self.admin_name = env.get("WIDGETS_ADMIN_USERNAME", "admin")
        self.gamma_name = env.get("WIDGETS_GAMMA_USERNAME", "widgets_gamma")
        self.admin = Api.login(
            self.base, self.admin_name, env["WIDGETS_ADMIN_PASSWORD"]
        )
        self.gamma = Api.login(
            self.base, self.gamma_name, env["WIDGETS_GAMMA_PASSWORD"]
        )
        self.datasets = {
            name: self._dataset_id(name)
            for name in ("birth_names", "video_game_sales", RLS_TABLE)
        }
        self.created_dashboards: list[int] = []
        self.created_widgets: list[str] = []
        self._playwright: Any = None
        self._browser: Any = None
        self._storage: Any = None
        self._page_problems: dict[int, list[str]] = {}

    def _dataset_id(self, table_name: str) -> int:
        query = f"(filters:!((col:table_name,opr:eq,value:{table_name})),columns:!(id,table_name))"
        found = self.admin.json(
            "GET", f"/api/v1/dataset/?q={requests.utils.quote(query)}"
        )
        ids = [
            row["id"]
            for row in found.get("result", [])
            if row.get("table_name") == table_name
        ]
        expect(
            ids,
            f"dataset {table_name!r} not found: the init job loads it "
            "(docker compose -f nxtbi/widgets/docker-compose.yml logs superset-init)",
        )
        return int(ids[0])

    # -- objects created through the API -------------------------------------------------

    def guest_token(
        self, body: dict[str, Any], allowed: tuple[int, ...] = (200,)
    ) -> requests.Response:
        """Mint a guest token as the admin; the response, checked against ``allowed``."""
        response = self.admin.call("POST", "/api/v1/security/guest_token/", body)
        need_status(response, allowed, f"guest token for {json.dumps(body)[:160]}")
        return response

    def guest(self, **grant: Any) -> Api:
        """A guest holding a token minted for ``grant`` (see guest_token_request)."""
        token = self.guest_token(guest_token_request(**grant)).json()["token"]
        return Api.guest(self.base, token)

    def save_widget(
        self,
        widget_type: str,
        props: dict[str, Any],
        title: str,
        api: Api | None = None,
    ) -> dict[str, Any]:
        """Create a saved widget and remember it for cleanup."""
        result = (api or self.admin).json(
            "POST",
            "/api/v1/widget/",
            {"widget_type": widget_type, "props": props, "title": f"{PREFIX} {title}"},
            allowed=(201,),
            what=f"create saved {widget_type} widget",
        )["result"]
        self.created_widgets.append(result["uuid"])
        return result

    def create_dashboard(self, label: str, document: dict[str, Any]) -> dict[str, Any]:
        """Create a Dashboard V2 and remember it for cleanup; the ``result`` object."""
        title = f"{PREFIX} {label} {uuid.uuid4().hex[:8]}"
        payload = self.admin.json(
            "POST",
            "/api/v1/dashboard_v2/",
            v2_create_body(title, document),
            allowed=(201,),
            what="create Dashboard V2",
        )
        self.created_dashboards.append(int(payload["result"]["id"]))
        return payload["result"]

    def cleanup(self) -> None:
        """Delete what the run created (best effort)."""
        for pk in self.created_dashboards:
            self.admin.call("DELETE", f"/api/v1/dashboard/{pk}")
        for ref in self.created_widgets:
            self.admin.call("DELETE", f"/api/v1/widget/{ref}")

    # -- browser ---------------------------------------------------------------------------

    def browser(self) -> Any:
        """The shared Chromium, started on first use."""
        if self.args.api_only:
            raise Skip("--api-only: browser checks are not run")
        if self._browser is None:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as error:
                raise Skip(
                    f"Playwright is not installed ({error}): pip install playwright "
                    "&& playwright install chromium"
                ) from error
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=not self.args.headed
            )
        return self._browser

    def new_context(self, signed_in: bool = True) -> Any:
        """A browser context, signed in as the admin through the login form by default."""
        browser = self.browser()
        if signed_in and self._storage is None:
            context = browser.new_context(viewport=VIEWPORT, locale="en-US")
            context.set_default_timeout(15_000)
            page = context.new_page()
            ui_login(
                page, self.base, self.admin_name, self.env["WIDGETS_ADMIN_PASSWORD"]
            )
            self._storage = context.storage_state()
            context.close()
        context = browser.new_context(
            viewport=VIEWPORT,
            locale="en-US",
            storage_state=self._storage if signed_in else None,
        )
        context.set_default_timeout(15_000)
        self._watch(context)
        return context

    def _watch(self, context: Any) -> None:
        """Record what no page of a context may do: throw, or break the page's CSP.

        A Content Security Policy violation is logged by the browser as a console
        error and does not fail anything by itself; a script that needs `eval` then
        dies with an uncaught EvalError. Both are collected per context and asserted
        by `expect_no_page_problems`.
        """
        problems: list[str] = []
        self._page_problems[id(context)] = problems

        def on_console(message: Any) -> None:
            text = message.text or ""
            if "Content Security Policy" in text or "EvalError" in text:
                problems.append(f"console {message.type}: {text[:400]}")

        def attach(page: Any) -> None:
            page.on(
                "pageerror",
                lambda error: problems.append(f"uncaught: {str(error)[:400]}"),
            )
            page.on("console", on_console)

        context.on("page", attach)

    def page_problems(self, context: Any) -> list[str]:
        """Uncaught errors and CSP violations of the pages of a context so far."""
        return list(self._page_problems.get(id(context), []))

    def expect_no_page_problems(self, context: Any, what: str) -> None:
        """Fail when a page of the context threw or violated its CSP."""
        problems = self.page_problems(context)
        expect(
            not problems,
            f"{what}: {len(problems)} uncaught error(s) or Content Security Policy "
            f"violation(s) in the page: {problems[:3]}",
        )

    def close(self) -> None:
        """Stop the browser."""
        if self._browser is not None:
            self._browser.close()
            self._playwright.stop()


# ---------------------------------------------------------------------- documents and props


def binding(
    dataset_id: int,
    metrics: list[Any],
    dimensions: list[str] | None = None,
    row_limit: int = 100,
) -> dict[str, Any]:
    """A widget data binding."""
    return {
        "datasetId": dataset_id,
        "metrics": metrics,
        "dimensions": dimensions or [],
        "rowLimit": row_limit,
    }


def widget_props(ctx: Ctx) -> dict[str, dict[str, Any]]:
    """Props of the five widget kinds of the brief, on the birth_names dataset."""
    births = ctx.datasets["birth_names"]
    return {
        "filter.select": {
            "datasetId": births,
            "column": "gender",
            "options": ["boy", "girl"],
        },
        "echarts": {
            "dataBinding": binding(births, ["count"], ["gender"]),
            "crossFilter": True,
            "echartsOptions": {
                "xAxis": {
                    "type": "category",
                    "data": {"$bind": {"source": "dimension", "alias": "gender"}},
                },
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "bar",
                        "data": {"$bind": {"source": "metric", "alias": "count"}},
                    }
                ],
            },
        },
        "ag-grid-table": {
            "dataBinding": binding(births, ["count"], ["gender", "state"], 200)
        },
        "metric-tile": {"dataBinding": binding(births, ["count"]), "label": "Births"},
        "markdown": {"content": f"# {PREFIX} heading\n\nمرحبا بالعالم"},
    }


NODE_IDS = {
    "filter.select": "w_filter",
    "echarts": "w_chart",
    "ag-grid-table": "w_table",
    "metric-tile": "w_metric",
    "markdown": "w_markdown",
}


def standard_document(ctx: Ctx) -> dict[str, Any]:
    """A document with one widget of each kind, as the builder would store it."""
    spans = {
        "filter.select": (24, 2),
        "echarts": (12, 9),
        "ag-grid-table": (12, 9),
        "metric-tile": (8, 4),
        "markdown": (16, 4),
    }
    nodes: dict[str, Any] = {
        "root": {
            "type": "grid",
            "layout": {"columns": 24},
            "children": list(NODE_IDS.values()),
        }
    }
    for widget_type, props in widget_props(ctx).items():
        col_span, row_span = spans[widget_type]
        nodes[NODE_IDS[widget_type]] = {
            "type": widget_type,
            "layout": {"colSpan": col_span, "rowSpan": row_span},
            "props": props,
        }
    return {"version": 1, "nodes": nodes}


def markdown_document(text: str = "hello") -> dict[str, Any]:
    """The smallest valid document: a root grid with one markdown widget."""
    return {
        "version": 1,
        "nodes": {
            "root": {"type": "grid", "layout": {"columns": 24}, "children": ["node_1"]},
            "node_1": {"type": "markdown", "props": {"content": text}},
        },
    }


def rows_of(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The rows of a widget data response."""
    return list(payload.get("result", {}).get("rows", []))


def distinct(rows: list[dict[str, Any]], column: str) -> list[Any]:
    """Sorted distinct values of one column."""
    return sorted({row.get(column) for row in rows}, key=str)


# ------------------------------------------------------------------------- browser helpers

SELECTORS = {
    "empty_canvas": '[data-test="empty-canvas"]',
    "canvas": '[data-test="canvas"]',
    "editor_panel": '[data-test="editor-panel"]',
    "save": '[data-test="header-save"]',
    "unsaved": '[data-test="header-unsaved"]',
    "title": '[data-test="header-title"]',
    "load_error": '[data-test="dashboard-load-error"]',
    "conflict_dialog": '[data-test="conflict-dialog"]',
    "conflict_keep": '[data-test="conflict-keep-editing"]',
    "conflict_reload": '[data-test="conflict-reload"]',
    "conflict_overwrite": '[data-test="conflict-overwrite"]',
    "node_identity": '[data-test="inspector-identity-meta"]',
    "props_tabs": '[data-test="inspector-props-tabs"]',
    "props_json": '[data-test="inspector-props"]',
    "props_apply": '[data-test="inspector-props-apply"]',
    "props_error": '[data-test="inspector-props-validation-error"]',
    "control_panel": '[data-test="schema-control-panel"]',
}
# data-test values built from a prefix and an id at run time.
SELECTOR_PREFIXES = ["palette-", "widget-content-", "chart-"]
GRID_ITEM = ".grid-stack-item"
WIDGET_ROOT = "[data-superset-widget]"  # the embed package's root, not the builder's
# A widget's content area in the builder; the root grid has one too and is not a widget.
BUILDER_WIDGET = '[data-test^="widget-content-"]:not([data-test="widget-content-root"])'
SAVED_URL = re.compile(r"/dashboard/v2/(\d+)/?(?:[?#].*)?$")


def palette(widget_type: str) -> str:
    """Selector of a palette entry."""
    return f'[data-test="palette-{widget_type}"]'


def content(node_id: str) -> str:
    """Selector of a widget's content area in the builder."""
    return f'[data-test="widget-content-{node_id}"]'


def need(
    page: Any, selector: str, what: str, timeout: int = 20_000, state: str = "visible"
) -> Any:
    """Wait for an element; fail naming the element, the selector and the page."""
    locator = page.locator(selector).first
    try:
        locator.wait_for(state=state, timeout=timeout)
    except Exception as error:  # noqa: BLE001 - Playwright's TimeoutError
        problem = ""
        if page.locator(SELECTORS["load_error"]).count():
            problem = " (the builder shows its load error)"
        raise AssertionError(
            f"{what}: no {state} element for {selector} after {timeout / 1000:.0f}s "
            f"at {page.url}{problem}"
        ) from error
    return locator


def wait_until(
    page: Any,
    predicate: Callable[[], Any],
    timeout_ms: int = 20_000,
    step_ms: int = 300,
) -> Any:
    """Poll ``predicate`` until it is truthy or the time is up; its last value."""
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        value = predicate()
        if value or time.monotonic() > deadline:
            return value
        page.wait_for_timeout(step_ms)


def ui_login(page: Any, base: str, username: str, password: str) -> None:
    """Sign in through the database login form.

    When the form does not render (a server without the frontend bundle), the same
    form post the page would make is sent from the page itself, with the CSRF token
    the server put into the document.
    """
    page.goto(f"{base}/login/", wait_until="domcontentloaded")
    try:
        form = need(
            page, '[data-test="login-form"], form', "login form", timeout=12_000
        )
    except AssertionError:
        token = page.evaluate(
            "() => document.querySelector('#csrf_token, input[name=csrf_token]')?.value"
        )
        expect(
            token,
            f"login form did not render at {page.url} and the page carries no CSRF token",
        )
        page.evaluate(
            """([username, password, token]) => {
              const form = document.createElement('form');
              form.method = 'POST';
              form.action = '/login/';
              for (const [name, value] of [['username', username], ['password', password],
                                           ['csrf_token', token]]) {
                const input = document.createElement('input');
                input.type = 'hidden'; input.name = name; input.value = value;
                form.appendChild(input);
              }
              document.body.appendChild(form);
              form.submit();
            }""",
            [username, password, token],
        )
        try:
            page.wait_for_url(lambda url: "/login" not in url, timeout=30_000)
        except Exception as error:  # noqa: BLE001
            raise AssertionError(
                f"form-post login of {username} did not leave {page.url}"
            ) from error
        return
    for field, value in (("username", username), ("password", password)):
        holder = page.locator(f'[data-test="{field}-input"]').first
        target = (
            holder if holder.count() else form.locator(f'input[name="{field}"]').first
        )
        if target.count() and target.evaluate("e => e.tagName") != "INPUT":
            target = target.locator("input").first
        expect(
            target.count(),
            f"login form at {page.url} has no {field} input "
            "(NXTBI_WIDGETS_AUTH=keycloak serves no database login form)",
        )
        target.fill(value)
    button = page.locator('[data-test="login-button"]').first
    (button if button.count() else form.locator('[type="submit"]').first).click()
    try:
        page.wait_for_url(lambda url: "/login" not in url, timeout=30_000)
    except Exception as error:  # noqa: BLE001
        raise AssertionError(f"login of {username} did not leave {page.url}") from error


def show_palette(page: Any) -> None:
    """Bring the building-blocks tab of the editor panel to the front."""
    tab = page.locator(
        f'{SELECTORS["editor_panel"]} [data-node-key="widgets"] [role="tab"]'
    ).first
    if tab.count():
        tab.click()


def place_block(
    page: Any, widget_type: str, props: dict[str, Any], expected_items: int
) -> str:
    """Click a palette entry, give the new block its props; the new node id."""
    show_palette(page)
    need(page, palette(widget_type), f"palette entry of {widget_type}").click()
    reached = wait_until(
        page, lambda: page.locator(GRID_ITEM).count() >= expected_items
    )
    expect(
        reached,
        f"placing {widget_type}: {page.locator(GRID_ITEM).count()} grid items, "
        f"expected {expected_items}",
    )
    node_id = need(
        page,
        SELECTORS["node_identity"],
        "inspector identity of the new block",
        state="attached",
    ).get_attribute("data-node-id")
    expect(node_id, f"the inspector names no node after placing {widget_type}")
    # Selecting a block renders its control form from the server's JSON Schema. This
    # is where a validator that needs `eval` takes the page down under the stack's
    # Content Security Policy, so the form has to be there before anything else.
    # (The inspector keeps the Form / JSON choice from one block to the next.)
    need(
        page,
        f'{SELECTORS["props_tabs"]} [data-node-key="form"] [role="tab"]',
        "Form tab of the inspector",
    ).click()
    need(
        page,
        SELECTORS["control_panel"],
        f"control form of the new {widget_type} block (rendered from its JSON Schema)",
    )
    need(
        page,
        f'{SELECTORS["props_tabs"]} [data-node-key="json"] [role="tab"]',
        "JSON tab of the inspector",
    ).click()
    need(page, SELECTORS["props_json"], "JSON props editor").fill(json.dumps(props))
    need(
        page, SELECTORS["props_apply"], "Apply button of the JSON props editor"
    ).click()
    page.wait_for_timeout(800)
    error = page.locator(SELECTORS["props_error"]).first
    expect(
        not (error.count() and error.is_visible()),
        f"props of {widget_type} were refused: "
        f"{error.inner_text()[:300] if error.count() else ''}",
    )
    return str(node_id)


def open_saved(page: Any, base: str, dashboard_id: int) -> None:
    """Open a saved Dashboard V2 in the builder and wait for its canvas."""
    page.goto(f"{base}/dashboard/v2/{dashboard_id}/", wait_until="domcontentloaded")
    need(
        page, SELECTORS["canvas"], f"canvas of dashboard {dashboard_id}", timeout=40_000
    )
    page.wait_for_timeout(1500)


def chart_data_log(page: Any) -> list[dict[str, Any]]:
    """Every POST /api/v1/chart/data body the page sends, in order (the builder's data path)."""
    payloads: list[dict[str, Any]] = []

    def on_request(request: Any) -> None:
        if "/api/v1/chart/data" in request.url and request.method == "POST":
            try:
                payloads.append(request.post_data_json or {})
            except Exception:  # noqa: BLE001 - not JSON
                pass

    page.on("request", on_request)
    return payloads


def filters_text(payload: dict[str, Any]) -> str:
    """The filters of a chart data request as text, for containment checks."""
    queries = payload.get("queries") or [{}]
    return json.dumps([query.get("filters") or [] for query in queries])


def rendered_summary(page: Any, widget: str = BUILDER_WIDGET) -> dict[str, Any]:
    """What the widgets of a page look like to a reader.

    ``widget`` selects one widget: a content area in the builder (the default), the
    root element of the embed package (``WIDGET_ROOT``) in a host application.
    """
    return page.evaluate(
        """(widget) => ({
          widgets: document.querySelectorAll(widget).length,
          gridRoots: document.querySelectorAll('.ag-root-wrapper').length,
          gridRtl: document.querySelectorAll('.ag-root-wrapper.ag-rtl, .ag-rtl .ag-root').length,
          gridRows: document.querySelectorAll('.ag-root-wrapper .ag-row').length,
          canvases: document.querySelectorAll('[data-test^="chart-"] canvas').length,
          chartDirections: [...document.querySelectorAll('[data-test^="chart-"] canvas')]
            .map(c => getComputedStyle(c).direction),
          dir: document.documentElement.getAttribute('dir'),
          lang: document.documentElement.getAttribute('lang'),
        })""",
        widget,
    )


def painted_fraction(page: Any, selector: str) -> float:
    """Share of a canvas's pixels that are not blank: 0 for a chart that drew nothing."""
    return float(
        page.evaluate(
            """(selector) => {
              const canvas = document.querySelector(selector);
              if (!canvas || !canvas.width || !canvas.height) return 0;
              const copy = document.createElement('canvas');
              copy.width = canvas.width; copy.height = canvas.height;
              const context = copy.getContext('2d');
              context.drawImage(canvas, 0, 0);
              const { data } = context.getImageData(0, 0, copy.width, copy.height);
              let painted = 0;
              for (let i = 0; i < data.length; i += 4) {
                const blank = data[i + 3] === 0
                  || (data[i] > 245 && data[i + 1] > 245 && data[i + 2] > 245);
                if (!blank) painted += 1;
              }
              return painted / (data.length / 4);
            }""",
            selector,
        )
    )


def table_values(page: Any, node_id: str, column: str) -> list[str]:
    """Distinct values of one column in the rows an AG Grid widget shows."""
    return list(
        page.evaluate(
            """([root, column]) => [...new Set(
              [...document.querySelectorAll(`${root} .ag-row [col-id="${column}"]`)]
                .map(cell => cell.innerText.trim()))].sort()""",
            [content(node_id), column],
        )
    )


def expect_widgets_rendered(
    page: Any, nodes: dict[str, str], what: str
) -> dict[str, Any]:
    """Every widget kind of the brief shows real content, not just a frame.

    ``nodes`` maps a widget type to its node id. Table rows, a painted chart, a
    number in the tile, the markdown text and the filter's select are each looked
    at; the summary of the page is returned.
    """
    for widget_type, node_id in nodes.items():
        need(page, content(node_id), f"{what}: content of the {widget_type} widget")
    table = nodes["ag-grid-table"]
    need(page, f"{content(table)} .ag-root-wrapper", f"{what}: AG Grid")
    rows = wait_until(
        page, lambda: page.locator(f"{content(table)} .ag-row").count(), 30_000
    )
    expect(rows, f"{what}: the table widget shows no rows")
    genders = wait_until(page, lambda: table_values(page, table, "gender"))
    expect(
        genders == ["boy", "girl"],
        f"{what}: the table's gender column shows {genders}, expected boy and girl",
    )
    chart = f"{content(nodes['echarts'])} canvas"
    need(page, chart, f"{what}: chart canvas")
    painted = wait_until(page, lambda: painted_fraction(page, chart) > 0.05, 30_000)
    expect(
        painted,
        f"{what}: the chart canvas is blank ({painted_fraction(page, chart):.1%} painted)",
    )
    tile = page.locator(content(nodes["metric-tile"])).first
    digits = wait_until(page, lambda: re.search(r"\d", tile.inner_text() or ""))
    expect(digits, f"{what}: metric tile shows no number: {tile.inner_text()[:80]!r}")
    markdown_text = page.locator(content(nodes["markdown"])).first.inner_text()
    expect(
        f"{PREFIX} heading" in markdown_text,
        f"{what}: markdown widget shows {markdown_text[:80]!r}",
    )
    need(
        page,
        f"{content(nodes['filter.select'])} .ant-select",
        f"{what}: select of the filter widget",
    )
    summary = rendered_summary(page)
    expect(
        summary["widgets"] == len(nodes),
        f"{what}: {summary['widgets']} widgets on the canvas, expected {len(nodes)}",
    )
    return summary


# --------------------------------------------------------------------------------- checks

Check = Callable[[Ctx], Any]
CHECKS: list[tuple[str, str, Check]] = []


def check(group: str, name: str) -> Callable[[Check], Check]:
    """Register a check under a group letter."""

    def register(fn: Check) -> Check:
        CHECKS.append((group, name, fn))
        return fn

    return register


@check("a", "a0-selectors-exist-in-source")
def selectors_in_source(_ctx: Ctx) -> dict[str, Any]:
    """Every data-test this script relies on is still written by the frontend source."""
    sources = [path for path in FRONTEND_SOURCES if path.is_dir()]
    if not sources:
        raise Skip("the frontend sources are not in this checkout")
    text = ""
    for root in sources:
        for path in root.rglob("*.tsx"):
            if ".test." not in path.name:
                text += path.read_text(encoding="utf-8", errors="replace")
    wanted = {
        name: re.search(r'data-test="([^"]+)"', selector).group(1)  # type: ignore[union-attr]
        for name, selector in SELECTORS.items()
    }
    missing = [value for value in wanted.values() if f'data-test="{value}"' not in text]
    missing += [
        prefix for prefix in SELECTOR_PREFIXES if f"data-test={{`{prefix}$" not in text
    ]
    for attribute in ("data-superset-widget", "data-node-id"):
        if attribute not in text:
            missing.append(attribute)
    expect(
        not missing, f"selectors no longer present in the frontend source: {missing}"
    )
    return {"checked": len(wanted) + len(SELECTOR_PREFIXES) + 2}


@check("a", "a1-builder-build-save-reload")
def builder_build_save_reload(ctx: Ctx) -> dict[str, Any]:
    """Place the five widget kinds in the builder, save, reload: the state is restored."""
    context = ctx.new_context()
    page = context.new_page()
    try:
        page.goto(f"{ctx.base}/dashboard/v2/new/", wait_until="domcontentloaded")
        need(
            page,
            SELECTORS["empty_canvas"],
            "empty canvas of a new Dashboard V2",
            timeout=40_000,
        )
        placed: dict[str, str] = {}
        for index, (widget_type, props) in enumerate(
            widget_props(ctx).items(), start=1
        ):
            placed[widget_type] = place_block(page, widget_type, props, index)
        title = f"{PREFIX} builder {uuid.uuid4().hex[:8]}"
        field = need(page, SELECTORS["title"], "dashboard title field")
        field.fill(title)
        field.blur()
        need(page, SELECTORS["save"], "Save button").click()
        try:
            page.wait_for_url(SAVED_URL, timeout=30_000)
        except Exception as error:  # noqa: BLE001
            raise AssertionError(
                f"saving did not move to /dashboard/v2/<id>/ (still {page.url}); a 422 from "
                "POST /api/v1/dashboard_v2/ is shown as a toast"
            ) from error
        dashboard_id = int(SAVED_URL.search(page.url).group(1))  # type: ignore[union-attr]
        ctx.created_dashboards.append(dashboard_id)
        need(
            page, SELECTORS["unsaved"], "unsaved marker to disappear", state="detached"
        )

        stored = ctx.admin.json("GET", f"/api/v1/dashboard_v2/{dashboard_id}")["result"]
        nodes = stored["document"]["nodes"]
        stored_types = sorted(
            node["type"] for key, node in nodes.items() if key != "root"
        )
        expect(
            stored_types == sorted(placed),
            f"stored widget types {stored_types}, placed {sorted(placed)}",
        )
        expect(
            stored["dashboard_title"] == title,
            f"stored title {stored['dashboard_title']!r}",
        )
        expect(
            stored["revision"] == 1,
            f"a first save stores revision 1, got {stored['revision']}",
        )
        for widget_type, node_id in placed.items():
            expect(
                node_id in nodes,
                f"node {node_id} ({widget_type}) is not in the stored document",
            )
            expect(
                nodes[node_id]["type"] == widget_type,
                f"node {node_id} stored as {nodes[node_id]['type']}",
            )

        page.reload(wait_until="domcontentloaded")
        need(page, SELECTORS["canvas"], "canvas after the reload", timeout=40_000)
        count = wait_until(page, lambda: page.locator(GRID_ITEM).count() == len(placed))
        expect(
            count,
            f"after the reload {page.locator(GRID_ITEM).count()} grid items, expected {len(placed)}",
        )
        summary = expect_widgets_rendered(page, placed, "after the reload")
        expect(
            page.locator(SELECTORS["unsaved"]).count() == 0,
            "a freshly loaded dashboard is marked unsaved",
        )
        expect(
            need(page, SELECTORS["title"], "title field").input_value() == title,
            "title not restored",
        )
        # Reopening a widget's control form on the restored dashboard: the form is
        # built from the server's schema again, with the stored props as its data.
        page.locator(content(placed["metric-tile"])).first.click()
        tab = need(
            page,
            f'{SELECTORS["editor_panel"]} [data-node-key="properties"] [role="tab"]',
            "Properties tab of the editor panel",
        )
        tab.click()
        need(
            page,
            SELECTORS["control_panel"],
            "control form of the restored metric tile",
        )
        # An edit made in the form (not the JSON tab) is validated by the form's own
        # schema validator and by the server, reaches the widget, and is saved.
        label = need(
            page,
            f"{SELECTORS['control_panel']} input#label",
            "Label field of the metric tile's control form",
        )
        expect(
            label.input_value() == "Births",
            f"the form shows the label {label.input_value()!r}, the stored one is 'Births'",
        )
        label.fill("Births e2e")
        tile = page.locator(content(placed["metric-tile"])).first
        relabelled = wait_until(page, lambda: "Births e2e" in (tile.inner_text() or ""))
        expect(
            relabelled,
            f"the form edit did not reach the metric tile: {tile.inner_text()[:80]!r}",
        )
        need(page, SELECTORS["unsaved"], "unsaved marker after the form edit")
        need(page, SELECTORS["save"], "Save button").click()
        need(
            page,
            SELECTORS["unsaved"],
            "unsaved marker to disappear after the second save",
            state="detached",
        )
        resaved = ctx.admin.json("GET", f"/api/v1/dashboard_v2/{dashboard_id}")[
            "result"
        ]
        stored_label = resaved["document"]["nodes"][placed["metric-tile"]]["props"].get(
            "label"
        )
        expect(
            stored_label == "Births e2e" and resaved["revision"] == 2,
            f"after the form edit the server holds label {stored_label!r} at revision "
            f"{resaved['revision']}",
        )
        ctx.expect_no_page_problems(context, "building, saving and reloading")
        return {"dashboard_id": dashboard_id, "nodes": placed, "summary": summary}
    finally:
        fail_shot(page, "a1-builder-build-save-reload")
        context.close()


@check("b", "b1-concurrent-edit-conflict-dialog")
def concurrent_edit(ctx: Ctx) -> dict[str, Any]:
    """Two editors on one dashboard: the second save gets the conflict dialog."""
    created = ctx.create_dashboard("conflict", markdown_document("base"))
    dashboard_id = int(created["id"])
    first, second = ctx.new_context(), ctx.new_context()
    one, two = first.new_page(), second.new_page()
    try:
        open_saved(one, ctx.base, dashboard_id)
        open_saved(two, ctx.base, dashboard_id)
        place_block(one, "markdown", {"content": "from editor one"}, 2)
        need(one, SELECTORS["save"], "Save button of editor one").click()
        need(
            one,
            SELECTORS["unsaved"],
            "unsaved marker of editor one to disappear",
            state="detached",
        )
        after_first = ctx.admin.json("GET", f"/api/v1/dashboard_v2/{dashboard_id}")[
            "result"
        ]
        expect(
            after_first["revision"] == created["revision"] + 1,
            f"editor one's save stored revision {after_first['revision']}",
        )

        place_block(two, "markdown", {"content": "from editor two"}, 2)
        need(two, SELECTORS["save"], "Save button of editor two").click()
        need(
            two,
            SELECTORS["conflict_dialog"],
            "conflict dialog after the second, stale save",
        )
        for key in ("conflict_reload", "conflict_overwrite", "conflict_keep"):
            need(two, SELECTORS[key], f"conflict dialog action {key}")
        stored = ctx.admin.json("GET", f"/api/v1/dashboard_v2/{dashboard_id}")["result"]
        text = json.dumps(stored["document"])
        expect(
            "from editor one" in text,
            "editor one's change is gone from the stored document",
        )
        expect(
            "from editor two" not in text,
            "editor two's stale save overwrote the stored document",
        )
        expect(
            stored["revision"] == after_first["revision"],
            f"the refused save changed the revision to {stored['revision']}",
        )
        two.locator(SELECTORS["conflict_keep"]).first.click()
        need(
            two,
            SELECTORS["conflict_dialog"],
            "conflict dialog to close",
            state="hidden",
        )
        expect(
            two.locator(SELECTORS["unsaved"]).count() > 0,
            "after 'keep editing' the editor no longer shows unsaved changes",
        )
        two.wait_for_timeout(2500)
        again = ctx.admin.json("GET", f"/api/v1/dashboard_v2/{dashboard_id}")["result"]
        expect(
            again["revision"] == stored["revision"],
            "a save was retried silently after the dialog",
        )

        # Saving again is refused again: the tab still holds the stale revision.
        need(two, SELECTORS["save"], "Save button of editor two").click()
        need(two, SELECTORS["conflict_dialog"], "conflict dialog on the second attempt")
        # "Reload" gives up editor two's work and shows what the server holds.
        two.locator(SELECTORS["conflict_reload"]).first.click()
        need(
            two,
            SELECTORS["conflict_dialog"],
            "conflict dialog to close after reload",
            state="hidden",
        )
        shown = wait_until(
            two,
            lambda: (
                "from editor one"
                in (two.locator(SELECTORS["canvas"]).first.inner_text() or "")
            ),
        )
        canvas_text = two.locator(SELECTORS["canvas"]).first.inner_text()
        expect(
            shown,
            f"after 'reload' editor two does not show editor one's block: {canvas_text[:200]!r}",
        )
        expect(
            "from editor two" not in canvas_text,
            "after 'reload' editor two still shows its own discarded block",
        )
        expect(
            two.locator(GRID_ITEM).count() == 2,
            f"after 'reload' editor two shows {two.locator(GRID_ITEM).count()} blocks, expected 2",
        )
        need(
            two,
            SELECTORS["unsaved"],
            "unsaved marker of editor two to disappear after the reload",
            state="detached",
        )
        untouched = ctx.admin.json("GET", f"/api/v1/dashboard_v2/{dashboard_id}")[
            "result"
        ]
        expect(
            untouched["revision"] == after_first["revision"],
            f"'reload' wrote to the server: revision {untouched['revision']}",
        )

        # The next save starts from the revision just loaded and is accepted.
        place_block(two, "markdown", {"content": "editor two, second try"}, 3)
        need(two, SELECTORS["save"], "Save button of editor two").click()
        need(
            two,
            SELECTORS["unsaved"],
            "unsaved marker of editor two to disappear after its accepted save",
            state="detached",
        )
        expect(
            two.locator(SELECTORS["conflict_dialog"]).count() == 0
            or not two.locator(SELECTORS["conflict_dialog"]).first.is_visible(),
            "the save after a reload ran into the conflict dialog again",
        )
        final = ctx.admin.json("GET", f"/api/v1/dashboard_v2/{dashboard_id}")["result"]
        final_text = json.dumps(final["document"])
        expect(
            final["revision"] == after_first["revision"] + 1,
            f"the accepted save stored revision {final['revision']}, "
            f"expected {after_first['revision'] + 1}",
        )
        expect(
            "from editor one" in final_text and "editor two, second try" in final_text,
            "the accepted save does not hold both editors' blocks",
        )
        expect(
            "from editor two" not in final_text,
            "the block discarded by 'reload' reached the server",
        )
        ctx.expect_no_page_problems(first, "editor one")
        ctx.expect_no_page_problems(second, "editor two")
        return {
            "dashboard_id": dashboard_id,
            "revision_after_first": after_first["revision"],
            "revision_after_conflict": again["revision"],
            "revision_after_reload_and_save": final["revision"],
        }
    finally:
        fail_shot(two, "b1-concurrent-edit-conflict-dialog")
        first.close()
        second.close()


@check("c", "c1-filter-widget-narrows-data-api")
def filter_narrows_api(ctx: Ctx) -> dict[str, Any]:
    """A structured filter on the request narrows the rows of a widget (server side)."""
    props = widget_props(ctx)["ag-grid-table"]
    selector = inline_selector("ag-grid-table", props)
    everything = rows_of(
        ctx.admin.json("POST", "/api/v1/widget/data", data_request(selector))
    )
    boys = rows_of(
        ctx.admin.json(
            "POST",
            "/api/v1/widget/data",
            data_request(selector, [resolved_filter("gender", "IN", ["boy"])]),
        )
    )
    expect(
        len(distinct(everything, "gender")) > 1,
        f"unfiltered rows hold one gender only: {distinct(everything, 'gender')}",
    )
    expect(
        distinct(boys, "gender") == ["boy"],
        f"filtered rows hold {distinct(boys, 'gender')}",
    )
    expect(
        0 < len(boys) < len(everything),
        f"filtered {len(boys)} rows of {len(everything)}",
    )
    injected = ctx.admin.call(
        "POST",
        "/api/v1/widget/data",
        data_request(
            selector,
            [
                {
                    "column": "gender",
                    "operator": "EQUALS",
                    "value": "boy",
                    "sqlExpression": "1=1",
                }
            ],
        ),
    )
    need_status(
        injected, (200, 400), "a structured filter with an extra sqlExpression key"
    )
    if injected.status_code == 200:
        expect(
            rows_of(injected.json()) == boys,
            "an extra sqlExpression key on a structured filter changed the rows",
        )
    return {
        "rows": len(everything),
        "rows_filtered": len(boys),
        "filter_with_sql_key_status": injected.status_code,
    }


@check("c", "c2-filter-and-cross-filter-in-builder")
def filter_and_cross_filter(ctx: Ctx) -> dict[str, Any]:
    """In the builder: picking a filter value and clicking a chart point refetch with a filter."""
    created = ctx.create_dashboard("filters", standard_document(ctx))
    context = ctx.new_context()
    page = context.new_page()
    payloads = chart_data_log(page)
    try:
        open_saved(page, ctx.base, int(created["id"]))
        loaded = wait_until(page, lambda: len(payloads) >= 3, 30_000)
        expect(
            loaded,
            f"only {len(payloads)} chart data requests after opening the dashboard, expected 3 "
            "(chart, table, metric)",
        )
        expect(
            not any('"boy"' in filters_text(p) for p in payloads),
            "a request carries the filter value before anything was picked",
        )
        table = NODE_IDS["ag-grid-table"]
        tile = page.locator(content(NODE_IDS["metric-tile"])).first
        unfiltered = wait_until(
            page, lambda: table_values(page, table, "gender") == ["boy", "girl"]
        )
        expect(
            unfiltered,
            f"before any filter the table shows genders {table_values(page, table, 'gender')}",
        )
        total = wait_until(page, lambda: re.sub(r"\D", "", tile.inner_text() or ""))
        expect(total, f"metric tile shows no number: {tile.inner_text()[:80]!r}")

        before = len(payloads)
        select = need(
            page,
            f"{content(NODE_IDS['filter.select'])} .ant-select",
            "select of the filter widget",
        )
        select.click()
        option = need(
            page,
            '.ant-select-dropdown .ant-select-item-option[title="boy"]',
            "option 'boy' in the filter dropdown",
        )
        option.click()
        page.keyboard.press("Escape")
        filtered = wait_until(
            page, lambda: [p for p in payloads[before:] if '"boy"' in filters_text(p)]
        )
        expect(
            filtered,
            f"picking 'boy' sent {len(payloads) - before} chart data requests, none with the value",
        )
        targets = sorted(
            {json.dumps(p.get("queries", [{}])[0].get("columns")) for p in filtered}
        )
        # What the reader sees, not only what was requested: the table keeps the
        # rows of the picked value and the tile's number gets smaller.
        narrowed = wait_until(
            page, lambda: table_values(page, table, "gender") == ["boy"]
        )
        expect(
            narrowed,
            f"after picking 'boy' the table shows genders {table_values(page, table, 'gender')}",
        )
        boys = wait_until(
            page,
            lambda: (
                (shown := re.sub(r"\D", "", tile.inner_text() or ""))
                and shown != total
                and shown
            ),
        )
        expect(
            boys and 0 < int(boys) < int(total),
            f"after picking 'boy' the metric tile shows {tile.inner_text()[:40]!r}, "
            f"it showed {total} before",
        )

        # Clear the filter widget, then cross-filter by clicking a bar of the chart.
        clear = page.locator(
            f"{content(NODE_IDS['filter.select'])} .ant-select-clear"
        ).first
        expect(clear.count(), "the filter widget offers no way to clear its value")
        select.hover()
        clear.click(force=True)
        restored = wait_until(
            page, lambda: table_values(page, table, "gender") == ["boy", "girl"]
        )
        expect(
            restored,
            "after clearing the filter the table shows genders "
            f"{table_values(page, table, 'gender')}",
        )
        canvas = need(page, f"{content(NODE_IDS['echarts'])} canvas", "chart canvas")
        rect = canvas.bounding_box()
        expect(rect, "chart canvas has no size")
        before = len(payloads)
        tried: list[str] = []
        crossed: list[dict[str, Any]] = []
        for fx, fy in ((0.3, 0.7), (0.72, 0.7), (0.3, 0.5), (0.72, 0.5), (0.5, 0.8)):
            page.mouse.click(
                rect["x"] + rect["width"] * fx, rect["y"] + rect["height"] * fy
            )
            tried.append(f"{fx:.2f},{fy:.2f}")
            crossed = wait_until(
                page,
                lambda: [
                    p
                    for p in payloads[before:]
                    if '"boy"' in filters_text(p) or '"girl"' in filters_text(p)
                ],
                4000,
            )
            if crossed:
                break
        expect(
            crossed,
            f"clicking the chart at {tried} (fractions of the canvas) sent "
            f"{len(payloads) - before} chart data requests, none with a gender filter: "
            "cross-filtering did not reach another widget",
        )
        crossed_to = wait_until(
            page,
            lambda: (
                len(values := table_values(page, table, "gender")) == 1 and values[0]
            ),
        )
        expect(
            crossed_to in ("boy", "girl"),
            "after the chart click the table still shows genders "
            f"{table_values(page, table, 'gender')}",
        )
        expect(
            f'"{crossed_to}"' in filters_text(crossed[-1]),
            f"the table shows {crossed_to!r} but the request filtered on "
            f"{filters_text(crossed[-1])}",
        )
        ctx.expect_no_page_problems(context, "filtering and cross-filtering")
        return {
            "dashboard_id": created["id"],
            "tile_total": int(total),
            "tile_filtered": int(boys),
            "cross_filtered_to": crossed_to,
            "filter_requests": len(filtered),
            "filter_targets": targets,
            "cross_filter_requests": len(crossed),
            "cross_filter_click": tried[-1],
        }
    finally:
        fail_shot(page, "c2-filter-and-cross-filter-in-builder")
        context.close()


@check("d", "d1-saved-and-inline-widget-same-data")
def saved_vs_inline(ctx: Ctx) -> dict[str, Any]:
    """A saved widget and the same definition sent inline return the same rows."""
    detail: dict[str, Any] = {}
    for widget_type in ("metric-tile", "ag-grid-table", "echarts"):
        props = widget_props(ctx)[widget_type]
        saved = ctx.save_widget(widget_type, props, f"saved-vs-inline {widget_type}")
        expect(
            saved["dataset_id"] == ctx.datasets["birth_names"],
            f"saved {widget_type} reports dataset {saved['dataset_id']}",
        )
        by_id = rows_of(
            ctx.admin.json(
                "POST",
                "/api/v1/widget/data",
                data_request(saved_selector(saved["uuid"])),
            )
        )
        inline = rows_of(
            ctx.admin.json(
                "POST",
                "/api/v1/widget/data",
                data_request(inline_selector(widget_type, props)),
            )
        )
        expect(by_id, f"saved {widget_type} returned no rows")
        expect(
            by_id == inline,
            f"{widget_type}: saved widget returned {len(by_id)} rows, "
            f"inline {len(inline)}; first rows {by_id[:1]} vs {inline[:1]}",
        )
        detail[widget_type] = len(by_id)
    values_props = widget_props(ctx)["filter.select"]
    values_props = {
        key: value for key, value in values_props.items() if key != "options"
    }
    saved_filter = ctx.save_widget(
        "filter.select", values_props, "saved-vs-inline filter"
    )
    by_id_values = ctx.admin.json(
        "POST", "/api/v1/widget/values", saved_selector(saved_filter["uuid"])
    )["result"]
    inline_values = ctx.admin.json(
        "POST", "/api/v1/widget/values", inline_selector("filter.select", values_props)
    )["result"]
    expect(
        sorted(map(str, by_id_values)) == sorted(map(str, inline_values))
        and by_id_values,
        f"filter values differ: saved {by_id_values} inline {inline_values}",
    )
    detail["filter_values"] = sorted(map(str, by_id_values))
    both = ctx.admin.call(
        "POST",
        "/api/v1/widget/data",
        {
            **saved_selector(saved_filter["uuid"]),
            **inline_selector("markdown", {"content": "x"}),
        },
    )
    need_status(both, (400,), "a request naming a saved widget and an inline one")
    return detail


def example_run(ctx: Ctx, url: str, guest: bool, name: str) -> dict[str, Any]:
    """Drive one instance of the standalone example app (session or guest mode)."""
    if not reachable(url):
        mode = "--guest" if guest else ""
        raise Skip(
            f"nothing answers at {url}: start it with "
            f"`python nxtbi/widgets/scripts/example_app.py {mode}`".replace("  ", " ")
        )
    context = ctx.new_context(signed_in=not guest)
    page = context.new_page()
    requests_seen: list[Any] = []
    responses: list[Any] = []
    broker_calls: list[str] = []

    def on_request(request: Any) -> None:
        if "/api/guest-token" in request.url:
            broker_calls.append(request.url)
        if (
            request.url.startswith(ctx.base)
            and "/api/v1/widget/data" in request.url
            and request.method == "POST"
        ):
            requests_seen.append(request)

    def on_response(response: Any) -> None:
        if (
            response.url.startswith(ctx.base)
            and "/api/v1/widget/data" in response.url
            and response.request.method == "POST"
        ):
            responses.append(response)

    page.on("request", on_request)
    page.on("response", on_response)

    def settle(minimum: int, timeout_ms: int = 45_000) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        last, stable = -1, 0
        while time.monotonic() < deadline:
            page.wait_for_timeout(700)
            count = len(responses)
            stable = stable + 1 if count == last and count >= minimum else 0
            if stable >= 4:
                return
            last = count

    def body_of(request: Any) -> dict[str, Any]:
        try:
            return request.post_data_json or {}
        except Exception:  # noqa: BLE001
            return {}

    try:
        page.goto(url, wait_until="domcontentloaded")
        need(
            page,
            WIDGET_ROOT,
            "a rendered Superset widget in the example app",
            timeout=60_000,
        )
        settle(1)
        statuses = [response.status for response in responses]
        expect(statuses, f"the example app sent no POST {ctx.base}/api/v1/widget/data")
        refused = [status for status in statuses if status in (401, 403)]
        expect(
            not refused,
            f"{len(refused)} of {len(statuses)} widget data requests were refused "
            f"({sorted(set(refused))}): in session mode sign in to {ctx.base} in the "
            "same browser; in guest mode check the broker and the token's datasets",
        )
        ok = [status for status in statuses if status == 200]
        expect(
            ok, f"no widget data request succeeded: statuses {sorted(set(statuses))}"
        )
        limited = [status for status in statuses if status == 429 or status >= 500]
        expect(
            not limited,
            f"{len(limited)} of {len(statuses)} widget data requests failed with "
            f"{sorted(set(limited))}: 429 is the application rate limit (RATELIMIT_APPLICATION, "
            "counted per client address), which a page full of widgets can exceed",
        )

        headers = [request.all_headers() for request in requests_seen]
        with_token = sum(1 for item in headers if "x-guesttoken" in item)
        with_cookie = sum(
            1 for item in headers if SESSION_COOKIE in item.get("cookie", "")
        )
        if guest:
            expect(
                broker_calls,
                "guest mode: the app never asked its token broker (/api/guest-token); "
                "is it running with EMBED_AUTH=guest?",
            )
            expect(
                with_token == len(headers),
                f"guest mode: {with_token} of {len(headers)} data requests "
                "carry X-GuestToken",
            )
            expect(
                with_cookie == 0,
                f"guest mode: {with_cookie} data requests carry the session cookie",
            )
        else:
            expect(
                not broker_calls,
                "session mode: the app asked the token broker; it runs in guest mode",
            )
            expect(
                with_token == 0,
                f"session mode: {with_token} data requests carry X-GuestToken",
            )
            expect(
                with_cookie == len(headers),
                f"session mode: {with_cookie} of {len(headers)} data "
                "requests carry the session cookie",
            )
        summary = rendered_summary(page, WIDGET_ROOT)
        expect(summary["widgets"] >= 3, f"only {summary['widgets']} widgets rendered")
        expect(summary["canvases"] >= 1, "no chart canvas rendered")
        providers = page.locator(
            '[data-component="<SupersetProvider>"], .provider'
        ).count()

        # Host-controlled filter: the first chip of a host filter bar. The example has a
        # section with two independent providers; its first provider is preferred, so
        # that the second one, on another dataset, is the witness of isolation.
        scope = (
            ".isolation-provider"
            if page.locator(".isolation-provider").count() >= 2
            else "body"
        )
        bar = f"{scope} fieldset.filter-bar"
        chip = need(
            page, f"{bar} button.chip:not([disabled])", "chip of the host filter bar"
        )
        chip.scroll_into_view_if_needed()
        value = chip.inner_text().strip()
        column = (page.locator(f"{bar} legend").first.inner_text() or "").strip()
        isolated_pair = scope != "body"

        def rows_by_selector(upto: int | None = None, start: int = 0) -> dict[str, Any]:
            latest: dict[str, Any] = {}
            for response in responses[start:upto]:
                if response.status != 200:
                    continue
                request_body = body_of(response.request)
                key = json.dumps(
                    {k: v for k, v in request_body.items() if k != "filters"},
                    sort_keys=True,
                )
                try:
                    latest[key] = response.json().get("result", {}).get("rows")
                except Exception:  # noqa: BLE001 - body no longer available
                    continue
            return latest

        initial_requests, initial_responses = len(requests_seen), len(responses)
        before_rows = rows_by_selector(initial_responses)
        chip.click()
        settle(initial_responses + 1, 30_000)
        new_requests = requests_seen[initial_requests:]
        expect(
            new_requests,
            f"clicking the host filter chip {value!r} sent no widget data request",
        )

        def carries_host_filter(request: Any) -> bool:
            return any(
                item.get("column") == column and value in json.dumps(item.get("value"))
                for item in body_of(request).get("filters", [])
            )

        without = [
            body_of(request)
            for request in new_requests
            if not carries_host_filter(request)
        ]
        expect(
            not without,
            f"{len(without)} of {len(new_requests)} requests after the host filter do not carry "
            f"{column}={value!r}: a widget outside the filtered provider was refetched, or the "
            f"filter did not reach its widget. First: {json.dumps(without[:1])[:300]}",
        )
        expect(
            len(new_requests) < initial_requests,
            f"the host filter refetched {len(new_requests)} widgets, as many as the whole page "
            f"loaded ({initial_requests}): the providers are not isolated",
        )
        after_rows = rows_by_selector(None, initial_responses)
        changed = [
            key
            for key, rows in after_rows.items()
            if key in before_rows and rows != before_rows[key]
        ]
        expect(
            changed,
            f"the host filter {column}={value!r} changed the rows of none of the "
            f"{len(after_rows)} refetched widgets",
        )

        def dataset_of(request: Any) -> Any:
            props = (body_of(request).get("widget") or {}).get("props") or {}
            return (props.get("dataBinding") or {}).get(
                "datasetId", props.get("datasetId")
            )

        filtered_datasets = sorted(
            {str(dataset_of(request)) for request in new_requests}
        )
        if isolated_pair:
            expect(
                len(filtered_datasets) == 1,
                f"filtering one of the two independent providers refetched widgets of datasets "
                f"{filtered_datasets}: the other provider was reached",
            )

        # The page's own right-to-left switch: widgets follow, charts stay left to right.
        rtl_detail: dict[str, Any] | None = None
        toggle = (
            page.locator("label.toggle", has_text="RTL")
            .locator("input[type=checkbox]")
            .first
        )
        if toggle.count():
            toggle.check()
            page.wait_for_timeout(1500)
            # The "embed one widget" section shows the smallest possible integration: a
            # provider that is given no direction. It is left out of the comparison.
            rtl_detail = page.evaluate(
                """() => ({
                  widgetDirs: [...new Set([...document.querySelectorAll('[data-superset-widget]')]
                    .filter(e => !e.closest('.minimal-embed'))
                    .map(e => e.getAttribute('dir')))],
                  widgetsWithoutDirection: document.querySelectorAll(
                    '.minimal-embed [data-superset-widget]').length,
                  chartDirections: [...new Set([...document.querySelectorAll('[data-test^="chart-"] canvas')]
                    .map(c => getComputedStyle(c).direction))],
                  gridRtl: document.querySelectorAll('.ag-root-wrapper.ag-rtl, .ag-rtl .ag-root').length,
                  grids: document.querySelectorAll('.ag-root-wrapper').length,
                })"""
            )
            toggle.uncheck()
            expect(
                rtl_detail["widgetDirs"] == ["rtl"],
                f"with the page switched to RTL the widget roots have dir {rtl_detail['widgetDirs']}",
            )
            expect(
                rtl_detail["chartDirections"] in (["ltr"], []),
                f"chart canvases under RTL compute direction {rtl_detail['chartDirections']}",
            )
            expect(
                rtl_detail["grids"] == 0 or rtl_detail["gridRtl"] > 0,
                "the AG Grid table is not in RTL mode after the switch",
            )
        ctx.expect_no_page_problems(context, "the example app")
        return {
            "url": url,
            "mode": "guest" if guest else "session",
            "data_requests": len(statuses),
            "statuses": sorted(set(statuses)),
            "widgets": summary["widgets"],
            "canvases": summary["canvases"],
            "provider_frames": providers,
            "host_filter": f"{column}={value}",
            "refetched": len(new_requests),
            "refetched_datasets": filtered_datasets,
            "widgets_with_changed_rows": len(changed),
            "rtl": rtl_detail,
        }
    finally:
        fail_shot(page, name)
        context.close()


@check("e", "e1-example-app-session")
def example_session(ctx: Ctx) -> dict[str, Any]:
    """The standalone React example renders widgets with the viewer's Superset session."""
    return example_run(ctx, ctx.example_session, False, "e1-example-app-session")


@check("e", "e2-example-app-guest-token")
def example_guest(ctx: Ctx) -> dict[str, Any]:
    """The standalone React example renders widgets with a guest token from its broker."""
    return example_run(ctx, ctx.example_guest, True, "e2-example-app-guest-token")


@check("e", "e3-cors-preflight")
def cors_preflight(ctx: Ctx) -> dict[str, Any]:
    """The API answers a cross-origin preflight of the host application as configured."""
    origin = ctx.example_session
    response = requests.options(
        f"{ctx.base}/api/v1/dashboard_v2/1",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type,x-guesttoken,x-csrftoken,if-match",
        },
        timeout=30,
    )
    allowed_origin = response.headers.get("Access-Control-Allow-Origin")
    allowed_headers = (
        response.headers.get("Access-Control-Allow-Headers") or ""
    ).lower()
    expect(
        allowed_origin == origin,
        f"preflight from {origin}: Access-Control-Allow-Origin={allowed_origin!r}",
    )
    expect(
        response.headers.get("Access-Control-Allow-Credentials") == "true",
        "preflight: credentials are not allowed (supports_credentials)",
    )
    for header in ("content-type", "x-guesttoken", "x-csrftoken", "if-match"):
        expect(
            header in allowed_headers,
            f"preflight: {header} is not in the allowed headers ({allowed_headers})",
        )
    simple = requests.get(
        f"{ctx.base}/api/v1/widgets/types",
        headers={"Origin": origin, **ctx.admin.headers},
        timeout=30,
    )
    exposed = (simple.headers.get("Access-Control-Expose-Headers") or "").lower()
    expect(
        "etag" in exposed, f"ETag is not exposed to cross-origin readers ({exposed!r})"
    )
    foreign = requests.options(
        f"{ctx.base}/api/v1/widget/data",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "POST",
        },
        timeout=30,
    )
    expect(
        foreign.headers.get("Access-Control-Allow-Origin") is None,
        f"an unlisted origin is allowed: {foreign.headers.get('Access-Control-Allow-Origin')!r}",
    )
    return {
        "origin": origin,
        "allow_headers": allowed_headers,
        "expose_headers": exposed,
    }


# ------------------------------------------------------------------------------- security


@check("f", "f1-guest-token-scoped-to-its-widget")
def guest_widget_scope(ctx: Ctx) -> dict[str, Any]:
    """A guest token for widget A reads A and is refused widget B."""
    props = widget_props(ctx)["metric-tile"]
    widget_a = ctx.save_widget("metric-tile", props, "guest A")
    widget_b = ctx.save_widget("metric-tile", props, "guest B")
    guest = ctx.guest(widget_uuids=[widget_a["uuid"]])
    own = guest.call(
        "POST", "/api/v1/widget/data", data_request(saved_selector(widget_a["uuid"]))
    )
    need_status(own, (200,), "guest reads the widget its token names")
    expect(rows_of(own.json()), "guest got no rows for its own widget")
    detail: dict[str, Any] = {}
    for label, method, path, body in (
        (
            "data of B",
            "POST",
            "/api/v1/widget/data",
            data_request(saved_selector(widget_b["uuid"])),
        ),
        ("definition of B", "GET", f"/api/v1/widget/{widget_b['uuid']}", None),
        (
            "values through B",
            "POST",
            "/api/v1/widget/values",
            saved_selector(widget_b["uuid"]),
        ),
        ("list of saved widgets", "GET", "/api/v1/widget/", None),
        (
            "create a widget",
            "POST",
            "/api/v1/widget/",
            {"widget_type": "markdown", "props": {"content": "x"}},
        ),
        (
            "change A",
            "PUT",
            f"/api/v1/widget/{widget_a['uuid']}",
            {"title": "taken over"},
        ),
        ("delete A", "DELETE", f"/api/v1/widget/{widget_a['uuid']}", None),
        (
            "inline widget without a dataset grant",
            "POST",
            "/api/v1/widget/data",
            data_request(inline_selector("metric-tile", props)),
        ),
    ):
        response = guest.call(method, path, body)
        csrf_refusal = (response.status_code == 400 and "CSRF" in response.text) or (
            response.status_code == 302
            and "/login" in response.headers.get("Location", "")
        )
        if method != "GET" and csrf_refusal:
            # A guest cannot obtain a CSRF token (its role lacks the permission), so a
            # write that is not CSRF-exempt is refused before authorisation is reached:
            # with a JSON body as 400, without one as a redirect to the login page.
            detail[label] = f"{response.status_code} (no CSRF token for a guest)"
            continue
        need_status(response, (403,), f"guest token for widget A: {label}")
        detail[label] = response.status_code
    anonymous = Api.anonymous(ctx.base).call(
        "POST", "/api/v1/widget/data", data_request(saved_selector(widget_a["uuid"]))
    )
    need_status(anonymous, (401,), "widget data without any credentials")
    forged = Api.guest(ctx.base, "not-a-token").call(
        "POST", "/api/v1/widget/data", data_request(saved_selector(widget_a["uuid"]))
    )
    need_status(forged, (401, 403), "widget data with a forged guest token")
    detail["anonymous"], detail["forged_token"] = (
        anonymous.status_code,
        forged.status_code,
    )
    return detail


@check("f", "f2-dashboard-token-with-datasets-cannot-use-inline-widgets")
def dashboard_token_inline(ctx: Ctx) -> dict[str, Any]:
    """A dashboard-scoped guest token that lists datasets is not a grant for inline widgets."""
    births = ctx.datasets["birth_names"]
    created = ctx.create_dashboard("embedded", standard_document(ctx))
    embedded = ctx.admin.json(
        "POST",
        f"/api/v1/dashboard/{created['id']}/embedded",
        {"allowed_domains": []},
        what="enable embedding of the dashboard",
    )["result"]
    guest = ctx.guest(dashboard_uuids=[embedded["uuid"]], dataset_allowlist=[births])
    response = guest.call(
        "POST",
        "/api/v1/widget/data",
        data_request(
            inline_selector(
                "ag-grid-table",
                {"dataBinding": binding(births, ["count"], ["name", "state"])},
            )
        ),
    )
    need_status(
        response,
        (403,),
        "inline widget with a dashboard-scoped token whose `datasets` claim lists the dataset "
        "(the claim narrows a dashboard token; it must not grant arbitrary inline queries)",
    )
    values = guest.call(
        "POST",
        "/api/v1/widget/values",
        inline_selector("filter.select", {"datasetId": births, "column": "name"}),
    )
    need_status(
        values, (403,), "inline filter values with the same dashboard-scoped token"
    )
    return {
        "embedded_uuid": embedded["uuid"],
        "inline_data": response.status_code,
        "inline_values": values.status_code,
    }


@check("f", "f3-inline-grant-is-per-dataset")
def inline_grant_per_dataset(ctx: Ctx) -> dict[str, Any]:
    """An inline grant for one dataset serves that dataset and no other."""
    births, games = ctx.datasets["birth_names"], ctx.datasets["video_game_sales"]
    guest = ctx.guest(inline_dataset_ids=[births])
    granted = guest.call(
        "POST",
        "/api/v1/widget/data",
        data_request(
            inline_selector("metric-tile", {"dataBinding": binding(births, ["count"])})
        ),
    )
    need_status(granted, (200,), "inline widget on the granted dataset")
    outside = guest.call(
        "POST",
        "/api/v1/widget/data",
        data_request(
            inline_selector("metric-tile", {"dataBinding": binding(games, ["count"])})
        ),
    )
    need_status(outside, (403,), "inline widget on a dataset outside the grant")
    outside_values = guest.call(
        "POST",
        "/api/v1/widget/values",
        inline_selector("filter.select", {"datasetId": games, "column": "genre"}),
    )
    need_status(
        outside_values, (403,), "inline filter values on a dataset outside the grant"
    )
    missing = guest.call(
        "POST",
        "/api/v1/widget/data",
        data_request(
            inline_selector(
                "metric-tile", {"dataBinding": binding(987654321, ["count"])}
            )
        ),
    )
    need_status(
        missing, (400, 403, 404), "inline widget on a dataset that does not exist"
    )
    return {
        "granted": granted.status_code,
        "outside": outside.status_code,
        "outside_values": outside_values.status_code,
        "missing_dataset": missing.status_code,
    }


def sql_bearing_definitions(dataset_id: int) -> dict[str, dict[str, Any]]:
    """Inline definitions that carry SQL in each place the binding accepts it."""
    sql_metric = {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "n"}
    return {
        "SQL metric": {"dataBinding": binding(dataset_id, [sql_metric])},
        "SQL filter": {
            "dataBinding": {
                **binding(dataset_id, ["count"]),
                "filters": [
                    {
                        "expressionType": "SQL",
                        "clause": "WHERE",
                        "sqlExpression": "1 = 1",
                    }
                ],
            }
        },
        "Jinja in a dimension": {
            "dataBinding": binding(dataset_id, ["count"], ["{{ current_username() }}"])
        },
    }


@check("f", "f4-sql-in-inline-definition-rejected-for-guest")
def sql_rejected_for_guest(ctx: Ctx) -> dict[str, Any]:
    """A guest with an inline grant cannot send a definition that carries SQL."""
    births = ctx.datasets["birth_names"]
    guest = ctx.guest(inline_dataset_ids=[births])
    control = guest.call(
        "POST",
        "/api/v1/widget/data",
        data_request(
            inline_selector("metric-tile", {"dataBinding": binding(births, ["count"])})
        ),
    )
    need_status(control, (200,), "control: SQL-free inline widget with the same token")
    detail: dict[str, Any] = {}
    for label, props in sql_bearing_definitions(births).items():
        response = guest.call(
            "POST",
            "/api/v1/widget/data",
            data_request(inline_selector("metric-tile", props)),
        )
        need_status(
            response, (400, 403, 422), f"guest inline definition with a {label}"
        )
        detail[label] = response.status_code
    return detail


@check("f", "f5-sql-authoring-rule-for-gamma")
def sql_rejected_for_gamma(ctx: Ctx) -> dict[str, Any]:
    """SQL in a definition follows the authoring rule for Gamma and never widens its data."""
    births, games, rls = (
        ctx.datasets[name] for name in ("birth_names", "video_game_sales", RLS_TABLE)
    )
    allowed = (200,) if DATASET_READERS_MAY_AUTHOR_SQL else (403,)
    created = (201,) if DATASET_READERS_MAY_AUTHOR_SQL else (403,)
    rule = (
        "a reader of the dataset may author SQL"
        if DATASET_READERS_MAY_AUTHOR_SQL
        else "only SQL Lab users and dataset editors may author SQL"
    )
    control = ctx.gamma.call(
        "POST",
        "/api/v1/widget/data",
        data_request(
            inline_selector("metric-tile", {"dataBinding": binding(births, ["count"])})
        ),
    )
    need_status(control, (200,), f"control: SQL-free inline widget as {ctx.gamma_name}")

    sql_props = sql_bearing_definitions(births)["SQL metric"]
    inline = ctx.gamma.call(
        "POST",
        "/api/v1/widget/data",
        data_request(inline_selector("metric-tile", sql_props)),
    )
    need_status(
        inline,
        allowed,
        f"inline SQL metric on a readable dataset as {ctx.gamma_name} ({rule})",
    )
    saved = ctx.gamma.call(
        "POST",
        "/api/v1/widget/",
        {"widget_type": "metric-tile", "props": sql_props, "title": f"{PREFIX} sql"},
    )
    if saved.status_code == 201:
        ctx.created_widgets.append(saved.json()["result"]["uuid"])
    need_status(
        saved,
        created,
        f"saving a widget with a SQL metric as {ctx.gamma_name} ({rule})",
    )

    # Whatever the authoring rule is, SQL never reaches data the author cannot read.
    foreign_sql = sql_bearing_definitions(games)["SQL metric"]
    outside = ctx.gamma.call(
        "POST",
        "/api/v1/widget/data",
        data_request(inline_selector("metric-tile", foreign_sql)),
    )
    need_status(
        outside, (403,), f"SQL metric as {ctx.gamma_name} on a dataset it cannot read"
    )
    outside_saved = ctx.gamma.call(
        "POST",
        "/api/v1/widget/",
        {
            "widget_type": "metric-tile",
            "props": foreign_sql,
            "title": f"{PREFIX} foreign sql",
        },
    )
    if outside_saved.status_code == 201:
        ctx.created_widgets.append(outside_saved.json()["result"]["uuid"])
    need_status(
        outside_saved,
        (403,),
        f"saving a SQL widget as {ctx.gamma_name} on a dataset it cannot read",
    )
    subquery = {
        "dataBinding": binding(
            births,
            [
                {
                    "expressionType": "SQL",
                    "label": "leak",
                    "sqlExpression": "(SELECT COUNT(*) FROM video_game_sales)",
                }
            ],
        )
    }
    leak = ctx.gamma.call(
        "POST",
        "/api/v1/widget/data",
        data_request(inline_selector("metric-tile", subquery)),
    )
    need_status(
        leak,
        (400, 403, 422),
        f"SQL metric as {ctx.gamma_name} with a subquery on a table it cannot read",
    )

    detail: dict[str, Any] = {
        "rule": rule,
        "inline": inline.status_code,
        "saved": saved.status_code,
        "foreign_dataset": outside.status_code,
        "subquery": leak.status_code,
    }
    rls_sql = {
        "dataBinding": binding(
            rls, [{"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "n"}]
        )
    }
    request = data_request(inline_selector("metric-tile", rls_sql))
    admin_count = rows_of(ctx.admin.json("POST", "/api/v1/widget/data", request))[0][
        "n"
    ]
    gamma_response = ctx.gamma.call("POST", "/api/v1/widget/data", request)
    need_status(
        gamma_response, allowed, f"SQL metric on the RLS dataset as {ctx.gamma_name}"
    )
    if gamma_response.status_code == 200:
        gamma_count = rows_of(gamma_response.json())[0]["n"]
        expect(
            0 < gamma_count < admin_count,
            f"a SQL metric shows {ctx.gamma_name} {gamma_count} rows of the RLS dataset, the admin "
            f"{admin_count}: the row-level-security rule does not apply to SQL metrics",
        )
        detail["rls_rows_with_sql_metric"] = {
            "admin": admin_count,
            ctx.gamma_name: gamma_count,
        }
    return detail


@check("f", "f6-row-level-security-applies-to-widget-data")
def rls_on_widget_data(ctx: Ctx) -> dict[str, Any]:
    """The RLS rule of the Gamma demo user shows in widget data; a guest brings its own rule."""
    dataset = ctx.datasets[RLS_TABLE]
    props = {"dataBinding": binding(dataset, ["count"], ["region", "product"], 500)}
    request = data_request(inline_selector("ag-grid-table", props))
    admin_rows = rows_of(ctx.admin.json("POST", "/api/v1/widget/data", request))
    gamma_rows = rows_of(ctx.gamma.json("POST", "/api/v1/widget/data", request))
    expect(
        len(distinct(admin_rows, "region")) == 3,
        f"admin sees regions {distinct(admin_rows, 'region')}, expected three",
    )
    expect(
        distinct(gamma_rows, "region") == [RLS_VISIBLE_REGION],
        f"{ctx.gamma_name} sees regions {distinct(gamma_rows, 'region')}, expected only "
        f"{RLS_VISIBLE_REGION!r}: the RLS rule is not applied to widget data",
    )
    expect(
        0 < len(gamma_rows) < len(admin_rows),
        f"row counts: admin {len(admin_rows)}, {ctx.gamma_name} {len(gamma_rows)}",
    )

    saved = ctx.save_widget("ag-grid-table", props, "rls")
    gamma_saved = rows_of(
        ctx.gamma.json(
            "POST", "/api/v1/widget/data", data_request(saved_selector(saved["uuid"]))
        )
    )
    expect(
        distinct(gamma_saved, "region") == [RLS_VISIBLE_REGION],
        f"saved widget as {ctx.gamma_name}: regions {distinct(gamma_saved, 'region')}",
    )
    values = ctx.gamma.json(
        "POST",
        "/api/v1/widget/values",
        inline_selector("filter.select", {"datasetId": dataset, "column": "region"}),
    )
    expect(
        sorted(map(str, values["result"])) == [RLS_VISIBLE_REGION],
        f"filter values as {ctx.gamma_name}: {values['result']}",
    )

    unfiltered = ctx.guest_token(
        guest_token_request(widget_uuids=[saved["uuid"]]), allowed=(400, 403)
    )
    unfiltered_inline = ctx.guest_token(
        guest_token_request(inline_dataset_ids=[dataset]), allowed=(400, 403)
    )
    guest = ctx.guest(
        widget_uuids=[saved["uuid"]], rls=[guest_rls_rule(dataset, "region = 'south'")]
    )
    guest_rows = rows_of(
        guest.json(
            "POST", "/api/v1/widget/data", data_request(saved_selector(saved["uuid"]))
        )
    )
    expect(
        distinct(guest_rows, "region") == ["south"],
        f"guest with rule region = 'south' sees {distinct(guest_rows, 'region')}",
    )
    return {
        "admin_rows": len(admin_rows),
        "gamma_rows": len(gamma_rows),
        "gamma_regions": distinct(gamma_rows, "region"),
        "guest_rows": len(guest_rows),
        "token_without_rule_for_rls_dataset": [
            unfiltered.status_code,
            unfiltered_inline.status_code,
        ],
    }


@check("f", "f9-widget-token-is-bound-to-the-dataset-at-mint")
def widget_token_bound_to_dataset(ctx: Ctx) -> dict[str, Any]:
    """A widget token stops granting data once the widget is pointed at another dataset."""
    births, games = ctx.datasets["birth_names"], ctx.datasets["video_game_sales"]
    widget = ctx.save_widget(
        "metric-tile", {"dataBinding": binding(births, ["count"])}, "rebind"
    )
    guest = ctx.guest(widget_uuids=[widget["uuid"]])
    request = data_request(saved_selector(widget["uuid"]))
    need_status(
        guest.call("POST", "/api/v1/widget/data", request),
        (200,),
        "guest reads the widget before it is changed",
    )
    ctx.admin.json(
        "PUT",
        f"/api/v1/widget/{widget['uuid']}",
        {"props": {"dataBinding": binding(games, ["count"])}},
        what="point the saved widget at another dataset",
    )
    after = guest.call("POST", "/api/v1/widget/data", request)
    need_status(
        after,
        (403,),
        "the token minted for the old dataset after the widget was "
        "pointed at another one",
    )
    fresh = ctx.guest(widget_uuids=[widget["uuid"]])
    need_status(
        fresh.call("POST", "/api/v1/widget/data", request),
        (200,),
        "a token minted after the change",
    )
    return {"before": 200, "after_rebind": after.status_code, "fresh_token": 200}


FLAG_GATED_ROUTES = [
    ("GET", "/api/v1/widgets/types"),
    ("GET", "/api/v1/widgets/type/markdown/control-schema"),
    ("GET", "/api/v1/widget/"),
    ("POST", "/api/v1/widget/data"),
    ("POST", "/api/v1/widget/values"),
    ("GET", "/api/v1/dashboard_v2/1"),
    ("POST", "/api/v1/dashboard_v2/"),
    ("GET", "/dashboard/v2/new/"),
    ("GET", "/dashboard/v2/1/"),
]


def compose(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Run docker compose for the nxtbi-widgets project only."""
    return subprocess.run(  # noqa: S603
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "--profile",
            "flag-off",
            *arguments,
        ],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
    )


@check("f", "f7-flag-off-answers-404")
def flag_off(ctx: Ctx) -> dict[str, Any]:
    """With DASHBOARD_V2 off every Widget Framework route answers 404, signed in or not."""
    base = ctx.flag_off_base
    started = False
    if not reachable(f"{base}/health"):
        if not ctx.args.manage_flag_off:
            raise Skip(
                f"nothing answers at {base}. Start the flag-off web container with\n"
                "  docker compose -f nxtbi/widgets/docker-compose.yml --profile flag-off up -d "
                "--no-deps --wait superset-flag-off\nor pass --manage-flag-off to have this script "
                "start and remove it (it touches no other container)."
            )
        result = compose("up", "-d", "--no-deps", "--wait", "superset-flag-off")
        expect(
            result.returncode == 0,
            f"could not start superset-flag-off: {result.stderr[-400:]}",
        )
        started = True
    try:
        control = requests.get(f"{ctx.base}/api/v1/widgets/types", timeout=30)
        expect(
            control.status_code == 401,
            f"control: anonymous GET /api/v1/widgets/types on the flag-on server -> {control.status_code}",
        )
        alive = requests.get(f"{base}/api/v1/chart/", timeout=30)
        expect(
            alive.status_code == 401,
            f"control: anonymous GET /api/v1/chart/ on the flag-off server -> {alive.status_code}",
        )
        admin = Api.login(base, ctx.admin_name, ctx.env["WIDGETS_ADMIN_PASSWORD"])
        problems: list[str] = []
        csrf_first: list[str] = []
        for principal in (Api.anonymous(base), admin):
            for method, path in FLAG_GATED_ROUTES:
                response = principal.call(
                    method, path, {} if method == "POST" else None
                )
                if response.status_code == 404:
                    continue
                what = f"{method} {path} as {principal.label} -> {response.status_code}"
                if (
                    principal.label == "anonymous"
                    and response.status_code == 400
                    and "CSRF" in response.text
                ):
                    # The CSRF check of a write without a token runs before the flag
                    # gate. No gated code ran; the same route answers 404 to the
                    # signed-in caller, who does send a token.
                    csrf_first.append(what)
                else:
                    problems.append(what)
        expect(
            not problems,
            "routes that do not answer 404 with DASHBOARD_V2 off: "
            + "; ".join(problems),
        )
        return {
            "flag_off_url": base,
            "routes": len(FLAG_GATED_ROUTES),
            "principals": 2,
            "answered_by_csrf_check_before_the_gate": csrf_first,
            "container_managed_by_script": started,
        }
    finally:
        if started:
            compose("rm", "-sf", "superset-flag-off")


@check("f", "f8-guest-role-holds-only-widget-permissions")
def guest_role_minimal(ctx: Ctx) -> dict[str, Any]:
    """The purpose-built guest role cannot use the rest of the API."""
    props = widget_props(ctx)["metric-tile"]
    widget = ctx.save_widget("metric-tile", props, "guest role")
    guest = ctx.guest(widget_uuids=[widget["uuid"]])
    types = guest.call("GET", "/api/v1/widgets/types")
    need_status(types, (200,), "guest lists widget types (can read on Chart)")
    detail: dict[str, Any] = {"widget_types": types.status_code}
    for path in (
        "/api/v1/dataset/",
        "/api/v1/database/",
        "/api/v1/security/roles/",
        "/api/v1/saved_query/",
        "/api/v1/sqllab/",
    ):
        response = guest.call("GET", path)
        need_status(response, (401, 403, 404), f"guest GET {path}")
        detail[path] = response.status_code
    sql = guest.call(
        "POST", "/api/v1/sqllab/execute/", {"database_id": 1, "sql": "select 1"}
    )
    need_status(sql, (400, 401, 403), "guest runs SQL Lab")
    detail["sqllab_execute"] = sql.status_code
    return detail


# ----------------------------------------------------------------------------------- REST


@check("g", "g1-saved-widget-crud")
def saved_widget_crud(ctx: Ctx) -> dict[str, Any]:
    """Create, read, list, update and delete a saved widget; invalid input is a 400."""
    created = ctx.save_widget("markdown", {"content": "first"}, "crud")
    ref = created["uuid"]
    expect(
        created["widget_type"] == "markdown"
        and created["props"] == {"content": "first"},
        f"created widget echoes {created}",
    )
    fetched = ctx.admin.json("GET", f"/api/v1/widget/{ref}")["result"]
    expect(
        fetched["uuid"] == ref and fetched["props"]["content"] == "first",
        f"GET returned {fetched}",
    )
    listed = ctx.admin.json("GET", "/api/v1/widget/")["result"]
    expect(
        any(item["uuid"] == ref for item in listed), "the new widget is not in the list"
    )
    updated = ctx.admin.json(
        "PUT",
        f"/api/v1/widget/{ref}",
        {"props": {"content": "second"}, "title": f"{PREFIX} renamed"},
    )["result"]
    expect(
        updated["props"]["content"] == "second"
        and updated["title"] == f"{PREFIX} renamed",
        f"PUT returned {updated}",
    )
    statuses = {
        "unknown type": ctx.admin.call(
            "POST", "/api/v1/widget/", {"widget_type": "no-such-widget", "props": {}}
        ),
        "invalid props": ctx.admin.call(
            "POST", "/api/v1/widget/", {"widget_type": "markdown", "props": {}}
        ),
        "missing props": ctx.admin.call(
            "POST", "/api/v1/widget/", {"widget_type": "markdown"}
        ),
        "invalid props on update": ctx.admin.call(
            "PUT", f"/api/v1/widget/{ref}", {"props": {"content": 5}}
        ),
    }
    for label, response in statuses.items():
        need_status(response, (400, 422), f"saved widget, {label}")
    foreign_put = ctx.gamma.call("PUT", f"/api/v1/widget/{ref}", {"title": "not yours"})
    need_status(foreign_put, (403,), f"{ctx.gamma_name} changes the admin's widget")
    foreign_delete = ctx.gamma.call("DELETE", f"/api/v1/widget/{ref}")
    need_status(foreign_delete, (403,), f"{ctx.gamma_name} deletes the admin's widget")
    gamma_list = ctx.gamma.json("GET", "/api/v1/widget/")["result"]
    expect(
        not any(item["uuid"] == ref for item in gamma_list),
        f"{ctx.gamma_name} lists the admin's widget",
    )
    need_status(
        ctx.admin.call("GET", f"/api/v1/widget/{uuid.uuid4()}"),
        (404,),
        "GET of an unknown uuid",
    )
    need_status(
        ctx.admin.call("DELETE", f"/api/v1/widget/{ref}"),
        (200,),
        "DELETE of the widget",
    )
    ctx.created_widgets.remove(ref)
    need_status(
        ctx.admin.call("GET", f"/api/v1/widget/{ref}"), (404,), "GET after the delete"
    )
    types = {
        item["id"] for item in ctx.admin.json("GET", "/api/v1/widgets/types")["result"]
    }
    expect(
        BUILTIN_TYPES <= types,
        f"widget types {sorted(types)} lack {sorted(BUILTIN_TYPES - types)}",
    )
    schema = ctx.admin.json("GET", "/api/v1/widgets/type/metric-tile/control-schema")[
        "result"
    ]
    expect(
        "dataBinding" in schema.get("properties", {}),
        "control schema of metric-tile has no dataBinding",
    )
    validation = ctx.admin.json(
        "POST", "/api/v1/widgets/type/markdown/validate", {"control_values": {}}
    )["result"]
    expect(validation["errors"], "validating empty markdown props reports no error")
    return {
        "uuid": ref,
        "invalid": {k: v.status_code for k, v in statuses.items()},
        "widget_types": sorted(types),
    }


@check("g", "g2-dashboard-v2-create-read-update")
def dashboard_v2_crud(ctx: Ctx) -> dict[str, Any]:
    """POST stores revision 1; each PUT on the current revision stores the next one."""
    title = f"{PREFIX} crud {uuid.uuid4().hex[:8]}"
    created = ctx.admin.call(
        "POST", "/api/v1/dashboard_v2/", v2_create_body(title, markdown_document("one"))
    )
    need_status(created, (201,), "POST /api/v1/dashboard_v2/")
    result = created.json()["result"]
    pk = int(result["id"])
    ctx.created_dashboards.append(pk)
    expect(
        v2_revision(created.json()) == 1 and v2_etag(created) == "1",
        f"create: revision {result['revision']}, ETag {created.headers.get('ETag')!r}",
    )
    expect("revision" not in result["document"], "the revision leaks into the document")

    fetched = ctx.admin.call("GET", f"/api/v1/dashboard_v2/{pk}")
    need_status(fetched, (200,), "GET by id")
    expect(
        fetched.json()["result"]["document"]["nodes"]["node_1"]["props"]["content"]
        == "one",
        "GET returns another document than the one stored",
    )
    by_uuid = ctx.admin.call("GET", f"/api/v1/dashboard_v2/{result['uuid']}")
    need_status(by_uuid, (200,), "GET by uuid")

    body_put = ctx.admin.call(
        "PUT",
        f"/api/v1/dashboard_v2/{pk}",
        v2_update_body(markdown_document("two"), 1, f"{title} v2"),
    )
    need_status(body_put, (200,), "PUT with base_revision in the body")
    expect(
        v2_revision(body_put.json()) == 2 and v2_etag(body_put) == "2",
        f"first update: revision {v2_revision(body_put.json())}, ETag {body_put.headers.get('ETag')!r}",
    )
    expect(
        body_put.json()["result"]["dashboard_title"] == f"{title} v2",
        "the title was not updated",
    )

    header_put = ctx.admin.call(
        "PUT",
        f"/api/v1/dashboard_v2/{pk}",
        v2_update_body(markdown_document("three"), None),
        v2_if_match(2),
    )
    need_status(header_put, (200,), "PUT with If-Match")
    expect(
        v2_revision(header_put.json()) == 3,
        f"second update: revision {v2_revision(header_put.json())}",
    )
    final = ctx.admin.json("GET", f"/api/v1/dashboard_v2/{pk}")["result"]
    expect(
        final["document"]["nodes"]["node_1"]["props"]["content"] == "three"
        and final["revision"] == 3,
        f"stored after two updates: revision {final['revision']}",
    )

    need_status(
        ctx.admin.call("GET", "/api/v1/dashboard_v2/987654321"),
        (404,),
        "GET of an unknown id",
    )
    need_status(
        Api.anonymous(ctx.base).call("GET", f"/api/v1/dashboard_v2/{pk}"),
        (401,),
        "anonymous GET",
    )
    foreign = ctx.gamma.call(
        "PUT", f"/api/v1/dashboard_v2/{pk}", v2_update_body(markdown_document("x"), 3)
    )
    need_status(foreign, (403, 404), f"{ctx.gamma_name} updates the admin's dashboard")
    after = ctx.admin.json("GET", f"/api/v1/dashboard_v2/{pk}")["result"]
    expect(after["revision"] == 3, "a refused update changed the revision")

    # A create that names a client uuid can be repeated: the answer is the same dashboard.
    client_uuid = str(uuid.uuid4())
    body = v2_create_body(f"{title} idempotent", markdown_document("once"), client_uuid)
    first = ctx.admin.call("POST", "/api/v1/dashboard_v2/", body)
    need_status(first, (201,), "POST with a client uuid")
    ctx.created_dashboards.append(int(first.json()["result"]["id"]))
    repeat = ctx.admin.call("POST", "/api/v1/dashboard_v2/", body)
    need_status(repeat, (200,), "the same POST with the same client uuid again")
    expect(
        repeat.json()["result"]["id"] == first.json()["result"]["id"],
        f"the repeated create answered dashboard {repeat.json()['result']['id']}, "
        f"the first {first.json()['result']['id']}",
    )
    return {
        "id": pk,
        "revisions": [1, 2, 3],
        "foreign_update": foreign.status_code,
        "repeated_create": repeat.status_code,
    }


@check("g", "g3-stale-revision-409")
def stale_revision(ctx: Ctx) -> dict[str, Any]:
    """A save on an old revision is a 409 and writes nothing; no revision at all is a 428."""
    created = ctx.create_dashboard("stale", markdown_document("one"))
    pk = int(created["id"])
    path = f"/api/v1/dashboard_v2/{pk}"
    ctx.admin.json("PUT", path, v2_update_body(markdown_document("two"), 1))

    stale = ctx.admin.call("PUT", path, v2_update_body(markdown_document("stale"), 1))
    need_status(stale, (409,), "PUT on a stale base revision")
    expect(v2_conflict_revision(stale.json()) == 2, f"409 body reports {stale.json()}")
    expect(v2_etag(stale) == "2", f"409 ETag is {stale.headers.get('ETag')!r}")
    ahead = ctx.admin.call("PUT", path, v2_update_body(markdown_document("ahead"), 7))
    need_status(ahead, (409,), "PUT on a base revision ahead of the stored one")
    stale_header = ctx.admin.call(
        "PUT", path, v2_update_body(markdown_document("stale"), None), v2_if_match(1)
    )
    need_status(stale_header, (409,), "PUT with a stale If-Match")
    missing = ctx.admin.call(
        "PUT", path, v2_update_body(markdown_document("none"), None)
    )
    need_status(missing, (428,), "PUT without a base revision")
    disagree = ctx.admin.call(
        "PUT", path, v2_update_body(markdown_document("x"), 2), v2_if_match(1)
    )
    need_status(disagree, (400,), "PUT whose If-Match and base_revision disagree")
    text_revision = ctx.admin.call(
        "PUT", path, {"document": markdown_document("x"), "base_revision": "2"}
    )
    need_status(text_revision, (400,), "PUT with base_revision as a string")
    wildcard = ctx.admin.call(
        "PUT", path, v2_update_body(markdown_document("x"), None), {"If-Match": "*"}
    )
    need_status(wildcard, (400,), "PUT with If-Match: *")

    stored = ctx.admin.json("GET", path)["result"]
    expect(
        stored["revision"] == 2
        and stored["document"]["nodes"]["node_1"]["props"]["content"] == "two",
        f"after the refused saves: revision {stored['revision']}, content "
        f"{stored['document']['nodes']['node_1']['props']['content']!r}",
    )
    return {
        "id": pk,
        "stale": 409,
        "ahead": 409,
        "missing": missing.status_code,
        "current_revision": v2_conflict_revision(stale.json()),
    }


def invalid_documents() -> dict[str, dict[str, Any]]:
    """Documents the server must refuse with a 422, by what is wrong with them."""

    def doc(nodes: dict[str, Any]) -> dict[str, Any]:
        return {"version": 1, "nodes": nodes}

    def md() -> dict[str, Any]:
        return {"type": "markdown", "props": {"content": "x"}}

    grid = {"type": "grid", "layout": {"columns": 24}}
    deep: dict[str, Any] = {"root": {**grid, "children": ["d_1"]}}
    for level in range(1, 20):
        deep[f"d_{level}"] = {**grid, "children": [f"d_{level + 1}"]}
    deep["d_20"] = md()
    many: dict[str, Any] = {
        "root": {**grid, "children": [f"m_{i}" for i in range(520)]}
    }
    for index in range(520):
        many[f"m_{index}"] = md()
    return {
        "cycle": doc(
            {
                "root": {**grid, "children": ["a"]},
                "a": {**grid, "children": ["b"]},
                "b": {**grid, "children": ["a"]},
            }
        ),
        "self reference": doc(
            {"root": {**grid, "children": ["a"]}, "a": {**grid, "children": ["a"]}}
        ),
        "cycle through root": doc(
            {"root": {**grid, "children": ["a"]}, "a": {**grid, "children": ["root"]}}
        ),
        "node under two parents": doc(
            {
                "root": {**grid, "children": ["a", "b"]},
                "a": {**grid, "children": ["c"]},
                "b": {**grid, "children": ["c"]},
                "c": md(),
            }
        ),
        "orphan": doc({"root": {**grid, "children": ["a"]}, "a": md(), "lost": md()}),
        "missing child": doc({"root": {**grid, "children": ["ghost"]}}),
        "duplicate child": doc({"root": {**grid, "children": ["a", "a"]}, "a": md()}),
        "no root": doc({"a": md()}),
        "unknown widget type": doc(
            {
                "root": {**grid, "children": ["a"]},
                "a": {"type": "no-such-widget", "props": {}},
            }
        ),
        # A prop that is present with a wrong type. A prop that is merely missing is
        # accepted, so that an unconfigured widget can be saved.
        "invalid props": doc(
            {
                "root": {**grid, "children": ["a"]},
                "a": {"type": "markdown", "props": {"content": 5}},
            }
        ),
        "bad node id": doc(
            {"root": {**grid, "children": ["bad id!"]}, "bad id!": md()}
        ),
        "wrong version": {"version": 2, "nodes": {"root": {**grid, "children": []}}},
        "too deep": doc(deep),
        "too many nodes": doc(many),
    }


@check("g", "g4-invalid-documents-422")
def invalid_documents_rejected(ctx: Ctx) -> dict[str, Any]:
    """Cyclic, orphaned, oversized-by-count and otherwise invalid documents are a 422."""
    created = ctx.create_dashboard("invalid", markdown_document("valid"))
    pk = int(created["id"])
    detail: dict[str, Any] = {}
    problems: list[str] = []
    revision = int(created["revision"])
    for label, document in invalid_documents().items():
        update = ctx.admin.call(
            "PUT", f"/api/v1/dashboard_v2/{pk}", v2_update_body(document, revision)
        )
        create = ctx.admin.call(
            "POST",
            "/api/v1/dashboard_v2/",
            v2_create_body(f"{PREFIX} invalid {label}", document),
        )
        if create.status_code in (200, 201):
            ctx.created_dashboards.append(int(create.json()["result"]["id"]))
        if update.status_code == 200:
            # Accepted although it should not be: follow the revision so the
            # remaining documents are still judged on their own.
            revision = v2_revision(update.json())
        detail[label] = [update.status_code, create.status_code]
        if update.status_code != 422 or create.status_code != 422:
            problems.append(
                f"{label}: PUT {update.status_code}, POST {create.status_code}"
            )
    expect(
        not problems, "documents that were not refused with 422: " + "; ".join(problems)
    )
    stored = ctx.admin.json("GET", f"/api/v1/dashboard_v2/{pk}")["result"]
    expect(
        stored["revision"] == created["revision"],
        f"a refused document changed the revision to {stored['revision']}",
    )
    with_errors = ctx.admin.call(
        "PUT",
        f"/api/v1/dashboard_v2/{pk}",
        v2_update_body(invalid_documents()["invalid props"], revision),
    ).json()
    expect(
        "a" in (with_errors.get("errors") or {}),
        f"422 for invalid props does not name the node: {json.dumps(with_errors)[:300]}",
    )
    unconfigured = markdown_document()
    unconfigured["nodes"]["node_2"] = {"type": "echarts"}
    unconfigured["nodes"]["node_3"] = {"type": "markdown", "props": {}}
    unconfigured["nodes"]["root"]["children"] += ["node_2", "node_3"]
    accepted = ctx.admin.call(
        "PUT", f"/api/v1/dashboard_v2/{pk}", v2_update_body(unconfigured, revision)
    )
    need_status(
        accepted, (200,), "a document with freshly placed, unconfigured widgets"
    )
    detail["unconfigured widgets"] = accepted.status_code
    return detail


@check("g", "g5-oversized-and-malformed-bodies")
def oversized_and_malformed(ctx: Ctx) -> dict[str, Any]:
    """A body above the size limit is a 413; malformed JSON and unknown fields are a 400."""
    created = ctx.create_dashboard("oversized", markdown_document("valid"))
    path = f"/api/v1/dashboard_v2/{created['id']}"
    big = markdown_document("x" * (1_200_000))

    def send_oversized(method: str, target: str, body: dict[str, Any]) -> int | str:
        """The status of an oversized request, or how the server cut it off.

        A server that answers 413 from the Content-Length header may close the
        connection while the client still uploads; that is a refusal as well, and
        the stored revision is checked below either way.
        """
        try:
            response = ctx.admin.call(method, target, body)
        except requests.ConnectionError:
            return "connection closed during the upload"
        if response.status_code == 201:
            ctx.created_dashboards.append(int(response.json()["result"]["id"]))
        need_status(response, (413,), f"{method} with a 1.2 MB body (limit 1 MiB)")
        return response.status_code

    oversized = send_oversized("PUT", path, v2_update_body(big, 1))
    oversized_post = send_oversized(
        "POST", "/api/v1/dashboard_v2/", v2_create_body(f"{PREFIX} big", big)
    )
    leftovers = [
        item
        for item in ctx.admin.json("GET", "/api/v1/dashboard/?q=(page_size:100)")[
            "result"
        ]
        if item.get("dashboard_title") == f"{PREFIX} big"
    ]
    expect(not leftovers, "the oversized POST created a dashboard")

    duplicate = (
        b'{"base_revision": 1, "document": {"version": 1, "nodes": {'
        b'"root": {"type": "grid", "children": ["a"]}, '
        b'"a": {"type": "markdown", "props": {"content": "1"}}, '
        b'"a": {"type": "markdown", "props": {"content": "2"}}}}}'
    )
    cases = {
        "duplicate node id": ctx.admin.call("PUT", path, raw=duplicate),
        "not JSON": ctx.admin.call("PUT", path, raw=b"{not json"),
        "NaN": ctx.admin.call(
            "PUT", path, raw=b'{"base_revision": 1, "document": {"version": NaN}}'
        ),
        "array body": ctx.admin.call("PUT", path, raw=b"[]"),
        "unknown field": ctx.admin.call(
            "PUT", path, {**v2_update_body(markdown_document(), 1), "owner": 1}
        ),
        "missing document": ctx.admin.call("PUT", path, {"base_revision": 1}),
        "missing title on create": ctx.admin.call(
            "POST", "/api/v1/dashboard_v2/", {"document": markdown_document()}
        ),
        "deeply nested body": ctx.admin.call(
            "PUT",
            path,
            raw=b'{"base_revision": 1, "document": ' + b"[" * 5000 + b"]" * 5000 + b"}",
        ),
    }
    for label, response in cases.items():
        need_status(response, (400,), f"Dashboard V2 body, {label}")
    stored = ctx.admin.json("GET", path)["result"]
    expect(
        stored["revision"] == 1,
        f"a refused body changed the revision to {stored['revision']}",
    )
    return {
        "oversized_put": oversized,
        "oversized_post": oversized_post,
        **{k: v.status_code for k, v in cases.items()},
    }


# ------------------------------------------------------------------------- RTL and MCP


@check("h", "h1-arabic-rtl-builder-and-widgets")
def arabic_rtl(ctx: Ctx) -> dict[str, Any]:
    """Under Arabic the builder is right-to-left, AG Grid is RTL and charts stay LTR."""
    created = ctx.create_dashboard("rtl", standard_document(ctx))
    context = ctx.new_context()
    page = context.new_page()

    def measure(locale: str) -> dict[str, Any]:
        page.goto(f"{ctx.base}/lang/{locale}", wait_until="domcontentloaded")
        open_saved(page, ctx.base, int(created["id"]))
        need(
            page,
            f"{content(NODE_IDS['ag-grid-table'])} .ag-root-wrapper",
            f"AG Grid ({locale})",
        )
        need(page, f"{content(NODE_IDS['echarts'])} canvas", f"chart canvas ({locale})")
        page.wait_for_timeout(1500)
        summary = expect_widgets_rendered(page, NODE_IDS, f"locale {locale}")
        panel = need(
            page, SELECTORS["editor_panel"], f"editor panel ({locale})"
        ).bounding_box()
        canvas = need(page, SELECTORS["canvas"], f"canvas ({locale})").bounding_box()
        summary["panel_right_of_canvas"] = (panel["x"] + panel["width"] / 2) > (
            canvas["x"] + canvas["width"] / 2
        )
        summary["hscroll"] = page.evaluate(
            "() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2"
        )
        summary["markdown_direction"] = page.evaluate(
            "sel => { const e = document.querySelector(sel); return e ? getComputedStyle(e).direction : null; }",
            content(NODE_IDS["markdown"]),
        )
        return summary

    try:
        arabic = measure("ar")
        english = measure("en")
        problems: list[str] = []
        if arabic["dir"] != "rtl" or arabic["lang"] != "ar":
            problems.append(
                f"Arabic page is <html dir={arabic['dir']!r} lang={arabic['lang']!r}>"
            )
        if english["dir"] not in ("ltr", None):
            problems.append(f"English page is <html dir={english['dir']!r}>")
        if arabic["gridRtl"] < 1:
            problems.append("AG Grid is not in RTL mode under Arabic (no .ag-rtl)")
        if english["gridRtl"] > 0:
            problems.append("AG Grid stays in RTL mode under English")
        if not arabic["chartDirections"] or any(
            d != "ltr" for d in arabic["chartDirections"]
        ):
            problems.append(
                f"chart canvases under Arabic compute direction {arabic['chartDirections']}"
            )
        if arabic["panel_right_of_canvas"] == english["panel_right_of_canvas"]:
            problems.append(
                "the editor panel is on the same side of the canvas in Arabic and English"
            )
        if arabic["hscroll"]:
            problems.append("the Arabic builder page scrolls horizontally")
        if arabic["markdown_direction"] != "rtl":
            problems.append(
                f"markdown widget direction under Arabic is {arabic['markdown_direction']!r}"
            )
        expect(not problems, " | ".join(problems))
        ctx.expect_no_page_problems(context, "Arabic and English builder")
        return {"ar": arabic, "en": english}
    finally:
        fail_shot(page, "h1-arabic-rtl-builder-and-widgets")
        try:
            page.goto(f"{ctx.base}/lang/en", wait_until="domcontentloaded")
        except Exception:  # noqa: BLE001
            pass
        context.close()


def mcp_token(username: str, secret: str, ttl: int = 600) -> str:
    """An HS256 bearer token the MCP service of this stack accepts for ``username``."""

    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    claims = {
        "iss": MCP_ISSUER,
        "aud": MCP_AUDIENCE,
        "sub": username,
        "preferred_username": username,
        "client_id": f"{PREFIX}-mcp",
        "iat": now,
        "nbf": now - 5,
        "exp": now + ttl,
        "jti": uuid.uuid4().hex,
    }
    signing_input = (
        f"{b64(json.dumps(header, separators=(',', ':')).encode())}."
        f"{b64(json.dumps(claims, separators=(',', ':')).encode())}"
    )
    signature = hmac.new(
        secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{signing_input}.{b64(signature)}"


def mcp_call(
    ctx: Ctx,
    method: str,
    params: dict[str, Any] | None,
    session_id: str | None,
    request_id: int | None,
    token: str | None,
) -> tuple[Any, str | None]:
    """One JSON-RPC message to the MCP server over streamable HTTP: (result, session id)."""
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        body["id"] = request_id
    if params is not None:
        body["params"] = params
    response = requests.post(f"{ctx.mcp}/mcp", headers=headers, json=body, timeout=120)
    sid = response.headers.get("Mcp-Session-Id") or session_id
    if request_id is None:
        return response.status_code, sid
    expect(
        response.status_code == 200,
        f"MCP {method} -> {response.status_code} {response.text[:200]}",
    )
    if "text/event-stream" in response.headers.get("Content-Type", ""):
        response.encoding = "utf-8"
        messages = [
            json.loads(line[5:].strip())
            for line in response.text.splitlines()
            if line.startswith("data:")
        ]
        message = next(
            (item for item in messages if item.get("id") == request_id), None
        )
        expect(
            message is not None,
            f"MCP {method}: no answer with id {request_id} in the event stream",
        )
    else:
        message = response.json()
    expect("error" not in message, f"MCP {method} error: {message.get('error')}")
    return message["result"], sid


def tool_result(result: dict[str, Any], tool: str) -> Any:
    """The structured content of a tools/call answer."""
    expect(
        not result.get("isError"),
        f"MCP tool {tool} failed: {str(result.get('content'))[:300]}",
    )
    if result.get("structuredContent") is not None:
        return result["structuredContent"]
    text = "".join(
        item.get("text", "")
        for item in result.get("content", [])
        if item.get("type") == "text"
    )
    try:
        return json.loads(text)
    except ValueError:
        return text


@check("h", "h2-mcp-widget-tools")
def mcp_widget_tools(ctx: Ctx) -> dict[str, Any]:
    """The MCP server lists the widget tools; list_widget_types and get_widget_data answer."""
    if not reachable(f"{ctx.mcp}/health"):
        raise Skip(
            f"nothing answers at {ctx.mcp}. Start the optional MCP service with\n"
            "  docker compose -f nxtbi/widgets/docker-compose.yml --profile mcp up -d superset-mcp"
        )
    token = mcp_token(ctx.admin_name, ctx.env["MCP_JWT_SECRET"])
    unauthenticated = requests.post(
        f"{ctx.mcp}/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        timeout=30,
    ).status_code
    expect(
        unauthenticated in (401, 403),
        f"MCP without a bearer token -> {unauthenticated}",
    )
    _, sid = mcp_call(
        ctx,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": PREFIX, "version": "1"},
        },
        None,
        1,
        token,
    )
    mcp_call(ctx, "notifications/initialized", None, sid, None, token)
    listed, _ = mcp_call(ctx, "tools/list", {}, sid, 2, token)
    names = {tool["name"] for tool in listed.get("tools", [])}
    wanted = {
        "list_widget_types",
        "get_widget_control_schema",
        "list_saved_widgets",
        "get_saved_widget",
        "get_widget_data",
    }
    expect(
        wanted <= names,
        f"MCP tools/list lacks {sorted(wanted - names)} (of {len(names)} tools)",
    )
    expect(
        "set_widget_control_values" not in names,
        "the removed tool set_widget_control_values is listed",
    )

    types_result, _ = mcp_call(
        ctx, "tools/call", {"name": "list_widget_types", "arguments": {}}, sid, 3, token
    )
    types = tool_result(types_result, "list_widget_types")
    type_ids = {item["id"] for item in types.get("widget_types", [])}
    expect(BUILTIN_TYPES <= type_ids, f"list_widget_types returned {sorted(type_ids)}")

    props = widget_props(ctx)["ag-grid-table"]
    saved = ctx.save_widget("ag-grid-table", props, "mcp")
    rest_rows = rows_of(
        ctx.admin.json(
            "POST", "/api/v1/widget/data", data_request(saved_selector(saved["uuid"]))
        )
    )
    data_result, _ = mcp_call(
        ctx,
        "tools/call",
        {"name": "get_widget_data", "arguments": {"request": {"id": saved["uuid"]}}},
        sid,
        4,
        token,
    )
    data = tool_result(data_result, "get_widget_data")
    mcp_rows = data.get("rows") if isinstance(data, dict) else None
    if mcp_rows is None and isinstance(data, dict):
        mcp_rows = (data.get("result") or data.get("data") or {}).get("rows")
    expect(
        isinstance(mcp_rows, list) and mcp_rows,
        f"get_widget_data returned no rows: {json.dumps(data)[:300]}",
    )
    expect(
        len(mcp_rows) == len(rest_rows),
        f"get_widget_data returned {len(mcp_rows)} rows, the REST endpoint {len(rest_rows)}",
    )
    inline_result, _ = mcp_call(
        ctx,
        "tools/call",
        {
            "name": "get_widget_data",
            "arguments": {
                "request": {
                    "id": saved["uuid"],
                    "widget": {"type": "markdown", "props": {}},
                }
            },
        },
        sid,
        5,
        token,
    )
    expect(
        inline_result.get("isError") or "error" in json.dumps(inline_result).lower(),
        "get_widget_data accepted an inline `widget` key; the tool takes a saved widget only",
    )
    return {
        "tools": len(names),
        "widget_types": sorted(type_ids),
        "rows": len(mcp_rows),
    }


# ---------------------------------------------------------------------------------- runner

_FAILED_PAGES: dict[str, Any] = {}


def fail_shot(page: Any, name: str) -> None:
    """Remember the page of a browser check so the runner can screenshot a failure."""
    if sys.exc_info()[0] not in (None, Skip):
        try:
            SHOTS.mkdir(parents=True, exist_ok=True)
            path = SHOTS / f"{name}.png"
            page.screenshot(path=str(path))
            _FAILED_PAGES[name] = str(path.relative_to(NXTBI_DIR)).replace("\\", "/")
        except Exception:  # noqa: BLE001 - the page may be gone
            pass


def selected(only: list[str], group: str, name: str) -> bool:
    """Whether --only keeps a check: a group letter or a fragment of the name."""
    return not only or any(
        item == group or (len(item) > 1 and item in name) for item in only
    )


def main() -> int:
    """Run the selected checks; return the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--only", default="", help="comma separated group letters or name fragments"
    )
    parser.add_argument(
        "--api-only", action="store_true", help="skip every check that needs a browser"
    )
    parser.add_argument(
        "--manage-flag-off",
        action="store_true",
        help="start the superset-flag-off container for f7 and remove it afterwards",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="keep the dashboards and widgets the run created",
    )
    parser.add_argument("--headed", action="store_true", help="show the browser")
    parser.add_argument("--list", action="store_true", help="print the checks and exit")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    only = [item.strip() for item in args.only.split(",") if item.strip()]
    if args.list:
        for group, name, fn in CHECKS:
            print(f"{group}  {name}: {(fn.__doc__ or '').strip()}")
        return 0

    env = read_env()
    base = env.get("SUPERSET_PUBLIC_URL", "http://localhost:8089").rstrip("/")
    if not reachable(f"{base}/health"):
        print(
            f"{base}/health does not answer. Start the stack:\n"
            "  docker compose -f nxtbi/widgets/docker-compose.yml up -d",
            file=sys.stderr,
        )
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    try:
        ctx = Ctx(env, args)
    except AssertionError as failure:
        print(f"[FAIL] setup: {failure}")
        RESULTS_FILE.write_text(
            json.dumps(
                {
                    "base": base,
                    "results": [
                        {"check": "setup", "status": "FAIL", "detail": str(failure)}
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return 1

    try:
        for group, name, fn in CHECKS:
            if not selected(only, group, name):
                continue
            started = time.monotonic()
            record: dict[str, Any] = {"check": name, "group": group}
            try:
                record.update({"status": "PASS", "detail": fn(ctx)})
            except Skip as skip:
                record.update({"status": "SKIP", "detail": str(skip)})
            except AssertionError as failure:
                record.update(
                    {"status": "FAIL", "kind": "assertion", "detail": str(failure)}
                )
            except Exception as error:  # noqa: BLE001 - a timeout or a missing element: needs triage
                record.update(
                    {
                        "status": "FAIL",
                        "kind": "error",
                        "detail": f"{type(error).__name__}: {str(error)[:400]}",
                    }
                )
            if record["status"] == "FAIL" and name in _FAILED_PAGES:
                record["screenshot"] = _FAILED_PAGES[name]
            record["seconds"] = round(time.monotonic() - started, 1)
            results.append(record)
            print(
                f"[{record['status']}] {name}: {json.dumps(record['detail'], ensure_ascii=False)[:420]}"
            )
    finally:
        if not args.keep:
            try:
                ctx.cleanup()
            except Exception as error:  # noqa: BLE001
                print(f"cleanup incomplete: {error}", file=sys.stderr)
        ctx.close()

    counts = {
        status: sum(1 for item in results if item["status"] == status)
        for status in ("PASS", "FAIL", "SKIP")
    }
    RESULTS_FILE.write_text(
        json.dumps(
            {
                "base": base,
                "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "counts": counts,
                "results": results,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(
        f"\n{counts['PASS']} passed, {counts['FAIL']} failed, {counts['SKIP']} skipped "
        f"-> {RESULTS_FILE.relative_to(REPO_ROOT)}"
    )
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
