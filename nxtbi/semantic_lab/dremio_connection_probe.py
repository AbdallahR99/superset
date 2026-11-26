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
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Check an approved Dremio account over TLS without printing its credentials."""

from __future__ import annotations

import argparse
import json  # noqa: TID251 - Standalone probe, also usable outside Superset.
import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from importlib.metadata import version
from pathlib import Path

from adbc_driver_flightsql import DatabaseOptions
from adbc_driver_flightsql.dbapi import connect
from adbc_driver_manager import DatabaseOptions as ManagerOptions
from adbc_driver_manager.dbapi import Connection
from dotenv import dotenv_values


def configure_proxy(host: str, port: int) -> None:
    """Use the workstation's explicit HTTPS route for the configured endpoint."""
    executable = shutil.which("git")
    if executable is None:
        raise ValueError("Git is required for the configured proxy.")
    route = subprocess.run(  # noqa: S603 - Fixed command and a validated host.
        [
            executable,
            "config",
            "--get-urlmatch",
            "http.proxy",
            f"https://{host}:{port}/",
        ],
        capture_output=True,
        check=True,
        text=True,
        timeout=5,
    ).stdout.strip()
    if not route.startswith(("http://", "https://")):
        raise ValueError("Expected a configured HTTP proxy.")
    os.environ.update(HTTPS_PROXY=route, https_proxy=route, grpc_proxy=route)


def safe_error(error: Exception) -> str:
    """Report a phase and a category without server messages or secret values."""
    detail = str(error).lower()
    for message, category in (
        ("does not have access", "denied"),
        ("permission denied", "denied"),
        ("unauthenticated", "authentication_rejected"),
        ("deadline exceeded", "timeout"),
        ("certificate", "certificate_error"),
        ("unavailable", "unavailable"),
    ):
        if message in detail:
            return category
    return type(error).__name__


def read_system_metadata(connection: Connection) -> dict[str, str | None]:
    """Report system-metadata visibility without fetching any policy contents."""
    result: dict[str, str | None] = {"warehouse_version": None}
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT "version" FROM sys."version" LIMIT 1')
            row = cursor.fetchone()
            if row:
                match = re.search(r"\b\d+\.\d+\.\d+(?:\.\d+)?\b", str(row[0]))
                if match:
                    result["warehouse_version"] = match.group()
            result["version_table"] = "readable"
    except Exception as error:  # pylint: disable=broad-exception-caught
        result["version_table"] = safe_error(error)

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT name FROM sys.options "
                "WHERE name = 'exec.impersonation.inbound_policies' LIMIT 1"
            )
            result["impersonation_option"] = (
                "visible" if cursor.fetchone() else "not_listed"
            )
    except Exception as error:  # pylint: disable=broad-exception-caught
        result["impersonation_option"] = safe_error(error)
    return result


def probe(config: Mapping[str, str | None], use_proxy: bool) -> dict[str, object]:
    """Run a bounded constant query as the supplied authenticated principal."""
    host = config.get("DREMIO_HOST") or ""
    port = int(config.get("DREMIO_PORT") or "443")
    username = config.get("DREMIO_USER")
    password = config.get("DREMIO_PASSWORD")
    if not (
        re.fullmatch(r"[A-Za-z0-9.-]+", host)
        and 0 < port <= 65535
        and username
        and password
    ):
        raise ValueError("Incomplete Dremio connection configuration.")
    if use_proxy:
        configure_proxy(host, port)
    options = {
        ManagerOptions.USERNAME.value: username,
        ManagerOptions.PASSWORD.value: password,
        DatabaseOptions.WITH_COOKIE_MIDDLEWARE.value: "true",
        "adbc.flight.sql.rpc.timeout_seconds.connect": "15",
        "adbc.flight.sql.rpc.timeout_seconds.query": "10",
        "adbc.flight.sql.rpc.timeout_seconds.fetch": "10",
    }
    with connect(
        f"grpc+tls://{host}:{port}", db_kwargs=options, autocommit=True
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1, QUERY_USER()")
            row = cursor.fetchone()
        return {
            "flight_driver": version("adbc-driver-flightsql"),
            "query_succeeded": bool(row and row[0] == 1),
            "principal_matches": bool(
                row and str(row[1]).casefold() == username.casefold()
            ),
            **read_system_metadata(connection),
        }


def main() -> int:
    """Load local connection fields and print the redacted result."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--configured-proxy", action="store_true")
    args = parser.parse_args()
    try:
        result = probe(dotenv_values(args.env_file), args.configured_proxy)
    except Exception as error:  # pylint: disable=broad-exception-caught
        print(json.dumps({"query_succeeded": False, "error": safe_error(error)}))
        return 1
    print(json.dumps(result))
    return 0 if result["query_succeeded"] and result["principal_matches"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
