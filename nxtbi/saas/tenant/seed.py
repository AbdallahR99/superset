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
"""Create the viewer role and one published Classic dashboard for this tenant."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

from flask import current_app

from superset import db, security_manager
from superset.app import create_app
from superset.utils import json

if TYPE_CHECKING:
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.slice import Slice

DATABASE_NAME = "Workspace warehouse"
TABLE_NAME = "workspace_kpis"
METRIC_NAME = "workspace_value"
CHART_NAME = "Workspace value"
DASHBOARD_TITLE = "Workspace overview"
DASHBOARD_SLUG = "workspace-overview"

_VIEWER_PERMISSIONS = {
    ("can_dashboard", "Superset"),
    ("can_read", "Chart"),
    ("can_read", "CurrentUserRestApi"),
    ("can_read", "Dashboard"),
    ("can_read", "DashboardFilterStateRestApi"),
    ("can_read", "DashboardPermalinkRestApi"),
    ("can_read", "Dataset"),
    ("can_read", "SecurityRestApi"),
    ("menu_access", "Dashboards"),
}


def seed_dataset() -> SqlaTable:
    """Register the tenant's data using its read-only PostgreSQL credentials."""
    # Mapped encrypted columns require Superset's initialized app.
    from superset.connectors.sqla.models import SqlaTable, SqlMetric
    from superset.models.core import Database

    warehouse = (
        db.session.query(Database).filter_by(database_name=DATABASE_NAME).one_or_none()
    )
    if warehouse is None:
        warehouse = Database(database_name=DATABASE_NAME)
        db.session.add(warehouse)
    warehouse.set_sqlalchemy_uri(current_app.config["NXTBI_SAAS_WAREHOUSE_URI"])
    db.session.flush()

    dataset = (
        db.session.query(SqlaTable)
        .filter_by(database_id=warehouse.id, schema="analytics", table_name=TABLE_NAME)
        .one_or_none()
    )
    if dataset is None:
        dataset = SqlaTable(
            database=warehouse, schema="analytics", table_name=TABLE_NAME
        )
        db.session.add(dataset)
        db.session.flush()
        dataset.fetch_metadata()
    if not any(metric.metric_name == METRIC_NAME for metric in dataset.metrics):
        dataset.metrics.append(
            SqlMetric(metric_name=METRIC_NAME, expression="SUM(value)")
        )
    db.session.flush()
    return dataset


def seed_role(dataset: SqlaTable) -> None:
    """Select only the dashboard read permissions that exist in Gamma."""
    gamma = security_manager.find_role("Gamma")
    if gamma is None:
        raise RuntimeError("Run superset init before seeding the tenant")
    role = security_manager.add_role(current_app.config["NXTBI_SAAS_VIEWER_ROLE"])
    if role is None:
        raise RuntimeError("Could not create the tenant viewer role")
    role.permissions = [
        grant
        for grant in gamma.permissions
        if (grant.permission.name, grant.view_menu.name) in _VIEWER_PERMISSIONS
    ]
    grant = security_manager.add_permission_view_menu("datasource_access", dataset.perm)
    if grant is None:
        raise RuntimeError("Could not create the tenant dataset permission")
    role.permissions.append(grant)


def dashboard_position(chart: Slice) -> dict[str, Any]:
    """Describe one native dashboard row with its chart."""
    chart_node = f"CHART-{chart.id}"
    return {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"id": "ROOT_ID", "type": "ROOT", "children": ["GRID_ID"]},
        "GRID_ID": {
            "id": "GRID_ID",
            "type": "GRID",
            "children": ["ROW-workspace"],
            "parents": ["ROOT_ID"],
        },
        "HEADER_ID": {
            "id": "HEADER_ID",
            "type": "HEADER",
            "meta": {"text": DASHBOARD_TITLE},
        },
        "ROW-workspace": {
            "id": "ROW-workspace",
            "type": "ROW",
            "children": [chart_node],
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        },
        chart_node: {
            "id": chart_node,
            "type": "CHART",
            "children": [],
            "parents": ["ROOT_ID", "GRID_ID", "ROW-workspace"],
            "meta": {
                "chartId": chart.id,
                "uuid": str(chart.uuid),
                "sliceName": CHART_NAME,
                "height": 16,
                "width": 6,
            },
        },
    }


def seed_dashboard(dataset: SqlaTable) -> None:
    """Create or refresh the seeded chart and its published dashboard."""
    from superset.models.dashboard import Dashboard
    from superset.models.slice import Slice

    tenant = current_app.config["NXTBI_SAAS_TENANT_SLUG"]
    chart_uuid = uuid5(NAMESPACE_URL, f"nxtbi-saas/{tenant}/workspace-value")
    chart = db.session.query(Slice).filter_by(uuid=chart_uuid).one_or_none()
    if chart is None:
        chart = Slice(uuid=chart_uuid)
        db.session.add(chart)
    chart.slice_name = CHART_NAME
    chart.datasource_id = dataset.id
    chart.datasource_type = "table"
    chart.datasource_name = dataset.table_name
    chart.viz_type = "big_number_total"
    chart.params = json.dumps(
        {
            "datasource": f"{dataset.id}__table",
            "viz_type": chart.viz_type,
            "metric": METRIC_NAME,
            "time_range": "No filter",
            "y_axis_format": ",d",
        }
    )
    db.session.flush()
    chart.query_context = json.dumps(
        {
            "datasource": {"id": dataset.id, "type": "table"},
            "queries": [{"columns": [], "metrics": [METRIC_NAME], "row_limit": 1}],
            "form_data": chart.form_data,
            "result_type": "full",
            "result_format": "json",
        }
    )

    dashboard_uuid = uuid5(NAMESPACE_URL, f"nxtbi-saas/{tenant}/workspace-overview")
    dashboard = db.session.query(Dashboard).filter_by(uuid=dashboard_uuid).one_or_none()
    if dashboard is None:
        dashboard = Dashboard(uuid=dashboard_uuid, slug=DASHBOARD_SLUG)
        db.session.add(dashboard)
    dashboard.dashboard_title = DASHBOARD_TITLE
    dashboard.published = True
    dashboard.slices = [chart]
    dashboard.position_json = json.dumps(dashboard_position(chart))
    dashboard.json_metadata = json.dumps({"native_filter_configuration": []})


def main() -> None:
    """Run seeding with the tenant migration database role."""
    with create_app().app_context():
        dataset = seed_dataset()
        seed_role(dataset)
        seed_dashboard(dataset)
        db.session.commit()


if __name__ == "__main__":
    main()
