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
"""Start the standalone React example of @apache-superset/widgets against this stack.

    python nxtbi/widgets/scripts/example_app.py              # session mode, http://localhost:5173
    python nxtbi/widgets/scripts/example_app.py --guest      # guest tokens, http://localhost:5174,
                                                             # plus the token broker
    python nxtbi/widgets/scripts/example_app.py --print-env  # show the settings and exit

The example lives in superset-frontend/packages/superset-widgets/example and reads its
settings from the environment (or from its own .env, which this script neither reads
nor writes). The script asks the running stack for the facts that differ between
installations (the ids of the example datasets, a saved widget to show) and passes
everything through the process environment, so no file outside nxtbi/widgets changes.
Stop with Ctrl+C.

Session mode uses the Superset login of the browser: sign in at the stack's URL first.
Guest mode starts the example's local token broker (server.mjs) with the admin account
of nxtbi/widgets/.env; the password reaches the broker through the environment only.

Requirements: `npm install` once in superset-frontend and once in the example folder.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from widgets_e2e import (  # noqa: E402
    Api,
    binding,
    inline_selector,
    PREFIX,
    reachable,
    read_env,
    REPO_ROOT,
)

EXAMPLE_DIR = (
    REPO_ROOT / "superset-frontend" / "packages" / "superset-widgets" / "example"
)
SAVED_WIDGET_TITLE = f"{PREFIX} example saved widget"


def dataset_id(admin: Api, table_name: str) -> int:
    """The id of an example dataset on this stack."""
    query = f"(filters:!((col:table_name,opr:eq,value:{table_name})),columns:!(id,table_name))"
    rows = admin.json("GET", f"/api/v1/dataset/?q={query}").get("result", [])
    ids = [row["id"] for row in rows if row.get("table_name") == table_name]
    if not ids:
        sys.exit(f"dataset {table_name} not found: is the init job of the stack done?")
    return int(ids[0])


def column_values(admin: Api, dataset: int, column: str, limit: int = 5) -> list[str]:
    """A few distinct values of a column, read through the widget API."""
    values = admin.json(
        "POST",
        "/api/v1/widget/values",
        inline_selector("filter.select", {"datasetId": dataset, "column": column}),
    ).get("result", [])
    return [str(value) for value in values[:limit]]


def saved_widget(admin: Api, dataset: int) -> str:
    """The uuid of the saved widget the example shows, created on first use."""
    for item in admin.json("GET", "/api/v1/widget/").get("result", []):
        if item.get("title") == SAVED_WIDGET_TITLE:
            return str(item["uuid"])
    created = admin.json(
        "POST",
        "/api/v1/widget/",
        {
            "widget_type": "metric-tile",
            "title": SAVED_WIDGET_TITLE,
            "props": {"dataBinding": binding(dataset, ["count"]), "label": "Births"},
        },
        allowed=(201,),
    )
    return str(created["result"]["uuid"])


def example_environment(env: dict[str, str], guest: bool, port: int) -> dict[str, str]:
    """The settings of the example app for this stack (see the example's .env.example)."""
    base = env.get("SUPERSET_PUBLIC_URL", "http://localhost:8089").rstrip("/")
    admin_name = env.get("WIDGETS_ADMIN_USERNAME", "admin")
    admin = Api.login(base, admin_name, env["WIDGETS_ADMIN_PASSWORD"])
    births = dataset_id(admin, "birth_names")
    games = dataset_id(admin, "video_game_sales")
    settings = {
        "SUPERSET_URL": base,
        "EMBED_AUTH": "guest" if guest else "session",
        "EMBED_WIDGET_IDS": saved_widget(admin, births),
        "EMBED_RTL_LOCALE": "ar",
        "FILTER_DATASET_TABLE": "birth_names",
        "FILTER_DATASET_ID": str(births),
        "FILTER_COLUMN": "state",
        "FILTER_VALUES": ",".join(column_values(admin, births, "state")),
        "EMBED_METRIC": "sum__num",
        "EMBED_SECOND_METRIC": "count",
        "EMBED_METRIC_COLUMN": "num",
        "EMBED_CATEGORY": "gender",
        "EMBED_CATEGORY_VALUES": "boy,girl",
        "EMBED_LABEL": "name",
        # A second provider on another dataset, for the isolation section of the example.
        # In guest mode the broker grants each of its two audiences one of the datasets.
        "EMBED_B_DATASET_TABLE": "video_game_sales",
        "EMBED_B_DATASET_ID": str(games),
        "EMBED_B_METRIC": "count",
        "EMBED_B_DIMENSION": "genre",
        "EMBED_B_VALUES": ",".join(column_values(admin, games, "genre", 3)),
        "BROKER_PORT": env.get("BROKER_PORT", "3011"),
    }
    if guest:
        settings["SUPERSET_USERNAME"] = admin_name
        settings["SUPERSET_PASSWORD"] = env["WIDGETS_ADMIN_PASSWORD"]
        # The broker answers the page of this origin only.
        settings["BROKER_ALLOWED_ORIGIN"] = f"http://localhost:{port}"
    return settings


def start(command: str, environment: dict[str, str]) -> subprocess.Popen[Any]:
    """Start a command of the example folder with the given settings."""
    return subprocess.Popen(  # noqa: S602 - npm is a .cmd shim on Windows
        command, cwd=str(EXAMPLE_DIR), env={**os.environ, **environment}, shell=True
    )


def main() -> int:
    """Start the example (and, in guest mode, its broker); return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--guest", action="store_true", help="guest-token mode with the local broker"
    )
    parser.add_argument(
        "--port", type=int, help="port of the app (default 5173, guest mode 5174)"
    )
    parser.add_argument(
        "--print-env", action="store_true", help="print the settings and exit"
    )
    args = parser.parse_args()
    env = read_env()
    base = env.get("SUPERSET_PUBLIC_URL", "http://localhost:8089").rstrip("/")
    if not reachable(f"{base}/health"):
        print(f"{base}/health does not answer: start the stack first", file=sys.stderr)
        return 2
    port = args.port or (5174 if args.guest else 5173)
    settings = example_environment(env, args.guest, port)
    if args.print_env:
        for key, value in settings.items():
            print(f"{key}={'<hidden>' if key == 'SUPERSET_PASSWORD' else value}")
        return 0
    if not (EXAMPLE_DIR / "node_modules").is_dir():
        print(f"run `npm install` in {EXAMPLE_DIR} first", file=sys.stderr)
        return 2
    origins = env.get(
        "NXTBI_WIDGETS_CORS_ORIGINS", "http://localhost:5173,http://localhost:5174"
    )
    if f"http://localhost:{port}" not in origins:
        print(
            f"warning: http://localhost:{port} is not in NXTBI_WIDGETS_CORS_ORIGINS; "
            "the API will refuse the app's requests",
            file=sys.stderr,
        )

    processes: list[subprocess.Popen[Any]] = []
    try:
        if args.guest:
            processes.append(start("node server.mjs", settings))
        processes.append(start(f"npm run dev -- --port {port} --strictPort", settings))
        print(
            f"example app: http://localhost:{port}  ({settings['EMBED_AUTH']} mode, Superset {base})"
        )
        if not args.guest:
            print(f"session mode: sign in at {base}/login/ in the same browser first")
        while all(process.poll() is None for process in processes):
            time.sleep(1)
        return (
            next(
                (
                    process.returncode
                    for process in processes
                    if process.poll() is not None
                ),
                0,
            )
            or 0
        )
    except KeyboardInterrupt:
        return 0
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()


if __name__ == "__main__":
    sys.exit(main())
