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


"""Verify the Copilot document passed to native Dashboard V2 authoring."""

from unittest.mock import Mock
from uuid import uuid4

import pytest

from superset.copilot import semantic_v2
from superset.copilot.contracts import ContentLocale
from superset.copilot.semantic_classic import SemanticClassicCaptions


@pytest.mark.parametrize(
    ("locale", "property_label"),
    [("en", "Property type"), ("ar", "نوع العقار")],
)
def test_create_semantic_dashboard_keeps_typed_bindings_and_localized_captions(
    monkeypatch: pytest.MonkeyPatch, locale: ContentLocale, property_label: str
) -> None:
    """Write native semantic table and KPI widgets without SQL dataset aliases."""
    view = Mock(uuid=uuid4())
    view.get_compatible_dimensions.return_value = ["property_type"]
    dashboard_uuid = uuid4()
    command = Mock()
    command.return_value.run.return_value = {"id": 20}
    command.return_value.created = True
    monkeypatch.setattr(semantic_v2, "CreateDashboardV2Command", command)
    captions = SemanticClassicCaptions(
        locale=locale,
        dashboard={"en": "Property Market", "ar": "سوق العقارات"},
        kpi={"en": "Price per square meter", "ar": "السعر لكل متر مربع"},
        breakdown={"en": "By property type", "ar": "حسب نوع العقار"},
    )

    assert semantic_v2.create_semantic_v2_dashboard(
        view,
        "weighted_price_per_sqm",
        captions,
        dashboard_uuid,
        unit="AED/m²",
        selection_version="7",
    ) == (20, True)

    view.raise_for_access.assert_called_once_with()
    view.get_compatible_dimensions.assert_called_once_with(
        ["weighted_price_per_sqm"], []
    )
    payload = command.call_args.args[0]
    assert payload["dashboard_title"] == captions.dashboard[locale]
    assert payload["uuid"] == dashboard_uuid
    nodes = payload["document"]["nodes"]
    assert nodes["root"]["children"] == ["metric", "breakdown"]
    localization = nodes["root"]["props"]["nxtbiLocalization"]
    assert localization["sourceLocale"] == locale
    assert localization["title"] == {
        "source": captions.dashboard[locale],
        "translations": captions.dashboard,
    }
    assert localization["widgets"]["breakdown"]["translations"] == captions.breakdown
    for node, dimensions in (
        (nodes["metric"], []),
        (nodes["breakdown"], ["property_type"]),
    ):
        binding = node["props"]["dataBinding"]
        assert binding["semanticViewId"] == str(view.uuid)
        assert binding["metrics"] == ["weighted_price_per_sqm"]
        assert binding["semanticSelectionVersion"] == "7"
        assert binding["dimensions"] == dimensions
        assert "datasetId" not in binding
    assert nodes["metric"]["props"]["decimals"] == 2
    assert nodes["breakdown"]["props"]["columnDefs"] == [
        {"field": "property_type", "headerName": property_label},
        {"field": "weighted_price_per_sqm", "headerName": captions.kpi[locale]},
    ]
