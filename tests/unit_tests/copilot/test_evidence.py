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

"""Regression coverage for aggregate-only Copilot evidence."""

from datetime import date
from decimal import Decimal
from inspect import unwrap
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from pydantic import ValidationError

from superset.copilot import api, services
from superset.copilot.contracts import (
    AggregateArguments,
    DashboardProposal,
    ProfileArguments,
    ProposalWidget,
)


def test_profile_projects_only_counts() -> None:
    dataset = MagicMock()
    dataset.columns = [MagicMock(column_name="year", is_dttm=False)]
    query_result = [
        {"row_count": 7, "present_0": 5, "distinct_0": 2, "extra": "private"}
    ]
    with (
        patch.object(services, "_evidence_dataset", return_value=dataset),
        patch.object(services, "_evidence_rows", return_value=query_result) as read,
    ):
        result = services.profile_dataset(ProfileArguments(id=2, columns=["year"]))
    assert result == {
        "dataset_id": 2,
        "row_count": 7,
        "columns": [
            {
                "column_name": "year",
                "non_null_count": 5,
                "null_count": 2,
                "distinct_count": 2,
            }
        ],
    }
    binding, filters = read.call_args.args
    assert filters == []
    assert binding["rowLimit"] == 1
    assert [m.get("aggregate") for m in binding["metrics"]] == [
        None,
        "COUNT",
        "COUNT_DISTINCT",
    ]


def test_aggregate_groups_project_only_the_selected_metric() -> None:
    dataset = MagicMock()
    dataset.metrics = [MagicMock(metric_name="total")]
    dataset.columns = [MagicMock(column_name="year", groupby=True, filterable=True)]
    rows = [
        {"year": i, "total": None if i == 0 else i, "raw": "private"} for i in range(11)
    ]
    with (
        patch.object(services, "_evidence_dataset", return_value=dataset),
        patch.object(services, "_evidence_rows", return_value=rows) as read,
    ):
        result = services.aggregate_dataset(
            AggregateArguments.model_validate(
                {
                    "id": 2,
                    "metric": "total",
                    "dimension": "year",
                    "filter": {"column": "year", "value": 2026},
                }
            )
        )
    assert result["truncated"]
    assert result["rows"] == [
        {"group": r["year"], "value": r["total"]} for r in rows[:10]
    ]
    binding, filters = read.call_args.args
    assert binding["rowLimit"] == 11
    assert filters[0]["comparator"] == 2026


def test_aggregate_converts_database_decimal_to_a_finite_json_number() -> None:
    dataset = MagicMock()
    dataset.metrics = [MagicMock(metric_name="share")]
    with (
        patch.object(services, "_evidence_dataset", return_value=dataset),
        patch.object(
            services, "_evidence_rows", return_value=[{"share": Decimal("0.48698")}]
        ),
    ):
        result = services.aggregate_dataset(AggregateArguments(id=23, metric="share"))
    assert result == {
        "dataset_id": 23,
        "metric": "share",
        "dimension": None,
        "rows": [{"group": None, "value": 0.48698}],
        "truncated": False,
    }


def test_aggregate_scope_keeps_filtered_ratios_and_distinct_counts() -> None:
    metric_names = ["share", "completed", "eligible", "distinct_users"]
    dataset = SimpleNamespace(
        metrics=[SimpleNamespace(metric_name=name) for name in metric_names],
        columns=[
            SimpleNamespace(column_name="region", groupby=True, filterable=False),
            SimpleNamespace(column_name="status", groupby=False, filterable=True),
        ],
    )
    grouped = [
        {
            "region": "North",
            "share": 0.75,
            "completed": 15,
            "eligible": 20,
            "distinct_users": 5,
            "raw": "ignored",
        },
        {
            "region": "South",
            "share": 0.25,
            "completed": 20,
            "eligible": 80,
            "distinct_users": 10,
        },
    ]
    baseline = {
        "share": Decimal("0.35"),
        "completed": 35,
        "eligible": 100,
        "distinct_users": 13,
        "raw": "ignored",
    }
    with (
        patch.object(services, "_evidence_dataset", return_value=dataset),
        patch.object(
            services, "_evidence_rows", side_effect=[grouped, [baseline]]
        ) as read,
    ):
        result = services.aggregate_dataset(
            AggregateArguments.model_validate(
                {
                    "id": 2,
                    "metric": "share",
                    "additionalMetrics": metric_names[1:],
                    "dimension": "region",
                    "filter": {"column": "status", "value": "active"},
                    "includeBaseline": True,
                    "limit": 1,
                }
            )
        )
    assert result == {
        "dataset_id": 2,
        "metric": "share",
        "metrics": metric_names,
        "dimension": "region",
        "rows": [
            {
                "group": "North",
                "value": 0.75,
                "values": {name: grouped[0][name] for name in metric_names},
            }
        ],
        "truncated": True,
        "order": "metric_desc",
        "limit": 1,
        "groups_returned": 1,
        "groups_total": None,
        "baseline": {
            "share": 0.35,
            "completed": 35,
            "eligible": 100,
            "distinct_users": 13,
        },
    }
    grouped_call, baseline_call = read.call_args_list
    assert grouped_call.args[0] == {
        "datasetId": 2,
        "metrics": metric_names,
        "dimensions": ["region"],
        "rowLimit": 2,
    }
    assert grouped_call.kwargs == {"ordered": True}
    assert baseline_call.args[0] == {
        "datasetId": 2,
        "metrics": metric_names,
        "dimensions": [],
        "rowLimit": 1,
    }
    assert grouped_call.args[1] == baseline_call.args[1]
    assert baseline_call.args[1][0]["comparator"] == "active"


def test_aggregate_chronological_groups_can_cover_more_than_ten_periods() -> None:
    dataset = SimpleNamespace(
        metrics=[SimpleNamespace(metric_name="count")],
        columns=[SimpleNamespace(column_name="month", groupby=True)],
    )
    month_rows = [
        {"month": date(2025 + i // 12, i % 12 + 1, 1), "count": i} for i in range(23)
    ]
    with (
        patch.object(services, "_evidence_dataset", return_value=dataset),
        patch.object(services, "_evidence_rows", return_value=month_rows) as read,
    ):
        result = services.aggregate_dataset(
            AggregateArguments(
                id=2, metric="count", dimension="month", limit=48, order="dimension_asc"
            )
        )
    assert result["groups_total"] == 23
    assert result["groups_returned"] == 23
    assert not result["truncated"]
    assert result["rows"][0]["group"] == "2025-01-01"
    assert result["rows"][-1]["group"] == "2026-11-01"
    assert read.call_args.args[0]["rowLimit"] == 49
    assert read.call_args.args[0]["orderByDimension"] is True
    assert read.call_args.kwargs == {"ordered": False}


def test_aggregate_ungrouped_baseline_reuses_measure_query() -> None:
    dataset = SimpleNamespace(metrics=[SimpleNamespace(metric_name="share")])
    with (
        patch.object(services, "_evidence_dataset", return_value=dataset),
        patch.object(
            services, "_evidence_rows", return_value=[{"share": None}]
        ) as read,
    ):
        result = services.aggregate_dataset(
            AggregateArguments.model_validate(
                {"id": 2, "metric": "share", "includeBaseline": True}
            )
        )
    read.assert_called_once()
    assert result["baseline"] == {"share": None}
    assert result["order"] is None


@pytest.mark.parametrize(
    "changes",
    [{"additionalMetrics": ["total"]}, {"limit": 49}, {"order": "unknown"}],
)
def test_aggregate_rejects_invalid_evidence_options(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        AggregateArguments.model_validate({"id": 2, "metric": "total", **changes})


def test_aggregate_rejects_unregistered_additional_measure_before_query() -> None:
    dataset = SimpleNamespace(metrics=[SimpleNamespace(metric_name="share")])
    with (
        patch.object(services, "_evidence_dataset", return_value=dataset),
        patch.object(services, "_evidence_rows") as read,
        pytest.raises(ValueError, match="existing metric"),
    ):
        services.aggregate_dataset(
            AggregateArguments.model_validate(
                {"id": 2, "metric": "share", "additionalMetrics": ["unknown"]}
            )
        )
    read.assert_not_called()


def test_profile_requires_dataset_access_before_query() -> None:
    with (
        patch.object(services, "user_can_view_data_model_metadata", return_value=False),
        patch.object(services, "_evidence_rows") as read,
        pytest.raises(services.CopilotAccessError),
    ):
        services.profile_dataset(ProfileArguments(id=2))
    read.assert_not_called()


def test_evidence_rejects_unregistered_metrics_and_raw_sql() -> None:
    with pytest.raises(ValidationError):
        ProfileArguments(id=2, columns=["year"] * 2)
    with pytest.raises(ValidationError):
        AggregateArguments.model_validate(
            {"id": 2, "metric": "total", "sql": "SELECT 1"}
        )
    dataset = MagicMock()
    dataset.metrics = []
    with (
        patch.object(services, "_evidence_dataset", return_value=dataset),
        patch.object(services, "_evidence_rows") as read,
        pytest.raises(ValueError, match="existing metric"),
    ):
        services.aggregate_dataset(AggregateArguments(id=2, metric="unknown"))
    read.assert_not_called()


def test_proposal_columns_require_temporal_and_filterable_metadata() -> None:
    dataset = MagicMock()
    dataset.columns = [
        MagicMock(column_name="region", groupby=True, is_dttm=False, filterable=False)
    ]
    spec = {
        "type": "echarts",
        "metric": "total",
        "dimension": "region",
        "datasetId": 23,
    }
    with pytest.raises(ValueError, match="temporal"):
        services._validate_widget_columns(
            ProposalWidget.model_validate({**spec, "chartStyle": "line"}), dataset
        )
    with pytest.raises(ValueError, match="filterable"):
        services._validate_widget_columns(
            ProposalWidget.model_validate(
                {**spec, "filter": {"column": "region", "value": "North"}}
            ),
            dataset,
        )


@pytest.mark.parametrize(
    ("denominator", "rate_format", "error"),
    [
        ("eligible", ".1%", None),
        ("unregistered", ".1%", "existing dataset metric"),
        ("eligible", ".1f", None),
        ("eligible", None, None),
    ],
)
def test_rate_cutoff_uses_authorized_dataset_metrics(
    denominator: str, rate_format: str | None, error: str | None
) -> None:
    proposal = DashboardProposal.model_validate(
        {
            "title": "Permit reviews",
            "widgets": [
                {
                    "type": "echarts",
                    "datasetId": 23,
                    "metric": "late_rate",
                    "dimension": "site",
                    "chartStyle": "ranked-bar",
                    "filter": {"column": "status", "value": "Closed"},
                    "rateCutoff": {
                        "denominatorMetric": denominator,
                        "minimumSampleSize": 30,
                    },
                }
            ],
        }
    )
    dataset = MagicMock(deleted_at=None)
    dataset.metrics = [
        SimpleNamespace(
            metric_name="late_rate", verbose_name=None, d3format=rate_format
        ),
        SimpleNamespace(metric_name="eligible", verbose_name=None, d3format=None),
    ]
    dataset.columns = [
        SimpleNamespace(column_name="site", groupby=True, filterable=False),
        SimpleNamespace(column_name="status", groupby=False, filterable=True),
    ]
    with (
        patch.object(services, "db") as database,
        patch.object(services, "security_manager", MagicMock()),
        patch.object(services, "user_can_view_data_model_metadata", return_value=True),
        patch.object(services, "raise_for_document_authoring") as authorize,
    ):
        database.session.get.return_value = dataset
        if error:
            with pytest.raises(ValueError, match=error):
                services.validate_dashboard_proposal(proposal)
            authorize.assert_not_called()
            dataset.raise_for_access.assert_called_once_with()
            return
        document = services.validate_dashboard_proposal(proposal)

    authorize.assert_called_once_with(document, None)
    dataset.raise_for_access.assert_called_once_with()
    props = document["nodes"]["widget_1"]["props"]
    metric_binding = props["echartsOptions"]["series"][0]["data"]["$bind"]
    assert metric_binding.get("format") == ("percent" if rate_format == ".1%" else None)
    dataset_id, query, _ = services.build_widget_query(props, [])
    assert dataset_id == 23
    assert query["metrics"] == ["late_rate", "eligible"]
    assert query["columns"] == ["site"]
    assert query["orderby"] == [("late_rate", False), ("site", True)]
    assert query["filters"] == [{"col": "status", "op": "==", "val": "Closed"}]


@pytest.mark.parametrize(
    ("second_metric", "second_dimension", "error"),
    [
        ("weighted_price", "property_type", None),
        ("unknown_metric", "property_type", "existing dataset metric"),
        ("weighted_price", "private_notes", "groupable dataset column"),
    ],
)
def test_compound_proposal_uses_only_authorized_saved_fields(
    second_metric: str, second_dimension: str, error: str | None
) -> None:
    proposal = DashboardProposal.model_validate(
        {
            "title": "Sale months",
            "widgets": [
                {"type": "metric-tile", "datasetId": 23, "metric": "weighted_price"},
                {
                    "type": "ag-grid-table",
                    "datasetId": 23,
                    "metrics": ["sale_count", second_metric],
                    "dimensions": ["sale_month", second_dimension],
                },
            ],
        }
    )
    dataset = MagicMock(deleted_at=None)
    dataset.metrics = [
        SimpleNamespace(metric_name="sale_count", verbose_name="Sales", d3format=None),
        SimpleNamespace(
            metric_name="weighted_price", verbose_name="Weighted price", d3format=",.2f"
        ),
    ]
    dataset.columns = [
        SimpleNamespace(
            column_name="sale_month",
            verbose_name="Sale month",
            groupby=True,
            is_dttm=True,
        ),
        SimpleNamespace(
            column_name="property_type",
            verbose_name="Property type",
            groupby=True,
            is_dttm=False,
        ),
        SimpleNamespace(column_name="private_notes", groupby=False),
    ]
    database = MagicMock()
    database.session.get.return_value = dataset
    with (
        patch.object(services, "db", database),
        patch.object(services, "security_manager", MagicMock()),
        patch.object(services, "user_can_view_data_model_metadata", return_value=True),
        patch.object(services, "raise_for_document_authoring") as authorize,
    ):
        if error:
            with pytest.raises(ValueError, match=error):
                services.validate_dashboard_proposal(proposal)
            authorize.assert_not_called()
            dataset.raise_for_access.assert_called_once_with()
            return
        document = services.validate_dashboard_proposal(proposal)

    authorize.assert_called_once_with(document, None)
    dataset.raise_for_access.assert_called_once_with()
    assert document["nodes"]["widget_1"]["props"]["label"] == "Weighted price"
    assert document["nodes"]["widget_1"]["props"]["decimals"] == 2
    props = document["nodes"]["widget_2"]["props"]
    columns = [
        {
            key: value
            for key, value in column.items()
            if key in {"field", "headerName", "valueFormat", "valueFormatPrecision"}
        }
        for column in props["columnDefs"]
    ]
    assert columns == [
        {"field": "sale_month", "headerName": "Sale month", "valueFormat": "date"},
        {"field": "property_type", "headerName": "Property type"},
        {"field": "sale_count", "headerName": "Sales"},
        {
            "field": "weighted_price",
            "headerName": "Weighted price",
            "valueFormat": "decimal",
            "valueFormatPrecision": 2,
        },
    ]
    _, query, _ = services.build_widget_query(props, [])
    assert query["metrics"] == ["sale_count", "weighted_price"]
    assert query["columns"] == ["sale_month", "property_type"]
    assert query["orderby"] == [("sale_month", True), ("property_type", True)]


@pytest.mark.parametrize("dashboard_type", ["v1", "v2"])
@pytest.mark.parametrize(
    ("rules", "impersonates", "reason"),
    [
        ([], False, None),
        ([SimpleNamespace(filter_type="Base")], False, "row-level security"),
        ([], True, "database impersonation"),
    ],
)
def test_dashboard_approval_checks_all_bound_datasets(
    dashboard_type: str,
    rules: list[SimpleNamespace],
    impersonates: bool,
    reason: str | None,
) -> None:
    """Keep previews private and refuse to persist captions for scoped sources."""
    app = Flask(__name__)
    actor = SimpleNamespace(id=17)
    draft = {
        "title": "Sales overview",
        "dashboardType": dashboard_type,
        "widgets": [
            {"type": "metric-tile", "datasetId": 23, "metric": "sale_count"},
            {"type": "metric-tile", "datasetId": 24, "metric": "sale_count"},
        ],
    }
    metric = SimpleNamespace(metric_name="sale_count", verbose_name=None, d3format=None)
    db = MagicMock()
    db.session.get.side_effect = lambda _model, dataset_id: MagicMock(
        deleted_at=None,
        sql=None,
        row_level_security_filters=rules if dataset_id == 24 else [],
        database=SimpleNamespace(impersonate_user=impersonates and dataset_id == 24),
        metrics=[metric],
    )
    with (
        patch.object(services, "db", db),
        patch.object(services, "security_manager", MagicMock()),
        patch.object(services, "user_can_view_data_model_metadata", return_value=True),
        patch.object(services, "raise_for_document_authoring"),
        patch.object(api, "_actor", return_value=actor),
        patch.object(api, "_secret", return_value="test" * 8),
        patch.object(api, "_require_widgets"),
        patch.object(
            api, "create_classic_dashboard", return_value=(29, True)
        ) as classic,
        patch.object(api, "CreateDashboardV2Command") as v2,
    ):
        v2.return_value.run.return_value = {"id": 29}
        v2.return_value.created = True
        with app.test_request_context():
            preview = api._preview_dashboard(draft, actor.id)
        assert preview.status_code == 200
        with app.test_request_context(method="POST", json=preview.get_json()):
            response = unwrap(api.NxtbiCopilotRestApi.approve)(
                api.NxtbiCopilotRestApi()
            )

    if reason:
        assert response.status_code == 403
        assert reason in response.get_json()["message"]
        classic.assert_not_called()
        v2.assert_not_called()
    else:
        assert response.status_code == 201
        assert response.get_json()["id"] == 29


@pytest.mark.parametrize(
    ("sql", "sources", "reason"),
    [
        ("SELECT * FROM sales", [SimpleNamespace(sql=None)], None),
        (
            "SELECT * FROM sales",
            [SimpleNamespace(sql=None, row_level_security_filters=["Base"])],
            "row-level security",
        ),
        ("SELECT * FROM sales", [], "verify the source tables"),
        (
            "SELECT * FROM sales",
            [SimpleNamespace(sql="SELECT * FROM orders")],
            "verify the source tables",
        ),
        ("SELECT * FROM {{ source_table }}", [], "verify the source tables"),
        (
            "SELECT adjust_sale_value(sale_count) FROM sales",
            [SimpleNamespace(sql=None)],
            "verify the source tables",
        ),
    ],
)
def test_virtual_dataset_approval_requires_registered_unrestricted_sources(
    sql: str, sources: list[SimpleNamespace], reason: str | None
) -> None:
    """Verify statically resolvable physical sources before approving virtual data."""
    dataset = MagicMock(id=23, deleted_at=None, row_level_security_filters=[], sql=sql)
    dataset.catalog = None
    dataset.schema = "main"
    dataset.database.impersonate_user = False
    dataset.database.db_engine_spec.engine = "sqlite"
    dataset.database.db_engine_spec.supports_dynamic_schema = False
    dataset.database.resolve_query_default_schema.return_value = "main"
    dataset.database.get_default_catalog.return_value = None
    dataset.metrics = [
        SimpleNamespace(metric_name="sale_count", verbose_name=None, d3format=None)
    ]
    db = MagicMock()
    db.session.get.return_value = dataset
    physical_sources = [
        SimpleNamespace(
            deleted_at=None,
            sql=source.sql,
            row_level_security_filters=getattr(
                source, "row_level_security_filters", []
            ),
        )
        for source in sources
    ]
    draft = DashboardProposal.model_validate(
        {
            "title": "Sales overview",
            "widgets": [
                {"type": "metric-tile", "datasetId": 23, "metric": "sale_count"}
            ],
        }
    )
    with (
        patch.object(services, "db", db),
        patch.object(services, "security_manager", MagicMock()),
        patch.object(services, "user_can_view_data_model_metadata", return_value=True),
        patch.object(services, "find_datasets", return_value=physical_sources) as find,
    ):
        services.validate_proposal_references(draft)
        find.assert_not_called()
        if reason:
            with pytest.raises(services.CopilotApprovalScopeError, match=reason):
                services.validate_proposal_references(draft, for_approval=True)
        else:
            services.validate_proposal_references(draft, for_approval=True)
            reference = find.call_args.args[0]
            assert (reference.schema, reference.table) == ("main", "sales")


def test_temporal_profile_reports_observed_bounds_and_nulls() -> None:
    dataset = MagicMock()
    dataset.columns = [MagicMock(column_name="snapshot", is_dttm=True)]
    row = {
        "row_count": 2,
        "present_0": 2,
        "distinct_0": 2,
        "earliest_0": "2015-01-01",
        "latest_0": "2026-01-01",
    }
    with (
        patch.object(services, "_evidence_dataset", return_value=dataset),
        patch.object(services, "_evidence_rows", return_value=[row]) as read,
    ):
        column = services.profile_dataset(
            ProfileArguments(id=23, columns=["snapshot"])
        )["columns"][0]
    assert column["earliest"] == "2015-01-01"
    assert column["latest"] == "2026-01-01"
    assert [m.get("aggregate") for m in read.call_args.args[0]["metrics"]][-2:] == [
        "MIN",
        "MAX",
    ]
    assert services._temporal_bound(None) is None
