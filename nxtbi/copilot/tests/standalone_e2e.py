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

"""Exercise the authenticated standalone Copilot in a real Chromium browser.

Install Playwright and Chromium, start the Copilot stack, then run:
    python nxtbi/copilot/tests/standalone_e2e.py

Only the two demo credential variables are read from nxtbi/copilot/.env.
The runner sends synthetic content through the configured GovAI service.
"""

from __future__ import annotations

import argparse
import json  # noqa: TID251 - The standalone test runs without Superset.
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import (
    expect,
    Locator,
    Page,
    Request,
    Response,
    sync_playwright,
)

DEMO_ENV = Path(__file__).resolve().parents[1] / ".env"
DEMO_FIELDS = ("NXTBI_COPILOT_DEMO_USERNAME", "NXTBI_COPILOT_DEMO_PASSWORD")
TIMEOUT = 120_000

FORM_PROMPT = (
    "Use render_a2ui to render an interactive form titled "
    "'Browser smoke form'. Include two short text fields: name 'region', label "
    "'Region', initial value 'North'; name 'quarter', label 'Quarter', initial "
    "value 'Q1'. Use component ID 'submit' for the button labeled "
    "'Apply selections'. Use only these "
    "synthetic values and do not read or change any saved assets."
)
TABLE_PROMPT = (
    "Render 'Browser smoke ledger' as an interactive table in "
    "A2UI. Use headings 'Location' and 'Units', and precisely two synthetic "
    "rows ['Cedar', '11'] and ['Juniper', '24']. Do not read any saved data."
)
ARABIC_PROMPT = (
    "أجب بجملة عربية قصيرة تتضمن عبارة «اختبار العربية» دون استخدام الأدوات."
)
CANCEL_PROMPT = "اكتب شرحاً عربياً مطولاً عن تصميم لوحات المعلومات التخيلية."

# Chromium's network debugger may discard completed SSE bodies after rendering.
# Observe a clone of the four test responses while leaving the live fetch and
# the cancellation run untouched.
CAPTURE_STREAMS = """
(() => {
  const originalFetch = window.fetch.bind(window);
  const streams = new Map();
  window.__nxtbiSmokeStreams = streams;
  window.fetch = (input, options) => {
    const result = originalFetch(input, options);
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    if (url.origin !== location.origin || url.pathname !== '/api/run'
        || typeof options?.body !== 'string' || streams.size >= 4) return result;
    const {runId} = JSON.parse(options.body);
    streams.set(runId, {done: false});
    result.then(async response => {
      let body = '';
      try {
        const decoder = new TextDecoder();
        const reader = response.clone().body.getReader();
        for (;;) {
          const {value, done} = await reader.read();
          body += decoder.decode(value, {stream: !done});
          if (done) break;
        }
        streams.set(runId, {done: true, body});
      } catch (error) {
        streams.set(runId, {done: true, body, failed: error.name});
      }
    }, error => streams.set(runId, {done: true, body: '', failed: error.name}));
    return result;
  };
})();
"""


def demo_credentials(env_file: Path) -> tuple[str, str]:
    """Load only the standalone gateway's Basic authentication credentials."""
    username_key, password_key = DEMO_FIELDS
    file_values = {}
    if env_file.is_file():
        with env_file.open(encoding="utf-8-sig") as stream:
            for line in stream:
                key, separator, value = line.strip().partition("=")
                if separator and key.strip() in DEMO_FIELDS:
                    value = value.strip()
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                        value = value[1:-1]
                    file_values[key.strip()] = value
    username = os.environ.get(username_key, file_values.get(username_key, ""))
    password = os.environ.get(password_key, file_values.get(password_key, ""))
    if not username or not password:
        raise ValueError("Standalone demo credentials are missing")
    return username, password


def is_run(request: Request) -> bool:
    """Identify the standalone gateway's authenticated stream request."""
    return request.method == "POST" and urlsplit(request.url).path == "/api/run"


def composer(page: Page) -> Locator:
    """Scope chat controls away from similarly named generated controls."""
    return page.locator(".nxtbi-copilot__composer")


def send(page: Page, text: str, *, arabic: bool = False) -> Response:
    """Send a real chat turn and wait for the gateway stream to start."""
    controls = composer(page)
    controls.get_by_role("textbox").fill(text)
    name = "إرسال" if arabic else "Send"
    with page.expect_response(lambda response: is_run(response.request)) as waiting:
        controls.get_by_role("button", name=name, exact=True).click()
    return waiting.value


def completed_events(page: Page, response: Response) -> list[dict[str, Any]]:
    """Validate and decode an actual completed AG-UI SSE run."""
    assert response.status == 200, f"Gateway returned HTTP {response.status}"
    assert "text/event-stream" in response.headers.get("content-type", "")
    expect(
        composer(page).get_by_role("button", name=re.compile(r"^(Stop|إيقاف)$"))
    ).to_have_count(0, timeout=TIMEOUT)
    run_id = response.request.post_data_json["runId"]
    page.wait_for_function(
        "runId => window.__nxtbiSmokeStreams.get(runId)?.done",
        arg=run_id,
        timeout=TIMEOUT,
    )
    stream = page.evaluate("runId => window.__nxtbiSmokeStreams.get(runId)", run_id)
    events = []
    frames = stream["body"].replace("\r\n", "\n").split("\n\n")
    if stream.get("failed"):
        frames = frames[:-1]  # Only complete frames are meaningful after an abort.
    for frame in frames:
        data = "\n".join(
            line.removeprefix("data:").lstrip(" ")
            for line in frame.splitlines()
            if line.startswith("data:")
        )
        if data and data != "[DONE]":
            events.append(json.loads(data))
    types = [event.get("type") for event in events]
    assert "RUN_STARTED" in types, "The AG-UI stream did not start"
    assert "RUN_ERROR" not in types, "The agent sent an AG-UI RUN_ERROR event"
    assert "RUN_FINISHED" in types, (
        f"The AG-UI stream ended without RUN_FINISHED "
        f"({stream.get('failed') or 'EOF'}, last events: {types[-5:]})"
    )
    expect(page.locator(".nxtbi-copilot__error")).to_have_count(0)
    return events


def check_surface_event(events: list[dict[str, Any]]) -> None:
    """Require the official v1.0 operations in an AG-UI activity snapshot."""
    operations = [
        operation
        for event in events
        if event.get("type") == "ACTIVITY_SNAPSHOT"
        and event.get("activityType") == "a2ui-surface"
        for operation in event["content"]["a2ui_operations"]
    ]
    assert operations, "GovAI did not stream an A2UI activity"
    assert all(operation.get("version") == "1.0" for operation in operations)
    assert any("createSurface" in operation for operation in operations)


def exercise_form(page: Page) -> None:
    """Render a streamed form, edit its binding and send its native action."""
    check_surface_event(completed_events(page, send(page, FORM_PROMPT)))
    region_name = re.compile(r"^region$", re.IGNORECASE)
    form = (
        page.locator("[data-a2ui-surface]")
        .filter(has=page.get_by_role("textbox", name=region_name))
        .last
    )
    region = form.get_by_role("textbox", name=region_name)
    quarter = form.get_by_role("textbox", name=re.compile(r"^quarter$", re.IGNORECASE))
    expect(region).to_have_value("North", timeout=TIMEOUT)
    expect(quarter).to_have_value("Q1")
    region.fill("West")
    expect(region).to_have_value("West")
    surface_id = form.get_attribute("data-a2ui-surface")
    submit = form.get_by_role("button", name=re.compile(r"^apply selections$", re.I))
    with page.expect_response(lambda response: is_run(response.request)) as waiting:
        submit.click()
    response = waiting.value
    completed_events(page, response)
    envelope = response.request.post_data_json["forwardedProps"]["a2uiAction"]
    assert envelope["version"] == "1.0"
    action = envelope["action"]
    assert action["name"] == "nxtbi.submit-form"
    assert action["sourceComponentId"] == "submit"
    assert action["surfaceId"] == surface_id
    assert action["context"] == {"region": "West", "quarter": "Q1"}


def exercise_table(page: Page) -> None:
    """Require a second, structured activity with the requested synthetic data."""
    check_surface_event(completed_events(page, send(page, TABLE_PROMPT)))
    table = (
        page.locator("[data-a2ui-surface]").filter(has_text="Browser smoke ledger").last
    )
    for value in ("Location", "Units", "Cedar", "11", "Juniper", "24"):
        expect(table.get_by_text(value, exact=True)).to_be_visible(timeout=TIMEOUT)
    native_table = table.get_by_role("table")
    if native_table.count():
        expect(native_table.get_by_role("row")).to_have_count(3)
    else:
        expect(table.locator('[data-a2ui-component="Row"]')).to_have_count(3)


def exercise_arabic(page: Page) -> None:
    """Switch the host locale and verify the Arabic chat request and response."""
    locale_name = re.compile(r"^(Arabic|العربية)(\s*\(AR\))?$", re.IGNORECASE)
    picker = page.get_by_role("button", name=locale_name)
    if picker.count():
        picker.first.click()
    else:
        page.get_by_role(
            "combobox", name=re.compile("language|اللغة", re.I)
        ).select_option("ar")
    panel = page.locator(".nxtbi-copilot")
    expect(page.get_by_role("main")).to_have_attribute("dir", "rtl")
    expect(panel).to_have_attribute("dir", "rtl")
    expect(panel).to_have_attribute("lang", re.compile(r"^ar(?:-|$)"))
    expect(composer(page).get_by_role("textbox", name="اسأل المساعد")).to_be_visible()

    response = send(page, ARABIC_PROMPT, arabic=True)
    completed_events(page, response)
    context = response.request.post_data_json["context"]
    assert any(
        entry.get("description") == "locale" and entry.get("value") == "ar"
        for entry in context
    )
    expect(panel.locator(".nxtbi-copilot__message--assistant").last).to_contain_text(
        "اختبار العربية", timeout=TIMEOUT
    )


def exercise_cancel(page: Page) -> None:
    """Cancel a real outgoing run and verify the composer is usable again."""
    controls = composer(page)
    textbox = controls.get_by_role("textbox")
    textbox.fill(CANCEL_PROMPT)
    with page.expect_request(is_run) as waiting:
        controls.get_by_role("button", name="إرسال", exact=True).click()
    request = waiting.value
    stop = controls.get_by_role("button", name="إيقاف", exact=True)
    expect(stop).to_be_visible()
    with page.expect_event(
        "requestfailed", predicate=lambda failed: failed == request, timeout=15_000
    ):
        stop.click()
    assert request.failure, "Chromium did not report an aborted AG-UI request"
    expect(stop).to_have_count(0)
    textbox.fill("اختبار")
    expect(controls.get_by_role("button", name="إرسال", exact=True)).to_be_enabled()


def main() -> int:
    """Run the browser checks without logging credentials or raw payloads."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:5186")
    parser.add_argument("--env", default=DEMO_ENV, type=Path)
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    url = urlsplit(args.url)
    if (
        url.scheme != "http"
        or url.hostname not in {"localhost", "127.0.0.1"}
        or url.username is not None
        or url.password is not None
        or url.path not in {"", "/"}
        or url.query
        or url.fragment
    ):
        parser.error("Use a plain loopback demo origin")
    origin = args.url.rstrip("/")
    username, password = demo_credentials(args.env)

    def redact(message: str) -> str:
        return message.replace(password, "<redacted>").replace(username, "<redacted>")

    errors: list[str] = []
    with sync_playwright() as playwright:
        unauthenticated = playwright.request.new_context()
        try:
            assert unauthenticated.get(origin).status == 401
        finally:
            unauthenticated.dispose()
        print("PASS Basic authentication is required", flush=True)

        browser = playwright.chromium.launch()
        context = browser.new_context(
            http_credentials={
                "username": username,
                "password": password,
                "origin": origin,
            },
            viewport={"width": 1280, "height": 960},
            locale="en-US",
        )
        page = context.new_page()
        page.add_init_script(CAPTURE_STREAMS)
        page.set_default_timeout(TIMEOUT)
        page.on("pageerror", lambda error: errors.append(redact(str(error))))
        page.on(
            "console",
            lambda message: (
                errors.append(redact(message.text))
                if message.type == "error"
                and not re.search(
                    r"401 \(Unauthorized\)|net::ERR_ABORTED", message.text
                )
                else None
            ),
        )
        try:
            response = page.goto(origin, wait_until="domcontentloaded")
            assert response is not None, "Standalone page did not load"
            assert response.ok, "Authenticated standalone page did not load"
            expect(page).to_have_title("NxtBI Copilot workspace")
            expect(
                composer(page).get_by_role("textbox", name="Ask Copilot")
            ).to_be_visible(timeout=TIMEOUT)
            checks = (
                ("Streamed A2UI form and native action", exercise_form),
                ("Streamed A2UI table", exercise_table),
                ("Arabic locale, RTL and Arabic reply", exercise_arabic),
                ("Cancel an in-flight run", exercise_cancel),
            )
            for label, check in checks:
                try:
                    check(page)
                except (
                    Exception
                ) as error:  # report safely without printing request data
                    for browser_error in errors:
                        print(f"FAIL browser runtime: {browser_error}", file=sys.stderr)
                    print(f"FAIL {label}: {redact(str(error))}", file=sys.stderr)
                    return 1
                print(f"PASS {label}", flush=True)

            if args.screenshot:
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(args.screenshot), full_page=True)
            if errors:
                for error in errors:
                    print(f"FAIL browser runtime: {error}", file=sys.stderr)
                return 1
            print("PASS no uncaught browser errors", flush=True)
        finally:
            context.close()
            browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
