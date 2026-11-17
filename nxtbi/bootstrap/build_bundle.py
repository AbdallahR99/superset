"""Dashboards-as-code generator for the NxtBI Superset demo.

Writes a Superset "assets" import bundle (database, datasets, charts, dashboards)
that ``ImportAssetsCommand`` / ``POST /api/v1/assets/import/`` accepts:

    <out>/nxtbi_bundle/metadata.yaml
    <out>/nxtbi_bundle/databases/NxtBI_Demo.yaml
    <out>/nxtbi_bundle/datasets/NxtBI_Demo/<table>.yaml
    <out>/nxtbi_bundle/charts/<key>.yaml
    <out>/nxtbi_bundle/dashboards/<slug>.yaml
    <out>/manifest.json

Usage:
    NXTBI_DEMO_SQLALCHEMY_URI=postgresql+psycopg2://user:pw@db:5432/nxtbi_demo \
        python build_bundle.py --out /path/to/out

Properties:
    * Deterministic. Every UUID is ``uuid5(NAMESPACE, key)`` and the metadata
      timestamp is fixed, so two runs produce byte-identical files and a re-import
      with ``overwrite=True`` updates the same objects in place.
    * The SQLAlchemy URI (which carries the read-only password) is read from the
      environment only and is written to exactly one file, the database YAML. It is
      never printed.
    * Charts reference saved dataset metrics by name; the warehouse schema mirrors
      ``nxtbi/seed/seed_demo_data.py``.

Importable API:
    build(out_dir, sqlalchemy_uri) -> manifest dict
    read_contents(bundle_dir)      -> {"metadata.yaml": "...", "charts/x.yaml": "..."}
                                      (the ``contents`` argument of ImportAssetsCommand)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

# --------------------------------------------------------------------------- constants

NAMESPACE = uuid.UUID("6e787462-692d-4e78-9462-692d64656d6f")
BUNDLE_DIR_NAME = "nxtbi_bundle"
ENV_URI = "NXTBI_DEMO_SQLALCHEMY_URI"
VERSION = "1.0.0"
FIXED_TIMESTAMP = "2026-11-17T00:00:00+00:00"

DATABASE_NAME = "NxtBI Demo"
DATABASE_FILE = "databases/NxtBI_Demo.yaml"
SCHEMA = "nxtbi"

# Categorical scheme registered by the deployment config (EXTRA_CATEGORICAL_COLOR_SCHEMES).
COLOR_SCHEME = "nxtbiColors"
# Built-in sequential schemes for heatmaps (never the categorical scheme).
SEQ_BLUE = "schemeBlues"
SEQ_GREEN = "schemeYlGnBu"
SEQ_WARM = "schemeYlOrRd"

# Conditional-formatting colours (hex, used with alpha gradients by the table plugins).
CF_GREEN = "#5AC189"
CF_RED = "#E04355"
CF_AMBER = "#FCC700"
CF_BLUE = "#1FA8C9"

# Cross-filter emitters (Behavior.InteractiveChart) among the viz types used here.
CROSS_FILTER_EMITTERS = {
    "echarts_timeseries_line",
    "echarts_timeseries_bar",
    "echarts_timeseries_smooth",
    "echarts_area",
    "mixed_timeseries",
    "pie",
    "treemap_v2",
    "sunburst_v2",
    "funnel",
    "gauge_chart",
    "radar",
    "box_plot",
    "pivot_table_v2",
    "table",
}


def uid(key: str) -> str:
    """Stable UUID for an asset key."""
    return str(uuid.uuid5(NAMESPACE, key))


# --------------------------------------------------------------------------- datasets


def col(
    name: str,
    type_: str,
    verbose: str,
    description: str | None = None,
    *,
    dttm: bool = False,
    groupby: bool = True,
    expression: str | None = None,
) -> dict[str, Any]:
    return {
        "column_name": name,
        "verbose_name": verbose,
        "description": description,
        "type": type_,
        "is_dttm": dttm,
        "is_active": True,
        "groupby": groupby,
        "filterable": True,
        "expression": expression,
        "python_date_format": None,
        "advanced_data_type": None,
        "extra": {},
    }


def metric(
    name: str,
    verbose: str,
    expression: str,
    d3format: str | None,
    description: str,
    *,
    currency: dict[str, str] | None = None,
    metric_type: str | None = None,
) -> dict[str, Any]:
    return {
        "metric_name": name,
        "verbose_name": verbose,
        "metric_type": metric_type,
        "expression": expression,
        "description": description,
        "d3format": d3format,
        "currency": currency,
        "extra": {},
        "warning_text": None,
    }


USD = {"symbol": "USD", "symbolPosition": "prefix"}
ORG_DESC = "Tenant key (Keycloak group slug); the Row Level Security rules filter on this column."

DATASETS: dict[str, dict[str, Any]] = {
    "budget_execution": {
        "main_dttm_col": "period_date",
        "description": (
            "Monthly capital budget execution by sector, programme and region "
            "(Ministry of Planning). Grain: month x programme x region. Synthetic demo data."
        ),
        "columns": [
            col("period_date", "DATE", "Period (month)", "First day of the reporting month.", dttm=True),
            col("fiscal_year", "INTEGER", "Fiscal year", "Calendar year of the period."),
            col("fiscal_quarter", "TEXT", "Fiscal quarter", "Q1 to Q4."),
            col("org_slug", "TEXT", "Organisation key", ORG_DESC),
            col("sector_en", "TEXT", "Sector", "Budget sector (English)."),
            col("sector_ar", "TEXT", "القطاع", "Budget sector (Arabic)."),
            col("program_en", "TEXT", "Programme", "Capital programme inside the sector."),
            col("region_en", "TEXT", "Region", "Region (English)."),
            col("region_ar", "TEXT", "المنطقة", "Region (Arabic)."),
            col("allocated_amount", "NUMERIC(16, 2)", "Allocated amount", "Budget allocated for the month.", groupby=False),
            col("committed_amount", "NUMERIC(16, 2)", "Committed amount", "Amount under contract / purchase order.", groupby=False),
            col("spent_amount", "NUMERIC(16, 2)", "Spent amount", "Amount actually disbursed.", groupby=False),
            col("projects_active", "INTEGER", "Active projects", "Projects running in the month (snapshot).", groupby=False),
            col("projects_delayed", "INTEGER", "Delayed projects", "Active projects behind schedule (snapshot).", groupby=False),
            col(
                "fiscal_period", "TEXT", "Fiscal period",
                "Calculated: fiscal year and quarter, e.g. 2025-Q3 (sorts chronologically).",
                expression="CAST(fiscal_year AS TEXT) || '-' || fiscal_quarter",
            ),
            col(
                "unspent_amount", "NUMERIC", "Unspent amount",
                "Calculated: allocated minus spent for the row.",
                groupby=False,
                expression="allocated_amount - spent_amount",
            ),
            col(
                "execution_band", "TEXT", "Execution band",
                "Calculated: row-level execution rate bucket.",
                expression=(
                    "CASE WHEN spent_amount >= 0.9 * allocated_amount THEN '1. On track (90%+)' "
                    "WHEN spent_amount >= 0.7 * allocated_amount THEN '2. Watch (70-90%)' "
                    "ELSE '3. At risk (<70%)' END"
                ),
            ),
        ],
        "metrics": [
            metric("count", "Rows", "COUNT(*)", ",d", "Number of fact rows.", metric_type="count"),
            metric("allocated", "Allocated budget", "SUM(allocated_amount)", "SMART_NUMBER",
                   "Total budget allocated."),
            metric("committed", "Committed", "SUM(committed_amount)", "SMART_NUMBER",
                   "Total amount committed (contracted)."),
            metric("spent", "Spent", "SUM(spent_amount)", "SMART_NUMBER", "Total amount disbursed."),
            metric("unspent", "Unspent balance", "SUM(allocated_amount) - SUM(spent_amount)", "SMART_NUMBER",
                   "Allocated minus spent."),
            metric("execution_rate", "Execution rate",
                   "SUM(spent_amount) / NULLIF(SUM(allocated_amount), 0)", ".1%",
                   "Spent divided by allocated."),
            metric("commitment_rate", "Commitment rate",
                   "SUM(committed_amount) / NULLIF(SUM(allocated_amount), 0)", ".1%",
                   "Committed divided by allocated."),
            metric("active_projects", "Active projects (monthly avg)",
                   "SUM(projects_active) * 1.0 / NULLIF(COUNT(DISTINCT period_date), 0)", ",.0f",
                   "Active projects per month: exact for one month, the monthly average over longer periods."),
            metric("delayed_projects", "Delayed projects (monthly avg)",
                   "SUM(projects_delayed) * 1.0 / NULLIF(COUNT(DISTINCT period_date), 0)", ",.0f",
                   "Delayed projects per month: exact for one month, the monthly average over longer periods."),
            metric("delayed_share", "Delayed share",
                   "SUM(projects_delayed) * 1.0 / NULLIF(SUM(projects_active), 0)", ".1%",
                   "Delayed projects divided by active projects."),
        ],
    },
    "trade_flows": {
        "main_dttm_col": "period_date",
        "description": (
            "Monthly merchandise trade by partner country and commodity group "
            "(Statistics Bureau). Grain: month x flow x partner x commodity. Synthetic demo data."
        ),
        "columns": [
            col("period_date", "DATE", "Period (month)", "First day of the reporting month.", dttm=True),
            col("org_slug", "TEXT", "Organisation key", ORG_DESC),
            col("flow", "TEXT", "Flow", "Import or Export."),
            col("partner_iso3", "TEXT", "Partner ISO3", "ISO 3166-1 alpha-3 code of the trading partner."),
            col("partner_en", "TEXT", "Trading partner", "Partner country (English)."),
            col("partner_ar", "TEXT", "الشريك التجاري", "Partner country (Arabic)."),
            col("partner_region", "TEXT", "Partner region", "World region of the partner."),
            col("commodity_en", "TEXT", "Commodity group", "Commodity group (English)."),
            col("commodity_ar", "TEXT", "مجموعة السلع", "Commodity group (Arabic)."),
            col("value_usd", "NUMERIC(16, 2)", "Value (USD)", "Trade value in US dollars.", groupby=False),
            col("weight_tons", "NUMERIC(14, 2)", "Weight (tons)", "Net weight in metric tons.", groupby=False),
            col(
                "signed_value_usd", "NUMERIC", "Signed value (USD)",
                "Calculated: exports positive, imports negative.",
                groupby=False,
                expression="CASE WHEN flow = 'Export' THEN value_usd ELSE -value_usd END",
            ),
            col(
                "trade_year", "INTEGER", "Year",
                "Calculated: calendar year of the period.",
                expression="CAST(EXTRACT(YEAR FROM period_date) AS INTEGER)",
            ),
        ],
        "metrics": [
            metric("count", "Rows", "COUNT(*)", ",d", "Number of fact rows.", metric_type="count"),
            metric("exports_usd", "Exports",
                   "SUM(CASE WHEN flow = 'Export' THEN value_usd ELSE 0 END)", "SMART_NUMBER",
                   "Export value in USD.", currency=USD),
            metric("imports_usd", "Imports",
                   "SUM(CASE WHEN flow = 'Import' THEN value_usd ELSE 0 END)", "SMART_NUMBER",
                   "Import value in USD.", currency=USD),
            metric("trade_balance", "Trade balance",
                   "SUM(CASE WHEN flow = 'Export' THEN value_usd ELSE -value_usd END)", "SMART_NUMBER",
                   "Exports minus imports in USD.", currency=USD),
            metric("total_trade", "Total trade", "SUM(value_usd)", "SMART_NUMBER",
                   "Exports plus imports in USD.", currency=USD),
            metric("tonnage", "Tonnage", "SUM(weight_tons)", "SMART_NUMBER", "Net weight in metric tons."),
            metric("unit_value", "Unit value (USD per ton)",
                   "SUM(value_usd) / NULLIF(SUM(weight_tons), 0)", ",.0f",
                   "Value divided by weight.", currency=USD),
            metric("export_coverage", "Export coverage",
                   "SUM(CASE WHEN flow = 'Export' THEN value_usd ELSE 0 END) / "
                   "NULLIF(SUM(CASE WHEN flow = 'Import' THEN value_usd ELSE 0 END), 0)", ".0%",
                   "Exports divided by imports."),
            metric("partners", "Trading partners", "COUNT(DISTINCT partner_iso3)", ",d",
                   "Number of distinct partner countries."),
        ],
    },
    "population": {
        "main_dttm_col": "year_date",
        "description": (
            "Mid-year population estimates by region, gender and age group "
            "(Statistics Bureau). Grain: year x region x gender x age group. Synthetic demo data."
        ),
        "columns": [
            col("year_date", "DATE", "Year", "1 January of the estimate year.", dttm=True),
            col("census_year", "INTEGER", "Census year", "Estimate year as a number."),
            col("org_slug", "TEXT", "Organisation key", ORG_DESC),
            col("region_en", "TEXT", "Region", "Region (English)."),
            col("region_ar", "TEXT", "المنطقة", "Region (Arabic)."),
            col("gender_en", "TEXT", "Gender", "Male or Female."),
            col("gender_ar", "TEXT", "الجنس", "Gender (Arabic)."),
            col("age_group", "TEXT", "Age group", "Ten-year age band."),
            col("age_order", "INTEGER", "Age order", "Sort order of the age band (1 = youngest)."),
            col("population", "INTEGER", "Population", "Estimated persons.", groupby=False),
            col(
                "age_band", "TEXT", "Age band",
                "Calculated: age band label ordered by age_order (zero-padded so it sorts youngest first).",
                expression="CASE WHEN age_order = 1 THEN '00-09' ELSE age_group END",
            ),
            col(
                "life_stage", "TEXT", "Life stage",
                "Calculated: Youth (0-19), Working age (20-59), Senior (60+).",
                expression=(
                    "CASE WHEN age_order <= 2 THEN '1. Youth (0-19)' "
                    "WHEN age_order <= 6 THEN '2. Working age (20-59)' "
                    "ELSE '3. Senior (60+)' END"
                ),
            ),
        ],
        "metrics": [
            metric("count", "Rows", "COUNT(*)", ",d", "Number of fact rows.", metric_type="count"),
            metric("population_total", "Population", "SUM(population)", "SMART_NUMBER",
                   "Total persons. Additive within a year: use with a yearly time grain or one year."),
            metric("population_avg", "Population (annual average)",
                   "SUM(population) * 1.0 / NULLIF(COUNT(DISTINCT census_year), 0)", "SMART_NUMBER",
                   "Persons per year: exact for one year, the annual average over several years."),
            metric("female_population", "Female",
                   "SUM(CASE WHEN gender_en = 'Female' THEN population ELSE 0 END) * 1.0 / "
                   "NULLIF(COUNT(DISTINCT census_year), 0)", "SMART_NUMBER",
                   "Female persons per year (annual average)."),
            metric("male_population_mirrored", "Male (mirrored)",
                   "-1.0 * SUM(CASE WHEN gender_en = 'Male' THEN population ELSE 0 END) / "
                   "NULLIF(COUNT(DISTINCT census_year), 0)", "SMART_NUMBER",
                   "Male persons per year as a negative number, for the left side of an age pyramid."),
            metric("female_share", "Female share",
                   "SUM(CASE WHEN gender_en = 'Female' THEN population ELSE 0 END) * 1.0 / "
                   "NULLIF(SUM(population), 0)", ".1%",
                   "Female persons divided by all persons."),
            metric("youth_share", "Youth share (0-19)",
                   "SUM(CASE WHEN age_order <= 2 THEN population ELSE 0 END) * 1.0 / "
                   "NULLIF(SUM(population), 0)", ".1%",
                   "Persons aged 0-19 divided by all persons."),
            metric("senior_share", "Senior share (60+)",
                   "SUM(CASE WHEN age_order >= 7 THEN population ELSE 0 END) * 1.0 / "
                   "NULLIF(SUM(population), 0)", ".1%",
                   "Persons aged 60 and over divided by all persons."),
        ],
    },
    "service_requests": {
        "main_dttm_col": "created_at",
        "description": (
            "Citizen and business service requests of both organisations. One row per request; "
            "org_slug drives the Row Level Security demo. Synthetic demo data."
        ),
        "columns": [
            col("request_id", "BIGINT", "Request ID", "Unique request number."),
            col("created_at", "TIMESTAMP WITHOUT TIME ZONE", "Created at", "Submission timestamp.", dttm=True),
            col("org_slug", "TEXT", "Organisation key", ORG_DESC),
            col("org_name_en", "TEXT", "Organisation", "Organisation name (English)."),
            col("org_name_ar", "TEXT", "الجهة", "Organisation name (Arabic)."),
            col("service_en", "TEXT", "Service", "Service name (English)."),
            col("service_ar", "TEXT", "الخدمة", "Service name (Arabic)."),
            col("channel_en", "TEXT", "Channel", "Submission channel (English)."),
            col("channel_ar", "TEXT", "القناة", "Submission channel (Arabic)."),
            col("region_en", "TEXT", "Region", "Applicant region (English)."),
            col("region_ar", "TEXT", "المنطقة", "Applicant region (Arabic)."),
            col("applicant_segment", "TEXT", "Applicant segment", "Citizen, Resident, Business or Government Entity."),
            col("status", "TEXT", "Status", "Completed, In Progress, Escalated or Rejected."),
            col("sla_hours", "INTEGER", "SLA target (hours)", "Service level target for the service.", groupby=False),
            col("resolution_hours", "NUMERIC(8, 1)", "Resolution time (hours)", "Hours to close; empty while in progress.", groupby=False),
            col("sla_met", "BOOLEAN", "SLA met", "True when closed within the SLA target; empty while in progress."),
            col("satisfaction", "SMALLINT", "Satisfaction (1-5)", "Survey score; empty when not answered.", groupby=False),
            col(
                "sla_status", "TEXT", "SLA status",
                "Calculated: Within SLA, Breached or Open.",
                expression=(
                    "CASE WHEN sla_met IS NULL THEN 'Open' "
                    "WHEN sla_met THEN 'Within SLA' ELSE 'Breached' END"
                ),
            ),
            col(
                "channel_type", "TEXT", "Channel type",
                "Calculated: Digital (app, portal) or Assisted (service centre, call centre).",
                expression=(
                    "CASE WHEN channel_en IN ('Mobile App', 'Web Portal') THEN 'Digital' ELSE 'Assisted' END"
                ),
            ),
            col(
                "resolution_days", "NUMERIC", "Resolution time (days)",
                "Calculated: resolution hours divided by 24.",
                groupby=False,
                expression="resolution_hours / 24.0",
            ),
            col(
                "weekday", "TEXT", "Weekday",
                "Calculated: ISO weekday number and name, e.g. 1 Mon (Friday and Saturday are the weekend).",
                expression="TO_CHAR(created_at, 'ID Dy')",
            ),
        ],
        "metrics": [
            metric("requests", "Requests", "COUNT(*)", ",d", "Number of service requests.", metric_type="count"),
            metric("completed", "Completed", "SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END)", ",d",
                   "Requests closed as completed."),
            metric("open_requests", "In progress", "SUM(CASE WHEN status = 'In Progress' THEN 1 ELSE 0 END)", ",d",
                   "Requests still being processed."),
            metric("completion_rate", "Completion rate",
                   "SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) * 1.0 / NULLIF(COUNT(*), 0)", ".1%",
                   "Completed requests divided by all requests."),
            metric("sla_compliance", "SLA compliance",
                   "SUM(CASE WHEN sla_met THEN 1 ELSE 0 END) * 1.0 / NULLIF(COUNT(sla_met), 0)", ".1%",
                   "Closed requests resolved within the SLA target, divided by closed requests."),
            metric("sla_breaches", "SLA breaches", "SUM(CASE WHEN sla_met = FALSE THEN 1 ELSE 0 END)", ",d",
                   "Closed requests that missed the SLA target."),
            metric("avg_resolution_hours", "Avg resolution (hours)", "AVG(resolution_hours)", ",.1f",
                   "Mean hours from submission to closure (closed requests)."),
            metric("median_resolution_hours", "Median resolution (hours)",
                   "PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY resolution_hours)", ",.1f",
                   "Median hours from submission to closure (closed requests)."),
            metric("avg_satisfaction", "Avg satisfaction (1-5)", "AVG(satisfaction)", ".2f",
                   "Mean survey score of answered surveys."),
            metric("escalation_rate", "Escalation rate",
                   "SUM(CASE WHEN status = 'Escalated' THEN 1 ELSE 0 END) * 1.0 / NULLIF(COUNT(*), 0)", ".1%",
                   "Escalated requests divided by all requests."),
        ],
    },
}


def dataset_uuid(table: str) -> str:
    return uid(f"dataset:{table}")


def build_dataset(table: str, catalog: str | None) -> dict[str, Any]:
    spec = DATASETS[table]
    columns = []
    for column in spec["columns"]:
        columns.append({**column, "uuid": uid(f"column:{table}:{column['column_name']}")})
    metrics = []
    for item in spec["metrics"]:
        metrics.append({**item, "uuid": uid(f"metric:{table}:{item['metric_name']}")})
    return {
        "table_name": table,
        "main_dttm_col": spec["main_dttm_col"],
        "description": spec["description"],
        "default_endpoint": None,
        "offset": 0,
        "cache_timeout": None,
        "catalog": catalog,
        "schema": SCHEMA,
        "sql": None,
        "params": None,
        "template_params": None,
        "filter_select_enabled": True,
        "fetch_values_predicate": None,
        "extra": None,
        "normalize_columns": False,
        "always_filter_main_dttm": False,
        "uuid": dataset_uuid(table),
        "metrics": metrics,
        "columns": columns,
        "version": VERSION,
        "database_uuid": uid("database:NxtBI Demo"),
    }


# --------------------------------------------------------------------------- chart params


def time_filter(table: str) -> dict[str, Any]:
    """The 'No filter' temporal ad-hoc filter the dashboard time-range filter overrides."""
    return {
        "clause": "WHERE",
        "comparator": "No filter",
        "expressionType": "SIMPLE",
        "operator": "TEMPORAL_RANGE",
        "subject": DATASETS[table]["main_dttm_col"],
    }


def base(table: str, viz_type: str, row_limit: int = 10000) -> dict[str, Any]:
    return {
        "viz_type": viz_type,
        "adhoc_filters": [time_filter(table)],
        "row_limit": row_limit,
        "annotation_layers": [],
        "extra_form_data": {},
    }


def big_total(table: str, metric_name: str, subtitle: str, fmt: str = "SMART_NUMBER") -> dict[str, Any]:
    return {
        **base(table, "big_number_total"),
        "metric": metric_name,
        "subtitle": subtitle,
        "header_font_size": 0.4,
        "subtitle_font_size": 0.15,
        "subheader_font_size": 0.15,
        "y_axis_format": fmt,
        "time_format": "smart_date",
        "force_timestamp_formatting": False,
    }


def big_trend(
    table: str,
    metric_name: str,
    subtitle: str,
    *,
    grain: str,
    aggregation: str,
    fmt: str = "SMART_NUMBER",
    rgb: tuple[int, int, int] = (31, 168, 201),
) -> dict[str, Any]:
    """Big number with trendline. aggregation: sum | mean | LAST_VALUE | raw (overall value)."""
    return {
        **base(table, "big_number"),
        "metric": metric_name,
        "x_axis": DATASETS[table]["main_dttm_col"],
        "time_grain_sqla": grain,
        "aggregation": aggregation,
        "subtitle": subtitle,
        "show_trend_line": True,
        "start_y_axis_at_zero": False,
        "show_timestamp": False,
        "color_picker": {"r": rgb[0], "g": rgb[1], "b": rgb[2], "a": 1},
        "header_font_size": 0.4,
        "subtitle_font_size": 0.2,
        "subheader_font_size": 0.2,
        "y_axis_format": fmt,
        "time_format": "smart_date",
        "force_timestamp_formatting": False,
        "rolling_type": "None",
    }


def timeseries(
    table: str,
    viz_type: str,
    *,
    x_axis: str,
    metrics: list[str],
    groupby: list[str] | None = None,
    grain: str | None = None,
    fmt: str = "SMART_NUMBER",
    stack: str | None = None,
    orientation: str | None = None,
    sort: tuple[str, bool] | None = None,
    show_value: bool = False,
    x_title: str = "",
    y_title: str = "",
    row_limit: int = 10000,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Shared form data of the ECharts timeseries family (line, smooth, bar, area).

    ``x_axis`` may be the temporal column (then pass ``grain``) or a categorical column.
    """
    params: dict[str, Any] = {
        **base(table, viz_type, row_limit),
        "x_axis": x_axis,
        "metrics": metrics,
        "groupby": groupby or [],
        "order_desc": True,
        "truncate_metric": True,
        "show_empty_columns": True,
        "comparison_type": "values",
        "color_scheme": COLOR_SCHEME,
        "show_legend": True,
        "legendType": "scroll",
        "legendOrientation": "top",
        "rich_tooltip": True,
        "showTooltipTotal": True,
        "tooltipTimeFormat": "smart_date",
        "x_axis_time_format": "smart_date",
        "x_axis_title": x_title,
        "x_axis_title_margin": 30 if x_title else 15,
        "y_axis_title": y_title,
        "y_axis_title_margin": 50 if y_title else 15,
        "y_axis_title_position": "Left",
        "y_axis_format": fmt,
        "y_axis_bounds": [None, None],
        "truncateXAxis": True,
        "truncateYAxis": False,
        "sort_series_type": "sum",
        "sort_series_ascending": False,
        "only_total": True,
        "show_value": show_value,
        "opacity": 0.2,
        "markerSize": 6,
        "markerEnabled": False,
        "zoomable": False,
        "minorTicks": False,
    }
    if grain:
        params["time_grain_sqla"] = grain
    if viz_type == "echarts_timeseries_bar":
        params["orientation"] = orientation or "vertical"
        params["stack"] = stack
    elif viz_type == "echarts_area":
        params["stack"] = stack
        params["seriesType"] = "line"
        params["opacity"] = 0.35
    elif viz_type == "echarts_timeseries_smooth":
        params["seriesType"] = "smooth"
    else:
        params["seriesType"] = "line"
    if sort:
        params["x_axis_sort"] = sort[0]
        params["x_axis_sort_asc"] = sort[1]
    if extra:
        params.update(extra)
    return params


def pie(table: str, groupby: str, metric_name: str, *, donut: bool = True, row_limit: int = 100) -> dict[str, Any]:
    return {
        **base(table, "pie", row_limit),
        "groupby": [groupby],
        "metric": metric_name,
        "sort_by_metric": True,
        "color_scheme": COLOR_SCHEME,
        "donut": donut,
        "innerRadius": 45,
        "outerRadius": 72,
        "show_total": donut,
        "show_labels": True,
        "labels_outside": True,
        "label_line": True,
        "label_type": "key_percent",
        "show_labels_threshold": 4,
        "number_format": "SMART_NUMBER",
        "date_format": "smart_date",
        "show_legend": True,
        "legendType": "scroll",
        "legendOrientation": "bottom",
    }


def heatmap(
    table: str,
    *,
    x_axis: str,
    y_axis: str,
    metric_name: str,
    scheme: str,
    fmt: str = "SMART_NUMBER",
    normalize_across: str = "heatmap",
    sort_x: str = "alpha_asc",
    sort_y: str = "alpha_asc",
) -> dict[str, Any]:
    return {
        **base(table, "heatmap_v2"),
        "x_axis": x_axis,
        "groupby": y_axis,
        "metric": metric_name,
        "normalize_across": normalize_across,
        "legend_type": "continuous",
        "linear_color_scheme": scheme,
        "border_color": {"r": 255, "g": 255, "b": 255, "a": 1},
        "border_width": 1,
        "xscale_interval": 1,
        "yscale_interval": 1,
        "left_margin": 20,
        "bottom_margin": 20,
        "value_bounds": [None, None],
        "y_axis_format": fmt,
        "x_axis_time_format": "smart_date",
        "sort_x_axis": sort_x,
        "sort_y_axis": sort_y,
        "show_legend": True,
        "show_percentage": False,
        "show_values": True,
        "normalized": False,
    }


def gradient(column: str, color: str) -> dict[str, Any]:
    """Conditional formatting: colour intensity grows with the value."""
    return {"column": column, "operator": "None", "colorScheme": color}


def threshold(column: str, operator: str, value: float, color: str) -> dict[str, Any]:
    """Conditional formatting: solid colour when the comparison holds."""
    return {
        "column": column,
        "operator": operator,
        "targetValue": value,
        "colorScheme": color,
        "useGradient": False,
    }


# --------------------------------------------------------------------------- charts
# key -> (dashboard, dataset, slice_name, description, params)

BUDGET = "budget_execution"
TRADE = "trade_flows"
POP = "population"
SVC = "service_requests"

GREEN_RGB = (90, 193, 137)
BLUE_RGB = (31, 168, 201)
ORANGE_RGB = (255, 127, 68)
RED_RGB = (224, 67, 85)
NAVY_RGB = (69, 78, 124)

CHARTS: dict[str, dict[str, Any]] = {}


def chart(key: str, table: str, name: str, description: str, params: dict[str, Any]) -> None:
    if key in CHARTS:
        raise ValueError(f"duplicate chart key {key}")
    CHARTS[key] = {
        "table": table,
        "slice_name": name,
        "description": description,
        "params": params,
    }


# ---- Dashboard 1: Budget Execution ---------------------------------------------------

chart(
    "budget_kpi_allocated", BUDGET, "Allocated Budget",
    "Total capital budget allocated in the selected period.",
    big_total(BUDGET, "allocated", "Allocated | المخصص"),
)
chart(
    "budget_kpi_spent", BUDGET, "Spent to Date",
    "Total disbursed in the selected period with the monthly trend.",
    big_trend(BUDGET, "spent", "Spent | المنصرف", grain="P1M", aggregation="sum", rgb=GREEN_RGB),
)
chart(
    "budget_kpi_execution_rate", BUDGET, "Execution Rate",
    "Spent divided by allocated over the whole selected period, with the monthly trend.",
    big_trend(BUDGET, "execution_rate", "Execution rate | نسبة التنفيذ", grain="P1M",
              aggregation="raw", fmt=".1%", rgb=BLUE_RGB),
)
chart(
    "budget_kpi_delayed_projects", BUDGET, "Delayed Projects",
    "Delayed projects in the latest month of the selected period, with the monthly trend.",
    big_trend(BUDGET, "delayed_projects", "Delayed projects, latest month | المشاريع المتأخرة",
              grain="P1M", aggregation="LAST_VALUE", fmt=",.0f", rgb=RED_RGB),
)
chart(
    "budget_spend_vs_allocation", BUDGET, "Spend vs Allocation by Month",
    "Monthly allocated and spent amounts (bars) with the execution rate (line, right axis).",
    {
        **base(BUDGET, "mixed_timeseries"),
        "x_axis": "period_date",
        "time_grain_sqla": "P1M",
        "metrics": ["allocated", "spent"],
        "groupby": [],
        "metrics_b": ["execution_rate"],
        "groupby_b": [],
        "adhoc_filters_b": [time_filter(BUDGET)],
        "row_limit_b": 10000,
        "order_desc": True,
        "order_desc_b": True,
        "truncate_metric": True,
        "truncate_metric_b": True,
        "comparison_type": "values",
        "comparison_type_b": "values",
        "seriesType": "bar",
        "seriesTypeB": "line",
        "stack": None,
        "stackB": None,
        "opacity": 0.2,
        "opacityB": 0.2,
        "markerEnabled": False,
        "markerEnabledB": True,
        "markerSize": 6,
        "markerSizeB": 5,
        "show_value": False,
        "show_valueB": False,
        "yAxisIndex": 0,
        "yAxisIndexB": 1,
        "y_axis_format": "SMART_NUMBER",
        "y_axis_format_secondary": ".0%",
        "y_axis_bounds": [None, None],
        "y_axis_bounds_secondary": [0, None],
        "y_axis_title": "Amount",
        "yAxisTitleSecondary": "",
        "y_axis_title_margin": 50,
        "y_axis_title_position": "Left",
        "x_axis_title_margin": 15,
        "x_axis_time_format": "smart_date",
        "tooltipTimeFormat": "smart_date",
        "rich_tooltip": True,
        "show_legend": True,
        "legendType": "scroll",
        "legendOrientation": "top",
        "color_scheme": COLOR_SCHEME,
        "truncateXAxis": True,
        "zoomable": False,
        "minorTicks": False,
    },
)
chart(
    "budget_execution_by_sector", BUDGET, "Execution Rate by Sector",
    "Spent divided by allocated per sector, highest at the top.",
    timeseries(
        BUDGET, "echarts_timeseries_bar", x_axis="sector_en", metrics=["execution_rate"],
        fmt=".0%", orientation="horizontal", sort=("execution_rate", True), show_value=True,
        extra={"show_legend": False},
    ),
)
chart(
    "budget_sector_programme_treemap", BUDGET, "Spending by Sector and Programme",
    "Share of spending by sector, broken down into capital programmes.",
    {
        **base(BUDGET, "treemap_v2"),
        "groupby": ["sector_en", "program_en"],
        "metric": "spent",
        "color_scheme": COLOR_SCHEME,
        "show_labels": True,
        "show_upper_labels": True,
        "label_type": "key_value",
        "number_format": "SMART_NUMBER",
        "date_format": "smart_date",
    },
)
chart(
    "budget_region_comparison", BUDGET, "Allocated, Committed and Spent by Region",
    "Regional comparison of the three budget stages.",
    timeseries(
        BUDGET, "echarts_timeseries_bar", x_axis="region_en",
        metrics=["allocated", "committed", "spent"], sort=("allocated", False),
    ),
)
chart(
    "budget_region_sector_heatmap", BUDGET, "Execution Rate: Region x Sector",
    "Execution rate for every region and sector combination; darker cells execute faster.",
    heatmap(BUDGET, x_axis="region_en", y_axis="sector_en", metric_name="execution_rate",
            scheme=SEQ_GREEN, fmt=".0%"),
)
chart(
    "budget_spending_by_sector_ar", BUDGET, "الإنفاق حسب القطاع",
    "Spending by sector with Arabic labels (sector_ar).",
    pie(BUDGET, "sector_ar", "spent"),
)
chart(
    "budget_quarterly_pivot", BUDGET, "Quarterly Spending by Sector",
    "Spent amount per fiscal year and quarter (rows) and sector (columns), with yearly subtotals and totals.",
    {
        **base(BUDGET, "pivot_table_v2"),
        "groupbyRows": ["fiscal_year", "fiscal_quarter"],
        "groupbyColumns": ["sector_en"],
        "metrics": ["spent"],
        "metricsLayout": "COLUMNS",
        "aggregateFunction": "Sum",
        "valueFormat": "SMART_NUMBER",
        "date_format": "smart_date",
        "rowOrder": "key_a_to_z",
        "colOrder": "key_a_to_z",
        "rowTotals": True,
        "colTotals": True,
        "rowSubTotals": True,
        "colSubTotals": False,
        "transposePivot": False,
        "combineMetric": False,
        "order_desc": True,
        "rowSubtotalPosition": False,
        "colSubtotalPosition": False,
        "conditional_formatting": [gradient("spent", CF_GREEN)],
    },
)

# ---- Dashboard 2: Trade & Population -------------------------------------------------

chart(
    "trade_kpi_balance", TRADE, "Trade Balance",
    "Exports minus imports over the selected period, with the monthly trend.",
    big_trend(TRADE, "trade_balance", "Exports minus imports | الميزان التجاري", grain="P1M",
              aggregation="sum", rgb=NAVY_RGB),
)
chart(
    "trade_exports_vs_imports", TRADE, "Exports vs Imports by Month",
    "Monthly exports and imports (lines) with the trade balance (bars).",
    {
        **base(TRADE, "mixed_timeseries"),
        "x_axis": "period_date",
        "time_grain_sqla": "P1M",
        "metrics": ["exports_usd", "imports_usd"],
        "groupby": [],
        "metrics_b": ["trade_balance"],
        "groupby_b": [],
        "adhoc_filters_b": [time_filter(TRADE)],
        "row_limit_b": 10000,
        "order_desc": True,
        "order_desc_b": True,
        "truncate_metric": True,
        "truncate_metric_b": True,
        "comparison_type": "values",
        "comparison_type_b": "values",
        "seriesType": "smooth",
        "seriesTypeB": "bar",
        "stack": None,
        "stackB": None,
        "opacity": 0.2,
        "opacityB": 0.2,
        "markerEnabled": False,
        "markerEnabledB": False,
        "markerSize": 6,
        "markerSizeB": 6,
        "show_value": False,
        "show_valueB": False,
        "yAxisIndex": 0,
        "yAxisIndexB": 0,
        "y_axis_format": "SMART_NUMBER",
        "y_axis_format_secondary": "SMART_NUMBER",
        "y_axis_bounds": [None, None],
        "y_axis_bounds_secondary": [None, None],
        "y_axis_title": "USD",
        "y_axis_title_margin": 50,
        "y_axis_title_position": "Left",
        "x_axis_title_margin": 15,
        "x_axis_time_format": "smart_date",
        "tooltipTimeFormat": "smart_date",
        "rich_tooltip": True,
        "show_legend": True,
        "legendType": "scroll",
        "legendOrientation": "top",
        "color_scheme": COLOR_SCHEME,
        "truncateXAxis": True,
        "zoomable": True,
        "minorTicks": False,
    },
)
chart(
    "trade_top_partners", TRADE, "Top Trading Partners",
    "Exports and imports per partner country, largest total at the top.",
    timeseries(
        TRADE, "echarts_timeseries_bar", x_axis="partner_en",
        metrics=["exports_usd", "imports_usd"], stack="Stack", orientation="horizontal",
        sort=("sum", True),
    ),
)
chart(
    "trade_commodity_mix", TRADE, "Commodity Mix",
    "Share of total trade value by commodity group.",
    pie(TRADE, "commodity_en", "total_trade"),
)
chart(
    "trade_region_commodity_sankey", TRADE, "Partner Region to Commodity Flows",
    "Total trade value flowing between partner regions and commodity groups.",
    {
        **base(TRADE, "sankey_v2"),
        "source": "partner_region",
        "target": "commodity_en",
        "metric": "total_trade",
        "color_scheme": COLOR_SCHEME,
    },
)
chart(
    "trade_flow_commodity_heatmap", TRADE, "Flow x Commodity Heatmap",
    "Trade value per commodity group, shaded within each flow (import or export).",
    heatmap(TRADE, x_axis="flow", y_axis="commodity_en", metric_name="total_trade",
            scheme=SEQ_BLUE, normalize_across="x"),
)
chart(
    "population_kpi_total", POP, "Population",
    "Population in the latest year of the selected period, with the yearly trend.",
    big_trend(POP, "population_total", "Latest year | عدد السكان", grain="P1Y",
              aggregation="LAST_VALUE", rgb=BLUE_RGB),
)
chart(
    "population_kpi_female_share", POP, "Female Share",
    "Female persons divided by all persons in the selected period.",
    big_total(POP, "female_share", "Female share | نسبة الإناث", fmt=".1%"),
)
chart(
    "population_trend_by_region", POP, "Population Trend by Region",
    "Yearly population stacked by region.",
    timeseries(
        POP, "echarts_area", x_axis="year_date", metrics=["population_total"],
        groupby=["region_en"], grain="P1Y", stack="Stack",
        extra={"x_axis_time_format": "%Y", "tooltipTimeFormat": "%Y"},
    ),
)
chart(
    "population_age_pyramid", POP, "Age Pyramid",
    "Population by age band and gender (annual average of the selected years); "
    "male values are mirrored to the left. Bands are ordered by age_order.",
    timeseries(
        POP, "echarts_timeseries_bar", x_axis="age_band",
        metrics=["male_population_mirrored", "female_population"], stack="Stack",
        orientation="horizontal", sort=("age_band", True),
    ),
)
chart(
    "population_detail_table", POP, "Population Detail by Region and Age Group",
    "Population (annual average) and female share by region (English and Arabic) and age band.",
    {
        **base(POP, "table", 1000),
        "query_mode": "aggregate",
        "groupby": ["region_en", "region_ar", "age_band"],
        "metrics": ["population_avg", "female_share"],
        "all_columns": [],
        "percent_metrics": [],
        "order_by_cols": [],
        "timeseries_limit_metric": "population_avg",
        "order_desc": True,
        "server_pagination": False,
        "page_length": 20,
        "include_search": True,
        "show_cell_bars": True,
        "show_totals": False,
        "align_pn": False,
        "color_pn": False,
        "allow_render_html": False,
        "allow_rearrange_columns": False,
        "table_timestamp_format": "smart_date",
        "column_config": {
            "population_avg": {"d3NumberFormat": ",.0f"},
            "female_share": {"d3NumberFormat": ".1%", "showCellBars": False},
        },
        "conditional_formatting": [gradient("female_share", CF_BLUE)],
    },
)

# ---- Dashboard 3: Service Operations (Row Level Security showcase) -------------------

chart(
    "service_kpi_requests", SVC, "Service Requests",
    "Requests received in the selected period, with the weekly trend.",
    big_trend(SVC, "requests", "Requests | الطلبات", grain="P1W", aggregation="sum",
              fmt=",d", rgb=BLUE_RGB),
)
chart(
    "service_kpi_sla_compliance", SVC, "SLA Compliance",
    "Closed requests resolved within the SLA target, with the weekly trend.",
    big_trend(SVC, "sla_compliance", "SLA compliance | الالتزام بمستوى الخدمة", grain="P1W",
              aggregation="raw", fmt=".1%", rgb=GREEN_RGB),
)
chart(
    "service_kpi_avg_resolution", SVC, "Avg Resolution Time",
    "Mean hours from submission to closure, with the weekly trend.",
    big_trend(SVC, "avg_resolution_hours", "Hours to resolve | ساعات الإنجاز", grain="P1W",
              aggregation="raw", fmt=",.1f", rgb=ORANGE_RGB),
)
chart(
    "service_satisfaction_gauge", SVC, "Customer Satisfaction",
    "Average survey score on a 1 to 5 scale.",
    {
        **base(SVC, "gauge_chart", 10),
        "groupby": [],
        "metric": "avg_satisfaction",
        "min_val": 1,
        "max_val": 5,
        "start_angle": 225,
        "end_angle": -45,
        "color_scheme": COLOR_SCHEME,
        "font_size": 15,
        "number_format": ".1f",
        "value_formatter": "{value} / 5",
        "show_pointer": True,
        "animation": True,
        "show_axis_tick": False,
        "show_split_line": False,
        "split_number": 4,
        "show_progress": True,
        "overlap": True,
        "round_cap": True,
    },
)
chart(
    "service_weekly_trend_by_org", SVC, "Weekly Requests by Organisation",
    "Requests per week for each organisation. With Row Level Security a user sees only "
    "the organisations they belong to.",
    timeseries(
        SVC, "echarts_timeseries_smooth", x_axis="created_at", metrics=["requests"],
        groupby=["org_name_en"], grain="P1W", fmt=",d",
    ),
)
chart(
    "service_status_funnel", SVC, "Requests by Status",
    "Number of requests in each status.",
    {
        **base(SVC, "funnel", 10),
        "groupby": ["status"],
        "metric": "requests",
        "sort_by_metric": True,
        "percent_calculation_type": "first_step",
        "color_scheme": COLOR_SCHEME,
        "show_legend": True,
        "legendOrientation": "top",
        "legendMargin": 50,
        "label_type": 3,
        "tooltip_label_type": 5,
        "number_format": ",d",
        "show_labels": True,
        "show_tooltip_labels": True,
    },
)
chart(
    "service_channel_mix", SVC, "Channel Mix",
    "Share of requests by submission channel.",
    pie(SVC, "channel_en", "requests"),
)
chart(
    "service_sla_by_service", SVC, "SLA Compliance by Service",
    "SLA compliance per service, coloured by the owning organisation.",
    timeseries(
        SVC, "echarts_timeseries_bar", x_axis="service_en", metrics=["sla_compliance"],
        groupby=["org_name_en"], fmt=".0%", stack="Stack", orientation="horizontal",
        show_value=True, extra={"only_total": False, "y_axis_bounds": [0, 1]},
    ),
)
chart(
    "service_resolution_boxplot", SVC, "Resolution Time by Channel",
    "Distribution of the weekly average resolution time (hours) for each channel.",
    {
        **base(SVC, "box_plot"),
        "columns": ["created_at"],
        "temporal_columns_lookup": {"created_at": True},
        "time_grain_sqla": "P1W",
        "groupby": ["channel_en"],
        "metrics": ["avg_resolution_hours"],
        "whiskerOptions": "Tukey",
        "color_scheme": COLOR_SCHEME,
        "number_format": ",.1f",
        "date_format": "smart_date",
        "x_ticks_layout": "flat",
        "legendOrientation": "bottom",
        "x_axis_title_margin": 15,
        "y_axis_title": "Hours",
        "y_axis_title_margin": 40,
        "y_axis_title_position": "Left",
    },
)
chart(
    "service_region_heatmap", SVC, "Requests: Service x Region",
    "Number of requests for every service and applicant region.",
    heatmap(SVC, x_axis="region_en", y_axis="service_en", metric_name="requests",
            scheme=SEQ_WARM, fmt=",d"),
)
chart(
    "service_recent_requests", SVC, "Recent Requests",
    "Latest 500 requests with organisation names in English and Arabic. Resolution time "
    "and satisfaction are colour coded.",
    {
        **base(SVC, "table", 500),
        "query_mode": "raw",
        "all_columns": [
            "created_at",
            "request_id",
            "org_name_en",
            "org_name_ar",
            "service_en",
            "channel_en",
            "region_en",
            "status",
            "sla_status",
            "sla_hours",
            "resolution_hours",
            "satisfaction",
        ],
        "groupby": [],
        "metrics": [],
        "percent_metrics": [],
        "order_by_cols": ['["created_at", false]'],
        "order_desc": True,
        "server_pagination": False,
        "page_length": 10,
        "include_search": True,
        "show_cell_bars": False,
        "align_pn": False,
        "color_pn": False,
        "allow_render_html": False,
        "allow_rearrange_columns": False,
        "table_timestamp_format": "%Y-%m-%d %H:%M",
        "temporal_columns_lookup": {"created_at": True},
        "column_config": {
            "request_id": {"d3NumberFormat": "d"},
            "resolution_hours": {"d3NumberFormat": ",.1f"},
        },
        "conditional_formatting": [
            threshold("resolution_hours", ">", 72, CF_RED),
            threshold("resolution_hours", "≤", 24, CF_GREEN),
            threshold("satisfaction", "≤", 2, CF_RED),
            threshold("satisfaction", "≥", 4, CF_GREEN),
        ],
    },
)


def chart_uuid(key: str) -> str:
    return uid(f"chart:{key}")


def build_chart(key: str) -> dict[str, Any]:
    spec = CHARTS[key]
    return {
        "slice_name": spec["slice_name"],
        "description": spec["description"],
        "certified_by": None,
        "certification_details": None,
        "viz_type": spec["params"]["viz_type"],
        "params": spec["params"],
        "query_context": None,
        "cache_timeout": None,
        "uuid": chart_uuid(key),
        "version": VERSION,
        "dataset_uuid": dataset_uuid(spec["table"]),
    }


# --------------------------------------------------------------------------- dashboards
# Layout DSL (12-column grid, height unit = 8px):
#   row(id, *children)
#   ch(chart_key, width, height)
#   md(id, code, width, height)
#   column(id, width, *children)
#   tabs(id, tab(id, text, *rows), ...)


def row(node_id: str, *children: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "ROW", "id": f"ROW-{node_id}", "children": list(children)}


def ch(key: str, width: int, height: int) -> dict[str, Any]:
    return {"kind": "CHART", "id": f"CHART-{key}", "key": key, "width": width, "height": height}


def md(node_id: str, code: str, width: int, height: int) -> dict[str, Any]:
    return {"kind": "MARKDOWN", "id": f"MARKDOWN-{node_id}", "code": code, "width": width, "height": height}


def column(node_id: str, width: int, *children: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "COLUMN", "id": f"COLUMN-{node_id}", "width": width, "children": list(children)}


def tab(node_id: str, text: str, *children: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "TAB", "id": f"TAB-{node_id}", "text": text, "children": list(children)}


def tabs(node_id: str, *children: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "TABS", "id": f"TABS-{node_id}", "children": list(children)}


def select_filter(
    filter_id: str,
    name: str,
    table: str,
    column_name: str,
    *,
    description: str = "",
    parents: tuple[str, ...] = (),
    root: str = "ROOT_ID",
    multi: bool = True,
) -> dict[str, Any]:
    return {
        "kind": "filter_select",
        "id": f"NATIVE_FILTER-{filter_id}",
        "name": name,
        "table": table,
        "column": column_name,
        "description": description,
        "parents": [f"NATIVE_FILTER-{p}" for p in parents],
        "root": root,
        "multi": multi,
    }


def time_range_filter(filter_id: str, name: str, *, description: str = "", root: str = "ROOT_ID") -> dict[str, Any]:
    return {
        "kind": "filter_time",
        "id": f"NATIVE_FILTER-{filter_id}",
        "name": name,
        "description": description,
        "parents": [],
        "root": root,
    }


DASHBOARDS: list[dict[str, Any]] = [
    {
        "slug": "nxtbi-budget-execution",
        "title": "NxtBI · Budget Execution | تنفيذ الميزانية",
        "description": "Capital budget execution of the Ministry of Planning by sector, programme and region.",
        "id_base": 100,
        "layout": [
            row(
                "budget-header",
                md(
                    "budget-header",
                    "## Budget Execution | تنفيذ الميزانية\n\n"
                    "Monthly capital budget of the **Ministry of Planning**: what was allocated, "
                    "committed and spent, by sector, programme and region (January 2023 to October 2026). "
                    "Use the filter bar, or click a bar, slice or cell to cross-filter the page.\n\n"
                    "متابعة شهرية لتنفيذ الميزانية الرأسمالية في **وزارة التخطيط**: المخصصات والالتزامات "
                    "والمصروفات حسب القطاع والبرنامج والمنطقة. استخدم شريط التصفية أو انقر على أي عنصر "
                    "في الرسوم لتصفية الصفحة.",
                    12,
                    22,
                ),
            ),
            row(
                "budget-kpis",
                ch("budget_kpi_allocated", 3, 22),
                ch("budget_kpi_spent", 3, 22),
                ch("budget_kpi_execution_rate", 3, 22),
                ch("budget_kpi_delayed_projects", 3, 22),
            ),
            row(
                "budget-trend",
                ch("budget_spend_vs_allocation", 8, 56),
                ch("budget_execution_by_sector", 4, 56),
            ),
            row(
                "budget-structure",
                ch("budget_sector_programme_treemap", 6, 56),
                ch("budget_region_comparison", 6, 56),
            ),
            row(
                "budget-matrix",
                ch("budget_region_sector_heatmap", 7, 56),
                ch("budget_spending_by_sector_ar", 5, 56),
            ),
            row("budget-pivot", ch("budget_quarterly_pivot", 12, 62)),
        ],
        "filters": [
            time_range_filter("budget-time", "Time range", description="Reporting period (month)."),
            select_filter("budget-year", "Fiscal year", BUDGET, "fiscal_year"),
            select_filter("budget-sector", "Sector", BUDGET, "sector_en"),
            select_filter(
                "budget-programme", "Programme", BUDGET, "program_en",
                description="Depends on Sector: only programmes of the selected sectors are listed.",
                parents=("budget-sector",),
            ),
            select_filter("budget-region", "Region", BUDGET, "region_en"),
        ],
    },
    {
        "slug": "nxtbi-trade-population",
        "title": "NxtBI · Trade & Population | التجارة والسكان",
        "description": "Merchandise trade and population statistics of the Statistics Bureau.",
        "id_base": 200,
        "layout": [
            row(
                "tradepop-header",
                md(
                    "tradepop-header",
                    "## Trade & Population | التجارة والسكان\n\n"
                    "Official statistics of the **Statistics Bureau**. The *Trade* tab covers monthly "
                    "merchandise trade by partner and commodity group (January 2023 to October 2026); "
                    "the *Population* tab covers yearly estimates by region, gender and age (2015 to 2026).\n\n"
                    "إحصاءات رسمية من **الجهاز المركزي للإحصاء**: تبويب *التجارة* يعرض التبادل التجاري الشهري "
                    "حسب الشريك ومجموعة السلع، وتبويب *السكان* يعرض التقديرات السنوية حسب المنطقة والجنس "
                    "والفئة العمرية.",
                    12,
                    22,
                ),
            ),
            tabs(
                "tradepop",
                tab(
                    "trade",
                    "Trade | التجارة",
                    row(
                        "trade-trend",
                        ch("trade_kpi_balance", 3, 56),
                        ch("trade_exports_vs_imports", 9, 56),
                    ),
                    row(
                        "trade-partners",
                        ch("trade_top_partners", 7, 60),
                        ch("trade_commodity_mix", 5, 60),
                    ),
                    row(
                        "trade-flows",
                        ch("trade_region_commodity_sankey", 7, 60),
                        ch("trade_flow_commodity_heatmap", 5, 60),
                    ),
                ),
                tab(
                    "population",
                    "Population | السكان",
                    row(
                        "population-trend",
                        column(
                            "population-kpis",
                            3,
                            ch("population_kpi_total", 3, 28),
                            ch("population_kpi_female_share", 3, 28),
                        ),
                        ch("population_trend_by_region", 9, 56),
                    ),
                    row(
                        "population-structure",
                        ch("population_age_pyramid", 5, 62),
                        ch("population_detail_table", 7, 62),
                    ),
                ),
            ),
        ],
        "filters": [
            time_range_filter(
                "tradepop-time", "Time range",
                description="Applies to both tabs (trade month, population year).",
            ),
            select_filter("trade-partner-region", "Partner region", TRADE, "partner_region", root="TAB-trade"),
            select_filter(
                "trade-partner", "Trading partner", TRADE, "partner_en",
                description="Depends on Partner region: only partners of the selected regions are listed.",
                parents=("trade-partner-region",), root="TAB-trade",
            ),
            select_filter("trade-commodity", "Commodity group", TRADE, "commodity_en", root="TAB-trade"),
            select_filter("population-region", "Region", POP, "region_en", root="TAB-population"),
        ],
    },
    {
        "slug": "nxtbi-service-operations",
        "title": "NxtBI · Service Operations | عمليات الخدمات",
        "description": (
            "Service request operations of both organisations; the Row Level Security showcase "
            "(each user sees only the organisations they belong to)."
        ),
        "id_base": 300,
        "layout": [
            row(
                "service-header",
                md(
                    "service-header",
                    "## Service Operations | عمليات الخدمات\n\n"
                    "Service requests handled by the **Ministry of Planning** and the **Statistics Bureau** "
                    "(1 January 2025 to 15 November 2026): volumes, SLA compliance, resolution time and "
                    "satisfaction. Row Level Security is applied to this dataset, so every user sees only "
                    "the organisations they belong to.\n\n"
                    "طلبات الخدمات لدى **وزارة التخطيط** و**الجهاز المركزي للإحصاء**: أعداد الطلبات والالتزام "
                    "بمستوى الخدمة وزمن الإنجاز ورضا المتعاملين. تُطبَّق صلاحيات مستوى الصف على هذه البيانات، "
                    "فيرى كل مستخدم بيانات جهته فقط.",
                    12,
                    22,
                ),
            ),
            row(
                "service-kpis",
                ch("service_kpi_requests", 4, 22),
                ch("service_kpi_sla_compliance", 4, 22),
                ch("service_kpi_avg_resolution", 4, 22),
            ),
            row(
                "service-trend",
                ch("service_weekly_trend_by_org", 8, 56),
                ch("service_status_funnel", 4, 56),
            ),
            row(
                "service-quality",
                ch("service_channel_mix", 4, 56),
                ch("service_sla_by_service", 5, 56),
                ch("service_satisfaction_gauge", 3, 56),
            ),
            row(
                "service-distribution",
                ch("service_resolution_boxplot", 6, 56),
                ch("service_region_heatmap", 6, 56),
            ),
            row("service-detail", ch("service_recent_requests", 12, 66)),
        ],
        "filters": [
            time_range_filter("service-time", "Time range", description="Request submission date."),
            select_filter(
                "service-org", "Organisation", SVC, "org_name_en",
                description="Lists only the organisations Row Level Security lets you see.",
            ),
            select_filter(
                "service-service", "Service", SVC, "service_en",
                description="Depends on Organisation: only services of the selected organisations are listed.",
                parents=("service-org",),
            ),
            select_filter("service-channel", "Channel", SVC, "channel_en"),
            select_filter("service-status", "Status", SVC, "status"),
        ],
    },
]


def dashboard_uuid(slug: str) -> str:
    return uid(f"dashboard:{slug}")


def _walk_charts(nodes: list[dict[str, Any]]) -> list[str]:
    keys: list[str] = []
    for node in nodes:
        if node["kind"] == "CHART":
            keys.append(node["key"])
        keys.extend(_walk_charts(node.get("children", [])))
    return keys


def build_position(spec: dict[str, Any], chart_ids: dict[str, int]) -> dict[str, Any]:
    position: dict[str, Any] = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {
            "type": "GRID",
            "id": "GRID_ID",
            "parents": ["ROOT_ID"],
            "children": [node["id"] for node in spec["layout"]],
        },
        "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID", "meta": {"text": spec["title"]}},
    }

    def emit(node: dict[str, Any], parents: list[str]) -> None:
        kind = node["kind"]
        entry: dict[str, Any] = {
            "type": kind,
            "id": node["id"],
            "parents": list(parents),
            "children": [child["id"] for child in node.get("children", [])],
        }
        if kind == "ROW":
            entry["meta"] = {"background": "BACKGROUND_TRANSPARENT"}
        elif kind == "COLUMN":
            entry["meta"] = {"background": "BACKGROUND_TRANSPARENT", "width": node["width"]}
        elif kind == "TABS":
            entry["meta"] = {}
        elif kind == "TAB":
            entry["meta"] = {"text": node["text"], "defaultText": "Tab title", "placeholder": "Tab title"}
        elif kind == "MARKDOWN":
            entry["meta"] = {"code": node["code"], "width": node["width"], "height": node["height"]}
        elif kind == "CHART":
            key = node["key"]
            entry["meta"] = {
                "chartId": chart_ids[key],
                "uuid": chart_uuid(key),
                "sliceName": CHARTS[key]["slice_name"],
                "width": node["width"],
                "height": node["height"],
            }
        else:
            raise ValueError(f"unknown layout node kind {kind}")
        if node["id"] in position:
            raise ValueError(f"duplicate layout id {node['id']}")
        position[node["id"]] = entry
        for child in node.get("children", []):
            emit(child, parents + [node["id"]])

    for top in spec["layout"]:
        emit(top, ["ROOT_ID", "GRID_ID"])
    return position


def _charts_under(position: dict[str, Any], root: str) -> list[int]:
    """Placeholder chart ids of the CHART nodes below ``root`` (in layout order)."""
    result = []
    for node in position.values():
        if isinstance(node, dict) and node.get("type") == "CHART":
            if root == "ROOT_ID" or root in node["parents"]:
                result.append(node["meta"]["chartId"])
    return result


def _tabs_with_charts(position: dict[str, Any], chart_id_list: list[int]) -> list[str]:
    wanted = set(chart_id_list)
    found: list[str] = []
    for node in position.values():
        if isinstance(node, dict) and node.get("type") == "CHART" and node["meta"]["chartId"] in wanted:
            for parent in node["parents"]:
                if parent.startswith("TAB-") and parent not in found:
                    found.append(parent)
    return found


def build_native_filter(spec: dict[str, Any], position: dict[str, Any]) -> dict[str, Any]:
    in_scope = _charts_under(position, spec["root"])
    common = {
        "id": spec["id"],
        "type": "NATIVE_FILTER",
        "name": spec["name"],
        "filterType": spec["kind"],
        "description": spec["description"],
        "cascadeParentIds": spec["parents"],
        "scope": {"rootPath": [spec["root"]], "excluded": []},
        "chartsInScope": in_scope,
        "tabsInScope": _tabs_with_charts(position, in_scope),
        "defaultDataMask": {"extraFormData": {}, "filterState": {}, "ownState": {}},
    }
    if spec["kind"] == "filter_time":
        return {**common, "targets": [{}], "controlValues": {"enableEmptyFilter": False}}
    return {
        **common,
        "targets": [{"column": {"name": spec["column"]}, "datasetUuid": dataset_uuid(spec["table"])}],
        "controlValues": {
            "multiSelect": spec["multi"],
            "enableEmptyFilter": False,
            "defaultToFirstItem": False,
            "inverseSelection": False,
            "searchAllOptions": False,
        },
    }


def build_dashboard(spec: dict[str, Any]) -> dict[str, Any]:
    keys = _walk_charts(spec["layout"])
    chart_ids = {key: spec["id_base"] + index for index, key in enumerate(keys, start=1)}
    position = build_position(spec, chart_ids)
    has_tabs = any(node["kind"] == "TABS" for node in spec["layout"])

    chart_configuration: dict[str, Any] = {}
    for key in keys:
        if CHARTS[key]["params"]["viz_type"] not in CROSS_FILTER_EMITTERS:
            continue
        chart_id = chart_ids[key]
        if has_tabs:
            # Keep cross-filters inside the chart's own tab: the other tab is a different dataset.
            own_tab = next(p for p in position[f"CHART-{key}"]["parents"] if p.startswith("TAB-"))
            scope: Any = {"rootPath": [own_tab], "excluded": [chart_id]}
            in_scope = [cid for cid in _charts_under(position, own_tab) if cid != chart_id]
        else:
            scope = "global"
            in_scope = [cid for cid in chart_ids.values() if cid != chart_id]
        chart_configuration[str(chart_id)] = {
            "id": chart_id,
            "crossFilters": {"scope": scope, "chartsInScope": in_scope},
        }

    metadata = {
        "color_scheme": COLOR_SCHEME,
        "color_scheme_domain": [],
        "label_colors": {},
        "shared_label_colors": [],
        "map_label_colors": {},
        "cross_filters_enabled": True,
        "refresh_frequency": 0,
        "timed_refresh_immune_slices": [],
        "expanded_slices": {},
        "default_filters": "{}",
        "chart_configuration": chart_configuration,
        "global_chart_configuration": {
            "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
            "chartsInScope": list(chart_ids.values()),
        },
        "native_filter_configuration": [build_native_filter(f, position) for f in spec["filters"]],
    }
    return {
        "dashboard_title": spec["title"],
        "description": spec["description"],
        "css": "",
        "slug": spec["slug"],
        "certified_by": None,
        "certification_details": None,
        "published": True,
        "uuid": dashboard_uuid(spec["slug"]),
        "position": position,
        "metadata": metadata,
        "version": VERSION,
    }


# --------------------------------------------------------------------------- bundle


def build_database(sqlalchemy_uri: str) -> dict[str, Any]:
    return {
        "database_name": DATABASE_NAME,
        "sqlalchemy_uri": sqlalchemy_uri,
        "cache_timeout": None,
        "expose_in_sqllab": True,
        "allow_run_async": True,
        "allow_ctas": False,
        "allow_cvas": False,
        "allow_dml": False,
        "allow_csv_upload": False,
        "impersonate_user": False,
        "extra": {"allows_virtual_table_explore": True},
        "uuid": uid("database:NxtBI Demo"),
        "version": VERSION,
    }


def default_catalog(sqlalchemy_uri: str) -> str | None:
    """PostgreSQL's default catalog is the database name in the URI (what the UI stores)."""
    parts = urlsplit(sqlalchemy_uri)
    if not parts.scheme.startswith("postgresql"):
        return None
    name = parts.path.lstrip("/")
    return name or None


def bundle_files(sqlalchemy_uri: str) -> dict[str, dict[str, Any]]:
    """All bundle documents keyed by their path relative to the bundle root."""
    catalog = default_catalog(sqlalchemy_uri)
    files: dict[str, dict[str, Any]] = {
        "metadata.yaml": {"version": VERSION, "type": "assets", "timestamp": FIXED_TIMESTAMP},
        DATABASE_FILE: build_database(sqlalchemy_uri),
    }
    for table in DATASETS:
        files[f"datasets/NxtBI_Demo/{table}.yaml"] = build_dataset(table, catalog)
    used = [key for spec in DASHBOARDS for key in _walk_charts(spec["layout"])]
    if sorted(used) != sorted(CHARTS):
        missing = sorted(set(CHARTS) - set(used))
        extra = sorted(set(used) - set(CHARTS))
        dupes = sorted({key for key in used if used.count(key) > 1})
        raise ValueError(f"chart/layout mismatch: unused={missing} unknown={extra} repeated={dupes}")
    for key in CHARTS:
        files[f"charts/{key}.yaml"] = build_chart(key)
    for spec in DASHBOARDS:
        files[f"dashboards/{spec['slug']}.yaml"] = build_dashboard(spec)
    return files


def build_manifest() -> dict[str, Any]:
    return {
        "database": {"name": DATABASE_NAME, "uuid": uid("database:NxtBI Demo")},
        "datasets": {table: dataset_uuid(table) for table in DATASETS},
        "charts": {key: chart_uuid(key) for key in CHARTS},
        "dashboards": {
            spec["slug"]: {"uuid": dashboard_uuid(spec["slug"]), "title": spec["title"]}
            for spec in DASHBOARDS
        },
    }


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def build(out_dir: str | os.PathLike[str], sqlalchemy_uri: str) -> dict[str, Any]:
    """Write the bundle and manifest under ``out_dir`` and return the manifest."""
    if not sqlalchemy_uri:
        raise ValueError(f"{ENV_URI} is empty")
    out = Path(out_dir)
    bundle = out / BUNDLE_DIR_NAME
    files = bundle_files(sqlalchemy_uri)
    # Drop stale YAML from an earlier run so the directory mirrors the generator exactly.
    if bundle.is_dir():
        for stale in sorted(bundle.rglob("*.yaml")):
            if stale.relative_to(bundle).as_posix() not in files:
                stale.unlink()
    for relative, document in files.items():
        text = yaml.safe_dump(
            document,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
            width=110,
        )
        _write_text(bundle / relative, text)
    manifest = build_manifest()
    _write_text(out / "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return manifest


def read_contents(bundle_dir: str | os.PathLike[str]) -> dict[str, str]:
    """Bundle as the ``contents`` mapping ``ImportAssetsCommand`` expects (root stripped)."""
    root = Path(bundle_dir)
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*.yaml"))
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the NxtBI Superset asset bundle.")
    parser.add_argument("--out", required=True, help="output directory (bundle + manifest.json)")
    args = parser.parse_args(argv)

    sqlalchemy_uri = os.environ.get(ENV_URI, "").strip()
    if not sqlalchemy_uri:
        print(
            f"error: environment variable {ENV_URI} is not set "
            "(expected e.g. postgresql+psycopg2://nxtbi_ro:<password>@db:5432/nxtbi_demo)",
            file=sys.stderr,
        )
        return 2

    manifest = build(args.out, sqlalchemy_uri)
    per_dashboard = ", ".join(
        f"{spec['slug']}={len(_walk_charts(spec['layout']))}" for spec in DASHBOARDS
    )
    print(
        f"wrote {Path(args.out) / BUNDLE_DIR_NAME}: 1 database, {len(manifest['datasets'])} datasets, "
        f"{len(manifest['charts'])} charts, {len(manifest['dashboards'])} dashboards ({per_dashboard})"
    )
    print(f"wrote {Path(args.out) / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
