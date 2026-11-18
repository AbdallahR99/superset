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

import secrets

import jwt
import pytest
from pydantic import ValidationError

from superset.copilot.contracts import (
    CopilotConversation,
    DashboardProposal,
    make_document,
    percent_precision,
    sign_claims,
    verify_claims,
)
from superset.copilot.services import delegated_mcp_token


def test_run_claims_are_bound_to_the_type_and_time() -> None:
    secret = secrets.token_hex(32)
    token = sign_claims(secret, {"sub": "7", "aud": "nxtbi-copilot", "exp": 140})

    assert verify_claims(secret, token, "nxtbi-copilot", 60, now=100)["sub"] == "7"
    for invalid, audience, now in (
        (token + "a", "nxtbi-copilot", 100),
        (token, "nxtbi-dashboard-approval", 100),
        (token, "nxtbi-copilot", 140),
        (token, "nxtbi-copilot", 79),
    ):
        with pytest.raises(ValueError, match="Invalid Copilot capability"):
            verify_claims(secret, invalid, audience, 60, now=now)


def test_history_accepts_only_chat_text_and_matching_dashboard_reference() -> None:
    transcript = {
        "threadId": "thread-1",
        "messages": [{"id": "m-1", "role": "user", "content": "Show sales"}],
        "updatedAt": "2026-11-18T09:00:00.000Z",
        "savedDashboard": {"id": 8, "url": "/dashboard/v2/8/"},
    }
    assert (
        CopilotConversation.model_validate(transcript).model_dump(by_alias=True)
        == transcript
    )

    for unsafe in (
        {**transcript, "approvalToken": "expired"},
        {**transcript, "messages": [{"id": "m-1", "role": "tool", "content": "data"}]},
        {**transcript, "savedDashboard": {"id": 8, "url": "/dashboard/v2/9/"}},
    ):
        with pytest.raises(ValidationError):
            CopilotConversation.model_validate(unsafe)


def test_proposal_compiles_only_registered_data_references() -> None:
    proposal = DashboardProposal.model_validate(
        {
            "title": "My dashboard",
            "widgets": [
                {
                    "type": "echarts",
                    "datasetId": 17,
                    "metric": "purchase_total",
                    "dimension": "channel",
                }
            ],
        }
    )
    document = make_document(proposal).copy()
    assert document["nodes"]["root"]["children"] == ["widget_1"]
    props = document["nodes"]["widget_1"]["props"]
    assert props["dataBinding"] == {
        "datasetId": 17,
        "dimensions": ["channel"],
        "metrics": ["purchase_total"],
        "rowLimit": 100,
    }
    assert props["echartsOptions"]["series"][0]["data"]["$bind"]["alias"] == (
        "purchase_total"
    )


def test_proposal_rejects_undeclared_fields() -> None:
    with pytest.raises(ValidationError):
        DashboardProposal.model_validate(
            {
                "title": "My dashboard",
                "widgets": [
                    {
                        "type": "metric-tile",
                        "datasetId": 17,
                        "metric": "purchase_total",
                        "options": {"unexpected": True},
                    }
                ],
            }
        )


def test_proposal_preserves_snapshot_filters_percentages_and_trend_order() -> None:
    kpis = [
        {
            "type": "metric-tile",
            "datasetId": 23,
            "metric": metric,
            "filter": {"column": "census_year", "value": 2026},
        }
        for metric in (
            "population_total",
            "female_share",
            "youth_share",
            "senior_share",
        )
    ]
    trend = {
        "type": "echarts",
        "datasetId": 23,
        "metric": "population_total",
        "dimension": "year_date",
        "chartStyle": "line",
    }
    proposal = DashboardProposal.model_validate(
        {"title": "Population", "widgets": [*kpis, trend]}
    )
    nodes = make_document(proposal, {(23, "female_share"): 1})["nodes"]
    assert [nodes[f"widget_{index}"]["layout"]["colSpan"] for index in range(1, 5)] == [
        6
    ] * 4
    props = nodes["widget_2"]["props"]
    assert props["dataBinding"]["filters"] == [
        {
            "expressionType": "SIMPLE",
            "clause": "WHERE",
            "subject": "census_year",
            "operator": "==",
            "comparator": 2026,
        }
    ]
    assert (props["percentage"], props["decimals"]) == (True, 1)
    trend_props = nodes["widget_5"]["props"]
    assert trend_props["dataBinding"]["orderByDimension"] is True
    assert trend_props["echartsOptions"]["xAxis"]["data"]["$bind"]["format"] == "date"
    assert trend_props["echartsOptions"]["series"][0]["type"] == "line"
    assert percent_precision(".1%") == 1
    assert percent_precision("%") == 0
    assert percent_precision(",.0f") is None


def test_mcp_delegation_is_read_only_and_user_scoped() -> None:
    secret = secrets.token_hex(32)
    token = delegated_mcp_token(
        "editor@example.invalid",
        {
            "MCP_AUTH_ENABLED": True,
            "MCP_JWT_ALGORITHM": "HS256",
            "MCP_JWT_SECRET": secret,
            "MCP_JWT_ISSUER": "local-test",
            "MCP_JWT_AUDIENCE": "superset-mcp-test",
        },
    )
    claims = jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        audience="superset-mcp-test",
        issuer="local-test",
    )
    assert claims["sub"] == "editor@example.invalid"
    assert claims["scope"] == "superset:read"
    assert claims["exp"] - claims["iat"] == 30
