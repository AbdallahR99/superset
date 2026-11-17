"""Create nxtbi/.env with freshly generated secrets.

Usage:  python nxtbi/scripts/gen_env.py                 (refuses to overwrite)
        python nxtbi/scripts/gen_env.py --add-missing   (keeps every existing value, generates
                                                         secrets that are missing or still a
                                                         placeholder, keeps keys the template
                                                         does not know)

Only the standard library is used. Secrets are never printed. The file is restricted to
the current user where the platform allows it.
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
PLACEHOLDER = "__GENERATE__"


def parse(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def restrict(path: Path) -> None:
    """Best effort: only the current user may read the file."""
    try:
        if os.name == "nt":
            subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{getpass.getuser()}:F"],
                           capture_output=True, check=False)
        else:
            path.chmod(0o600)
    except OSError:
        pass


def main() -> int:
    add_missing = "--add-missing" in sys.argv
    if ENV.exists() and not add_missing:
        print(f"{ENV} already exists; use --add-missing to add new keys only")
        return 1
    existing = parse(ENV) if ENV.exists() else {}
    out: list[str] = []
    seen: set[str] = set()
    generated = kept = 0
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, _, template = line.partition("=")
            key, template = key.strip(), template.strip()
            seen.add(key)
            current = existing.get(key)
            if template == PLACEHOLDER and current in (None, "", PLACEHOLDER):
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
    extras = {k: v for k, v in existing.items() if k not in seen}
    if extras:
        out += ["", "# ---- local additions (not in .env.example) ----------------------------------------"]
        out += [f"{k}={v}" for k, v in extras.items()]
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    restrict(ENV)
    print(f"wrote {ENV}: {generated} secrets generated, {kept} existing values kept, "
          f"{len(extras)} local keys preserved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
