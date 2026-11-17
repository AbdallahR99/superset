"""Render nxtbi/docs/TEST-RESULTS.md from the JSON written by smoke_test.py and browser_check.py.

    python nxtbi/scripts/smoke_test.py && python nxtbi/scripts/browser_check.py
    python nxtbi/scripts/test_report.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GROUP_TITLES = {
    "stack": "Stack, branding and language packs",
    "sso": "Keycloak single sign-on",
    "rls": "Tenant isolation (roles, row level security, SQL Lab)",
    "api": "REST API",
    "mcp": "MCP server",
    "content": "Dashboards and charts",
    "reports": "Alerts and reports",
}


def cell(value: object) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text.replace("|", "\\|").replace("\n", " ")


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(ROOT.parent), *args], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def main() -> int:
    smoke = json.loads((ROOT / "out" / "smoke-results.json").read_text(encoding="utf-8"))
    browser = json.loads((ROOT / "out" / "browser-results.json").read_text(encoding="utf-8"))
    lines = [
        "# NxtBI Superset demo - test results",
        "",
        f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by `nxtbi/scripts/test_report.py` from the last runs of "
        "`smoke_test.py` and `browser_check.py`. Superset source: fork commit "
        f"`{git('rev-parse', '--short=10', 'HEAD')}` (branch `{git('rev-parse', '--abbrev-ref', 'HEAD')}`).",
        "",
        "Every row is a check that was executed against the running stack. Nothing here is inferred.",
        "",
        "| Suite | Passed | Failed |",
        "|---|---|---|",
        f"| HTTP smoke test (`smoke_test.py`) | {sum(r['status'] == 'PASS' for r in smoke)} | {sum(r['status'] != 'PASS' for r in smoke)} |",
        f"| Browser check (`browser_check.py`, Chromium) | {sum(r['status'] == 'PASS' for r in browser['results'])} | "
        f"{sum(r['status'] != 'PASS' for r in browser['results'])} |",
        "",
    ]
    for group, title in GROUP_TITLES.items():
        rows = [r for r in smoke if r["group"] == group]
        if not rows:
            continue
        lines += [f"## {title}", "", "| Result | Check | Observed |", "|---|---|---|"]
        lines += [f"| {r['status']} | {cell(r['check'])} | {cell(r['detail'])} |" for r in rows]
        lines.append("")
    lines += ["## Browser check (real Chromium, Keycloak UI login)", "", "| Result | Check | Observed |", "|---|---|---|"]
    lines += [f"| {r['status']} | {cell(r['check'])} | {cell(r['detail'])} |" for r in browser["results"]]
    lines += ["", f"Browser console errors during the run: {len(browser['console_errors'])}"
              + (" (" + "; ".join(sorted(set(browser["console_errors"]))) + ")" if browser["console_errors"] else "") + ".",
              "Screenshots: `nxtbi/docs/screenshots/`.", ""]
    (ROOT / "docs" / "TEST-RESULTS.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"wrote {ROOT / 'docs' / 'TEST-RESULTS.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
