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
"""Create nxtbi/widgets/.env with freshly generated secrets.

    python nxtbi/widgets/scripts/gen_env.py                  (refuses to overwrite)
    python nxtbi/widgets/scripts/gen_env.py --add-missing    (keeps every existing value,
                                                              generates what is missing)
    python nxtbi/widgets/scripts/gen_env.py --add-missing --copy-keycloak
                                                             (also copies the KEYCLOAK_* and
                                                              NXTBI_PLATFORM_ADMINS values
                                                              from nxtbi/.env, read-only,
                                                              for NXTBI_WIDGETS_AUTH=keycloak)

The file belongs to the compose project "nxtbi-widgets" and is git-ignored by
nxtbi/widgets/.gitignore. Only the standard library is used. Secrets are never printed.
The file is restricted to the current user where the platform allows it.
"""

from __future__ import annotations

import getpass
import os
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"
MAIN_DEMO_ENV = ROOT.parent / ".env"
PLACEHOLDER = "__GENERATE__"
KEYCLOAK_KEYS = (
    "KEYCLOAK_BROWSER_URL",
    "KEYCLOAK_INTERNAL_URL",
    "KEYCLOAK_REALM",
    "KEYCLOAK_CLIENT_ID",
    "KEYCLOAK_CLIENT_SECRET",
    "KEYCLOAK_SCOPE",
    "NXTBI_PLATFORM_ADMINS",
)


def is_assignment(line: str) -> bool:
    """Whether a line of an env file assigns a value."""
    return bool(line.strip()) and not line.lstrip().startswith("#") and "=" in line


def parse(path: Path) -> dict[str, str]:
    """Read KEY=value pairs from an env file."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if is_assignment(line):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def restrict(path: Path) -> None:
    """Best effort: only the current user may read the file."""
    try:
        if os.name == "nt":
            subprocess.run(  # noqa: S603
                [  # noqa: S607
                    "icacls",
                    str(path),
                    "/inheritance:r",
                    "/grant:r",
                    f"{getpass.getuser()}:F",
                ],
                capture_output=True,
                check=False,
            )
        else:
            path.chmod(0o600)
    except OSError:
        pass


def keycloak_values() -> dict[str, str]:
    """The Keycloak settings of the main demo, read without touching its file."""
    if not MAIN_DEMO_ENV.exists():
        print(f"{MAIN_DEMO_ENV} does not exist: nothing to copy", file=sys.stderr)
        return {}
    main = parse(MAIN_DEMO_ENV)
    return {key: main[key] for key in KEYCLOAK_KEYS if main.get(key)}


def main() -> int:
    """Write the env file; return a process exit code."""
    add_missing = "--add-missing" in sys.argv
    copy_keycloak = "--copy-keycloak" in sys.argv
    if ENV.exists() and not add_missing:
        print(f"{ENV} already exists; use --add-missing to add new keys only")
        return 1
    existing = parse(ENV) if ENV.exists() else {}
    copied = keycloak_values() if copy_keycloak else {}
    out: list[str] = []
    seen: set[str] = set()
    generated = kept = 0
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        if is_assignment(line):
            key, _, template = line.partition("=")
            key, template = key.strip(), template.strip()
            seen.add(key)
            current = existing.get(key)
            if key in copied:
                value = copied[key]
            elif template == PLACEHOLDER and current in (None, "", PLACEHOLDER):
                # 48 random bytes -> 64 URL-safe characters
                value = secrets.token_urlsafe(48)
                generated += 1
            elif current is not None:
                value = current
                kept += 1
            else:
                value = template
            line = f"{key}={value}"
        out.append(line)
    extras = {key: value for key, value in existing.items() if key not in seen}
    if extras:
        out += ["", "# ---- local additions (not in .env.example) ----"]
        out += [f"{key}={value}" for key, value in extras.items()]
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    restrict(ENV)
    print(
        f"wrote {ENV}: {generated} secrets generated, {kept} existing values kept, "
        f"{len(copied)} Keycloak values copied, {len(extras)} local keys preserved"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
