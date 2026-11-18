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

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from superset.copilot import services
from superset.copilot.contracts import (
    AggregateArguments,
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
    assert result["rows"] == [{"group": None, "value": 0.48698}]


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
