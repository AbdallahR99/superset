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
    DashboardProposal,
    make_document,
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
