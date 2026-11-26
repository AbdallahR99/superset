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
"""Regression coverage for session-only semantic widget bindings."""

from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from pydantic import BaseModel, ValidationError

from superset.exceptions import SupersetSecurityException
from superset.utils.core import DatasourceType
from superset.widgets import data
from superset.widgets.builtin import AgGridTable, Echarts, MetricTile
from superset.widgets.controls import AgGridTableControls, MetricTileControls

VIEW_ID = UUID("fa2578be-733b-4bd1-9de5-95bf0ff04f4d")


def semantic_props(**binding: object) -> dict[str, object]:
    """Construct a valid semantic payload with optional binding overrides."""
    return {
        "dataBinding": {
            "semanticViewId": str(VIEW_ID),
            "metrics": ["transactions"],
            **binding,
        }
    }


@pytest.mark.parametrize("model", [MetricTileControls, AgGridTableControls])
def test_semantic_controls_round_trip_a_separate_source(model: type[BaseModel]) -> None:
    """Keep the native table shape and semantic UUID variants disjoint."""
    semantic = model.model_validate(semantic_props()).model_dump(by_alias=True)
    assert semantic["dataBinding"]["semanticViewId"] == str(VIEW_ID)
    assert "datasetId" not in semantic["dataBinding"]

    table = model.model_validate(
        {"dataBinding": {"datasetId": 8, "metrics": ["transactions"]}}
    ).model_dump(by_alias=True)
    assert table["dataBinding"]["datasetId"] == 8
    assert "semanticViewId" not in table["dataBinding"]


@pytest.mark.parametrize("model", [MetricTileControls, AgGridTableControls])
def test_semantic_controls_preserve_the_table_picker_schema(
    model: type[BaseModel],
) -> None:
    """Retain the native inspector's data binding contract for tables."""
    schema = model.model_json_schema()
    assert schema["properties"]["dataBinding"]["$ref"] == "#/$defs/DataBinding"
    binding = schema["$defs"]["DataBinding"]
    assert "datasetId" in binding["required"]
    assert "semanticViewId" not in binding["properties"]


@pytest.mark.parametrize(
    "binding",
    [
        {"datasetId": 8},
        {"semanticViewId": "19"},
        {"metrics": []},
        {"metrics": [{"expressionType": "SIMPLE", "aggregate": "SUM"}]},
        {"filters": [{"expressionType": "SIMPLE", "subject": "property_type"}]},
    ],
)
def test_semantic_controls_reject_unsupported_binding_fields(
    binding: dict[str, object],
) -> None:
    """Reject bindings outside the semantic contract at validation time."""
    with pytest.raises(ValidationError):
        AgGridTableControls.model_validate(semantic_props(**binding))


def test_semantic_tile_accepts_one_ungrouped_metric() -> None:
    """Prevent source ambiguity within a metric tile's single value."""
    with pytest.raises(ValidationError):
        MetricTileControls.model_validate(semantic_props(dimensions=["property_type"]))
    with pytest.raises(ValidationError):
        MetricTileControls.model_validate(semantic_props(metrics=["one", "two"]))


def test_widget_source_type_limits_semantic_id_extraction() -> None:
    """Only the built-in semantic widgets accept a semantic source."""
    props = semantic_props()
    assert data.widget_semantic_view_id(MetricTile, props) == VIEW_ID
    assert data.widget_semantic_view_id(AgGridTable, props) == VIEW_ID
    assert data.widget_semantic_view_id(Echarts, props) is None
    assert data.widget_semantic_view_id(None, props) is None
    assert data.widget_dataset_id(AgGridTable, props) is None


def test_guest_semantic_widget_resolution_stops_before_view_lookup() -> None:
    """Semantic widget execution requires a normal signed-in principal."""
    with (
        patch.object(data, "is_semantic_layers_enabled", return_value=True),
        patch.object(data, "security_manager") as security,
        patch.object(data.SemanticViewDAO, "find_by_id") as find,
    ):
        security.is_guest_user.return_value = True
        with pytest.raises(SupersetSecurityException):
            data.resolve_widget_semantic_view(VIEW_ID)
    find.assert_not_called()


def test_semantic_widget_uses_native_query_after_source_authorization() -> None:
    """Build native typed semantics with selection versions and safe filters."""
    props = semantic_props(
        dimensions=["property_type"], semanticSelectionVersion="property-v1"
    )
    view = MagicMock(id=19, uuid=VIEW_ID, column_names=["property_type"])
    view.metrics = [MagicMock(metric_name="transactions")]
    with (
        patch.object(
            data, "resolve_widget_semantic_view", return_value=view
        ) as resolve,
        patch.object(data, "QueryContextFactory") as factory,
        patch.object(data, "ChartDataCommand") as command,
    ):
        command.return_value.run.return_value = {
            "queries": [{"colnames": ["transactions"], "data": [{"transactions": 6}]}]
        }

        assert AgGridTable.fetch_data(
            props,
            [{"column": "property_type", "operator": "EQUALS", "value": "Villa"}],
            data.WidgetContext(None, semantic_view_id=VIEW_ID),
        ) == {"columns": ["transactions"], "rows": [{"transactions": 6}]}

    resolve.assert_called_once_with(VIEW_ID)
    factory.assert_called_once_with(authorize_semantic_before_metadata=True)
    request = factory.return_value.create.call_args.kwargs
    assert request["datasource"] == {
        "id": 19,
        "type": DatasourceType.SEMANTIC_VIEW.value,
    }
    query = request["queries"][0]
    assert query["metrics"] == ["transactions"]
    assert query["columns"] == ["property_type"]
    assert query["extras"] == {"semantic_selection_version": "property-v1"}
    assert query["filters"] == [{"col": "property_type", "op": "==", "val": "Villa"}]
    command.return_value.validate.assert_called_once_with()


def test_semantic_widget_rejects_mismatched_context_before_resolution() -> None:
    """A table context cannot authorize a semantic widget binding."""
    with (
        patch.object(data, "resolve_widget_semantic_view") as resolve,
        pytest.raises(data.WidgetDataError, match="context"),
    ):
        MetricTile.fetch_data(semantic_props(), [], data.WidgetContext(19))
    resolve.assert_not_called()


def test_semantic_widget_rejects_metric_outside_the_authorized_catalog() -> None:
    """Query execution may refer only to an existing saved metric."""
    view = MagicMock(id=19, uuid=VIEW_ID, column_names=["property_type"])
    view.metrics = [MagicMock(metric_name="total_sales")]
    with (
        patch.object(data, "resolve_widget_semantic_view", return_value=view),
        patch.object(data, "QueryContextFactory") as factory,
        pytest.raises(data.WidgetDataError, match="saved metrics"),
    ):
        MetricTile.fetch_data(
            semantic_props(), [], data.WidgetContext(None, semantic_view_id=VIEW_ID)
        )
    factory.assert_not_called()
