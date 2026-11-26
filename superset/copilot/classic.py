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

"""Materialize a verified Copilot proposal as a classic dashboard."""

from dataclasses import dataclass
from typing import Any, cast, Literal
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from superset import db
from superset.commands.chart.create import CreateChartCommand
from superset.commands.dashboard.create import CreateDashboardCommand
from superset.commands.dashboard.exceptions import DashboardCreateFailedError
from superset.copilot.contracts import (
    ContentLocale,
    DashboardProposal,
    ProposalWidget,
    TitleTranslations,
)
from superset.copilot.localization import LOCALIZATION_KEY
from superset.dashboard_v2.document import load_stored_document
from superset.models.dashboard import Dashboard
from superset.models.helpers import skip_visibility_filter
from superset.models.slice import Slice
from superset.utils import json
from superset.utils.core import get_user_id
from superset.utils.decorators import transaction
from superset.widgets.data import resolved_filters_to_adhoc


@dataclass(frozen=True)
class ClassicChartSpec:
    """A verified datasource and native form data for a Classic chart."""

    datasource_id: int
    datasource_type: Literal["table", "semantic_view"]
    title: str
    form_data: dict[str, Any]
    title_translations: TitleTranslations


def classic_chart_form_data(
    widget: ProposalWidget, precision: int | None = None
) -> dict[str, Any]:
    """Map a proposal widget to native chart controls with its saved bindings."""
    form_data: dict[str, Any] = {
        "datasource": f"{widget.dataset_id}__table",
        "row_limit": 100,
        "time_range": "No filter",
        "adhoc_filters": [],
    }
    if widget.filter:
        form_data["adhoc_filters"] = resolved_filters_to_adhoc(
            [{**widget.filter.model_dump(), "operator": "EQUALS"}],
            {widget.filter.column},
        )
    if widget.type == "metric-tile":
        form_data.update(viz_type="big_number_total", metric=widget.metric)
        if precision is not None:
            form_data["y_axis_format"] = f".{precision}%" if precision else "%"
    elif widget.type == "ag-grid-table":
        form_data.update(
            viz_type="table",
            query_mode="aggregate",
            metrics=[widget.metric],
            groupby=[widget.dimension] if widget.dimension else [],
        )
    else:
        line = widget.chart_style == "line"
        form_data.update(
            viz_type="echarts_timeseries_line" if line else "echarts_timeseries_bar",
            metrics=[widget.metric],
            groupby=[],
            x_axis=widget.dimension,
            x_axis_sort=widget.dimension,
            x_axis_sort_asc=True,
            x_axis_sort_series_type="name",
            x_axis_sort_series_ascending=True,
            granularity_sqla=widget.dimension if line else None,
            time_grain_sqla=None,
        )
        if line:
            form_data["orderby"] = [[widget.dimension, True]]
    return form_data


def _classic_layout(title: str, charts: list[Slice]) -> dict[str, Any]:
    """Build classic grid rows retaining the proposal's chart order and sizing."""
    row_ids: list[str] = []
    position: dict[str, Any] = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"id": "ROOT_ID", "type": "ROOT", "children": ["GRID_ID"]},
        "GRID_ID": {
            "id": "GRID_ID",
            "type": "GRID",
            "children": row_ids,
            "parents": ["ROOT_ID"],
        },
        "HEADER_ID": {
            "id": "HEADER_ID",
            "type": "HEADER",
            "meta": {"text": title},
        },
    }
    kpis = sum(cast(str, chart.viz_type) == "big_number_total" for chart in charts)
    kpi_width = 12 // max(2, min(kpis, 4))
    remaining = 0
    row_id = ""
    for chart in charts:
        viz_type = cast(str, chart.viz_type)
        is_kpi = viz_type == "big_number_total"
        width = (
            kpi_width if is_kpi else 12 if viz_type == "echarts_timeseries_line" else 6
        )
        if width > remaining:
            row_id = f"ROW-copilot-{len(row_ids) + 1}"
            row_ids.append(row_id)
            position[row_id] = {
                "id": row_id,
                "type": "ROW",
                "children": [],
                "parents": ["ROOT_ID", "GRID_ID"],
                "meta": {"background": "BACKGROUND_TRANSPARENT"},
            }
            remaining = 12
        chart_id = f"CHART-{chart.id}"
        position[row_id]["children"].append(chart_id)
        position[chart_id] = {
            "id": chart_id,
            "type": "CHART",
            "children": [],
            "parents": ["ROOT_ID", "GRID_ID", row_id],
            "meta": {
                "chartId": chart.id,
                "uuid": str(chart.uuid),
                "sliceName": chart.slice_name,
                "height": 16 if is_kpi else 38,
                "width": width,
            },
        }
        remaining -= width
    return position


def _classic_metadata(
    title: str,
    title_translations: TitleTranslations,
    content_locale: ContentLocale | None,
    charts: list[Slice],
    chart_specs: list[ClassicChartSpec],
) -> dict[str, Any]:
    """Store approved captions alongside their original native chart titles."""
    localization: dict[str, Any] = {
        "sourceLocale": content_locale or "en",
    }
    if title_translations:
        localization["title"] = {
            "source": title,
            "translations": title_translations,
        }
    captions = {
        str(chart.id): {
            "source": chart.slice_name,
            "translations": spec.title_translations,
        }
        for spec, chart in zip(chart_specs, charts, strict=True)
        if spec.title_translations
    }
    if captions:
        localization["widgets"] = captions
    if len(localization) > 1 or content_locale:
        return {LOCALIZATION_KEY: localization}
    return {}


def _existing_dashboard(approval_uuid: UUID) -> Dashboard | None:
    """Return a prior save only to the actor who created and can read it."""
    with skip_visibility_filter(db.session, Dashboard):
        dashboard = (
            db.session.query(Dashboard)
            .filter(Dashboard.uuid == approval_uuid)
            .one_or_none()
        )
    if dashboard is None:
        return None
    user_id = get_user_id()
    if (
        user_id is None
        or dashboard.created_by_fk != user_id
        or dashboard.deleted_at is not None
        or load_stored_document(dashboard.json_metadata) is not None
    ):
        raise ValueError("A dashboard with this UUID already exists.")
    dashboard.raise_for_access()
    return dashboard


@transaction(on_error=None)
def _save_classic_dashboard(
    approval_uuid: UUID,
    title: str,
    title_translations: TitleTranslations,
    content_locale: ContentLocale | None,
    chart_specs: list[ClassicChartSpec],
) -> tuple[int, bool]:
    """Save the dashboard and all its charts in a single transaction."""
    if existing := _existing_dashboard(approval_uuid):
        return cast(int, existing.id), False

    charts: list[Slice] = []
    for spec in chart_specs:
        chart = CreateChartCommand(
            {
                "slice_name": spec.title,
                "viz_type": spec.form_data["viz_type"],
                "datasource_id": spec.datasource_id,
                "datasource_type": spec.datasource_type,
                "params": json.dumps(spec.form_data),
            }
        ).run()
        charts.append(cast(Slice, chart))
    db.session.flush()

    layout = _classic_layout(title, charts)
    metadata = {
        **_classic_metadata(
            title, title_translations, content_locale, charts, chart_specs
        ),
        "positions": layout,
    }
    dashboard = cast(
        Dashboard,
        CreateDashboardCommand(
            {
                "uuid": approval_uuid,
                "dashboard_title": title,
                "json_metadata": json.dumps(metadata),
                "position_json": json.dumps(layout),
                "published": False,
            }
        ).run(),
    )
    if {chart.id for chart in dashboard.slices} != {chart.id for chart in charts}:
        raise DashboardCreateFailedError()
    return cast(int, dashboard.id), True


def save_classic_dashboard(
    *,
    approval_uuid: UUID,
    title: str,
    title_translations: TitleTranslations,
    content_locale: ContentLocale | None,
    chart_specs: list[ClassicChartSpec],
) -> tuple[int, bool]:
    """Persist verified chart specifications, resolving a retry to its original save."""
    try:
        return _save_classic_dashboard(
            approval_uuid, title, title_translations, content_locale, chart_specs
        )
    except IntegrityError as ex:
        if existing := _existing_dashboard(approval_uuid):
            return cast(int, existing.id), False
        raise DashboardCreateFailedError() from ex
    except SQLAlchemyError as ex:
        raise DashboardCreateFailedError() from ex


def create_classic_dashboard(
    proposal: DashboardProposal,
    approval_uuid: UUID,
    percentages: dict[tuple[int, str], int],
) -> tuple[int, bool]:
    """Compile a validated table-backed proposal and save it atomically."""
    return save_classic_dashboard(
        approval_uuid=approval_uuid,
        title=proposal.title,
        title_translations=proposal.title_translations,
        content_locale=proposal.content_locale,
        chart_specs=[
            ClassicChartSpec(
                datasource_id=widget.dataset_id,
                datasource_type="table",
                title=widget.title or widget.metric[:250],
                form_data=classic_chart_form_data(
                    widget, percentages.get((widget.dataset_id, widget.metric))
                ),
                title_translations=widget.title_translations,
            )
            for widget in proposal.widgets
        ],
    )
