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

"""Resolve and confirm draft dashboards for the isolated semantic catalog."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID, uuid4

from flask import current_app
from marshmallow import ValidationError as ChartQueryValidationError
from pydantic import Field
from superset_core.semantic_layers.types import Metric
from superset_core.semantic_layers.view import SemanticView as ProviderView

from superset import db, is_feature_enabled, security_manager
from superset.charts.schemas import ChartDataQueryContextSchema
from superset.commands.chart.data.get_data_command import ChartDataCommand
from superset.commands.exceptions import CommandException
from superset.common.query_context_factory import QueryContextFactory
from superset.copilot.contracts import (
    APPROVAL_TTL,
    ContentLocale,
    Contract,
    ShortText,
    sign_claims,
    verify_claims,
)
from superset.copilot.semantic_classic import (
    BREAKDOWN_DIMENSION,
    create_semantic_classic_dashboard,
    SemanticClassicCaptions,
)
from superset.copilot.semantic_v2 import create_semantic_v2_dashboard
from superset.daos.semantic_layer import SemanticViewDAO
from superset.exceptions import QueryObjectValidationError, SupersetSecurityException
from superset.mcp_service.privacy import user_can_view_data_model_metadata
from superset.semantic_layers.access import is_semantic_layers_enabled
from superset.semantic_layers.exceptions import (
    discover_metrics,
    DiscoveryTarget,
    SemanticLayerExecutionError,
    SemanticLayerQueryRejectedError,
)
from superset.semantic_layers.models import SemanticLayer, SemanticView
from superset.semantic_layers.registry import registry

SemanticDashboardType = Literal["v1", "v2"]

_PROVIDER = "extensions.nxtbi.property-market-lab.market"
_VIEW_NAME = "property_transactions"
_APPROVAL_AUDIENCE = "nxtbi-semantic-lab-approval"
_DASHBOARD_PREFIXES = (
    "create a dashboard for ",
    "أنشئ لوحة معلومات عن ",
)


class SemanticCatalogUnavailableError(ValueError):
    """The active actor cannot use the configured lab view."""


class SemanticCatalogApprovalError(ValueError):
    """The supplied approval does not authorize this actor and current view."""


class SemanticCatalogPreviewError(ValueError):
    """The catalog or native chart query did not return an approved result."""


class _DraftRequest(Contract):
    """Accept a bounded phrase and optional follow-up selection."""

    phrase: ShortText
    locale: ContentLocale
    metric_id: ShortText | None = Field(default=None, alias="metricId")
    dashboard_type: SemanticDashboardType = Field(default="v1", alias="dashboardType")


class _ApprovalRequest(Contract):
    """Accept only the server-issued capability from the preview."""

    approval_token: str = Field(alias="approvalToken", min_length=10, max_length=2048)


@runtime_checkable
class _CatalogResolver(Protocol):
    """The read-only resolver supplied by the lab semantic provider."""

    def resolve_catalog_metric(
        self, phrase: str, locale: ContentLocale
    ) -> tuple[str, ...]:
        """Return stable approved metric names matching the input phrase."""


@dataclass(frozen=True)
class _ApprovedMetric:
    """Validated bilingual metadata for one existing semantic metric."""

    name: str
    labels: dict[ContentLocale, str]
    definitions: dict[ContentLocale, str]
    unit: str
    version: str

    def candidate(self, locale: ContentLocale) -> dict[str, str]:
        """Return localized, public display fields for one candidate."""
        return {
            "metricId": self.name,
            "label": self.labels[locale],
            "definition": self.definitions[locale],
            "unit": self.unit,
        }

    def captions(self, locale: ContentLocale) -> SemanticClassicCaptions:
        """Build fixed bilingual captions from the approved metric labels."""
        english = self.labels["en"]
        arabic = self.labels["ar"]
        return SemanticClassicCaptions(
            locale=locale,
            dashboard={
                "en": f"Property Market · {english}",
                "ar": f"سوق العقارات · {arabic}",
            },
            kpi=self.labels,
            breakdown={
                "en": f"{english} by property type",
                "ar": f"{arabic} حسب نوع العقار",
            },
        )


def _view_for_actor() -> SemanticView:
    """Resolve one registered lab view through native grants before discovery."""
    if not (
        current_app.config.get("NXTBI_COPILOT_SEMANTIC_LAB") is True
        and is_semantic_layers_enabled()
        and _PROVIDER in registry
        and not security_manager.is_guest_user()
        and user_can_view_data_model_metadata()
        and security_manager.can_access("can_read", "Chart")
        and security_manager.can_access("can_read", "Dashboard")
        and security_manager.can_access("can_write", "Dashboard")
    ):
        raise SemanticCatalogUnavailableError
    query = (
        db.session.query(SemanticView)
        .join(SemanticLayer)
        .filter(SemanticView.name == _VIEW_NAME, SemanticLayer.type == _PROVIDER)
    )
    views = SemanticViewDAO.apply_access_filter(query).limit(2).all()
    if len(views) != 1:
        raise SemanticCatalogUnavailableError
    view = views[0]
    try:
        view.raise_for_access()
    except SupersetSecurityException as ex:
        raise SemanticCatalogUnavailableError from ex
    return view


def _can_create_dashboard(dashboard_type: SemanticDashboardType) -> bool:
    """Apply the authoring permission specific to the selected format."""
    if dashboard_type == "v2":
        return is_feature_enabled("DASHBOARD_V2")
    return security_manager.can_access("can_write", "Chart")


def semantic_catalog_dashboard_types() -> list[SemanticDashboardType]:
    """List the formats this actor can draft from the approved lab view."""
    try:
        _view_for_actor()
    except SemanticCatalogUnavailableError:
        return []
    formats: tuple[SemanticDashboardType, ...] = ("v1", "v2")
    return [
        dashboard_type
        for dashboard_type in formats
        if _can_create_dashboard(dashboard_type)
    ]


def _catalog_text(value: object) -> str:
    """Check a bounded provider label or description before displaying it."""
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise SemanticCatalogPreviewError
    return value


def _approved_metric(metric: Metric) -> _ApprovedMetric:
    """Read approved display metadata from a native semantic metric."""
    metadata = metric.metadata
    return _ApprovedMetric(
        name=metric.name,
        labels={
            "en": _catalog_text(metric.verbose_name),
            "ar": _catalog_text(metadata.get("label_ar")),
        },
        definitions={
            "en": _catalog_text(metric.description),
            "ar": _catalog_text(metadata.get("definition_ar")),
        },
        unit=_catalog_text(metadata.get("unit")),
        version=_catalog_text(metadata.get("model_version")),
    )


def _provider_catalog(
    view: SemanticView,
) -> tuple[ProviderView, dict[str, _ApprovedMetric]]:
    """Load metric definitions using the host's guarded provider discovery."""
    try:
        metrics = discover_metrics(
            lambda: view.implementation, DiscoveryTarget.of(view)
        )
        provider = view.implementation
    except SemanticLayerExecutionError:
        raise SemanticCatalogPreviewError from None
    return provider, {metric.name: _approved_metric(metric) for metric in metrics}


def _matching_metrics(
    provider: ProviderView,
    metrics: dict[str, _ApprovedMetric],
    draft: _DraftRequest,
) -> list[_ApprovedMetric]:
    """Resolve approved names through the bilingual lab catalog."""
    if not isinstance(provider, _CatalogResolver):
        raise SemanticCatalogUnavailableError
    phrase = draft.phrase
    for prefix in _DASHBOARD_PREFIXES:
        if phrase.casefold().startswith(prefix):
            phrase = phrase[len(prefix) :].strip()
            break
    names = provider.resolve_catalog_metric(phrase, draft.locale)
    if not all(name in metrics for name in names):
        raise SemanticCatalogPreviewError
    if draft.metric_id is not None:
        if draft.metric_id not in names:
            raise ValueError("Choose one of the approved candidate metrics.")
        return [metrics[draft.metric_id]]
    return [metrics[name] for name in names]


def _preview_value(value: object) -> int | float | None:
    """Validate finite numeric values before strict JSON serialization."""
    if value is None or type(value) is int:
        return value
    if type(value) is float and isfinite(value):
        return value
    raise SemanticCatalogPreviewError


def _preview(
    view: SemanticView,
    metric: _ApprovedMetric,
    selection_version: str | None,
) -> tuple[int | float | None, list[dict[str, object]]]:
    """Run the approved KPI and property-type grouping with native chart access."""
    extras = (
        {"semantic_selection_version": selection_version} if selection_version else {}
    )
    schema = ChartDataQueryContextSchema()
    schema.query_context_factory = QueryContextFactory(
        authorize_semantic_before_metadata=True
    )
    try:
        context = schema.load(
            {
                "datasource": {"id": view.id, "type": "semantic_view"},
                "queries": [
                    {
                        "metrics": [metric.name],
                        "columns": [],
                        "row_limit": 1,
                        "extras": extras,
                    },
                    {
                        "metrics": [metric.name],
                        "columns": [BREAKDOWN_DIMENSION],
                        "row_limit": 20,
                        "extras": extras,
                    },
                ],
                "form_data": {"viz_type": "table", "query_mode": "aggregate"},
                "result_format": "json",
                "result_type": "results",
                "force": True,
            }
        )
        command = ChartDataCommand(context)
        command.validate()
        queries = command.run()["queries"]
    except (
        ChartQueryValidationError,
        CommandException,
        QueryObjectValidationError,
        SemanticLayerExecutionError,
        SemanticLayerQueryRejectedError,
    ):
        raise SemanticCatalogPreviewError from None
    if len(queries) != 2:
        raise SemanticCatalogPreviewError
    aggregate = queries[0].get("data")
    breakdown = queries[1].get("data")
    if not (
        isinstance(aggregate, list)
        and len(aggregate) == 1
        and isinstance(aggregate[0], dict)
        and metric.name in aggregate[0]
        and isinstance(breakdown, list)
        and breakdown
    ):
        raise SemanticCatalogPreviewError
    rows: list[dict[str, object]] = []
    for row in breakdown:
        if not isinstance(row, dict) or metric.name not in row:
            raise SemanticCatalogPreviewError
        rows.append(
            {
                "label": _catalog_text(row.get(BREAKDOWN_DIMENSION)),
                "value": _preview_value(row[metric.name]),
            }
        )
    return _preview_value(aggregate[0][metric.name]), rows


def stage_semantic_dashboard(
    body: Mapping[str, object], actor_id: int, secret: str
) -> dict[str, object]:
    """Clarify an ambiguous request or prepare a read-only native draft."""
    view = _view_for_actor()
    draft = _DraftRequest.model_validate(body)
    if not _can_create_dashboard(draft.dashboard_type):
        raise SemanticCatalogUnavailableError
    provider, metrics = _provider_catalog(view)
    matched = _matching_metrics(provider, metrics, draft)
    if len(matched) != 1:
        return {
            "status": "ambiguous" if matched else "unmatched",
            "candidates": [metric.candidate(draft.locale) for metric in matched],
        }
    metric = matched[0]
    selection_version = provider.selection_identity_version
    value, rows = _preview(view, metric, selection_version)
    token = sign_claims(
        secret,
        {
            "aud": _APPROVAL_AUDIENCE,
            "sub": str(actor_id),
            "exp": int(time.time()) + APPROVAL_TTL,
            "uuid": str(uuid4()),
            "view": str(view.uuid),
            "metric": metric.name,
            "locale": draft.locale,
            "dashboard_type": draft.dashboard_type,
            "version": metric.version,
            "selection": selection_version,
        },
    )
    return {
        "status": "draft",
        "dashboardType": draft.dashboard_type,
        "metric": metric.candidate(draft.locale),
        "title": metric.captions(draft.locale).dashboard[draft.locale],
        "value": value,
        "rows": rows,
        "approvalToken": token,
    }


def approve_semantic_dashboard(
    body: Mapping[str, object], actor_id: int, secret: str
) -> tuple[int, bool, SemanticDashboardType]:
    """Reauthorize the view and persist the exact confirmed semantic selection."""
    view = _view_for_actor()
    approval = _ApprovalRequest.model_validate(body)
    try:
        claims = verify_claims(
            secret, approval.approval_token, _APPROVAL_AUDIENCE, APPROVAL_TTL
        )
        if claims["sub"] != str(actor_id) or claims.get("view") != str(view.uuid):
            raise ValueError
        approval_uuid = UUID(claims["uuid"])
        locale = claims.get("locale")
        name = claims.get("metric")
        # Approvals issued before V2 support always saved a Classic dashboard.
        dashboard_type = claims.get("dashboard_type", "v1")
        if (
            locale not in ("en", "ar")
            or dashboard_type not in ("v1", "v2")
            or not isinstance(name, str)
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError) as ex:
        raise SemanticCatalogApprovalError from ex
    if not _can_create_dashboard(dashboard_type):
        raise SemanticCatalogUnavailableError
    provider, metrics = _provider_catalog(view)
    metric = metrics.get(name)
    if (
        metric is None
        or metric.version != claims.get("version")
        or provider.selection_identity_version != claims.get("selection")
    ):
        raise SemanticCatalogApprovalError
    captions = metric.captions(locale)
    if dashboard_type == "v2":
        dashboard_id, created = create_semantic_v2_dashboard(
            view,
            metric.name,
            captions,
            approval_uuid,
            unit=metric.unit,
            selection_version=provider.selection_identity_version,
        )
    else:
        dashboard_id, created = create_semantic_classic_dashboard(
            view, metric.name, captions, approval_uuid
        )
    return dashboard_id, created, dashboard_type
