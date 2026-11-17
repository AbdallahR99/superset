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
"""Idempotent provisioning of the Widget Framework stack inside the Superset app context.

    python widgets_bootstrap.py accounts   admin, Gamma demo user, WidgetGuest and
                                           WidgetsRlsDemo roles
    python widgets_bootstrap.py examples   the birth_names and video_game_sales datasets
    python widgets_bootstrap.py rls        the row-level-security demo dataset and rule
    python widgets_bootstrap.py all        the three above, in that order

Runs in the superset-init container of the compose project "nxtbi-widgets". Everything
is keyed by stable names, so a re-run converges instead of duplicating.

The two example datasets are the ones the upstream Playwright specs under
superset-frontend/playwright/tests/dashboard-v2 look up by name. `superset
load_examples` has no option to load a subset, so the bundled loaders of exactly those
two datasets are called directly; when the image does not ship them, two small tables
with the same names and columns are created instead.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("nxtbi.widgets.bootstrap")

GUEST_ROLE = "WidgetGuest"  # GUEST_ROLE_NAME in config/superset_config.py
RLS_ROLE = "WidgetsRlsDemo"
RLS_TABLE = "widgets_rls_demo"
RLS_RULE = "Widgets RLS demo: north only"
RLS_VISIBLE_REGION = "north"

# What the widget endpoints check for a guest, and nothing else:
#   /api/v1/widget/data, /values, /<uuid>   "can read on Chart" (SavedWidgetRestApi)
#   /api/v1/widgets/types, /type/<t>/...    "can read on Chart" (WidgetControlsRestApi)
GUEST_ROLE_PERMISSIONS: list[tuple[str, str]] = [("can_read", "Chart")]
# The embedded Dashboard V2 document route (GET /api/v1/dashboard_v2/embedded/<uuid>)
# also checks "can read on Dashboard". Off by default: no widget endpoint needs it.
GUEST_ROLE_DASHBOARD_PERMISSIONS: list[tuple[str, str]] = [("can_read", "Dashboard")]

# (bundled loader name, table name). The loader names follow the example folders of
# superset/examples; the table names are what the Playwright specs query.
EXAMPLE_DATASETS: list[tuple[str, str]] = [
    ("load_usa_births_names", "birth_names"),
    ("load_video_game_sales", "video_game_sales"),
]
# Saved metrics the specs and the standalone example app name.
EXAMPLE_METRICS: dict[str, dict[str, str]] = {
    "birth_names": {"count": "COUNT(*)", "sum__num": "SUM(num)"},
    "video_game_sales": {"count": "COUNT(*)"},
    RLS_TABLE: {"count": "COUNT(*)", "sum__amount": "SUM(amount)"},
}


def _on(name: str) -> bool:
    """An on/off environment switch."""
    return os.environ.get(name, "off").strip().lower() in {"1", "true", "yes", "on"}


# --------------------------------------------------------------------------- accounts


def _ensure_user(
    username: str, password: str, role_names: list[str], first: str
) -> None:
    """Create a local account or bring its password and roles in line."""
    from superset import security_manager as sm

    roles = [sm.find_role(name) for name in role_names]
    if any(role is None for role in roles):
        raise RuntimeError(f"a role of {role_names} does not exist")
    user = sm.find_user(username=username)
    if user is None:
        user = sm.add_user(
            username=username,
            first_name=first,
            last_name="Widgets",
            email=f"{username}@nxtbi-widgets.local",
            role=roles,
            password=password,
        )
        if not user:
            raise RuntimeError(f"could not create account {username}")
        log.info("created account %s with roles %s", username, role_names)
        return
    sm.reset_password(user.id, password)
    user.roles = roles
    log.info("account %s present (password and roles synced)", username)


def _ensure_role(name: str) -> Any:
    """A role by name, created when missing."""
    from superset import security_manager as sm

    role = sm.find_role(name)
    if role is None:
        role = sm.add_role(name)
        log.info("created role %s", name)
    return role


def ensure_guest_role() -> None:
    """Keep the guest role at exactly the declared permissions."""
    from superset import security_manager as sm

    wanted = list(GUEST_ROLE_PERMISSIONS)
    if _on("NXTBI_WIDGETS_GUEST_DASHBOARD_READ"):
        wanted += GUEST_ROLE_DASHBOARD_PERMISSIONS
    role = _ensure_role(GUEST_ROLE)
    pvms = [
        sm.add_permission_view_menu(permission, view) for permission, view in wanted
    ]
    if any(pvm is None for pvm in pvms):
        raise RuntimeError(f"could not resolve the permissions {wanted}")
    role.permissions = pvms
    log.info(
        "role %s holds exactly: %s", GUEST_ROLE, [f"{p} on {v}" for p, v in wanted]
    )


def ensure_accounts() -> None:
    """Admin, the Gamma demo user and the two purpose-built roles."""
    from superset import db
    from superset.subjects.sync import sync_role_subject

    ensure_guest_role()
    _ensure_role(RLS_ROLE)
    db.session.commit()
    _ensure_user(
        os.environ.get("WIDGETS_ADMIN_USERNAME", "admin"),
        os.environ["WIDGETS_ADMIN_PASSWORD"],
        ["Admin"],
        "Admin",
    )
    # Gamma has no SQL Lab permission and edits no dataset: the principal the
    # "SQL in a widget definition" checks need. The second role carries the data
    # access and is the subject of the RLS rule.
    _ensure_user(
        os.environ.get("WIDGETS_GAMMA_USERNAME", "widgets_gamma"),
        os.environ["WIDGETS_GAMMA_PASSWORD"],
        ["Gamma", RLS_ROLE],
        "Gamma",
    )
    from superset import security_manager as sm

    for name in ("Admin", "Alpha", "Gamma", "sql_lab", GUEST_ROLE, RLS_ROLE):
        sync_role_subject(sm.find_role(name))
    db.session.commit()


# --------------------------------------------------------------------------- datasets


def _examples_schema(database: Any) -> str | None:
    """The default schema of the examples database."""
    from sqlalchemy import inspect

    with database.get_sqla_engine() as engine:
        return inspect(engine).default_schema_name


def _find_dataset(table_name: str) -> Any:
    """The dataset on the examples database with this table name, if any."""
    from superset import db
    from superset.connectors.sqla.models import SqlaTable
    from superset.utils.database import get_example_database

    return (
        db.session.query(SqlaTable)
        .filter_by(table_name=table_name, database_id=get_example_database().id)
        .first()
    )


def _register_table(table_name: str, rows: list[dict[str, Any]], force: bool) -> Any:
    """Write ``rows`` as a physical table of the examples database and register it."""
    import pandas as pd

    from superset import db
    from superset.connectors.sqla.models import SqlaTable
    from superset.sql.parse import Table
    from superset.utils.database import get_example_database

    database = get_example_database()
    schema = _examples_schema(database)
    if force or not database.has_table(Table(table_name, schema=schema)):
        with database.get_sqla_engine() as engine:
            pd.DataFrame(rows).to_sql(
                table_name, engine, schema=schema, if_exists="replace", index=False
            )
        log.info("wrote table %s (%d rows)", table_name, len(rows))
    dataset = _find_dataset(table_name)
    if dataset is None:
        dataset = SqlaTable(table_name=table_name, schema=schema)
        dataset.database = database
        db.session.add(dataset)
        log.info("registered dataset %s", table_name)
    dataset.fetch_metadata()
    return dataset


def _ensure_metrics(dataset: Any) -> None:
    """Add the saved metrics the checks refer to by name."""
    from superset.connectors.sqla.models import SqlMetric

    present = {metric.metric_name for metric in dataset.metrics}
    for name, expression in EXAMPLE_METRICS.get(dataset.table_name, {}).items():
        if name not in present:
            dataset.metrics.append(SqlMetric(metric_name=name, expression=expression))
            log.info("added metric %s to %s", name, dataset.table_name)


def _fallback_rows(table_name: str) -> list[dict[str, Any]]:
    """A small stand-in for a bundled example table, with the same column names."""
    if table_name == "birth_names":
        names = [("Aaron", "boy"), ("Amy", "girl"), ("Omar", "boy"), ("Layla", "girl")]
        rows: list[dict[str, Any]] = []
        for year in (2005, 2006, 2007, 2008):
            for state_index, state in enumerate(("CA", "NY", "TX", "IL", "FL")):
                for name_index, (name, gender) in enumerate(names):
                    num = 100 + 37 * state_index + 11 * name_index + (year - 2005) * 5
                    rows.append(
                        {
                            "ds": datetime(year, 1, 1),
                            "gender": gender,
                            "name": name,
                            "num": num,
                            "state": state,
                            "num_boys": num if gender == "boy" else 0,
                            "num_girls": num if gender == "girl" else 0,
                        }
                    )
        return rows
    if table_name == "video_game_sales":
        games = [
            ("Wii Sports", "Wii", 2006, "Sports", "Nintendo", 41.5, 29.0, 3.8, 8.5),
            (
                "Super Mario Bros.",
                "NES",
                1985,
                "Platform",
                "Nintendo",
                29.1,
                3.6,
                6.8,
                0.8,
            ),
            ("Mario Kart Wii", "Wii", 2008, "Racing", "Nintendo", 15.9, 12.9, 3.8, 3.3),
            ("Tetris", "GB", 1989, "Puzzle", "Nintendo", 23.2, 2.3, 4.2, 0.6),
            (
                "Grand Theft Auto V",
                "PS3",
                2013,
                "Action",
                "Take-Two",
                7.0,
                9.3,
                1.0,
                4.1,
            ),
            (
                "Call of Duty: Black Ops",
                "X360",
                2010,
                "Shooter",
                "Activision",
                9.7,
                3.7,
                0.1,
                1.1,
            ),
            ("FIFA 16", "PS4", 2015, "Sports", "Electronic Arts", 1.1, 6.1, 0.1, 1.3),
            ("Minecraft", "X360", 2013, "Misc", "Microsoft", 5.6, 2.8, 0.0, 0.8),
        ]
        return [
            {
                "rank": rank,
                "name": name,
                "platform": platform,
                "year": year,
                "genre": genre,
                "publisher": publisher,
                "na_sales": na,
                "eu_sales": eu,
                "jp_sales": jp,
                "other_sales": other,
                "global_sales": round(na + eu + jp + other, 2),
            }
            for rank, (
                name,
                platform,
                year,
                genre,
                publisher,
                na,
                eu,
                jp,
                other,
            ) in enumerate(games, start=1)
        ]
    raise ValueError(f"no fallback rows for {table_name}")


def ensure_examples(force: bool) -> None:
    """The two example datasets, from the bundled loaders or from the stand-ins."""
    from superset import db

    try:
        import superset.examples.data_loading as bundled
    except Exception:  # pylint: disable=broad-except
        log.exception("bundled example loaders are not importable")
        bundled = None  # type: ignore[assignment]

    for loader_name, table_name in EXAMPLE_DATASETS:
        loader = getattr(bundled, loader_name, None) if bundled else None
        dataset = None
        if loader is not None:
            try:
                loader(force=force)
                db.session.commit()
                dataset = _find_dataset(table_name)
                log.info(
                    "%s: loaded with the bundled loader %s", table_name, loader_name
                )
            except Exception:  # pylint: disable=broad-except
                db.session.rollback()
                log.exception("%s: bundled loader %s failed", table_name, loader_name)
        if dataset is None:
            log.warning("%s: seeding the small stand-in table instead", table_name)
            dataset = _register_table(table_name, _fallback_rows(table_name), force)
        if not dataset.columns:
            dataset.fetch_metadata()
        _ensure_metrics(dataset)
        db.session.commit()
        log.info(
            "%s ready: id=%s, %d columns, metrics=%s",
            table_name,
            dataset.id,
            len(dataset.columns),
            sorted(metric.metric_name for metric in dataset.metrics),
        )


# --------------------------------------------------------------------------------- rls


def _rls_rows() -> list[dict[str, Any]]:
    """Twelve rows over three regions; the Gamma demo user is limited to one of them."""
    rows: list[dict[str, Any]] = []
    for region_index, region in enumerate((RLS_VISIBLE_REGION, "south", "west")):
        for item in range(4):
            rows.append(
                {
                    "region": region,
                    "product": f"product-{item + 1}",
                    "amount": 100 * (region_index + 1) + 10 * item,
                }
            )
    return rows


def _role_subject(role_name: str) -> Any:
    """The subject row that stands for a role in row-level-security rules."""
    from superset import db, security_manager as sm
    from superset.subjects.models import Subject
    from superset.subjects.sync import sync_role_subject

    role = sm.find_role(role_name)
    if role is None:
        raise RuntimeError(f"role {role_name} not found")
    subject = db.session.query(Subject).filter(Subject.role_id == role.id).one_or_none()
    if subject is None:
        sync_role_subject(role)
        db.session.flush()
        subject = db.session.query(Subject).filter(Subject.role_id == role.id).one()
    return subject


def _grant_datasets(role_name: str, datasets: list[Any]) -> None:
    """Give a role datasource_access on exactly these datasets."""
    from superset import security_manager as sm

    role = sm.find_role(role_name)
    keep: set[int] = set()
    for dataset in datasets:
        pvm = sm.add_permission_view_menu("datasource_access", dataset.perm)
        keep.add(pvm.id)
        if pvm not in role.permissions:
            sm.add_permission_role(role, pvm)
            log.info("granted datasource_access on %s to %s", dataset.perm, role_name)
    for pvm in list(role.permissions):
        if pvm.permission.name == "datasource_access" and pvm.id not in keep:
            sm.del_permission_role(role, pvm)
            log.info("revoked stale %s from %s", pvm.view_menu.name, role_name)


def ensure_rls(force: bool) -> None:
    """One dataset with a rule for the Gamma demo user's role.

    Admin is no subject of the rule and reads all twelve rows; a member of
    WidgetsRlsDemo reads the four rows of one region. The end-to-end script compares
    the two through the widget data endpoint.
    """
    from superset import db
    from superset.connectors.sqla.models import RowLevelSecurityFilter

    dataset = _register_table(RLS_TABLE, _rls_rows(), force)
    _ensure_metrics(dataset)
    db.session.commit()

    birth_names = _find_dataset("birth_names")
    _grant_datasets(
        RLS_ROLE, [item for item in (dataset, birth_names) if item is not None]
    )

    rule = (
        db.session.query(RowLevelSecurityFilter).filter_by(name=RLS_RULE).one_or_none()
    )
    if rule is None:
        rule = RowLevelSecurityFilter(name=RLS_RULE)
        db.session.add(rule)
        log.info("created RLS rule %s", RLS_RULE)
    rule.filter_type = "Regular"
    rule.clause = f"region = '{RLS_VISIBLE_REGION}'"
    rule.group_key = None
    rule.description = (
        f"Members of {RLS_ROLE} only see the rows of region {RLS_VISIBLE_REGION}. "
        "Managed by nxtbi/widgets/bootstrap."
    )
    rule.tables = [dataset]
    rule.subjects = [_role_subject(RLS_ROLE)]
    db.session.commit()
    log.info(
        "RLS demo ready: dataset %s id=%s, rule %r", RLS_TABLE, dataset.id, rule.clause
    )


def main(argv: list[str]) -> int:
    """Run one provisioning command; return a process exit code."""
    command = argv[1] if len(argv) > 1 else "all"
    if command not in {"accounts", "examples", "rls", "all"}:
        print(__doc__)
        return 2
    force = _on("WIDGETS_FORCE_SEED")
    from superset.app import create_app

    app = create_app()
    with app.app_context():
        if command in {"accounts", "all"}:
            ensure_accounts()
        if command in {"examples", "all"}:
            ensure_examples(force)
        if command in {"rls", "all"}:
            ensure_rls(force)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
