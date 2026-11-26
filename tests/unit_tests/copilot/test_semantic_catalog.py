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

"""Exercise semantic catalog clarification and native approval binding."""

import secrets
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from superset.copilot import semantic_catalog as catalog

_SECRET = secrets.token_hex(32)
_AVERAGE = "average_transaction_price"
_WEIGHTED = "weighted_price_per_sqm"


class _Provider:
    """Return approved discovery results without starting the data provider."""

    selection_identity_version = None

    def resolve_catalog_metric(
        self, phrase: str, locale: catalog.ContentLocale
    ) -> tuple[str, ...]:
        """Recognize the bounded fixture phrases in each language."""
        return {
            ("average property price", "en"): (_AVERAGE, _WEIGHTED),
            ("متوسط سعر العقار", "ar"): (_AVERAGE, _WEIGHTED),
        }.get((phrase, locale), ())


@pytest.fixture
def catalog_stubs(monkeypatch: pytest.MonkeyPatch) -> tuple[Mock, Mock]:
    """Isolate the chart query and persistence from the request contract."""
    view = SimpleNamespace(uuid=uuid4())
    metrics = {
        _AVERAGE: catalog._ApprovedMetric(
            _AVERAGE,
            {"en": "Average transaction price", "ar": "متوسط سعر المعاملة"},
            {"en": "Mean of recorded prices.", "ar": "متوسط الأسعار المسجلة."},
            "AED",
            "v1",
        ),
        _WEIGHTED: catalog._ApprovedMetric(
            _WEIGHTED,
            {"en": "Price per square meter", "ar": "السعر لكل متر مربع"},
            {
                "en": "Sum of prices divided by area.",
                "ar": "الأسعار مقسومة على المساحة.",
            },
            "AED/m²",
            "v1",
        ),
    }
    preview = Mock(return_value=(3737.7, [{"label": "Villa", "value": 2714.29}]))
    save = Mock(return_value=(17, True))
    monkeypatch.setattr(catalog, "_view_for_actor", lambda: view)
    monkeypatch.setattr(catalog, "_can_create_dashboard", lambda _: True)
    monkeypatch.setattr(catalog, "_provider_catalog", lambda *_: (_Provider(), metrics))
    monkeypatch.setattr(catalog, "_preview", preview)
    monkeypatch.setattr(catalog, "create_semantic_classic_dashboard", save)
    return preview, save


@pytest.mark.parametrize(
    ("locale", "phrase", "labels"),
    [
        (
            "en",
            "Create a dashboard for average property price",
            ["Average transaction price", "Price per square meter"],
        ),
        (
            "ar",
            "أنشئ لوحة معلومات عن متوسط سعر العقار",
            ["متوسط سعر المعاملة", "السعر لكل متر مربع"],
        ),
    ],
)
def test_clarification_does_not_preview_or_save(
    catalog_stubs: tuple[Mock, Mock], locale: str, phrase: str, labels: list[str]
) -> None:
    """Clarify a shared alias without querying or creating dashboard objects."""
    preview, save = catalog_stubs
    result = catalog.stage_semantic_dashboard(
        {"phrase": phrase, "locale": locale}, 7, _SECRET
    )
    assert result["status"] == "ambiguous"
    result_candidates = result["candidates"]
    assert isinstance(result_candidates, list)
    assert [candidate["label"] for candidate in result_candidates] == labels
    assert "approvalToken" not in result
    preview.assert_not_called()
    save.assert_not_called()


def test_approval_preserves_metric_locale_and_retry_identity(
    catalog_stubs: tuple[Mock, Mock],
) -> None:
    """Use the prepared selection and one native dashboard UUID on each retry."""
    preview, save = catalog_stubs
    draft = catalog.stage_semantic_dashboard(
        {"phrase": "متوسط سعر العقار", "locale": "ar", "metricId": _WEIGHTED},
        7,
        _SECRET,
    )
    assert draft["status"] == "draft"
    assert draft["dashboardType"] == "v1"
    assert draft["title"] == "سوق العقارات · السعر لكل متر مربع"
    assert draft["value"] == 3737.7
    preview.assert_called_once()
    save.assert_not_called()
    body = {"approvalToken": draft["approvalToken"]}
    assert catalog.approve_semantic_dashboard(body, 7, _SECRET) == (17, True, "v1")
    save.return_value = (17, False)
    assert catalog.approve_semantic_dashboard(body, 7, _SECRET) == (17, False, "v1")
    first, second = (call.args for call in save.call_args_list)
    assert first[1] == second[1] == _WEIGHTED
    assert first[2].locale == second[2].locale == "ar"
    assert first[2].dashboard["en"] == "Property Market · Price per square meter"
    assert first[3] == second[3]


def test_only_authorized_actor_can_confirm_catalog_draft(
    catalog_stubs: tuple[Mock, Mock],
) -> None:
    """Require the same actor who prepared the native chart preview."""
    _, save = catalog_stubs
    draft = catalog.stage_semantic_dashboard(
        {"phrase": "average property price", "locale": "en", "metricId": _AVERAGE},
        7,
        _SECRET,
    )
    with pytest.raises(catalog.SemanticCatalogApprovalError):
        catalog.approve_semantic_dashboard(
            {"approvalToken": draft["approvalToken"]}, 8, _SECRET
        )
    save.assert_not_called()


def test_approval_saves_the_confirmed_v2_dashboard(
    catalog_stubs: tuple[Mock, Mock], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Use the signed format and native semantic source for Dashboard V2."""
    _, classic = catalog_stubs
    v2 = Mock(return_value=(29, True))
    monkeypatch.setattr(catalog, "create_semantic_v2_dashboard", v2)
    draft = catalog.stage_semantic_dashboard(
        {
            "phrase": "متوسط سعر العقار",
            "locale": "ar",
            "metricId": _WEIGHTED,
            "dashboardType": "v2",
        },
        7,
        _SECRET,
    )
    assert draft["dashboardType"] == "v2"
    body = {"approvalToken": draft["approvalToken"]}
    assert catalog.approve_semantic_dashboard(body, 7, _SECRET) == (29, True, "v2")
    assert v2.call_args.args[1] == _WEIGHTED
    assert v2.call_args.args[2].locale == "ar"
    assert v2.call_args.kwargs == {"unit": "AED/m²", "selection_version": None}
    classic.assert_not_called()


def test_v2_feature_is_checked_before_preview_and_save(
    catalog_stubs: tuple[Mock, Mock], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Apply the current flag at each operation, including after staging."""
    preview, classic = catalog_stubs
    v2 = Mock()
    monkeypatch.setattr(catalog, "create_semantic_v2_dashboard", v2)
    formats = {"v1", "v2"}
    monkeypatch.setattr(catalog, "_can_create_dashboard", formats.__contains__)
    draft = {
        "phrase": "average property price",
        "locale": "en",
        "metricId": _AVERAGE,
        "dashboardType": "v2",
    }
    prepared = catalog.stage_semantic_dashboard(draft, 7, _SECRET)
    formats.remove("v2")
    assert catalog.semantic_catalog_dashboard_types() == ["v1"]
    preview.reset_mock()
    with pytest.raises(catalog.SemanticCatalogUnavailableError):
        catalog.stage_semantic_dashboard(draft, 7, _SECRET)
    with pytest.raises(catalog.SemanticCatalogUnavailableError):
        catalog.approve_semantic_dashboard(
            {"approvalToken": prepared["approvalToken"]}, 7, _SECRET
        )
    preview.assert_not_called()
    classic.assert_not_called()
    v2.assert_not_called()


def test_untyped_legacy_approval_remains_classic(
    catalog_stubs: tuple[Mock, Mock],
) -> None:
    """Interpret approvals issued before V2 support as Classic only."""
    _, classic = catalog_stubs
    draft = catalog.stage_semantic_dashboard(
        {"phrase": "average property price", "locale": "en", "metricId": _AVERAGE},
        7,
        _SECRET,
    )
    token = draft["approvalToken"]
    assert isinstance(token, str)
    claims = catalog.verify_claims(
        _SECRET, token, catalog._APPROVAL_AUDIENCE, catalog.APPROVAL_TTL
    )
    claims.pop("dashboard_type")
    old_token = catalog.sign_claims(_SECRET, claims)
    result = catalog.approve_semantic_dashboard(
        {"approvalToken": old_token}, 7, _SECRET
    )
    assert result == (17, True, "v1")
    classic.assert_called_once()
