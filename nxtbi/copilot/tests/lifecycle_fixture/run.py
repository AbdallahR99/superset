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
"""Run the Copilot lifecycle on disposable Superset, Postgres, MCP, and Vite.

Use locally built Superset and agent images, a packaged Copilot extension,
installed Widget SDK example dependencies, Node on PATH, and Playwright
Chromium. Every run writes its logs and screenshots under nxtbi/out.
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import ExitStack, suppress
from http.client import HTTPConnection, HTTPException
from ipaddress import IPv4Network
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / "nxtbi/out/copilot-lifecycle"
EXTENSION = ROOT / "nxtbi/copilot/superset-extension"
WIDGET_EXAMPLE = ROOT / "superset-frontend/packages/superset-widgets/example"
TEST = Path(__file__).resolve().parent.parent / "dashboard_lifecycle_e2e.py"
VITE = WIDGET_EXAMPLE / "node_modules/vite/bin/vite.js"
PROVIDER_KEYS = (
    "NXTBI_COPILOT_MODEL",
    "NXTBI_COPILOT_MODEL_BASE_URL",
    "NXTBI_COPILOT_MODEL_API_KEY",
)

SETUP_DATA = """
import json
import os
from superset.app import create_app
from superset.extensions import db
with create_app().app_context():
    from superset.models.core import Database

    database = Database(
        database_name="Lifecycle uploads",
        sqlalchemy_uri=os.environ["A2UI_FIXTURE_DATA_URI"],
        allow_file_upload=True,
        extra=json.dumps({"schemas_allowed_for_file_upload": ["public"]}),
    )
    db.session.add(database)
    db.session.commit()
"""

CREATE_ADMIN = """
superset fab create-admin --username "$NXTBI_E2E_ADMIN_USERNAME" \
  --firstname Lifecycle --lastname Admin --email lifecycle@example.invalid \
  --password "$NXTBI_E2E_ADMIN_PASSWORD"
"""


def loopback_port() -> int:
    """Choose a loopback port for Vite's strict-port bind."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_http(url: str, wait_seconds: float = 90) -> None:
    """Poll readiness on a fixture service's explicit loopback address."""
    address = urlsplit(url)
    until = time.monotonic() + wait_seconds
    while time.monotonic() < until:
        connection = HTTPConnection("127.0.0.1", address.port, timeout=2)
        try:
            connection.request("GET", address.path or "/")
            if connection.getresponse().status == 200:
                return
        except (OSError, HTTPException):
            pass
        finally:
            connection.close()
        time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {url}")


def model_env(path: Path | None) -> dict[str, str]:
    """Read only provider settings from an optional local env file."""
    if path is None:
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() in PROVIDER_KEYS:
            values[key.strip()] = value.strip().strip("\"'")
    return values


def docker_env(keys: list[str]) -> list[str]:
    """Refer to values by environment name instead of passing secrets as args."""
    return [part for key in keys for part in ("-e", key)]


def inputs() -> tuple[argparse.Namespace, dict[str, str], str, str]:
    """Validate the images, optional provider file, and local prerequisites."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--superset-image", required=True)
    parser.add_argument("--agent-image", required=True)
    parser.add_argument(
        "--subnet",
        type=IPv4Network,
        help="Unused private IPv4 CIDR to use when Docker's default pools are full",
    )
    parser.add_argument(
        "--provider-env", type=Path, help="Local env file for the agent"
    )
    parser.add_argument("--run-model-probe", action="store_true")
    parser.add_argument("--channel", help="Optional installed Chromium channel")
    args = parser.parse_args()
    if not (EXTENSION / "dist/manifest.json").is_file():
        parser.error("Build and package the Copilot extension first.")
    if not VITE.is_file():
        parser.error("Install the Widget SDK example dependencies first.")
    if args.provider_env is not None and not args.provider_env.is_file():
        parser.error("The provider env file does not exist.")
    provider = model_env(args.provider_env)
    if args.run_model_probe and not all(provider.get(key) for key in PROVIDER_KEYS):
        parser.error("Supply the model, base URL and key through --provider-env.")
    docker = shutil.which("docker")
    node = shutil.which("node")
    if not docker or not node:
        parser.error("Put Docker and the repository's Node version on PATH.")
    return args, provider, docker, node


def stop_vite(vite: subprocess.Popen[bytes]) -> None:
    """Stop only this run's SDK host process."""
    vite.terminate()
    try:
        vite.wait(timeout=10)
    except subprocess.TimeoutExpired:
        vite.kill()
        vite.wait()


def wait_container(
    docker: Callable[..., subprocess.CompletedProcess[str]],
    *command: str,
    label: str,
) -> None:
    """Wait for an owned container's readiness command."""
    for _ in range(50):
        if docker("exec", *command, required=False).returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError(f"{label} did not become ready.")


def main() -> int:
    """Start an isolated stack, run Chromium, and tear down owned resources."""
    args, provider, docker_executable, node = inputs()
    label = f"nxtbi-lifecycle-{uuid4().hex}"
    out = OUT / label
    out.mkdir(parents=True)
    print(f"Fixture logs and screenshots: {out}", flush=True)
    db_name, web_name, agent_name, mcp_name = (
        f"{label}-{service}" for service in ("db", "web", "agent", "mcp")
    )
    widget_port = loopback_port()
    widget_url = f"http://127.0.0.1:{widget_port}"
    db_password = secrets.token_hex(16)
    password = secrets.token_hex(16) + "Aa9"
    postgres = f"postgresql+psycopg2://copilot:{db_password}@{db_name}:5432"
    parent_env = {
        key: val for key, val in os.environ.items() if key not in PROVIDER_KEYS
    }
    browser_env = {
        "NXTBI_E2E_ADMIN_USERNAME": "lifecycle-admin",
        "NXTBI_E2E_ADMIN_PASSWORD": password,
        "NXTBI_E2E_MODEL_PROBE": "1" if args.run_model_probe else "0",
    }
    config = {
        "A2UI_FIXTURE_APP_SECRET": secrets.token_hex(32),
        "A2UI_FIXTURE_GUEST_SECRET": secrets.token_hex(32),
        "A2UI_FIXTURE_METADATA_URI": f"{postgres}/copilot",
        "A2UI_FIXTURE_DATA_URI": f"{postgres}/lifecycle_data",
        "A2UI_FIXTURE_WIDGET_ORIGIN": widget_url,
        "A2UI_FIXTURE_MCP_SECRET": secrets.token_hex(32),
        "A2UI_FIXTURE_MCP_URL": f"http://{mcp_name}:5008/mcp",
        "A2UI_FIXTURE_AGENT_URL": f"http://{agent_name}:8100/ag-ui",
        "NXTBI_COPILOT_SHARED_SECRET": secrets.token_hex(32),
        "SUPERSET_CONFIG_PATH": "/app/pythonpath/superset_config.py",
    }
    agent_config = {
        **provider,
        "NXTBI_COPILOT_TOOL_URL": (
            f"http://{web_name}:8088/api/v1/nxtbi_copilot/internal/tools"
        ),
        "NXTBI_COPILOT_SHARED_SECRET": config["NXTBI_COPILOT_SHARED_SECRET"],
    }
    env = {
        **parent_env,
        **browser_env,
        **config,
        **agent_config,
        "POSTGRES_PASSWORD": db_password,
    }
    redactions = [
        db_password,
        password,
        config["A2UI_FIXTURE_APP_SECRET"],
        config["A2UI_FIXTURE_GUEST_SECRET"],
        config["A2UI_FIXTURE_MCP_SECRET"],
        config["NXTBI_COPILOT_SHARED_SECRET"],
        provider.get("NXTBI_COPILOT_MODEL_API_KEY", ""),
    ]

    def save_log(name: str, text: str) -> None:
        """Store local diagnostics with fixture and model credentials redacted."""
        for value in filter(None, redactions):
            text = text.replace(value, "[redacted]")
        (out / name).write_text(text, encoding="utf-8")

    def docker(
        *command: str, required: bool = True
    ) -> subprocess.CompletedProcess[str]:
        """Run against Docker without printing its raw diagnostics to the terminal."""
        result = subprocess.run(  # noqa: S603 - Fixed CLI, explicit fixture args.
            [docker_executable, *command],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
        if required and result.returncode:
            save_log("docker-error.log", result.stdout + result.stderr)
            raise RuntimeError(f"Docker {command[0]} failed. See docker-error.log.")
        return result

    config_file = Path(__file__).with_name("superset_config.py")
    web_runtime = [
        "--network",
        label,
        *docker_env(list(config)),
        "--mount",
        f"type=bind,src={config_file},dst=/app/pythonpath/superset_config.py,readonly",
        "--mount",
        f"type=bind,src={EXTENSION},dst=/app/copilot-extension,readonly",
    ]

    setup_name = f"{label}-setup"

    def web_command(entrypoint: str, *command: str) -> None:
        """Run a one-shot command sharing only the fixture's network and config."""
        docker(
            "run",
            "--rm",
            "--name",
            setup_name,
            *web_runtime,
            *docker_env(["NXTBI_E2E_ADMIN_USERNAME", "NXTBI_E2E_ADMIN_PASSWORD"]),
            "--entrypoint",
            entrypoint,
            args.superset_image,
            *command,
        )

    def remove(*command: str) -> None:
        """Attempt cleanup even when a prior owned resource has disappeared."""
        with suppress(OSError, subprocess.SubprocessError):
            docker(*command, required=False)

    def stop(name: str) -> None:
        """Collect redacted service output before discarding a fixture container."""
        try:
            with suppress(OSError, subprocess.SubprocessError):
                logs = docker("logs", name, required=False)
                save_log(f"{name.rsplit('-', 1)[-1]}.log", logs.stdout + logs.stderr)
        finally:
            remove("stop", "-t", "3", name)

    def start(cleanup: ExitStack, name: str, *command: str) -> None:
        """Register cleanup for a container created by this run."""
        docker("run", "-d", "--rm", "--name", name, *command)
        cleanup.callback(stop, name)

    with ExitStack() as cleanup:
        subnet_options = ["--subnet", str(args.subnet)] if args.subnet else []
        docker("network", "create", *subnet_options, label)
        cleanup.callback(remove, "network", "rm", label)
        cleanup.callback(remove, "rm", "-f", setup_name)
        start(
            cleanup,
            db_name,
            "--network",
            label,
            "-e",
            "POSTGRES_USER=copilot",
            "-e",
            "POSTGRES_DB=copilot",
            "-e",
            "POSTGRES_PASSWORD",
            "postgres:17",
        )
        wait_container(
            docker,
            db_name,
            "pg_isready",
            "-h",
            "127.0.0.1",
            "-U",
            "copilot",
            "-d",
            "copilot",
            label="PostgreSQL",
        )
        docker(
            "exec",
            db_name,
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "copilot",
            "-d",
            "copilot",
            "-c",
            "CREATE DATABASE lifecycle_data",
        )
        web_command("superset", "db", "upgrade")
        web_command("sh", "-ec", CREATE_ADMIN)
        web_command("superset", "init")
        web_command("python", "-c", SETUP_DATA)
        print(
            "PASS disposable PostgreSQL, migrations, and upload connection", flush=True
        )

        start(
            cleanup,
            mcp_name,
            *web_runtime,
            "--entrypoint",
            "superset",
            args.superset_image,
            "mcp",
            "run",
            "--host",
            "0.0.0.0",  # noqa: S104 - Private container network, no published port.
            "--port",
            "5008",
        )
        start(
            cleanup,
            agent_name,
            "--network",
            label,
            *docker_env(list(agent_config)),
            args.agent_image,
        )
        start(
            cleanup,
            web_name,
            *web_runtime,
            "-p",
            "127.0.0.1::8088",
            "--entrypoint",
            "gunicorn",
            args.superset_image,
            "-w",
            "1",
            # The streaming request remains open while the agent calls back.
            "--threads",
            "4",
            "--access-logfile",
            "-",
            "-t",
            "120",
            "-b",
            "0.0.0.0:8088",
            "superset.app:create_app()",
        )
        web_port = docker("port", web_name, "8088/tcp").stdout.strip().rsplit(":", 1)[1]
        superset_url = f"http://127.0.0.1:{web_port}"
        wait_http(f"{superset_url}/health")
        wait_container(
            docker,
            mcp_name,
            "curl",
            "-fsS",
            "http://127.0.0.1:5008/health",
            label="Authenticated MCP",
        )
        print("PASS live Superset and authenticated MCP service readiness", flush=True)

        with (out / "vite.log").open("wb") as log:
            vite = subprocess.Popen(  # noqa: S603 - Local Vite entry point only.
                [
                    node,
                    str(VITE),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(widget_port),
                    "--strictPort",
                ],
                cwd=WIDGET_EXAMPLE,
                env={**parent_env, "SUPERSET_URL": superset_url},
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            cleanup.callback(stop_vite, vite)
            wait_http(widget_url)
        result = subprocess.run(  # noqa: S603 - Run the checked-in test with Python.
            [
                sys.executable,
                "-u",
                str(TEST),
                "--base-url",
                superset_url,
                "--widget-host-url",
                widget_url,
                "--artifact-dir",
                str(out),
                *(["--channel", args.channel] if args.channel else []),
            ],
            env={**parent_env, **browser_env},
            timeout=420,
            check=False,
        )
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
