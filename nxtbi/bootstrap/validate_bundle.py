"""Validate an NxtBI Superset asset bundle before it is imported.

    python validate_bundle.py <bundle_dir> [options]

Checks, in order:

  1. schema      Every YAML file is loaded through the fork's real marshmallow import
                 schemas (the instances ``ImportAssetsCommand`` uses) and through
                 ``ImportAssetsCommand.validate()`` itself. This needs the ``superset``
                 package: a throwaway app is created against a temporary SQLite metadata
                 database (never the configured one). Skip with ``--no-schema`` to run the
                 structural checks alone on a plain Python with PyYAML.
  2. structure   Unique UUIDs; chart -> dataset references; every metric / column a chart
                 uses exists in its dataset; dashboard layout tree (parents / children,
                 CHART uuids, unique chartId, ROW widths <= 12); native filters (dataset,
                 column, cascade parents, scope, chartsInScope); cross-filter configuration.
  3. sql syntax  Metric and calculated-column expressions are parsed with sqlglot
                 (PostgreSQL dialect) when sqlglot is importable.

Optional deep checks:

  --dry-run-import      Run the real ``ImportAssetsCommand(overwrite=True)`` twice as an
                        Admin user against the temporary SQLite metadata database and verify
                        the stored result (no network, the warehouse is never contacted).
  --sql-dsn-env NAME    Read a PostgreSQL DSN from environment variable NAME and execute
                        every metric, calculated column and a per-chart aggregate query
                        against the seeded warehouse (needs psycopg2).

Exit status is non-zero when any error is found. Connection strings are never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import uuid as uuid_lib
from pathlib import Path
from typing import Any, Iterable

import yaml

PREFIXES = ("databases/", "datasets/", "charts/", "dashboards/")
METADATA_FILE = "metadata.yaml"

# Stable chart types the demo is allowed to use.
ALLOWED_VIZ_TYPES = {
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
    "sankey_v2",
    "heatmap_v2",
    "box_plot",
    "waterfall",
    "big_number_total",
    "big_number",
    "pivot_table_v2",
    "table",
}
TIMESERIES_VIZ_TYPES = {
    "echarts_timeseries_line",
    "echarts_timeseries_bar",
    "echarts_timeseries_smooth",
    "echarts_area",
    "mixed_timeseries",
    "waterfall",
}
# Form-data keys that must be present and non-empty for the chart to render.
REQUIRED_PARAMS: dict[str, tuple[str, ...]] = {
    "echarts_timeseries_line": ("x_axis", "metrics"),
    "echarts_timeseries_bar": ("x_axis", "metrics"),
    "echarts_timeseries_smooth": ("x_axis", "metrics"),
    "echarts_area": ("x_axis", "metrics"),
    "mixed_timeseries": ("x_axis", "metrics", "metrics_b"),
    "pie": ("groupby", "metric"),
    "treemap_v2": ("groupby", "metric"),
    "sunburst_v2": ("columns", "metric"),
    "funnel": ("groupby", "metric"),
    "gauge_chart": ("metric",),
    "radar": ("groupby", "metrics"),
    "sankey_v2": ("source", "target", "metric"),
    "heatmap_v2": ("x_axis", "groupby", "metric"),
    "box_plot": ("columns", "groupby", "metrics"),
    "waterfall": ("x_axis", "metric"),
    "big_number_total": ("metric",),
    "big_number": ("metric", "x_axis", "time_grain_sqla"),
    "pivot_table_v2": ("groupbyRows", "metrics"),
    "table": (),
}
METRIC_KEYS = (
    "metric",
    "metrics",
    "metrics_b",
    "percent_metrics",
    "timeseries_limit_metric",
    "series_limit_metric",
    "secondary_metric",
    "size",
    "x",
    "y",
)
COLUMN_KEYS = (
    "groupby",
    "groupby_b",
    "columns",
    "x_axis",
    "series",
    "entity",
    "source",
    "target",
    "all_columns",
    "groupbyRows",
    "groupbyColumns",
    "granularity_sqla",
    "column",
)
FILTER_KEYS = ("adhoc_filters", "adhoc_filters_b")
SERIES_AGGREGATES = {"name", "sum", "min", "max", "avg"}
NATIVE_FILTER_TYPES = {"filter_select", "filter_range", "filter_time", "filter_timecolumn", "filter_timegrain"}
CATEGORICAL_ONLY = {"nxtbiColors", "supersetColors"}
GRAIN_UNITS = {"PT1H": "hour", "P1D": "day", "P1W": "week", "P1M": "month", "P3M": "quarter", "P1Y": "year"}


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.notes: list[str] = []

    def error(self, where: str, message: str) -> None:
        self.errors.append(f"{where}: {message}")

    def warn(self, where: str, message: str) -> None:
        self.warnings.append(f"{where}: {message}")

    def note(self, message: str) -> None:
        self.notes.append(message)


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def is_uuid(value: Any) -> bool:
    try:
        uuid_lib.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return False
    return True


# --------------------------------------------------------------------------- loading


def read_contents(bundle_dir: Path) -> dict[str, str]:
    return {
        path.relative_to(bundle_dir).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(bundle_dir.rglob("*"))
        if path.is_file() and path.suffix in (".yaml", ".yml")
    }


def load_documents(contents: dict[str, str], report: Report) -> dict[str, dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    for name, text in contents.items():
        if "\r" in text:
            report.error(name, "contains CR characters (files must use LF line endings)")
        try:
            document = yaml.safe_load(text)
        except yaml.YAMLError as ex:
            report.error(name, f"not valid YAML ({type(ex).__name__})")
            continue
        if not isinstance(document, dict):
            report.error(name, "top-level YAML value is not a mapping")
            continue
        if name != METADATA_FILE and not name.startswith(PREFIXES):
            report.error(name, "unexpected path (the importer only reads databases/, datasets/, charts/, dashboards/)")
            continue
        documents[name] = document
    return documents


# --------------------------------------------------------------------------- structure


class Bundle:
    """Indexed view of the bundle documents."""

    def __init__(self, documents: dict[str, dict[str, Any]]) -> None:
        self.documents = documents
        self.databases = {n: d for n, d in documents.items() if n.startswith("databases/")}
        self.datasets = {n: d for n, d in documents.items() if n.startswith("datasets/")}
        self.charts = {n: d for n, d in documents.items() if n.startswith("charts/")}
        self.dashboards = {n: d for n, d in documents.items() if n.startswith("dashboards/")}
        self.dataset_by_uuid = {str(d.get("uuid")): d for d in self.datasets.values()}
        self.chart_by_uuid = {str(d.get("uuid")): d for d in self.charts.values()}
        self.chart_file_by_uuid = {str(d.get("uuid")): n for n, d in self.charts.items()}

    @staticmethod
    def columns(dataset: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {c.get("column_name"): c for c in dataset.get("columns") or []}

    @staticmethod
    def metrics(dataset: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {m.get("metric_name"): m for m in dataset.get("metrics") or []}


def check_metadata(bundle: Bundle, report: Report) -> None:
    metadata = bundle.documents.get(METADATA_FILE)
    if metadata is None:
        report.error(METADATA_FILE, "missing")
        return
    if str(metadata.get("version")) != "1.0.0":
        report.error(METADATA_FILE, "version must be the string 1.0.0")
    if metadata.get("type") != "assets":
        report.error(METADATA_FILE, "type must be 'assets' for ImportAssetsCommand")
    if not isinstance(metadata.get("timestamp"), str):
        report.error(METADATA_FILE, "timestamp must be a quoted ISO-8601 string")


def check_uuids(bundle: Bundle, report: Report) -> None:
    seen: dict[str, str] = {}

    def register(value: Any, where: str) -> None:
        if not is_uuid(value):
            report.error(where, f"invalid or missing uuid {value!r}")
            return
        key = str(value).lower()
        if key in seen:
            report.error(where, f"uuid {key} is already used by {seen[key]}")
        seen[key] = where

    for name, document in bundle.documents.items():
        if name == METADATA_FILE:
            continue
        register(document.get("uuid"), name)
        if str(document.get("version")) != "1.0.0":
            report.error(name, "version must be the string 1.0.0")
        for kind, key in (("columns", "column_name"), ("metrics", "metric_name")):
            for child in document.get(kind) or [] if name.startswith("datasets/") else []:
                if child.get("uuid") is not None:
                    register(child.get("uuid"), f"{name} {kind[:-1]} {child.get(key)}")


def check_databases(bundle: Bundle, report: Report) -> None:
    if not bundle.databases:
        report.error("databases/", "no database file in the bundle")
    for name, database in bundle.databases.items():
        uri = str(database.get("sqlalchemy_uri") or "")
        if "://" not in uri:
            report.error(name, "sqlalchemy_uri is missing or malformed")
        if "XXXXXXXXXX" in uri and not database.get("password"):
            report.error(name, "sqlalchemy_uri carries a masked password and no password is supplied")
        if uri.startswith("sqlite"):
            report.error(name, "sqlite targets are blocked by PREVENT_UNSAFE_DB_CONNECTIONS")
        for flag in ("allow_ctas", "allow_cvas", "allow_dml"):
            if database.get(flag):
                report.warn(name, f"{flag} is enabled")


def check_datasets(bundle: Bundle, report: Report) -> None:
    database_uuids = {str(d.get("uuid")) for d in bundle.databases.values()}
    identities: dict[tuple[Any, ...], str] = {}
    for name, dataset in bundle.datasets.items():
        if str(dataset.get("database_uuid")) not in database_uuids:
            report.error(name, "database_uuid does not match a database in the bundle")
        identity = (dataset.get("database_uuid"), dataset.get("catalog"), dataset.get("schema"), dataset.get("table_name"))
        if identity in identities:
            report.error(name, f"same physical table as {identities[identity]}")
        identities[identity] = name
        if not dataset.get("schema"):
            report.warn(name, "no schema set")

        columns: dict[str, dict[str, Any]] = {}
        for column in dataset.get("columns") or []:
            column_name = column.get("column_name")
            if column_name in columns:
                report.error(name, f"duplicate column {column_name}")
            columns[column_name] = column
            if not column.get("type"):
                report.error(name, f"column {column_name} has no type")
            if not column.get("verbose_name"):
                report.warn(name, f"column {column_name} has no verbose_name")
        metrics: dict[str, dict[str, Any]] = {}
        for item in dataset.get("metrics") or []:
            metric_name = item.get("metric_name")
            if metric_name in metrics:
                report.error(name, f"duplicate metric {metric_name}")
            if metric_name in columns:
                report.error(name, f"metric {metric_name} has the same name as a column")
            metrics[metric_name] = item
            if not str(item.get("expression") or "").strip():
                report.error(name, f"metric {metric_name} has no expression")
            if not item.get("verbose_name"):
                report.warn(name, f"metric {metric_name} has no verbose_name")
        if not metrics:
            report.error(name, "dataset has no saved metrics")

        main_dttm = dataset.get("main_dttm_col")
        if main_dttm:
            if main_dttm not in columns:
                report.error(name, f"main_dttm_col {main_dttm} is not a column")
            elif not columns[main_dttm].get("is_dttm"):
                report.error(name, f"main_dttm_col {main_dttm} is not flagged is_dttm")
        else:
            report.warn(name, "no main_dttm_col")


def _metric_label(item: Any) -> str | None:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return item.get("label")
    return None


def _check_metric(item: Any, key: str, where: str, dataset: dict[str, Any], report: Report) -> None:
    metrics = Bundle.metrics(dataset)
    columns = Bundle.columns(dataset)
    if isinstance(item, str):
        if item not in metrics:
            report.error(where, f"{key}: saved metric {item!r} does not exist in dataset {dataset.get('table_name')}")
    elif isinstance(item, dict):
        expression_type = item.get("expressionType")
        if expression_type == "SIMPLE":
            column_name = (item.get("column") or {}).get("column_name")
            if column_name not in columns:
                report.error(where, f"{key}: ad-hoc metric column {column_name!r} does not exist")
            if not item.get("aggregate"):
                report.error(where, f"{key}: ad-hoc SIMPLE metric without aggregate")
        elif expression_type == "SQL":
            if not item.get("sqlExpression"):
                report.error(where, f"{key}: ad-hoc SQL metric without sqlExpression")
            report.warn(where, f"{key}: ad-hoc SQL metric {item.get('label')!r} (prefer a saved metric)")
        else:
            report.error(where, f"{key}: ad-hoc metric with unknown expressionType {expression_type!r}")
    else:
        report.error(where, f"{key}: unsupported metric value {item!r}")


def _check_column(item: Any, key: str, where: str, dataset: dict[str, Any], report: Report) -> None:
    columns = Bundle.columns(dataset)
    if isinstance(item, str):
        if item not in columns:
            report.error(where, f"{key}: column {item!r} does not exist in dataset {dataset.get('table_name')}")
    elif isinstance(item, dict):
        if not item.get("sqlExpression") or not item.get("label"):
            report.error(where, f"{key}: ad-hoc column needs sqlExpression and label")
    else:
        report.error(where, f"{key}: unsupported column value {item!r}")


def chart_columns(params: dict[str, Any]) -> list[str]:
    """Plain column names a chart's form data references (ad-hoc columns excluded)."""
    names: list[str] = []
    for key in COLUMN_KEYS:
        for item in as_list(params.get(key)):
            if isinstance(item, str) and item not in names:
                names.append(item)
    return names


def chart_metrics(params: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for key in METRIC_KEYS:
        for item in as_list(params.get(key)):
            label = _metric_label(item)
            if label and label not in names:
                names.append(label)
    return names


def check_charts(bundle: Bundle, report: Report) -> None:
    for name, chart in bundle.charts.items():
        params = chart.get("params")
        if not isinstance(params, dict):
            report.error(name, "params must be a mapping")
            continue
        dataset = bundle.dataset_by_uuid.get(str(chart.get("dataset_uuid")))
        if dataset is None:
            report.error(name, "dataset_uuid does not match a dataset in the bundle")
            continue
        columns = Bundle.columns(dataset)
        viz_type = chart.get("viz_type")
        if params.get("viz_type") != viz_type:
            report.error(name, f"params.viz_type {params.get('viz_type')!r} differs from viz_type {viz_type!r}")
        if viz_type not in ALLOWED_VIZ_TYPES:
            report.error(name, f"viz_type {viz_type!r} is not in the stable allow-list")
        if chart.get("query_context") is not None:
            try:
                json.loads(chart["query_context"])
            except (TypeError, ValueError):
                report.error(name, "query_context must be null or a JSON string")
        if not chart.get("slice_name"):
            report.error(name, "slice_name is empty")

        for key in REQUIRED_PARAMS.get(str(viz_type), ()):
            if params.get(key) in (None, "", [], {}):
                report.error(name, f"{viz_type} needs a non-empty {key!r}")
        if viz_type == "table":
            mode = params.get("query_mode")
            if mode == "raw" and not params.get("all_columns"):
                report.error(name, "raw table needs all_columns")
            if mode == "aggregate" and not (params.get("groupby") or params.get("metrics")):
                report.error(name, "aggregate table needs groupby or metrics")
            if mode not in ("raw", "aggregate"):
                report.error(name, f"table query_mode {mode!r} is invalid")
        if "row_limit" not in params:
            report.warn(name, "no row_limit")
        if "datasource" in params:
            report.warn(name, "params.datasource is overwritten by the importer; omit it")

        for key in METRIC_KEYS:
            for item in as_list(params.get(key)):
                _check_metric(item, key, name, dataset, report)
        for key in COLUMN_KEYS:
            for item in as_list(params.get(key)):
                _check_column(item, key, name, dataset, report)
        for column_name in params.get("temporal_columns_lookup") or {}:
            if column_name not in columns:
                report.error(name, f"temporal_columns_lookup: column {column_name!r} does not exist")
            elif not columns[column_name].get("is_dttm"):
                report.error(name, f"temporal_columns_lookup: column {column_name!r} is not temporal")
        for raw in as_list(params.get("order_by_cols")):
            try:
                column_name, _ascending = json.loads(raw)
            except (TypeError, ValueError):
                report.error(name, f"order_by_cols entry {raw!r} is not a JSON [column, ascending] pair")
                continue
            if column_name not in columns:
                report.error(name, f"order_by_cols: column {column_name!r} does not exist")

        has_time_filter = False
        for key in FILTER_KEYS:
            for adhoc in as_list(params.get(key)):
                if not isinstance(adhoc, dict):
                    report.error(name, f"{key}: entry is not a mapping")
                    continue
                if adhoc.get("expressionType") == "SIMPLE":
                    subject = adhoc.get("subject")
                    if subject not in columns:
                        report.error(name, f"{key}: filter subject {subject!r} does not exist")
                    elif adhoc.get("operator") == "TEMPORAL_RANGE":
                        if not columns[subject].get("is_dttm"):
                            report.error(name, f"{key}: TEMPORAL_RANGE on non-temporal column {subject!r}")
                        if key == "adhoc_filters":
                            has_time_filter = True
                elif adhoc.get("expressionType") == "SQL":
                    if not adhoc.get("sqlExpression"):
                        report.error(name, f"{key}: SQL filter without sqlExpression")
                else:
                    report.error(name, f"{key}: unknown expressionType {adhoc.get('expressionType')!r}")
        if not has_time_filter:
            report.warn(name, "no TEMPORAL_RANGE ad-hoc filter: the dashboard time filter will not apply")
        if viz_type == "mixed_timeseries" and not params.get("adhoc_filters_b"):
            report.warn(name, "mixed_timeseries query B has no adhoc_filters_b (time filter will not apply to it)")

        x_axis = params.get("x_axis")
        if isinstance(x_axis, str) and x_axis in columns:
            temporal = bool(columns[x_axis].get("is_dttm"))
            if temporal and viz_type in TIMESERIES_VIZ_TYPES | {"big_number"} and not params.get("time_grain_sqla"):
                report.error(name, "temporal x_axis without time_grain_sqla")
            if viz_type == "big_number" and not temporal:
                report.error(name, "big_number trendline needs a temporal x_axis")
        grain = params.get("time_grain_sqla")
        if grain is not None and grain not in GRAIN_UNITS:
            report.warn(name, f"unusual time_grain_sqla {grain!r}")

        labels = set(chart_metrics(params))
        sort = params.get("x_axis_sort")
        if sort is not None:
            allowed = labels | SERIES_AGGREGATES | ({x_axis} if isinstance(x_axis, str) else set())
            if sort not in allowed:
                report.error(name, f"x_axis_sort {sort!r} is neither the x-axis, a chart metric nor a series aggregate")
            if "x_axis_sort_asc" not in params:
                report.error(name, "x_axis_sort without x_axis_sort_asc")
        referable = labels | set(chart_columns(params))
        for rule in as_list(params.get("conditional_formatting")):
            rule_column = rule.get("column") if isinstance(rule, dict) else None
            if rule_column not in referable:
                report.error(name, f"conditional_formatting column {rule_column!r} is not shown by the chart")
        for column_name in params.get("column_config") or {}:
            if column_name not in referable:
                report.error(name, f"column_config key {column_name!r} is not shown by the chart")
        linear = params.get("linear_color_scheme")
        if linear in CATEGORICAL_ONLY:
            report.error(name, f"linear_color_scheme {linear!r} is a categorical scheme")


def check_position(name: str, dashboard: dict[str, Any], bundle: Bundle, report: Report) -> dict[int, str]:
    """Validate the layout tree; returns {chartId: chart uuid} of the dashboard."""
    position = dashboard.get("position")
    chart_ids: dict[int, str] = {}
    if not isinstance(position, dict):
        report.error(name, "position must be a mapping")
        return chart_ids
    if position.get("DASHBOARD_VERSION_KEY") != "v2":
        report.error(name, "position.DASHBOARD_VERSION_KEY must be v2")
    nodes = {key: node for key, node in position.items() if isinstance(node, dict)}
    for required in ("ROOT_ID", "GRID_ID", "HEADER_ID"):
        if required not in nodes:
            report.error(name, f"position.{required} is missing")
    if not nodes.get("HEADER_ID", {}).get("meta", {}).get("text"):
        report.error(name, "HEADER_ID.meta.text is empty")

    children_of = {"ROOT": {"GRID", "TABS"}, "GRID": {"ROW", "TABS", "MARKDOWN", "CHART", "DIVIDER", "HEADER"},
                   "TABS": {"TAB"}, "TAB": {"ROW", "TABS", "MARKDOWN", "CHART", "DIVIDER", "HEADER"},
                   "ROW": {"CHART", "MARKDOWN", "COLUMN"}, "COLUMN": {"CHART", "MARKDOWN", "ROW", "DIVIDER", "HEADER"}}
    parent_of: dict[str, str] = {}
    uuids_seen: dict[str, str] = {}
    for key, node in nodes.items():
        where = f"{name} {key}"
        if node.get("id") != key:
            report.error(where, f"id {node.get('id')!r} differs from its key")
        node_type = node.get("type")
        for child in node.get("children") or []:
            if child not in nodes:
                report.error(where, f"child {child!r} does not exist")
                continue
            if child in parent_of:
                report.error(where, f"child {child!r} is also a child of {parent_of[child]}")
            parent_of[child] = key
            child_type = nodes[child].get("type")
            if node_type in children_of and child_type not in children_of[node_type]:
                report.error(where, f"{node_type} cannot contain {child_type} ({child})")
        if node_type in ("CHART", "MARKDOWN", "HEADER", "DIVIDER") and node.get("children"):
            report.error(where, f"{node_type} must not have children")

        meta = node.get("meta") or {}
        if node_type in ("CHART", "MARKDOWN", "COLUMN"):
            width = meta.get("width")
            if not isinstance(width, int) or not 1 <= width <= 12:
                report.error(where, f"width {width!r} must be an integer between 1 and 12")
        if node_type in ("CHART", "MARKDOWN"):
            height = meta.get("height")
            if not isinstance(height, int) or height < 5:
                report.error(where, f"height {height!r} must be an integer >= 5")
        if node_type == "MARKDOWN" and not str(meta.get("code") or "").strip():
            report.error(where, "markdown code is empty")
        if node_type == "TAB" and not meta.get("text"):
            report.error(where, "tab has no text")
        if node_type == "CHART":
            chart_uuid = str(meta.get("uuid"))
            chart = bundle.chart_by_uuid.get(chart_uuid)
            if chart is None:
                report.error(where, f"meta.uuid {chart_uuid} is not a chart in the bundle")
            elif meta.get("sliceName") != chart.get("slice_name"):
                report.warn(where, "meta.sliceName differs from the chart's slice_name")
            if chart_uuid in uuids_seen:
                report.error(where, f"chart {chart_uuid} is already placed at {uuids_seen[chart_uuid]}")
            uuids_seen[chart_uuid] = key
            chart_id = meta.get("chartId")
            if not isinstance(chart_id, int) or isinstance(chart_id, bool):
                report.error(where, f"meta.chartId {chart_id!r} must be an integer")
            elif chart_id in chart_ids:
                report.error(where, f"meta.chartId {chart_id} is used twice")
            else:
                chart_ids[chart_id] = chart_uuid

    for key, node in nodes.items():
        where = f"{name} {key}"
        node_type = node.get("type")
        if key in ("ROOT_ID", "HEADER_ID"):
            continue
        parents = node.get("parents")
        if key not in parent_of:
            report.error(where, "node is not referenced as a child of any node (orphan)")
            continue
        parent = parent_of[key]
        expected = list(nodes[parent].get("parents") or []) + [parent]
        if parents != expected:
            report.error(where, f"parents {parents} should be {expected}")
        if not parents or parents[0] != "ROOT_ID":
            report.error(where, "parents chain does not start at ROOT_ID")
        if node_type == "ROW":
            total = sum(int((nodes[c].get("meta") or {}).get("width") or 0) for c in node.get("children") or [] if c in nodes)
            if total > 12:
                report.error(where, f"child widths sum to {total} (> 12)")
            elif total < 12:
                report.warn(where, f"child widths sum to {total} (< 12 leaves a gap)")
            if not node.get("children"):
                report.error(where, "row is empty")
        if node_type == "COLUMN":
            width = int((node.get("meta") or {}).get("width") or 0)
            for child in node.get("children") or []:
                child_width = (nodes.get(child, {}).get("meta") or {}).get("width")
                if isinstance(child_width, int) and child_width > width:
                    report.error(where, f"child {child} is wider ({child_width}) than the column ({width})")
    return chart_ids


def charts_in_scope(position: dict[str, Any], scope: Any) -> set[int] | None:
    """Chart ids a {rootPath, excluded} scope selects (mirrors getChartIdsInFilterScope)."""
    if not isinstance(scope, dict) or not isinstance(scope.get("rootPath"), list):
        return None
    excluded = set(scope.get("excluded") or [])
    selected: set[int] = set()
    for node in position.values():
        if isinstance(node, dict) and node.get("type") == "CHART":
            chart_id = node["meta"].get("chartId")
            parents = set(node.get("parents") or [])
            if chart_id not in excluded and parents & set(scope["rootPath"]):
                selected.add(chart_id)
    return selected


def _check_scope(where: str, scope: Any, position: dict[str, Any], chart_ids: dict[int, str], report: Report) -> None:
    if not isinstance(scope, dict):
        report.error(where, "scope must be a {rootPath, excluded} mapping")
        return
    if not isinstance(scope.get("rootPath"), list) or not scope["rootPath"]:
        report.error(where, "scope.rootPath must be a non-empty list")
    if not isinstance(scope.get("excluded"), list):
        report.error(where, "scope.excluded must be a list")
    for element in scope.get("rootPath") or []:
        if element not in position:
            report.error(where, f"scope.rootPath element {element!r} is not in the layout")
    for chart_id in scope.get("excluded") or []:
        if chart_id not in chart_ids:
            report.error(where, f"scope.excluded chart id {chart_id!r} is not on the dashboard")


def _check_chart_id_list(where: str, values: Any, chart_ids: dict[int, str], report: Report) -> set[int]:
    by_uuid = {chart_uuid: chart_id for chart_id, chart_uuid in chart_ids.items()}
    resolved: set[int] = set()
    for value in values or []:
        if isinstance(value, int) and value in chart_ids:
            resolved.add(value)
        elif isinstance(value, str) and value in by_uuid:
            resolved.add(by_uuid[value])
        else:
            report.error(where, f"chartsInScope entry {value!r} is not a chart on the dashboard")
    return resolved


def check_dashboards(bundle: Bundle, report: Report) -> None:
    slugs: dict[str, str] = {}
    placed: set[str] = set()
    for name, dashboard in bundle.dashboards.items():
        slug = dashboard.get("slug")
        if slug:
            if slug in slugs:
                report.error(name, f"slug {slug!r} is also used by {slugs[slug]}")
            slugs[slug] = name
        if dashboard.get("published") is not True:
            report.warn(name, "dashboard is not published")
        chart_ids = check_position(name, dashboard, bundle, report)
        placed.update(chart_ids.values())
        position = dashboard.get("position") if isinstance(dashboard.get("position"), dict) else {}
        metadata = dashboard.get("metadata")
        if not isinstance(metadata, dict):
            report.error(name, "metadata must be a mapping")
            continue
        if not chart_ids:
            report.error(name, "dashboard has no charts")
        if not any(isinstance(n, dict) and n.get("type") == "MARKDOWN" for n in position.values()):
            report.warn(name, "no Markdown header block")
        if not isinstance(metadata.get("color_scheme"), str) or not metadata.get("color_scheme"):
            report.warn(name, "metadata.color_scheme is not set")
        if metadata.get("cross_filters_enabled") is not True:
            report.warn(name, "cross_filters_enabled is not true")
        if "default_filters" in metadata:
            try:
                json.loads(metadata["default_filters"])
            except (TypeError, ValueError):
                report.error(name, "metadata.default_filters must be a JSON string")
        for legacy in metadata.get("timed_refresh_immune_slices") or []:
            if legacy not in chart_ids:
                report.error(name, f"timed_refresh_immune_slices id {legacy!r} is not on the dashboard")

        dataset_of_chart = {
            chart_id: str(bundle.chart_by_uuid[chart_uuid].get("dataset_uuid"))
            for chart_id, chart_uuid in chart_ids.items()
            if chart_uuid in bundle.chart_by_uuid
        }

        # native filters
        filters = metadata.get("native_filter_configuration") or []
        filter_by_id: dict[str, dict[str, Any]] = {}
        for native in filters:
            filter_id = native.get("id")
            if filter_id in filter_by_id:
                report.error(name, f"native filter id {filter_id!r} is used twice")
            filter_by_id[filter_id] = native
        kinds = [f.get("filterType") for f in filters]
        if "filter_time" not in kinds:
            report.warn(name, "no filter_time native filter")
        if not any(f.get("cascadeParentIds") for f in filters):
            report.warn(name, "no cascading (dependent) native filter")
        for native in filters:
            where = f"{name} filter {native.get('id')} ({native.get('name')})"
            filter_type = native.get("filterType")
            if native.get("type") != "NATIVE_FILTER":
                report.error(where, "type must be NATIVE_FILTER")
            if not native.get("name"):
                report.error(where, "name is empty")
            if filter_type not in NATIVE_FILTER_TYPES:
                report.error(where, f"unknown filterType {filter_type!r}")
            for key in ("controlValues", "defaultDataMask"):
                if not isinstance(native.get(key), dict):
                    report.error(where, f"{key} must be a mapping")
            _check_scope(where, native.get("scope"), position, chart_ids, report)
            listed = _check_chart_id_list(where, native.get("chartsInScope"), chart_ids, report)
            computed = charts_in_scope(position, native.get("scope"))
            if computed is not None and listed != computed:
                report.error(where, f"chartsInScope {sorted(listed)} does not match the scope ({sorted(computed)})")
            for tab_id in native.get("tabsInScope") or []:
                if (position.get(tab_id) or {}).get("type") != "TAB":
                    report.error(where, f"tabsInScope entry {tab_id!r} is not a TAB in the layout")
            for parent_id in native.get("cascadeParentIds") or []:
                parent = filter_by_id.get(parent_id)
                if parent is None:
                    report.error(where, f"cascade parent {parent_id!r} does not exist")
                elif parent is native:
                    report.error(where, "filter is its own cascade parent")
                elif parent.get("filterType") != "filter_select":
                    report.error(where, "cascade parent must be a filter_select")

            targets = native.get("targets")
            if not isinstance(targets, list) or not targets:
                report.error(where, "targets must be a non-empty list")
                continue
            if filter_type in ("filter_select", "filter_range"):
                for target in targets:
                    dataset = bundle.dataset_by_uuid.get(str(target.get("datasetUuid")))
                    column_name = (target.get("column") or {}).get("name")
                    if "datasetId" in target:
                        report.warn(where, "target carries datasetId; the importer derives it from datasetUuid")
                    if dataset is None:
                        report.error(where, f"target datasetUuid {target.get('datasetUuid')!r} is not a dataset in the bundle")
                        continue
                    column = Bundle.columns(dataset).get(column_name)
                    if column is None:
                        report.error(where, f"target column {column_name!r} does not exist in {dataset.get('table_name')}")
                        continue
                    if column.get("filterable") is False:
                        report.error(where, f"target column {column_name!r} is not filterable")
                    target_dataset = str(dataset.get("uuid"))
                    for chart_id in sorted(listed):
                        other = bundle.dataset_by_uuid.get(dataset_of_chart.get(chart_id, ""))
                        if other is not None and column_name not in Bundle.columns(other):
                            report.error(where, f"chart {chart_id} in scope uses dataset {other.get('table_name')} which has no column {column_name!r}")
                    missed = [cid for cid, ds in dataset_of_chart.items() if ds == target_dataset and cid not in listed]
                    if missed:
                        report.warn(where, f"charts {sorted(missed)} use the filter's dataset but are out of scope")
                    for parent_id in native.get("cascadeParentIds") or []:
                        parent = filter_by_id.get(parent_id) or {}
                        parent_targets = parent.get("targets") or [{}]
                        if str(parent_targets[0].get("datasetUuid")) != target_dataset:
                            report.warn(where, "cascade parent targets a different dataset")

        # cross filters
        by_uuid = {chart_uuid: chart_id for chart_id, chart_uuid in chart_ids.items()}
        configuration = metadata.get("chart_configuration")
        if not isinstance(configuration, dict):
            report.error(name, "metadata.chart_configuration must be a mapping")
            configuration = {}
        for key, entry in configuration.items():
            where = f"{name} chart_configuration[{key}]"
            try:
                chart_id: Any = int(key)
            except (TypeError, ValueError):
                chart_id = by_uuid.get(str(key))
            if chart_id not in chart_ids:
                report.error(where, "key is not a chart on the dashboard")
                continue
            if not isinstance(entry, dict):
                report.error(where, "entry must be a mapping")
                continue
            if entry.get("id") not in (chart_id, chart_ids[chart_id]):
                report.error(where, f"id {entry.get('id')!r} does not match the key")
            cross = entry.get("crossFilters")
            if not isinstance(cross, dict):
                report.error(where, "crossFilters must be a mapping")
                continue
            scope = cross.get("scope")
            if scope != "global":
                _check_scope(where, scope, position, chart_ids, report)
            listed = _check_chart_id_list(where, cross.get("chartsInScope"), chart_ids, report)
            if chart_id in listed:
                report.error(where, "a chart must not cross-filter itself")
        global_configuration = metadata.get("global_chart_configuration")
        if isinstance(global_configuration, dict):
            where = f"{name} global_chart_configuration"
            _check_scope(where, global_configuration.get("scope"), position, chart_ids, report)
            _check_chart_id_list(where, global_configuration.get("chartsInScope"), chart_ids, report)
        elif metadata.get("cross_filters_enabled"):
            report.warn(name, "no global_chart_configuration")

    for chart_uuid, file_name in bundle.chart_file_by_uuid.items():
        if chart_uuid not in placed:
            report.warn(file_name, "chart is not placed on any dashboard")


def check_sql_syntax(bundle: Bundle, report: Report) -> None:
    try:
        import sqlglot
    except ImportError:
        report.note("sql syntax: skipped (sqlglot is not installed)")
        return
    checked = 0
    for name, dataset in bundle.datasets.items():
        expressions = [(f"metric {m.get('metric_name')}", m.get("expression")) for m in dataset.get("metrics") or []]
        expressions += [
            (f"column {c.get('column_name')}", c.get("expression"))
            for c in dataset.get("columns") or []
            if c.get("expression")
        ]
        for label, expression in expressions:
            checked += 1
            try:
                sqlglot.parse_one(f"SELECT {expression} AS c FROM t", dialect="postgres")
            except Exception as ex:  # sqlglot raises ParseError/TokenError
                report.error(name, f"{label}: expression does not parse as PostgreSQL ({type(ex).__name__})")
    report.note(f"sql syntax: {checked} metric/column expressions parsed with sqlglot (postgres)")


def run_structure(bundle: Bundle, report: Report) -> None:
    check_metadata(bundle, report)
    check_uuids(bundle, report)
    check_databases(bundle, report)
    check_datasets(bundle, report)
    check_charts(bundle, report)
    check_dashboards(bundle, report)


# --------------------------------------------------------------------------- superset


class SupersetSandbox:
    """Throwaway Superset app bound to a temporary SQLite metadata database."""

    def __init__(self) -> None:
        self.directory = tempfile.mkdtemp(prefix="nxtbi_validate_")
        self.app: Any = None

    def start(self) -> Any:
        import logging

        config_path = os.path.join(self.directory, "superset_config.py")
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write(
                f"SQLALCHEMY_DATABASE_URI = 'sqlite:///{self.directory}/metadata.db'\n"
                f"SECRET_KEY = '{uuid_lib.uuid4().hex}{uuid_lib.uuid4().hex}'\n"
                "WTF_CSRF_ENABLED = False\n"
            )
        # Always the sandbox config: the validator must never touch a real metadata database.
        os.environ["SUPERSET_CONFIG_PATH"] = config_path
        logging.disable(logging.WARNING)
        from superset.app import create_app

        self.app = create_app()
        return self.app

    def create_tables(self) -> None:
        from flask_appbuilder import Model

        from superset import db

        Model.metadata.create_all(db.engine)

    def close(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)


def _messages(ex: Any) -> str:
    messages = getattr(ex, "normalized_messages", None)
    payload = messages() if callable(messages) else getattr(ex, "messages", str(ex))
    return json.dumps(payload, ensure_ascii=False, default=str)[:1500]


def run_schema(contents: dict[str, str], report: Report) -> None:
    """Load every file through the importer's marshmallow schemas, then run its validate()."""
    from marshmallow import ValidationError

    from superset.commands.exceptions import CommandInvalidError
    from superset.commands.importers.v1.assets import ImportAssetsCommand
    from superset.commands.importers.v1.utils import MetadataSchema

    counts: dict[str, int] = {}
    for name, text in contents.items():
        document = yaml.safe_load(text)
        if not isinstance(document, dict):
            continue
        if name == METADATA_FILE:
            schema: Any = MetadataSchema()
            prefix = "metadata"
        else:
            prefix = name.split("/")[0] + "/"
            schema = ImportAssetsCommand.schemas.get(prefix)
            if schema is None:
                continue
        try:
            schema.load(document)
            counts[prefix] = counts.get(prefix, 0) + 1
        except ValidationError as ex:
            report.error(name, f"{type(schema).__name__}: {_messages(ex)}")
    command = ImportAssetsCommand(dict(contents), overwrite=True)
    try:
        command.validate()
    except CommandInvalidError as ex:
        report.error("ImportAssetsCommand.validate()", _messages(ex))
    else:
        summary = ", ".join(f"{count} {prefix.rstrip('/')}" for prefix, count in sorted(counts.items()))
        report.note(f"schema: {summary} loaded through the import schemas; ImportAssetsCommand.validate() passed")


def run_dry_import(contents: dict[str, str], bundle: Bundle, report: Report) -> None:
    """Import twice with the real command into the sandbox metadata DB and verify the result."""
    from superset import db, security_manager
    from superset.commands.importers.v1.assets import ImportAssetsCommand
    from superset.connectors.sqla.models import SqlaTable
    from superset.extensions import appbuilder
    from superset.models.dashboard import Dashboard
    from superset.models.slice import Slice
    from superset.utils.core import override_user

    appbuilder.add_permissions(update_perms=True)
    security_manager.sync_role_definitions()
    admin = security_manager.add_user(
        "nxtbi_validator", "Bundle", "Validator", "validator@example.org",
        security_manager.find_role("Admin"), password=uuid_lib.uuid4().hex,
    )
    if not admin:
        report.error("dry-run import", "could not create a sandbox Admin user")
        return
    for attempt in (1, 2):
        try:
            with override_user(admin):
                ImportAssetsCommand(dict(contents), overwrite=True).run()
        except Exception as ex:
            db.session.rollback()
            report.error(f"dry-run import (pass {attempt})", f"{type(ex).__name__}: {_messages(ex)}")
            return

    where = "dry-run import"
    stored_datasets = {str(t.uuid): t for t in db.session.query(SqlaTable).all()}
    stored_charts = {str(s.uuid): s for s in db.session.query(Slice).all()}
    stored_dashboards = {str(d.uuid): d for d in db.session.query(Dashboard).all()}
    for label, stored, expected in (
        ("datasets", stored_datasets, bundle.datasets),
        ("charts", stored_charts, bundle.charts),
        ("dashboards", stored_dashboards, bundle.dashboards),
    ):
        if len(stored) != len(expected):
            report.error(where, f"{len(stored)} {label} stored after two imports, expected {len(expected)} (not idempotent?)")
    for name, dataset in bundle.datasets.items():
        table = stored_datasets.get(str(dataset["uuid"]))
        if table is None:
            report.error(where, f"{name} was not stored")
            continue
        if len(table.columns) != len(dataset["columns"]) or len(table.metrics) != len(dataset["metrics"]):
            report.error(where, f"{name}: stored {len(table.columns)} columns / {len(table.metrics)} metrics")
    for name, chart in bundle.charts.items():
        stored_chart = stored_charts.get(str(chart["uuid"]))
        if stored_chart is None:
            report.error(where, f"{name} was not stored")
            continue
        table = stored_datasets.get(str(chart["dataset_uuid"]))
        if table is None or stored_chart.datasource_id != table.id or stored_chart.datasource_type != "table":
            report.error(where, f"{name}: stored chart is not bound to its dataset")
        if json.loads(stored_chart.params).get("datasource") != f"{stored_chart.datasource_id}__table":
            report.error(where, f"{name}: params.datasource was not rewritten")
    for name, dashboard in bundle.dashboards.items():
        stored_dashboard = stored_dashboards.get(str(dashboard["uuid"]))
        if stored_dashboard is None:
            report.error(where, f"{name} was not stored")
            continue
        position = json.loads(stored_dashboard.position_json)
        metadata = json.loads(stored_dashboard.json_metadata)
        expected_ids = {
            stored_charts[str(n["meta"]["uuid"])].id
            for n in dashboard["position"].values()
            if isinstance(n, dict) and n.get("type") == "CHART" and str(n["meta"]["uuid"]) in stored_charts
        }
        layout_ids = {n["meta"]["chartId"] for n in position.values() if isinstance(n, dict) and n.get("type") == "CHART"}
        slice_ids = {s.id for s in stored_dashboard.slices}
        if not (expected_ids == layout_ids == slice_ids):
            report.error(where, f"{name}: layout chart ids / dashboard slices do not match the imported charts")
        if stored_dashboard.slug != dashboard.get("slug") or not stored_dashboard.published:
            report.error(where, f"{name}: slug or published flag was not stored")
        for native in metadata.get("native_filter_configuration") or []:
            if not set(native.get("chartsInScope") or []) <= slice_ids:
                report.error(where, f"{name}: filter {native.get('name')} chartsInScope was not remapped")
            if native.get("filterType") == "filter_select":
                target = (native.get("targets") or [{}])[0]
                if "datasetUuid" in target or target.get("datasetId") not in {t.id for t in stored_datasets.values()}:
                    report.error(where, f"{name}: filter {native.get('name')} target was not bound to a dataset id")
        for key, entry in (metadata.get("chart_configuration") or {}).items():
            if not str(key).isdigit() or int(key) not in slice_ids or entry.get("id") != int(key):
                report.error(where, f"{name}: chart_configuration key {key!r} was not remapped")
            elif not set(entry["crossFilters"].get("chartsInScope") or []) <= slice_ids:
                report.error(where, f"{name}: chart_configuration[{key}] chartsInScope was not remapped")
    report.note(
        "dry-run import: ImportAssetsCommand(overwrite=True) ran twice as Admin on a throwaway SQLite "
        f"metadata DB; stored {len(stored_datasets)} datasets, {len(stored_charts)} charts, "
        f"{len(stored_dashboards)} dashboards"
    )


# --------------------------------------------------------------------------- warehouse sql


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _column_sql(dataset: dict[str, Any], column_name: str) -> str:
    column = Bundle.columns(dataset)[column_name]
    return f"({column['expression']})" if column.get("expression") else _quote(column_name)


def run_sql_checks(bundle: Bundle, dsn: str, report: Report) -> None:
    """Execute metrics, calculated columns and one aggregate query per chart on PostgreSQL."""
    try:
        import psycopg2
    except ImportError:
        report.error("sql check", "psycopg2 is not installed")
        return
    try:
        connection = psycopg2.connect(dsn)
    except Exception as ex:
        report.error("sql check", f"could not connect ({type(ex).__name__})")
        return
    connection.autocommit = True
    executed = 0

    def run(where: str, sql: str) -> list[tuple[Any, ...]] | None:
        nonlocal executed
        executed += 1
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql)
                return cursor.fetchall()
        except Exception as ex:
            report.error(where, f"SQL failed: {str(ex).strip().splitlines()[0]} | {sql[:300]}")
            return None

    def relation(dataset: dict[str, Any]) -> str:
        schema = dataset.get("schema")
        table = _quote(dataset["table_name"])
        return f"{_quote(schema)}.{table}" if schema else table

    for name, dataset in bundle.datasets.items():
        source = relation(dataset)
        counted = run(name, f"SELECT COUNT(*) FROM {source}")
        if counted is not None and counted[0][0] == 0:
            report.error(name, "table is empty")
        declared = {c["column_name"] for c in dataset.get("columns") or [] if not c.get("expression")}
        actual = run(
            name,
            "SELECT column_name FROM information_schema.columns "
            f"WHERE table_schema = '{dataset.get('schema')}' AND table_name = '{dataset['table_name']}'",
        )
        if actual is not None:
            physical = {row[0] for row in actual}
            if declared - physical:
                report.error(name, f"columns not in the table: {sorted(declared - physical)}")
            if physical - declared:
                report.warn(name, f"table columns missing from the dataset: {sorted(physical - declared)}")
        for item in dataset.get("metrics") or []:
            rows = run(f"{name} metric {item['metric_name']}", f"SELECT {item['expression']} FROM {source}")
            if rows is not None and rows[0][0] is None:
                report.error(f"{name} metric {item['metric_name']}", "evaluates to NULL over the whole table")
        for column in dataset.get("columns") or []:
            if column.get("expression"):
                rows = run(
                    f"{name} column {column['column_name']}",
                    f"SELECT COUNT(*), COUNT({_column_sql(dataset, column['column_name'])}) FROM {source}",
                )
                if rows is not None and rows[0][1] == 0:
                    report.error(f"{name} column {column['column_name']}", "is NULL for every row")
            if column.get("is_dttm"):
                run(f"{name} column {column['column_name']}", f"SELECT DATE_TRUNC('month', {_quote(column['column_name'])}) FROM {source} LIMIT 1")

    for name, chart in bundle.charts.items():
        dataset = bundle.dataset_by_uuid.get(str(chart.get("dataset_uuid")))
        params = chart.get("params") or {}
        if dataset is None:
            continue
        columns = Bundle.columns(dataset)
        metrics = Bundle.metrics(dataset)
        source = relation(dataset)
        unit = GRAIN_UNITS.get(params.get("time_grain_sqla") or "")
        dimensions: list[str] = []
        for column_name in chart_columns(params):
            if column_name not in columns:
                continue
            sql = _column_sql(dataset, column_name)
            if unit and columns[column_name].get("is_dttm"):
                sql = f"DATE_TRUNC('{unit}', {sql})"
            dimensions.append(sql)
        measures = [metrics[m]["expression"] for m in chart_metrics(params) if m in metrics]
        if params.get("query_mode") == "raw" or not measures:
            rows = run(name, f"SELECT {', '.join(dimensions) or '*'} FROM {source} LIMIT 50")
        else:
            select = ", ".join(dimensions + measures)
            group = f" GROUP BY {', '.join(str(i + 1) for i in range(len(dimensions)))}" if dimensions else ""
            rows = run(name, f"SELECT {select} FROM {source}{group} LIMIT 20000")
            if rows:
                first = len(dimensions)
                for offset in range(len(measures)):
                    if all(row[first + offset] is None for row in rows):
                        report.error(name, f"metric #{offset + 1} is NULL in every group")
        if rows is not None:
            if not rows:
                report.error(name, "query returned no rows")
            elif len(rows) >= 20000:
                report.warn(name, "query returns 20000+ groups (chart row_limit will truncate)")
            row_limit = params.get("row_limit")
            if isinstance(row_limit, int) and len(rows) > row_limit and params.get("query_mode") != "raw":
                report.warn(name, f"{len(rows)} groups exceed row_limit {row_limit}")
    connection.close()
    report.note(f"sql check: {executed} statements executed on PostgreSQL")


# --------------------------------------------------------------------------- cli


def summarize(bundle: Bundle, report: Report) -> None:
    print(
        f"bundle: {len(bundle.databases)} database(s), {len(bundle.datasets)} dataset(s), "
        f"{len(bundle.charts)} chart(s), {len(bundle.dashboards)} dashboard(s)"
    )
    for dataset in bundle.datasets.values():
        calculated = sum(1 for c in dataset.get("columns") or [] if c.get("expression"))
        print(
            f"  dataset {dataset.get('schema')}.{dataset.get('table_name')}: "
            f"{len(dataset.get('columns') or [])} columns ({calculated} calculated), "
            f"{len(dataset.get('metrics') or [])} metrics"
        )
    for dashboard in bundle.dashboards.values():
        position = dashboard.get("position") if isinstance(dashboard.get("position"), dict) else {}
        metadata = dashboard.get("metadata") if isinstance(dashboard.get("metadata"), dict) else {}
        charts = [n for n in position.values() if isinstance(n, dict) and n.get("type") == "CHART"]
        tabs = [n for n in position.values() if isinstance(n, dict) and n.get("type") == "TAB"]
        filters = metadata.get("native_filter_configuration") or []
        viz = sorted({
            str(bundle.chart_by_uuid[str(n["meta"].get("uuid"))].get("viz_type"))
            for n in charts
            if str(n["meta"].get("uuid")) in bundle.chart_by_uuid
        })
        print(
            f"  dashboard {dashboard.get('slug')}: {len(charts)} charts, {len(tabs)} tabs, "
            f"{len(filters)} native filters, {len(metadata.get('chart_configuration') or {})} cross-filter emitters"
        )
        print(f"    viz types: {', '.join(viz)}")
    for note in report.notes:
        print(note)
    for warning in report.warnings:
        print(f"WARNING {warning}")
    for error in report.errors:
        print(f"ERROR   {error}")
    verdict = "FAILED" if report.errors else "OK"
    print(f"result: {verdict} ({len(report.errors)} error(s), {len(report.warnings)} warning(s))")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate an NxtBI Superset asset bundle.")
    parser.add_argument("bundle_dir", help="bundle directory (contains metadata.yaml)")
    parser.add_argument("--no-schema", action="store_true",
                        help="skip the marshmallow schema checks (no superset package needed)")
    parser.add_argument("--dry-run-import", action="store_true",
                        help="import twice with ImportAssetsCommand into a throwaway SQLite metadata DB")
    parser.add_argument("--sql-dsn-env", metavar="NAME",
                        help="environment variable holding a PostgreSQL DSN of the seeded warehouse")
    args = parser.parse_args(list(argv) if argv is not None else None)

    bundle_dir = Path(args.bundle_dir)
    if not (bundle_dir / METADATA_FILE).is_file():
        print(f"error: {bundle_dir} is not a bundle directory (no {METADATA_FILE})", file=sys.stderr)
        return 2
    if args.no_schema and args.dry_run_import:
        print("error: --dry-run-import needs the schema step (drop --no-schema)", file=sys.stderr)
        return 2

    report = Report()
    contents = read_contents(bundle_dir)
    bundle = Bundle(load_documents(contents, report))
    run_structure(bundle, report)
    check_sql_syntax(bundle, report)

    if args.no_schema:
        report.note("schema: skipped (--no-schema)")
    else:
        sandbox = SupersetSandbox()
        try:
            app = sandbox.start()
            with app.app_context():
                sandbox.create_tables()
                run_schema(contents, report)
                if args.dry_run_import:
                    if report.errors:
                        report.note("dry-run import: skipped because earlier checks failed")
                    else:
                        run_dry_import(contents, bundle, report)
        except ImportError as ex:
            report.error("schema", f"the superset package is not importable ({ex}); use --no-schema for structure only")
        finally:
            sandbox.close()

    if args.sql_dsn_env:
        dsn = os.environ.get(args.sql_dsn_env, "")
        if not dsn:
            report.error("sql check", f"environment variable {args.sql_dsn_env} is not set")
        else:
            run_sql_checks(bundle, dsn, report)

    summarize(bundle, report)
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
