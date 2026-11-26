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
from typing import Any

import jwt
import pytest
from pydantic import ValidationError

from superset.commands.dashboard_v2.save import normalize_and_validate
from superset.copilot.contracts import (
    CopilotConversation,
    DashboardProposal,
    make_document,
    percent_precision,
    ProposalMetadata,
    sign_claims,
    verify_claims,
)
from superset.copilot.services import delegated_mcp_token
from superset.dashboard_v2.document import normalize_document
from superset.dashboards.schemas import validate_json_metadata
from superset.utils import json
from superset.widgets.safety import (
    column_defs_problem,
    echarts_option_problem,
    MAX_COLUMN_TEXT_LENGTH,
)


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
    assert props["echartsOptions"]["xAxis"]["type"] == "category"
    assert props["echartsOptions"]["yAxis"]["type"] == "value"
    assert "realtimeSort" not in props["echartsOptions"]["series"][0]


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


@pytest.mark.parametrize(
    "summary",
    [
        "April had **2 sales** across the three observed months.",
        "Both comparisons include the eligible denominator and baseline. " * 9
        + "Review the individual groups before acting.",
        "🧭" * 1024,
    ],
)
def test_compound_proposal_preserves_native_bindings_and_summary(summary: str) -> None:
    payload = {
        "title": "Sales",
        "summary": summary,
        "widgets": [
            {
                "type": "ag-grid-table",
                "datasetId": 23,
                "metrics": ["count_sales", "weighted_price"],
                "dimensions": ["sale_month", "property_type"],
            }
        ],
    }
    proposal = DashboardProposal.model_validate(payload)
    widget = proposal.widgets[0]
    assert widget.metric_names == ["count_sales", "weighted_price"]
    assert widget.dimension_names == ["sale_month", "property_type"]
    assert proposal.model_dump(by_alias=True, exclude_unset=True) == payload

    nodes = normalize_and_validate(make_document(proposal))["nodes"]
    assert nodes["root"]["children"] == ["widget_1", "summary"]
    assert nodes["widget_1"]["props"]["dataBinding"] == {
        "datasetId": 23,
        "dimensions": ["sale_month", "property_type"],
        "metrics": ["count_sales", "weighted_price"],
        "orderByDimension": True,
        "rowLimit": 100,
    }
    assert nodes["summary"]["type"] == "markdown"
    assert nodes["summary"]["props"] == {"content": summary}


def test_compound_table_headers_obey_native_column_rules() -> None:
    proposal = DashboardProposal.model_validate(
        {
            "title": "Sales",
            "widgets": [
                {
                    "type": "ag-grid-table",
                    "datasetId": 23,
                    "metrics": ["count_sales", "weighted_price"],
                    "dimensions": ["sale_month"],
                }
            ],
        }
    )
    long_label = "A" * (MAX_COLUMN_TEXT_LENGTH + 1)
    metadata = ProposalMetadata(
        dimension_labels={(23, "sale_month"): "<b>Sale month</b>"},
        metric_labels={
            (23, "count_sales"): long_label,
            (23, "weighted_price"): "Price",
        },
    )

    columns = make_document(proposal, metadata)["nodes"]["widget_1"]["props"][
        "columnDefs"
    ]
    assert column_defs_problem(columns) is None
    headers = [
        {key: column[key] for key in ("field", "headerName")} for column in columns
    ]
    assert headers == [
        {"field": "sale_month", "headerName": "sale_month"},
        {"field": "count_sales", "headerName": long_label[:MAX_COLUMN_TEXT_LENGTH]},
        {"field": "weighted_price", "headerName": "Price"},
    ]
    assert columns[0]["minWidth"] > columns[1]["minWidth"]
    assert columns[0]["flex"] > columns[1]["flex"]
    assert columns[0]["wrapText"]
    assert columns[0]["autoHeight"]
    assert all(
        column["wrapHeaderText"] and column["autoHeaderHeight"] for column in columns
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"metric": "count_sales"},
        {"dimension": None},
        {"type": "metric-tile"},
        {"type": "echarts"},
        {"metrics": []},
        {"metrics": ["count_sales"] * 7},
        {"metrics": ["count_sales", "count_sales"]},
        {"metrics": ["sale_month"]},
        {"metrics": [{"expressionType": "SQL"}]},
        {"dimensions": ["sale_month"] * 5},
        {"dimensions": ["sale_month", "sale_month"]},
        {"dimensions": None},
    ],
)
def test_compound_proposal_rejects_ambiguous_or_invalid_bindings(
    changes: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        DashboardProposal.model_validate(
            {
                "title": "Sales",
                "widgets": [
                    {
                        "type": "ag-grid-table",
                        "datasetId": 23,
                        "metrics": ["count_sales"],
                        "dimensions": ["sale_month"],
                        **changes,
                    }
                ],
            }
        )


def test_summary_and_compound_table_are_v2_only() -> None:
    widget = {
        "type": "ag-grid-table",
        "datasetId": 23,
        "metrics": ["count_sales"],
        "dimensions": [],
    }
    proposal = DashboardProposal.model_validate({"title": "Sales", "widgets": [widget]})
    binding = make_document(proposal)["nodes"]["widget_1"]["props"]["dataBinding"]
    assert binding["dimensions"] == []
    assert "orderByDimension" not in binding

    for extra in (
        {"dashboardType": "v1", "widgets": [widget]},
        {
            "dashboardType": "v1",
            "summary": "April sales",
            "widgets": [
                {"type": "metric-tile", "datasetId": 23, "metric": "count_sales"}
            ],
        },
        {"summary": "🧭" * 1025},
        {"summary": "  "},
        {
            "widgets": [
                {key: value for key, value in widget.items() if key != "dimensions"}
            ]
        },
    ):
        with pytest.raises(ValidationError):
            DashboardProposal.model_validate(
                {"title": "Sales", "widgets": [widget], **extra}
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
    metadata = ProposalMetadata(metric_formats={(23, "female_share"): ".1%"})
    nodes = make_document(proposal, metadata)["nodes"]
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
    assert "orderByMetric" not in trend_props["dataBinding"]
    assert trend_props["echartsOptions"]["xAxis"]["data"]["$bind"]["format"] == "date"
    series = trend_props["echartsOptions"]["series"][0]
    assert (series["type"], series["smooth"], series["connectNulls"]) == (
        "line",
        False,
        False,
    )
    assert series["showSymbol"]
    assert series["symbolSize"] > 0
    assert percent_precision(".1%") == 1
    assert percent_precision("%") == 0
    assert percent_precision(",.0f") is None


def test_analytical_dashboard_pairs_ranked_charts_in_proposal_order() -> None:
    table = {
        "type": "ag-grid-table",
        "datasetId": 23,
        "metrics": ["mean_price", "weighted_price"],
        "dimensions": ["property_type"],
    }
    kpi = {"type": "metric-tile", "datasetId": 23, "metric": "mean_price"}
    chart = {
        "type": "echarts",
        "datasetId": 23,
        "metric": "weighted_price",
        "dimension": "property_type",
        "chartStyle": "ranked-bar",
        "title": "Weighted price by property type",
    }
    proposal = DashboardProposal.model_validate(
        {
            "title": "Property prices",
            "widgets": [table, kpi, chart, {**chart, "metric": "mean_price"}],
            "summary": "The property types rank differently across the two measures.",
        }
    )
    metadata = ProposalMetadata(
        metric_formats={(23, "weighted_price"): ",.2f"},
        metric_labels={(23, "weighted_price"): "Area-weighted price (AED/m²)"},
    )

    nodes = make_document(proposal, metadata)["nodes"]
    assert nodes["root"]["children"] == [
        "widget_1",
        "widget_2",
        "summary",
        "widget_3",
        "widget_4",
    ]
    assert nodes["widget_3"]["layout"] == nodes["widget_4"]["layout"]
    assert nodes["widget_3"]["layout"]["colSpan"] == 12
    props = nodes["widget_3"]["props"]
    assert props["dataBinding"]["rowLimit"] == 12
    assert props["dataBinding"]["orderByMetric"] is True
    assert "orderByDimension" not in props["dataBinding"]
    assert props["crossFilter"] is True
    options = props["echartsOptions"]
    assert echarts_option_problem(options) is None
    assert options["title"]["text"] == "Weighted price by property type · Top 12"
    assert options["xAxis"]["type"] == "value"
    assert options["xAxis"]["minInterval"] == 0.01
    assert options["yAxis"]["type"] == "category"
    assert options["yAxis"]["inverse"] is True
    assert options["yAxis"]["data"] == {
        "$bind": {"source": "dimension", "alias": "property_type"}
    }
    assert options["series"][0]["realtimeSort"] is True
    assert options["series"][0]["name"] == "Area-weighted price (AED/m²)"
    assert options["series"][0]["data"] == {
        "$bind": {"source": "metric", "alias": "weighted_price"}
    }


def test_ranked_rate_and_numeric_table_formats_follow_saved_metadata() -> None:
    proposal = DashboardProposal.model_validate(
        {
            "title": "طلبات الخدمة",
            "contentLocale": "ar",
            "widgets": [
                {
                    "type": "echarts",
                    "datasetId": 23,
                    "metric": "rate",
                    "dimension": "service",
                    "chartStyle": "ranked-bar",
                    "title": "نسبة الطلبات حسب الخدمة",
                    "titleTranslations": {"en": "Request rate by service"},
                },
                {
                    "type": "ag-grid-table",
                    "datasetId": 23,
                    "metrics": ["rate", "amount", "count", "unknown"],
                    "dimensions": ["service"],
                },
            ],
        }
    )
    metadata = ProposalMetadata(
        metric_formats={
            (23, "rate"): ".1%",
            (23, "amount"): ",.2f",
            (23, "count"): ",d",
            (23, "unknown"): ".99%",
        }
    )

    nodes = make_document(proposal, metadata)["nodes"]
    options = nodes["widget_1"]["props"]["echartsOptions"]
    assert echarts_option_problem(options) is None
    assert options["title"]["text"] == "نسبة الطلبات حسب الخدمة · أعلى ١٢"
    assert options["xAxis"]["axisLabel"]["formatter"] == "{value}٪"
    assert options["tooltip"]["formatter"] == "{b0}: {c0}٪"
    assert options["series"][0]["data"]["$bind"]["format"] == "percent"
    translations = nodes["root"]["props"]["nxtbiLocalization"]["widgets"]["widget_1"]
    assert translations["source"] == options["title"]["text"]
    assert translations["translations"]["en"] == "Request rate by service · Top 12"

    columns = nodes["widget_2"]["props"]["columnDefs"]
    assert column_defs_problem(columns) is None
    assert [(c.get("valueFormat"), c.get("valueFormatPrecision")) for c in columns] == [
        (None, None),
        ("percent", 1),
        ("decimal", 2),
        ("decimal", 0),
        (None, None),
    ]
    assert column_defs_problem([{**columns[1], "valueFormatPrecision": 1.5}])
    assert column_defs_problem([{**columns[1], "valueFormatPrecision": 11}])


def test_chart_layout_keeps_separated_charts_and_legacy_bar_behavior() -> None:
    chart = {
        "type": "echarts",
        "datasetId": 23,
        "metric": "mean_price",
        "dimension": "property_type",
        "chartStyle": "bar",
    }
    table = {"type": "ag-grid-table", "datasetId": 23, "metric": "mean_price"}
    payload = {
        "title": "Property prices",
        "widgets": [chart, table, chart, chart, chart],
        "summary": "Property prices by category",
    }
    nodes = make_document(DashboardProposal.model_validate(payload))["nodes"]
    assert nodes["root"]["children"] == [
        "summary",
        "widget_1",
        "widget_2",
        "widget_3",
        "widget_4",
        "widget_5",
    ]
    assert [
        nodes[f"widget_{index}"]["layout"]["colSpan"] for index in (1, 3, 4, 5)
    ] == [
        24,
        12,
        12,
        24,
    ]
    props = nodes["widget_1"]["props"]
    assert props["dataBinding"]["rowLimit"] == 100
    assert "orderByMetric" not in props["dataBinding"]
    assert props["echartsOptions"]["yAxis"] == {"type": "value"}

    classic = {"title": "Property prices", "dashboardType": "v1", "widgets": [chart]}
    assert DashboardProposal.model_validate(classic).widgets[0].chart_style == "bar"
    with pytest.raises(ValidationError, match="ranked charts require Dashboard V2"):
        DashboardProposal.model_validate(
            {**classic, "widgets": [{**chart, "chartStyle": "ranked-bar"}]}
        )


@pytest.mark.parametrize(("locale", "percent_sign"), [("en", "%"), ("ar", "٪")])
def test_vertical_bar_formats_saved_rates(locale: str, percent_sign: str) -> None:
    proposal = DashboardProposal.model_validate(
        {
            "title": "Service rates",
            "contentLocale": locale,
            "widgets": [
                {
                    "type": "echarts",
                    "datasetId": 23,
                    "metric": "delay_rate",
                    "dimension": "service",
                    "chartStyle": "bar",
                    "title": "Delay rate by service",
                }
            ],
        }
    )
    metadata = ProposalMetadata(metric_formats={(23, "delay_rate"): ".1%"})

    props = make_document(proposal, metadata)["nodes"]["widget_1"]["props"]
    assert props["dataBinding"]["rowLimit"] == 100
    assert "orderByMetric" not in props["dataBinding"]
    options = props["echartsOptions"]
    assert echarts_option_problem(options) is None
    assert options["title"]["text"] == "Delay rate by service"
    assert options["xAxis"]["type"] == "category"
    assert options["yAxis"] == {
        "type": "value",
        "axisLabel": {"formatter": f"{{value}}{percent_sign}"},
        "minInterval": 0.1,
    }
    assert options["tooltip"]["formatter"] == f"{{b0}}: {{c0}}{percent_sign}"
    assert options["series"][0]["data"]["$bind"]["format"] == "percent"


@pytest.mark.parametrize("locale", ["en", "ar"])
def test_rate_chart_queries_denominator_without_plotting_it(locale: str) -> None:
    cutoff = {"denominatorMetric": "eligible_reviews", "minimumSampleSize": 50}
    proposal = DashboardProposal.model_validate(
        {
            "title": "Permit reviews",
            "contentLocale": locale,
            "widgets": [
                {
                    "type": "echarts",
                    "datasetId": 23,
                    "metric": "late_rate",
                    "dimension": "site",
                    "chartStyle": "ranked-bar",
                    "filter": {"column": "status", "value": "Closed"},
                    "rateCutoff": cutoff,
                }
            ],
        }
    )
    metadata = ProposalMetadata(metric_formats={(23, "late_rate"): ".1%"})

    document, _ = normalize_document(make_document(proposal, metadata))
    props = document["nodes"]["widget_1"]["props"]
    assert props["rateCutoff"] == {
        **cutoff,
        "scope": {"datasetId": 23, "rateMetric": "late_rate", "dimension": "site"},
    }
    assert proposal.model_dump(by_alias=True)["widgets"][0]["rateCutoff"] == cutoff
    binding = props["dataBinding"]
    assert binding["metrics"] == ["late_rate", "eligible_reviews"]
    assert binding["dimensions"] == ["site"]
    assert binding["filters"][0]["comparator"] == "Closed"
    assert binding["orderByMetric"] is True
    assert [series["data"] for series in props["echartsOptions"]["series"]] == [
        {"$bind": {"source": "metric", "alias": "late_rate", "format": "percent"}}
    ]


@pytest.mark.parametrize(
    ("widget_fields", "dashboard_type", "error"),
    [
        ({"type": "metric-tile"}, "v2", "only available on charts"),
        ({"dimension": "eligible_reviews"}, "v2", "distinct denominator"),
        ({"metric": "eligible_reviews"}, "v2", "distinct denominator"),
        ({"metric": "site"}, "v2", "distinct rate metric"),
        ({}, "v1", "Rate cutoffs require Dashboard V2"),
    ],
)
def test_rate_cutoff_requires_distinct_v2_chart_bindings(
    widget_fields: dict[str, Any], dashboard_type: str, error: str
) -> None:
    with pytest.raises(ValidationError, match=error):
        DashboardProposal.model_validate(
            {
                "title": "Permit reviews",
                "dashboardType": dashboard_type,
                "widgets": [
                    {
                        "type": "echarts",
                        "datasetId": 23,
                        "metric": "late_rate",
                        "dimension": "site",
                        "rateCutoff": {
                            "denominatorMetric": "eligible_reviews",
                            "minimumSampleSize": 50,
                        },
                        **widget_fields,
                    }
                ],
            }
        )


@pytest.mark.parametrize("minimum", [True, 0, -1, 1.5, "50", 2**31])
def test_cutoff_requires_a_bounded_positive_integer(minimum: object) -> None:
    with pytest.raises(ValidationError, match="minimumSampleSize"):
        DashboardProposal.model_validate(
            {
                "title": "Permit reviews",
                "widgets": [
                    {
                        "type": "echarts",
                        "datasetId": 23,
                        "metric": "late_rate",
                        "dimension": "site",
                        "rateCutoff": {
                            "denominatorMetric": "eligible_reviews",
                            "minimumSampleSize": minimum,
                        },
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


def test_localization_captions_survive_v2_document_normalization() -> None:
    """The document keeps translated captions separate from chart bindings."""
    proposal = DashboardProposal.model_validate(
        {
            "title": "Revenue",
            "contentLocale": "en",
            "titleTranslations": {"ar": "الإيرادات"},
            "widgets": [
                {
                    "type": "metric-tile",
                    "datasetId": 23,
                    "metric": "sum_revenue",
                    "title": "Total revenue",
                    "titleTranslations": {"ar": "إجمالي الإيرادات"},
                }
            ],
        }
    )
    document, _widgets = normalize_document(make_document(proposal))
    assert document["nodes"]["root"]["props"]["nxtbiLocalization"] == {
        "sourceLocale": "en",
        "title": {"source": "Revenue", "translations": {"ar": "الإيرادات"}},
        "widgets": {
            "widget_1": {
                "source": "Total revenue",
                "translations": {"ar": "إجمالي الإيرادات"},
            }
        },
    }
    assert document["nodes"]["widget_1"]["props"]["dataBinding"]["metrics"] == [
        "sum_revenue"
    ]


def test_classic_edit_accepts_localization_metadata() -> None:
    """Classic editors can save a generated dashboard with localized captions."""
    validate_json_metadata(
        json.dumps(
            {
                "nxtbi_localization": {
                    "sourceLocale": "ar",
                    "title": {"source": "الإيرادات", "translations": {"en": "Revenue"}},
                    "widgets": {
                        "42": {"source": "الإيرادات", "translations": {"en": "Revenue"}}
                    },
                },
            }
        )
    )
