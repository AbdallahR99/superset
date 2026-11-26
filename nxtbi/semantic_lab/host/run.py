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
"""Run the native semantic-view lab in a fresh, loopback-only Superset container."""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import time
from contextlib import suppress
from http.client import HTTPConnection, HTTPException
from pathlib import Path
from uuid import uuid4

HOST = Path(__file__).resolve().parent
LAB = HOST.parent
OUT = LAB.parent / "out" / "semantic-lab"

DEFAULT_IMAGE = "nxtbi/superset-fork:copilot-localization-verified"
LAB_AUTH_ENV = "NXTBI_SEMANTIC_LAB_PASSWORD"

# Every run starts with an empty, container-local metadata database.
BOOTSTRAP = """
superset db upgrade
superset init
superset fab create-admin --username "$NXTBI_SEMANTIC_LAB_USER" \\
    --firstname Lab --lastname Admin --email lab-admin@example.invalid \\
    --password "$NXTBI_SEMANTIC_LAB_PASSWORD"
superset fab create-user --username "$NXTBI_SEMANTIC_LAB_VIEWER" \\
    --firstname Lab --lastname Viewer --email lab-viewer@example.invalid \\
    --role Gamma --password "$NXTBI_SEMANTIC_LAB_VIEWER_PASSWORD"
exec gunicorn --workers 1 --threads 4 --bind 0.0.0.0:8088 'superset.app:create_app()'
"""


def wait_for_health(port: int, timeout: float = 135) -> None:
    """Wait for the loopback web service to serve its health endpoint."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        connection = HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            connection.request("GET", "/health")
            if connection.getresponse().status == 200:
                return
        except (OSError, HTTPException):
            pass
        finally:
            connection.close()
        time.sleep(1)
    raise RuntimeError("Superset health check timed out.")


def run_browser(base_url: str, out: Path, env: dict[str, str]) -> int:
    """Run the checked-in browser flow without passing credentials on the CLI."""
    return subprocess.run(  # noqa: S603 - Local browser smoke test.
        [
            sys.executable,
            "-u",
            str(LAB / "tests" / "browser_smoke.py"),
            "--base-url",
            base_url,
            "--artifact-dir",
            str(out),
        ],
        env=env,
        timeout=360,
        check=False,
    ).returncode


def run_lab(
    image: str, docker_path: str, *, serve: bool, mcp: bool, password: str | None
) -> int:
    """Start one loopback container, run the selected checks, and dispose of it."""
    name = f"nxtbi-semantic-lab-{uuid4().hex[:12]}"
    out = OUT / name
    out.mkdir(parents=True)
    print(f"Lab logs and screenshots: {out}", flush=True)
    accounts = {
        "NXTBI_SEMANTIC_LAB_USER": "lab_admin",
        LAB_AUTH_ENV: password or secrets.token_urlsafe(24),
        "NXTBI_SEMANTIC_LAB_VIEWER": "lab_viewer",
        "NXTBI_SEMANTIC_LAB_VIEWER_PASSWORD": secrets.token_urlsafe(24),
    }
    app_secret = secrets.token_hex(32)
    container_env = {
        **accounts,
        "NXTBI_SEMANTIC_LAB_APP_SECRET": app_secret,
        "SUPERSET_CONFIG_PATH": "/semantic-lab-host/superset_config.py",
    }
    redactions = (
        accounts[LAB_AUTH_ENV],
        accounts["NXTBI_SEMANTIC_LAB_VIEWER_PASSWORD"],
        app_secret,
    )

    def save_log(filename: str, message: str) -> None:
        """Store lab logs without authentication secrets."""
        for value in redactions:
            message = message.replace(value, "[redacted]")
        (out / filename).write_text(message, encoding="utf-8")

    def docker(*parts: str, required: bool = True) -> subprocess.CompletedProcess[str]:
        """Run Docker with diagnostics and lab secrets kept out of command arguments."""
        result = subprocess.run(  # noqa: S603 - Fixed CLI, explicit fixture arguments.
            [docker_path, *parts],
            env={**os.environ, **container_env},
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            check=False,
        )
        if required and result.returncode:
            save_log("docker-error.log", result.stdout + result.stderr)
            raise RuntimeError(f"Docker {parts[0]} failed. See {out}/docker-error.log.")
        return result

    env_args = [part for key in container_env for part in ("--env", key)]
    container_id = docker(
        "run",
        "--detach",
        "--name",
        name,
        "--pull",
        "never",
        "--network",
        "bridge",
        "--publish",
        "127.0.0.1::8088",
        "--mount",
        f"type=bind,src={HOST},dst=/semantic-lab-host,readonly",
        "--mount",
        f"type=bind,src={LAB / 'property_market'},dst=/semantic-lab-extension,readonly",
        *env_args,
        "--entrypoint",
        "/bin/sh",
        image,
        "-ec",
        BOOTSTRAP,
    ).stdout.strip()
    try:
        binding = docker("port", container_id, "8088/tcp").stdout.strip()
        address, port_text = binding.rsplit(":", 1)
        if address != "127.0.0.1":
            raise RuntimeError("The semantic lab port must be bound to loopback.")
        wait_for_health(int(port_text))
        base_url = f"http://{binding}"
        print(f"Semantic lab ready at {base_url} ({name})", flush=True)
        browser_env = {
            **os.environ,
            **accounts,
            "NXTBI_SEMANTIC_LAB_KEEP_ASSETS": str(int(serve or mcp)),
        }
        return_code = run_browser(base_url, out, browser_env)
        if return_code == 0 and serve:
            print(f"Property market preview: {base_url}/dashboard/list/", flush=True)
            while True:
                time.sleep(1)
        if return_code == 0 and mcp:
            result = docker(
                "exec",
                container_id,
                "python",
                "/semantic-lab-host/mcp_smoke.py",
                "--username",
                accounts["NXTBI_SEMANTIC_LAB_USER"],
            )
            save_log("mcp.log", result.stdout + result.stderr)
            print(f"Native MCP smoke passed. See {out}/mcp.log.", flush=True)
        return return_code
    except KeyboardInterrupt:
        return 0 if serve else 130
    finally:
        with suppress(OSError, subprocess.SubprocessError):
            logs = docker("logs", container_id, required=False)
            save_log("superset.log", logs.stdout + logs.stderr)
        docker("rm", "--force", container_id, required=False)


def main() -> int:
    """Start one isolated Superset instance and dispose of it after the run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=DEFAULT_IMAGE, help="Local Superset image")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--serve", action="store_true", help="Seed the dashboard and wait for Ctrl+C"
    )
    modes.add_argument("--mcp", action="store_true", help="Also verify native MCP")
    args = parser.parse_args()
    docker_path = shutil.which("docker")
    if docker_path is None:
        parser.error("Docker CLI must be on PATH.")
    password = os.getenv(LAB_AUTH_ENV)
    if args.serve and not password:
        parser.error(f"Set {LAB_AUTH_ENV} before starting a manual preview.")

    return run_lab(
        args.image,
        docker_path,
        serve=args.serve,
        mcp=args.mcp,
        password=password,
    )


if __name__ == "__main__":
    raise SystemExit(main())
