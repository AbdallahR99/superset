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
"""Exercise overlapping Dashboard V2 and classic saves on disposable PostgreSQL."""

from __future__ import annotations

import argparse
import json  # noqa: TID251 - The harness runs outside the Superset runtime.
import subprocess
from concurrent.futures import Future, ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path
from shutil import which
from time import monotonic, sleep
from typing import Any
from uuid import uuid4

from widgets_e2e import (
    Api,
    expect,
    invalid_documents,
    markdown_document,
    v2_create_body,
    v2_etag,
    v2_update_body,
)

V2_API = "/api/v1/dashboard_v2"
CLASSIC_API = "/api/v1/dashboard"
WAITING_BACKENDS = """
WITH RECURSIVE waiting(pid) AS (
    SELECT pg_backend_pid()
    UNION
    SELECT waiter.pid
    FROM (SELECT DISTINCT pid FROM pg_locks WHERE NOT granted) AS waiter
    JOIN waiting ON waiting.pid = ANY(pg_blocking_pids(waiter.pid))
)
SELECT count(*) - 1 FROM waiting;
"""

WriteResult = tuple[int, str | None, dict[str, Any]]


def psql(process: subprocess.Popen[str], sql: str) -> str:
    """Execute a statement that returns a single unaligned row."""
    assert process.stdin is not None
    assert process.stdout is not None
    process.stdin.write(sql + "\n")
    process.stdin.flush()
    result = process.stdout.readline()
    expect(bool(result), "The PostgreSQL coordination session closed unexpectedly")
    return result.strip()


def put(
    base_url: str,
    credentials: tuple[str, str],
    path: str,
    body: dict[str, Any],
) -> WriteResult:
    """Send one write from a separate process and authenticated HTTP session."""
    api = Api.login(base_url, *credentials)
    with api.session:
        response = api.call("PUT", path, body)
        result = (
            response.json()
            if response.headers.get("Content-Type", "").startswith("application/json")
            else {}
        )
        return response.status_code, v2_etag(response), result


def wait_for_overlap(
    process: subprocess.Popen[str], writes: list[Future[WriteResult]]
) -> None:
    """Prove every submitted writer is blocked behind the coordinator."""
    deadline = monotonic() + 20
    while monotonic() < deadline:
        for write in writes:
            if write.done():
                status, _, _ = write.result()
                raise AssertionError(f"A write finished with {status} before overlap")
        if int(psql(process, WAITING_BACKENDS)) == len(writes):
            return
        sleep(0.05)
    raise AssertionError(f"Timed out waiting for {len(writes)} PostgreSQL sessions")


def overlap_writes(
    db_container: str,
    base_url: str,
    credentials: tuple[str, str],
    pk: int,
    client_uuid: str,
) -> list[WriteResult]:
    """Queue two same-base saves and a classic update on one live row."""
    writes: list[Future[WriteResult]] = []
    docker = which("docker")
    if docker is None:
        raise RuntimeError("Docker is required to reach the disposable PostgreSQL")
    with (
        ProcessPoolExecutor(max_workers=3, mp_context=get_context("spawn")) as pool,
        subprocess.Popen(  # noqa: S603 - Fixed executable and an explicit test container.
            [
                docker,
                "exec",
                "-i",
                "--",
                db_container,
                "psql",
                "-XqAt",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                "superset",
                "-d",
                "superset",
                f"--set=dashboard_id={pk}",
                f"--set=client_uuid={client_uuid}",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        ) as controller,
    ):
        locked = psql(
            controller,
            """BEGIN;
            SET LOCAL statement_timeout = '5s';
            SELECT COALESCE((
                SELECT id FROM dashboards
                WHERE id = :'dashboard_id' AND uuid = :'client_uuid'
                    AND deleted_at IS NULL
                FOR UPDATE
            ), 0);""",
        )
        expect(locked == str(pk), "The chosen database does not contain the test row")
        changes = [
            (f"{V2_API}/{pk}", v2_update_body(markdown_document(content), 1))
            for content in ("first editor", "second editor")
        ]
        changes.append(
            (
                f"{CLASSIC_API}/{pk}",
                {"json_metadata": json.dumps({"refresh_frequency": 37})},
            )
        )
        try:
            for path, body in changes:
                writes.append(pool.submit(put, base_url, credentials, path, body))
                # Submit the classic write after both V2 writers have read revision 1.
                wait_for_overlap(controller, writes)
            print("Three PostgreSQL sessions waited on the same dashboard row.")
        finally:
            psql(controller, "ROLLBACK; SELECT 'released';")
        return [write.result() for write in writes]


def verify(db_container: str, base_url: str, credentials: tuple[str, str]) -> None:
    """Check conflict and persisted state, then verify rejecting a cyclic edit."""
    api = Api.login(base_url, *credentials)
    client_uuid = str(uuid4())
    created = api.json(
        "POST",
        f"{V2_API}/",
        v2_create_body(
            f"Dashboard V2 concurrent saves {client_uuid}",
            markdown_document("original"),
            client_uuid,
        ),
        allowed=(201,),
    )["result"]
    pk = int(created["id"])
    path = f"{V2_API}/{pk}"
    try:
        first, second, classic = overlap_writes(
            db_container, base_url, credentials, pk, client_uuid
        )
        expect(
            sorted([first[0], second[0]]) == [200, 409] and classic[0] == 200,
            f"Expected V2 statuses 200 and 409, classic 200. "
            f"Received {first[0]}, {second[0]}, {classic[0]}",
        )
        winner, conflict = (first, second) if first[0] == 200 else (second, first)
        winner_text = "first editor" if first[0] == 200 else "second editor"
        result = winner[2]["result"]
        expect(
            result["revision"] == 2 and winner[1] == "2", "Expected winner revision 2"
        )
        expect(
            result["document"]["nodes"]["node_1"]["props"]["content"] == winner_text,
            "The winner's response contained a different document",
        )
        expect(
            conflict[2].get("current_revision") == 2 and conflict[1] == "2",
            "The conflict did not report the winning revision",
        )
        stored = api.json("GET", path)["result"]
        expect(
            stored["revision"] == 2 and stored["document"] == result["document"],
            "The winning save was lost",
        )
        classic_result = api.json("GET", f"{CLASSIC_API}/{pk}")["result"]
        expect(
            json.loads(classic_result["json_metadata"])["refresh_frequency"] == 37,
            "The classic metadata change was lost",
        )
        response = api.call(
            "PUT", path, v2_update_body(invalid_documents()["cycle"], 2)
        )
        expect(response.status_code == 422, "The cyclic edit was not rejected with 422")
        expect(
            api.json("GET", path)["result"] == stored,
            "The rejected cyclic edit changed the committed dashboard",
        )
        print(
            "PASS: one save won, one conflicted, classic metadata survived, "
            "and a cyclic edit changed nothing."
        )
    finally:
        api.json("DELETE", f"{CLASSIC_API}/{pk}")
        api.session.close()


def main() -> None:
    """Read test credentials from a local env file without logging them."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Disposable widgets web URL")
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument(
        "--db-container", required=True, help="Disposable Postgres container"
    )
    args = parser.parse_args()
    env = dict(
        line.split("=", 1)
        for line in args.env_file.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )
    verify(
        args.db_container,
        args.base_url,
        (env.get("WIDGETS_ADMIN_USERNAME", "admin"), env["WIDGETS_ADMIN_PASSWORD"]),
    )


if __name__ == "__main__":
    main()
