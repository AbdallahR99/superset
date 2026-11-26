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
from collections.abc import Callable
from contextlib import ExitStack, suppress
from http.client import HTTPConnection, HTTPException
from pathlib import Path
from uuid import uuid4

HOST = Path(__file__).resolve().parent
LAB = HOST.parent
OUT = LAB.parent / "out" / "semantic-lab"
REPO = LAB.parents[1]
COPILOT_BUNDLE = (
    LAB.parent / "copilot" / "superset-extension" / "nxtbi.ai-copilot-0.1.0.supx"
)

DEFAULT_IMAGE = "nxtbi/superset-fork:copilot-localization-verified"
DEFAULT_AGENT_IMAGE = "nxtbi/copilot-agent:zero-code-bi"
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


def wait_for_health(binding: str, timeout: float = 135) -> str:
    """Validate the loopback binding and wait for the app's health endpoint."""
    address, port_text = binding.rsplit(":", 1)
    if address != "127.0.0.1":
        raise RuntimeError("The semantic lab port must be bound to loopback.")
    port = int(port_text)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        connection = HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            connection.request("GET", "/health")
            if connection.getresponse().status == 200:
                return f"http://{binding}"
        except (OSError, HTTPException):
            pass
        finally:
            connection.close()
        time.sleep(1)
    raise RuntimeError("Superset health check timed out.")


def run_browser(
    base_url: str, out: Path, env: dict[str, str], *, script: str = "browser_smoke.py"
) -> int:
    """Run the checked-in browser flow without passing credentials on the CLI."""
    return subprocess.run(  # noqa: S603 - Local browser smoke test.
        [
            sys.executable,
            "-u",
            str(LAB / "tests" / script),
            "--base-url",
            base_url,
            "--artifact-dir",
            str(out),
        ],
        env=env,
        timeout=360,
        check=False,
    ).returncode


def run_checks(
    docker: Callable[..., subprocess.CompletedProcess[str]],
    container_id: str,
    base_url: str,
    out: Path,
    accounts: dict[str, str],
    *,
    save_log: Callable[[str, str], None],
    serve: bool,
    mcp: bool,
    copilot: bool,
) -> int:
    """Seed the native view, then run the selected verification path."""
    browser_env = {
        **os.environ,
        **accounts,
        "NXTBI_SEMANTIC_LAB_KEEP_ASSETS": str(int(serve or mcp or copilot)),
    }
    if return_code := run_browser(base_url, out, browser_env):
        return return_code
    if serve:
        print(f"Property market preview: {base_url}/dashboard/list/", flush=True)
        while True:
            time.sleep(1)
    if mcp:
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
    if copilot:
        docker(
            "exec",
            container_id,
            "python",
            "-c",
            "import os, requests; "
            "agent = os.environ['NXTBI_COPILOT_AGENT_URL']; "
            "url = agent.removesuffix('/ag-ui') + '/health'; "
            "requests.get(url, timeout=5).raise_for_status()",
        )
        return run_browser(
            base_url, out, browser_env, script="copilot_browser_smoke.py"
        )
    return 0


def snapshot_copilot_bundle(bundle_dir: Path) -> None:
    """Copy the packaged extension once so the lab loads a fixed artifact."""
    if not COPILOT_BUNDLE.is_file():
        raise RuntimeError("Build and package the Copilot extension before --copilot.")
    bundle_dir.mkdir()
    shutil.copy2(COPILOT_BUNDLE, bundle_dir)


def run_lab(
    image: str,
    docker_path: str,
    *,
    serve: bool,
    mcp: bool,
    password: str | None,
    copilot_agent_image: str | None = None,
) -> int:
    """Start one loopback container, run the selected checks, and dispose of it."""
    name = f"nxtbi-semantic-lab-{uuid4().hex[:12]}"
    out = OUT / name
    out.mkdir(parents=True)
    bundle_dir = out / "extensions"
    if copilot_agent_image:
        snapshot_copilot_bundle(bundle_dir)
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
    redactions = [
        accounts[LAB_AUTH_ENV],
        accounts["NXTBI_SEMANTIC_LAB_VIEWER_PASSWORD"],
        app_secret,
    ]
    agent_name = f"{name}-agent"
    agent_env: dict[str, str] = {}
    if copilot_agent_image:
        shared_secret = secrets.token_hex(32)
        container_env.update(
            NXTBI_COPILOT_SEMANTIC_LAB="1",
            NXTBI_COPILOT_AGENT_URL=f"http://{agent_name}:8100/ag-ui",
            NXTBI_COPILOT_SHARED_SECRET=shared_secret,
        )
        agent_env = {
            "NXTBI_COPILOT_SHARED_SECRET": shared_secret,
            "NXTBI_COPILOT_TOOL_URL": (
                f"http://{name}:8088/api/v1/nxtbi_copilot/internal/tools"
            ),
        }
        redactions.append(shared_secret)

    def save_log(filename: str, message: str) -> None:
        """Store lab logs without authentication secrets."""
        for value in redactions:
            message = message.replace(value, "[redacted]")
        (out / filename).write_text(message, encoding="utf-8")

    def docker(*parts: str, required: bool = True) -> subprocess.CompletedProcess[str]:
        """Run Docker with diagnostics and lab secrets kept out of command arguments."""
        result = subprocess.run(  # noqa: S603 - Fixed CLI, explicit fixture arguments.
            [docker_path, *parts],
            env={**os.environ, **container_env, **agent_env},
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

    def stop(container_id: str, log_name: str) -> None:
        """Collect redacted diagnostics before removing this run's container."""
        try:
            with suppress(OSError, subprocess.SubprocessError):
                logs = docker("logs", container_id, required=False)
                save_log(log_name, logs.stdout + logs.stderr)
        finally:
            docker("rm", "--force", container_id, required=False)

    try:
        with ExitStack() as cleanup:
            web_arguments: list[str] = []
            network = "bridge"
            if copilot_agent_image:
                network = name
                docker("network", "create", network)
                cleanup.callback(docker, "network", "rm", network, required=False)
                agent_id = docker(
                    "run",
                    "--detach",
                    "--name",
                    agent_name,
                    "--pull",
                    "never",
                    "--network",
                    network,
                    *[part for key in agent_env for part in ("--env", key)],
                    copilot_agent_image,
                ).stdout.strip()
                cleanup.callback(stop, agent_id, "copilot-agent.log")
                web_arguments = [
                    "--mount",
                    f"type=bind,src={bundle_dir},dst=/semantic-lab-bundles,readonly",
                    "--mount",
                    f"type=bind,src={REPO / 'superset' / 'copilot'},"
                    "dst=/app/superset/copilot,readonly",
                ]

            container_id = docker(
                "run",
                "--detach",
                "--name",
                name,
                "--pull",
                "never",
                "--network",
                network,
                "--publish",
                "127.0.0.1::8088",
                "--mount",
                f"type=bind,src={HOST},dst=/semantic-lab-host,readonly",
                "--mount",
                f"type=bind,src={LAB / 'property_market'},"
                "dst=/semantic-lab-extension,readonly",
                *web_arguments,
                *[part for key in container_env for part in ("--env", key)],
                "--entrypoint",
                "/bin/sh",
                image,
                "-ec",
                BOOTSTRAP,
            ).stdout.strip()
            cleanup.callback(stop, container_id, "superset.log")

            binding = docker("port", container_id, "8088/tcp").stdout.strip()
            base_url = wait_for_health(binding)
            print(f"Semantic lab ready at {base_url} ({name})", flush=True)

            return run_checks(
                docker,
                container_id,
                base_url,
                out,
                accounts,
                save_log=save_log,
                serve=serve,
                mcp=mcp,
                copilot=bool(copilot_agent_image),
            )
    except KeyboardInterrupt:
        return 0 if serve else 130


def main() -> int:
    """Start one isolated Superset instance and dispose of it after the run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=DEFAULT_IMAGE, help="Local Superset image")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--serve", action="store_true", help="Seed the dashboard and wait for Ctrl+C"
    )
    modes.add_argument("--mcp", action="store_true", help="Also verify native MCP")
    modes.add_argument(
        "--copilot", action="store_true", help="Also verify bilingual Copilot saves"
    )
    parser.add_argument(
        "--agent-image",
        default=DEFAULT_AGENT_IMAGE,
        help="Local Copilot agent image used by --copilot",
    )
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
        copilot_agent_image=args.agent_image if args.copilot else None,
    )


if __name__ == "__main__":
    raise SystemExit(main())
