"""Idempotent provisioning of the NxtBI demo inside the Superset application context.

    python bootstrap.py accounts         service account + organisation roles
    python bootstrap.py examples-loaded  exit 0 when Superset's example dashboards exist
    python bootstrap.py content          dashboards-as-code import, data access, row level security

Runs in the superset-init container. Everything is keyed by stable names/UUIDs, so a
re-run converges instead of duplicating.
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("nxtbi.bootstrap")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

PLANNING = "ministry-of-planning"
STATS = "statistics-bureau"
# Which organisation may read which dataset (by physical table name).
DATASET_ACCESS: dict[str, list[str]] = {
    "budget_execution": [PLANNING],
    "trade_flows": [STATS],
    "population": [STATS],
    "service_requests": [PLANNING, STATS],
}
# Tables whose rows belong to more than one organisation: isolated with RLS on org_slug.
RLS_TABLES = ["service_requests"]


def _service_username() -> str:
    return os.environ.get("SUPERSET_SERVICE_USERNAME", "nxtbi-service")


def ensure_accounts(app: Any) -> None:
    """Local service account (Admin) and one role per organisation."""
    from superset import db, security_manager as sm
    from superset.subjects.sync import sync_role_subject

    password = os.environ["SUPERSET_SERVICE_PASSWORD"]
    username = _service_username()
    admin_role = sm.find_role("Admin")
    user = sm.find_user(username=username)
    if user is None:
        user = sm.add_user(
            username=username,
            first_name="NxtBI",
            last_name="Service",
            email=f"{username}@nxtbi.local",
            role=admin_role,
            password=password,
        )
        if not user:
            raise RuntimeError(f"could not create service account {username}")
        log.info("created service account %s", username)
    else:
        sm.reset_password(user.id, password)
        if admin_role not in user.roles:
            user.roles.append(admin_role)
        log.info("service account %s present (password synced from the environment)", username)

    for org in app.config["NXTBI_ORGS"]:
        name = f"nxt_org_{org}"
        role = sm.find_role(name)
        if role is None:
            role = sm.add_role(name)
            log.info("created role %s", name)
        sync_role_subject(role)
    for builtin in ("Admin", "Alpha", "Gamma", "sql_lab"):
        sync_role_subject(sm.find_role(builtin))
    db.session.commit()


def examples_loaded() -> bool:
    from superset import db
    from superset.models.dashboard import Dashboard

    if os.environ.get("SUPERSET_FORCE_LOAD_EXAMPLES", "no").lower() in {"1", "true", "yes"}:
        return False
    return db.session.query(Dashboard).filter(Dashboard.slug == "world_health").count() > 0


def import_content(app: Any) -> dict[str, Any]:
    """Generate the YAML bundle and import it with overwrite (assets as code)."""
    import build_bundle  # nxtbi/bootstrap/build_bundle.py

    from superset import security_manager as sm
    from superset.commands.importers.v1.assets import ImportAssetsCommand
    from superset.utils.core import override_user

    # The database YAML carries the read-only connection string, so the bundle is written
    # to a private temp dir inside the container and never to a mounted folder.
    out = Path(tempfile.mkdtemp(prefix="nxtbi_bundle_"))
    manifest = build_bundle.build(out, app.config["NXTBI_DEMO_SQLALCHEMY_URI"])
    contents = build_bundle.read_contents(out / "nxtbi_bundle")
    user = sm.find_user(username=_service_username())
    with override_user(user):
        ImportAssetsCommand(contents, overwrite=True).run()
    log.info(
        "imported bundle: %d datasets, %d charts, %d dashboards",
        len(manifest["datasets"]), len(manifest["charts"]), len(manifest["dashboards"]),
    )
    return manifest


def _dataset(table_name: str, uuid: str) -> Any:
    from superset import db
    from superset.connectors.sqla.models import SqlaTable

    dataset = db.session.query(SqlaTable).filter(SqlaTable.uuid == uuid).one_or_none()
    if dataset is None:
        raise RuntimeError(f"dataset {table_name} ({uuid}) not found after import")
    return dataset


def grant_data_access(manifest: dict[str, Any]) -> None:
    """Organisation roles get datasource_access on exactly their datasets."""
    from superset import db, security_manager as sm

    wanted: dict[str, set[int]] = {}
    for table_name, uuid in manifest["datasets"].items():
        dataset = _dataset(table_name, uuid)
        pvm = sm.add_permission_view_menu("datasource_access", dataset.perm)
        for org in DATASET_ACCESS.get(table_name, []):
            role = sm.find_role(f"nxt_org_{org}")
            if role is None:  # organisation not configured in NXTBI_ORGS
                continue
            wanted.setdefault(role.name, set()).add(pvm.id)
            if pvm not in role.permissions:
                sm.add_permission_role(role, pvm)
                log.info("granted %s on %s to %s", "datasource_access", dataset.perm, role.name)
    # Remove dataset grants that are no longer declared (keeps the role authoritative).
    for role_name, keep in wanted.items():
        role = sm.find_role(role_name)
        for pvm in list(role.permissions):
            if pvm.permission.name == "datasource_access" and pvm.id not in keep:
                sm.del_permission_role(role, pvm)
                log.info("revoked stale %s from %s", pvm.view_menu.name, role.name)
    db.session.commit()


def _role_subject(role_name: str) -> Any:
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


def _upsert_rls(name: str, filter_type: str, clause: str, group_key: str | None,
                tables: list[Any], subjects: list[Any], description: str) -> None:
    from superset import db
    from superset.connectors.sqla.models import RowLevelSecurityFilter

    rule = db.session.query(RowLevelSecurityFilter).filter_by(name=name).one_or_none()
    if rule is None:
        rule = RowLevelSecurityFilter(name=name)
        db.session.add(rule)
        log.info("created RLS rule %s", name)
    rule.filter_type = filter_type
    rule.clause = clause
    rule.group_key = group_key
    rule.description = description
    rule.tables = tables
    rule.subjects = subjects


def ensure_rls(app: Any, manifest: dict[str, Any]) -> None:
    """Tenant isolation on shared tables.

    Regular rules: members of an organisation role only see that organisation's rows.
    Base rule: everyone who is neither Admin nor in an organisation role sees nothing.
    """
    from superset import db

    tables = [_dataset(t, manifest["datasets"][t]) for t in RLS_TABLES]
    org_subjects = []
    known_orgs = {org for orgs in DATASET_ACCESS.values() for org in orgs}
    for org in app.config["NXTBI_ORGS"]:
        if org not in known_orgs:
            log.warning("organisation %s has no demo data: role created, no grants or RLS rule", org)
            continue
        subject = _role_subject(f"nxt_org_{org}")
        org_subjects.append(subject)
        _upsert_rls(
            name=f"NxtBI org isolation: {org}",
            filter_type="Regular",
            clause=f"org_slug = '{org}'",
            group_key="nxtbi_org",
            tables=tables,
            subjects=[subject],
            description=f"Members of nxt_org_{org} only see rows of {org}. Managed by nxtbi/bootstrap.",
        )
    _upsert_rls(
        name="NxtBI org isolation: deny by default",
        filter_type="Base",
        clause="1 = 0",
        group_key=None,
        tables=tables,
        subjects=[_role_subject("Admin"), *org_subjects],
        description="Anyone outside Admin and the organisation roles sees no rows. Managed by nxtbi/bootstrap.",
    )
    db.session.commit()


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "content"
    from superset.app import create_app

    app = create_app()
    with app.app_context():
        if command == "accounts":
            ensure_accounts(app)
        elif command == "examples-loaded":
            return 0 if examples_loaded() else 1
        elif command == "content":
            manifest = import_content(app)
            grant_data_access(manifest)
            ensure_rls(app, manifest)
            from superset import db

            db.session.commit()
            log.info("NxtBI content ready: %s", ", ".join(sorted(manifest["dashboards"])))
        else:
            print(__doc__)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
