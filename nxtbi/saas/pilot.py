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
"""Run and verify a local Keycloak and two-customer Superset pilot."""

from __future__ import annotations

import argparse
import json  # noqa: TID251 - This host-side runner has no Superset runtime.
import os
import re
import secrets
import shutil
import socket
import subprocess
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, suppress
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPException
from ipaddress import ip_network, IPv4Network
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "out" / "saas-pilot"
REALM = "nxtbi-saas-pilot"
LABEL = "org.nxtbi.saas-pilot"
DEFAULT_IMAGE = "nxtbi/superset-fork:copilot-localization-verified"
TENANTS = {"alpha": ("North Coast", 101), "beta": ("Cedar Works", 202)}
MEMBERSHIPS = {
    "alpha-viewer": ("alpha",),
    "beta-viewer": ("beta",),
    "shared-viewer": ("alpha", "beta"),
}


@dataclass(frozen=True)
class Project:
    """One randomized Compose project and its local configuration."""

    run: str
    key: str

    @property
    def name(self) -> str:
        """Return the project and private network name."""
        return f"nxtbi-saas-{self.run}-{self.key}"

    @property
    def env_file(self) -> Path:
        """Return the git-ignored environment file for this run."""
        return OUT / self.run / f"{self.key}.env"

    def command(self, *args: str) -> tuple[str, ...]:
        """Use an explicit project name and environment for every operation."""
        template = "portal" if self.key == "portal" else "tenant"
        return (
            "compose",
            "--project-name",
            self.name,
            "--env-file",
            str(self.env_file),
            "--file",
            str(ROOT / f"{template}.compose.yml"),
            *args,
        )


class Docker:
    """Run the local pilot's Docker commands with redacted diagnostics."""

    def __init__(self, directory: Path) -> None:
        executable = shutil.which("docker")
        if executable is None:
            raise RuntimeError("Docker must be available on PATH.")
        self.executable = executable
        self.directory = directory
        self.secrets: list[str] = []
        self.env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("NXTBI_SAAS_", "COMPOSE_"))
        }

    def secret(self) -> str:
        """Generate independent credentials and redact them from collected logs."""
        value = secrets.token_hex(24)
        self.secrets.append(value)
        return value

    def log(self, name: str, output: str) -> None:
        """Write local diagnostics without fixture credentials."""
        for secret in self.secrets:
            output = output.replace(secret, "[redacted]")
        (self.directory / name).write_text(output, encoding="utf-8")

    def run(
        self, *args: str, label: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        """Run a bounded Docker command and write any failure to its own file."""
        result = subprocess.run(  # noqa: S603 - Fixed local Docker CLI.
            [self.executable, *args],
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
        )
        if result.returncode:
            self.log(f"{label}.log", result.stdout + result.stderr)
            if check:
                raise RuntimeError(
                    f"{label} failed. See {self.directory / (label + '.log')}"
                )
        return result


def port_allocation() -> dict[str, int]:
    """Reserve distinct loopback ports while allocating the fixture addresses."""
    with ExitStack() as listeners:
        ports = {}
        for key in ("identity", "portal", *TENANTS):
            listener = listeners.enter_context(socket.socket())
            listener.bind(("127.0.0.1", 0))
            ports[key] = listener.getsockname()[1]
    return ports


def group(slug: str) -> str:
    """Return the complete, per-tenant Keycloak group path."""
    return f"/nxt/{slug}/viewer"


def realm_configuration(
    clients: dict[str, tuple[str, str]], passwords: dict[str, str]
) -> dict[str, object]:
    """Build a synthetic realm with exact callback URLs and signed group claims."""
    return {
        "realm": REALM,
        "enabled": True,
        "sslRequired": "none",
        "registrationAllowed": False,
        "groups": [
            {
                "name": "nxt",
                "subGroups": [
                    {"name": slug, "subGroups": [{"name": "viewer"}]}
                    for slug in TENANTS
                ],
            }
        ],
        "clients": [
            {
                "clientId": f"nxtbi-pilot-{key}",
                "secret": secret,
                "enabled": True,
                "protocol": "openid-connect",
                "publicClient": False,
                "standardFlowEnabled": True,
                "directAccessGrantsEnabled": False,
                "redirectUris": [callback],
                "defaultClientScopes": ["profile", "email"],
                "attributes": {"pkce.code.challenge.method": "S256"},
                "protocolMappers": [
                    {
                        "name": "NxtBI pilot groups",
                        "protocol": "openid-connect",
                        "protocolMapper": "oidc-group-membership-mapper",
                        "config": {
                            "full.path": "true",
                            "id.token.claim": "true",
                            "access.token.claim": "false",
                            "userinfo.token.claim": "false",
                            "claim.name": "groups",
                        },
                    }
                ],
            }
            for key, (callback, secret) in clients.items()
        ],
        "users": [
            {
                "username": username,
                "firstName": username.split("-")[0].capitalize(),
                "lastName": "Viewer",
                "email": f"{username}@example.invalid",
                "emailVerified": True,
                "enabled": True,
                "groups": [group(slug) for slug in memberships],
                "credentials": [
                    {
                        "type": "password",
                        "value": passwords[username],
                        "temporary": False,
                    }
                ],
            }
            for username, memberships in MEMBERSHIPS.items()
        ],
    }


def write_env(project: Project, values: dict[str, object]) -> None:
    """Write fixture-only Compose settings without exposing credentials in argv."""
    project.env_file.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8"
    )


def configure(
    docker: Docker, projects: list[Project], image: str, ports: dict[str, int]
) -> tuple[dict[str, str], dict[str, str]]:
    """Materialize independent cell and control-plane settings for this run."""
    run = projects[0].run
    urls = {key: f"http://{key}-{run}.localhost:{port}" for key, port in ports.items()}
    clients = {
        project.key: (
            urls[project.key]
            + (
                "/oidc/callback"
                if project.key == "portal"
                else "/oauth-authorized/keycloak"
            ),
            docker.secret(),
        )
        for project in projects
    }
    passwords = {username: docker.secret() for username in MEMBERSHIPS}
    realm_file = docker.directory / "realm.json"
    inventory_directory = docker.directory / "catalog"
    inventory_directory.mkdir()
    inventory_file = inventory_directory / "inventory.json"
    realm_file.write_text(
        json.dumps(realm_configuration(clients, passwords)), encoding="utf-8"
    )
    inventory_file.write_text(
        json.dumps(
            [
                {
                    "id": str(uuid4()),
                    "slug": slug,
                    "name": title,
                    "base_url": urls[slug],
                    "group": group(slug),
                    "state": "provisioning",
                }
                for slug, (title, _) in TENANTS.items()
            ]
        ),
        encoding="utf-8",
    )
    for project in projects:
        key = project.key
        common = {
            "NXTBI_SAAS_SUPERSET_IMAGE": image,
            "NXTBI_SAAS_NETWORK": project.name,
            "NXTBI_SAAS_PUBLIC_URL": urls[key],
            "NXTBI_SAAS_PORTAL_URL": urls["portal"],
            "NXTBI_SAAS_OIDC_ISSUER": f"{urls['identity']}/realms/{REALM}",
            "NXTBI_SAAS_OIDC_BACKEND": f"http://identity:8080/realms/{REALM}",
            "NXTBI_SAAS_OIDC_CLIENT_ID": f"nxtbi-pilot-{key}",
            "NXTBI_SAAS_OIDC_CLIENT_SECRET": clients[key][1],
        }
        if key == "portal":
            write_env(
                project,
                {
                    **common,
                    "NXTBI_SAAS_PORTAL_PORT": ports[key],
                    "NXTBI_SAAS_KEYCLOAK_PORT": ports["identity"],
                    "NXTBI_SAAS_KEYCLOAK_URL": urls["identity"],
                    "NXTBI_SAAS_REALM_FILE": realm_file.as_posix(),
                    "NXTBI_SAAS_INVENTORY_DIR": inventory_directory.as_posix(),
                    "NXTBI_SAAS_PORTAL_SECRET": docker.secret(),
                },
            )
        else:
            write_tenant_env(docker, project, common, ports[key])
    return urls, passwords


def write_tenant_env(
    docker: Docker, project: Project, common: Mapping[str, object], port: int
) -> None:
    """Generate distinct database roles and secrets for an isolated deployment."""
    slug = project.key
    migration, runtime, reader = (docker.secret() for _ in range(3))
    write_env(
        project,
        {
            **common,
            "NXTBI_SAAS_HTTP_PORT": port,
            "NXTBI_SAAS_TENANT_SLUG": slug,
            "NXTBI_SAAS_TENANT_NAME": TENANTS[slug][0],
            "NXTBI_SAAS_TENANT_GROUP": group(slug),
            "NXTBI_SAAS_TENANT_VALUE": TENANTS[slug][1],
            "NXTBI_SAAS_TENANT_SECRET": docker.secret(),
            "NXTBI_SAAS_POSTGRES_PASSWORD": docker.secret(),
            "NXTBI_SAAS_MIGRATION_PASSWORD": migration,
            "NXTBI_SAAS_RUNTIME_PASSWORD": runtime,
            "NXTBI_SAAS_READER_PASSWORD": reader,
            "NXTBI_SAAS_MIGRATION_URI": (
                f"postgresql+psycopg2://nxtbi_migrator:{migration}@db/nxtbi_metadata"
            ),
            "NXTBI_SAAS_RUNTIME_URI": (
                f"postgresql+psycopg2://nxtbi_runtime:{runtime}@db/nxtbi_metadata"
            ),
            "NXTBI_SAAS_WAREHOUSE_URI": (
                f"postgresql+psycopg2://nxtbi_reader:{reader}@db/nxtbi_warehouse"
            ),
        },
    )


def wait_http(port: int, path: str, label: str) -> None:
    """Wait on a loopback-only readiness URL."""
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        connection = HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            with suppress(OSError, HTTPException):
                connection.request("GET", path)
                if connection.getresponse().status == 200:
                    return
        finally:
            connection.close()
        time.sleep(0.5)
    raise RuntimeError(f"{label} did not become ready.")


def create_networks(
    docker: Docker, projects: list[Project], block: IPv4Network
) -> None:
    """Create labelled networks without relying on Docker's default address pool."""
    current = docker.run("network", "ls", "-q", label="list-networks").stdout.split()
    occupied = []
    if current:
        result = docker.run("network", "inspect", *current, label="inspect-networks")
        occupied = [
            ip_network(entry["Subnet"])
            for net in json.loads(result.stdout)
            for entry in net["IPAM"].get("Config") or []
            if entry.get("Subnet")
        ]
    available = (
        subnet
        for subnet in block.subnets(new_prefix=28)
        if not any(subnet.overlaps(other) for other in occupied)
    )
    for project in projects:
        subnet = next(available, None)
        if subnet is None:
            raise RuntimeError(
                "No pilot subnet is free. Choose a different --network-block."
            )
        docker.run(
            "network",
            "create",
            "--label",
            f"{LABEL}={project.run}",
            "--subnet",
            str(subnet),
            project.name,
            label=f"network-{project.key}",
        )


def stop(docker: Docker, projects: list[Project]) -> None:
    """Collect redacted logs and remove only this pilot's Compose resources."""
    for project in reversed(projects):
        result = docker.run(
            *project.command("logs", "--no-color", "--tail", "100"),
            label=f"logs-{project.key}",
            check=False,
        )
        docker.log(f"{project.key}.log", result.stdout + result.stderr)
        docker.run(*project.command("down", "--volumes"), label=f"down-{project.key}")
    for project in projects:
        result = docker.run(
            "network",
            "inspect",
            "--format",
            f'{{{{index .Labels "{LABEL}"}}}}',
            project.name,
            label=f"check-network-{project.key}",
            check=False,
        )
        if result.stdout.strip() == project.run:
            docker.run("network", "rm", project.name, label=f"remove-{project.key}")
    for path in (
        *[project.env_file for project in projects],
        docker.directory / "realm.json",
    ):
        path.unlink(missing_ok=True)
    (docker.directory / "credentials.json").unlink(missing_ok=True)


def verify_database(docker: Docker, project: Project, image_id: str) -> str:
    """Check image parity, migration state, reader grants, and actual SQL RLS."""
    container = docker.run(
        *project.command("ps", "-q", "web"), label="web-id"
    ).stdout.strip()
    image = docker.run(
        "inspect", "--format", "{{.Image}}", container, label="web-image"
    )
    if image.stdout.strip() != image_id:
        raise RuntimeError("A pilot tenant did not start on the approved local image.")
    sql = (
        'PGPASSWORD="$NXTBI_SAAS_READER_PASSWORD" psql -h 127.0.0.1 -U nxtbi_reader '
        "-d nxtbi_warehouse -At -v ON_ERROR_STOP=1 "
        '-c "SELECT count(*), min(value), max(value) FROM analytics.workspace_kpis '
        "WHERE current_user = 'nxtbi_reader' "
        "AND row_security_active('analytics.workspace_kpis') "
        "AND NOT has_table_privilege('analytics.workspace_kpis', 'INSERT')"
        '"'
    )
    value = TENANTS[project.key][1]
    row = docker.run(
        *project.command("exec", "-T", "db", "sh", "-ec", sql),
        label=f"rls-{project.key}",
    ).stdout.strip()
    if row != f"1|{value}|{value}":
        raise RuntimeError(f"PostgreSQL row isolation failed for {project.key}.")
    metadata = (
        'PGPASSWORD="$NXTBI_SAAS_RUNTIME_PASSWORD" psql -h 127.0.0.1 -U nxtbi_runtime '
        "-d nxtbi_metadata -At -v ON_ERROR_STOP=1 "
        '-c "SELECT version_num FROM alembic_version '
        "WHERE current_user = 'nxtbi_runtime' "
        "AND NOT has_schema_privilege('public', 'CREATE')"
        '"'
    )
    return docker.run(
        *project.command("exec", "-T", "db", "sh", "-ec", metadata),
        label=f"migration-{project.key}",
    ).stdout.strip()


def activate_tenants(directory: Path) -> None:
    """Publish the verified tenants together through the read-only catalog mount."""
    inventory = directory / "catalog" / "inventory.json"
    rows = json.loads(inventory.read_text(encoding="utf-8"))
    for tenant in rows:
        tenant["state"] = "active"
    temporary = inventory.with_suffix(".tmp")
    temporary.write_text(json.dumps(rows), encoding="utf-8")
    temporary.replace(inventory)


def run_pilot(
    docker: Docker, projects: list[Project], args: argparse.Namespace
) -> None:
    """Boot twin deployments, then prove SQL and browser isolation."""
    from .tests.browser_check import verify_browser

    image_id = docker.run(
        "image",
        "inspect",
        "--format",
        "{{.Id}}",
        args.superset_image,
        label="base-image",
    ).stdout.strip()
    ports = port_allocation()
    urls, passwords = configure(docker, projects, args.superset_image, ports)
    create_networks(docker, projects, args.network_block)
    portal, *tenants = projects
    docker.run(*portal.command("up", "-d"), label="start-portal")
    wait_http(
        ports["identity"],
        f"/realms/{REALM}/.well-known/openid-configuration",
        "Keycloak",
    )
    wait_http(ports["portal"], "/health", "Portal")
    identity = docker.run(
        *portal.command("ps", "-q", "identity"), label="identity-id"
    ).stdout.strip()
    for project in tenants:
        docker.run(
            "network",
            "connect",
            "--alias",
            "identity",
            project.name,
            identity,
            label=f"attach-{project.key}",
        )
    with ThreadPoolExecutor(max_workers=2) as workers:
        starts = [
            workers.submit(
                docker.run, *project.command("up", "-d"), label=f"start-{project.key}"
            )
            for project in tenants
        ]
        for start in starts:
            start.result()
    revisions = set()
    for project in tenants:
        wait_http(ports[project.key], "/health", project.key)
        revisions.add(verify_database(docker, project, image_id))
    if len(revisions) != 1 or not re.fullmatch(r"[a-z0-9]+", next(iter(revisions))):
        raise RuntimeError("The tenants must share one Alembic head.")
    print(
        f"PASS common image {image_id} and Alembic head {next(iter(revisions))}",
        flush=True,
    )
    print("PASS PostgreSQL RLS exposes one permitted row in each warehouse", flush=True)
    activate_tenants(docker.directory)
    verify_browser(
        urls["portal"],
        {slug: urls[slug] for slug in TENANTS},
        passwords,
        docker.directory,
    )
    if args.keep:
        (docker.directory / "credentials.json").write_text(
            json.dumps(passwords), encoding="utf-8"
        )
        print(f"Pilot portal: {urls['portal']}", flush=True)
        print(
            f"Synthetic viewer passwords: {docker.directory / 'credentials.json'}",
            flush=True,
        )
        print(f"Stop: python -m nxtbi.saas.pilot --stop {portal.run}", flush=True)


def main() -> None:
    """Start the disposable pilot or stop an explicitly retained run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--superset-image", default=DEFAULT_IMAGE)
    parser.add_argument(
        "--network-block", default=IPv4Network("172.31.224.0/19"), type=IPv4Network
    )
    lifecycle = parser.add_mutually_exclusive_group()
    lifecycle.add_argument(
        "--keep", action="store_true", help="Keep the verified local pilot running"
    )
    lifecycle.add_argument(
        "--stop",
        metavar="RUN_ID",
        help="Stop one retained pilot and remove its synthetic data",
    )
    args = parser.parse_args()
    run = args.stop or uuid4().hex[:12]
    if not re.fullmatch(r"[0-9a-f]{12}", run):
        parser.error("Run ID must be 12 lowercase hexadecimal characters.")
    if args.network_block.prefixlen > 26 or not args.network_block.is_private:
        parser.error("Choose a private IPv4 block with room for three /28 networks.")
    directory = OUT / run
    projects = [Project(run, key) for key in ("portal", *TENANTS)]
    docker = Docker(directory)
    if args.stop:
        if not all(project.env_file.is_file() for project in projects):
            parser.error("The retained pilot was not found.")
        for project in projects:
            docker.secrets.extend(
                re.findall(
                    r"(?:=|:)([0-9a-f]{48})(?=[@\n]|$)",
                    project.env_file.read_text(encoding="utf-8"),
                )
            )
        passwords = docker.directory / "credentials.json"
        if passwords.is_file():
            docker.secrets.extend(
                json.loads(passwords.read_text(encoding="utf-8")).values()
            )
        stop(docker, projects)
        return
    directory.mkdir(parents=True)
    print(f"Pilot evidence: {directory}", flush=True)
    retained = False
    try:
        run_pilot(docker, projects, args)
        retained = args.keep
    finally:
        if not retained and all(project.env_file.is_file() for project in projects):
            stop(docker, projects)


if __name__ == "__main__":
    main()
