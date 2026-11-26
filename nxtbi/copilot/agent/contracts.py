# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Validate the gateway's signed run claims and text-only browser input."""

from __future__ import annotations

import base64
import binascii
import hmac
import json  # noqa: TID251 - The standalone service has no Superset runtime.
import re
import time
from typing import Annotated, Literal

from ag_ui.core import AssistantMessage, RunAgentInput, UserMessage
from pydantic import BaseModel, ConfigDict, Field, model_validator, StringConstraints

MAX_BODY_BYTES = 64_000
MAX_MESSAGE_COUNT = 40
MAX_MESSAGE_LENGTH = 8_000
MAX_HISTORY_LENGTH = 32_000
MAX_TOKEN_AGE = 300
NONEMPTY_ID = Annotated[str, Field(min_length=1, max_length=200)]
POSITIVE_ID = Annotated[int, Field(gt=0, le=2_147_483_647)]
LABEL = Annotated[str, Field(min_length=1, max_length=160)]
ContentLocale = Literal["en", "ar"]
DashboardType = Literal["v1", "v2"]
Caption = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)
]
CaptionText = Annotated[str, StringConstraints(max_length=256)]
CaptionList = Annotated[list[CaptionText | None], Field(min_length=1, max_length=9)]
DatasetFieldId = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]
DashboardSummary = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)
]


class GatewayClaims(BaseModel):
    """Host authority is signed by the server-side gateway."""

    model_config = ConfigDict(strict=True, extra="forbid")

    sub: NONEMPTY_ID
    aud: Literal["nxtbi-copilot"]
    host: Literal["superset", "standalone"]
    exp: int
    run_id: NONEMPTY_ID
    thread_id: NONEMPTY_ID


class DatasetFilter(BaseModel):
    """An exact match on a verified dataset field."""

    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)

    column: LABEL
    value: LABEL | int | float | bool


class TitleTranslations(BaseModel):
    """Author-facing captions with no data-binding or layout fields."""

    model_config = ConfigDict(strict=True, extra="forbid")
    en: Caption | None = None
    ar: Caption | None = None

    def for_locale(self, locale: ContentLocale) -> str | None:
        """Choose the requested caption when supplied."""
        return self.ar if locale == "ar" else self.en


class WidgetDraft(BaseModel):
    """A dashboard widget that can be proposed for a separate approval."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["metric-tile", "ag-grid-table", "echarts"]
    dataset_id: Annotated[
        int, Field(alias="datasetId", strict=True, gt=0, le=2_147_483_647)
    ]
    metric: LABEL | None = None
    dimension: LABEL | None = None
    metrics: list[DatasetFieldId] | None = Field(
        default=None, min_length=1, max_length=6
    )
    dimensions: list[DatasetFieldId] | None = Field(default=None, max_length=4)
    chart_style: Literal["bar", "line"] | None = Field(default=None, alias="chartStyle")
    filter: DatasetFilter | None = None
    title: LABEL | None = None
    title_translations: TitleTranslations | None = Field(
        default=None, alias="titleTranslations"
    )

    @model_validator(mode="after")
    def validate_bindings(self) -> WidgetDraft:
        """Allow one scalar measure or a complete grouped table binding."""
        if self.chart_style is not None and self.type != "echarts":
            raise ValueError("chartStyle requires an echarts widget.")
        if not ({"metrics", "dimensions"} & self.model_fields_set):
            if self.metric is None:
                raise ValueError("A widget requires a saved metric.")
            return self
        if (
            self.type != "ag-grid-table"
            or self.metrics is None
            or self.dimensions is None
            or {"metric", "dimension"} & self.model_fields_set
        ):
            raise ValueError(
                "Supply both metrics and dimensions only on an ag-grid-table, "
                "and omit metric and dimension."
            )
        field_names = [*self.metrics, *self.dimensions]
        if len(set(field_names)) != len(field_names):
            raise ValueError("Select distinct metrics and dimensions.")
        return self


class DashboardDraft(BaseModel):
    """Only this bounded shape can be sent to the proposal gateway."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    title: LABEL
    widgets: Annotated[list[WidgetDraft], Field(min_length=1, max_length=8)]
    summary: DashboardSummary | None = None
    title_translations: TitleTranslations | None = Field(
        default=None, alias="titleTranslations"
    )
    content_locale: ContentLocale | None = Field(default=None, alias="contentLocale")
    dashboard_type: DashboardType | None = Field(default=None, alias="dashboardType")

    @property
    def requires_dashboard_v2(self) -> bool:
        """Identify draft features available only in Dashboard V2."""
        return self.summary is not None or any(
            w.metrics is not None for w in self.widgets
        )


class DashboardProposal(DashboardDraft):
    """The gateway's verified draft and opaque one-time approval token."""

    approval_token: Annotated[
        str, Field(alias="approvalToken", min_length=1, max_length=12_000)
    ]


class DashboardLocalization(BaseModel):
    """Request translated captions for the current draft only."""

    model_config = ConfigDict(strict=True, extra="forbid")

    source_locale: ContentLocale = Field(alias="sourceLocale")
    target_locale: ContentLocale = Field(alias="targetLocale")
    captions: CaptionList

    @model_validator(mode="after")
    def validate_scope(self) -> DashboardLocalization:
        """Require a real dashboard caption and a distinct target language."""
        if (
            self.source_locale == self.target_locale
            or not (self.captions[0] or "").strip()
        ):
            raise ValueError("A title and distinct target language are required")
        return self


class CaptionSuggestions(BaseModel):
    """A bounded list of model suggestions in the original caption order."""

    model_config = ConfigDict(strict=True, extra="forbid")

    captions: CaptionList


class DatasetDraftRequest(BaseModel):
    """Select a registered SQL dataset for a deterministic dashboard draft."""

    model_config = ConfigDict(strict=True, extra="forbid")

    dataset_id: Annotated[POSITIVE_ID, Field(alias="datasetId")]


class RunHints(BaseModel):
    """Untrusted page hints used for presentation and tool selection."""

    locale: ContentLocale = "en"
    content_locale: ContentLocale | None = None
    dashboard_type: DashboardType | None = None
    page: str | None = None
    active_dashboard_id: int | None = None
    active_chart_id: int | None = None
    active_dataset_id: int | None = None
    uploaded_dataset_id: int | None = None
    uploaded_dataset_action: Literal["draft"] | None = None
    form_values: dict[str, str] | None = None
    dashboard_localization: DashboardLocalization | None = None
    dataset_draft: DatasetDraftRequest | None = None


class FormAction(BaseModel):
    """The native A2UI action understood by the presentation-only agent."""

    model_config = ConfigDict(strict=True, extra="forbid", populate_by_name=True)

    name: Literal["nxtbi.submit-form"]
    surface_id: Annotated[
        str, Field(alias="surfaceId", pattern=r"^nxtbi-[a-f0-9]{32}$")
    ]
    source_component_id: Literal["submit"] = Field(alias="sourceComponentId")
    timestamp: Annotated[
        str, Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
    ]
    context: Annotated[dict[str, str], Field(min_length=1, max_length=8)]


class A2UIAction(BaseModel):
    """A complete 1.0 action message with a single allowed event."""

    model_config = ConfigDict(strict=True, extra="forbid")

    version: Literal["1.0"]
    action: FormAction


def _encode_segment(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def sign_context(secret: str, claims: dict[str, object]) -> str:
    """Return the gateway's wire token for an explicitly authorized context."""
    if len(secret) < 32:
        raise ValueError("The gateway shared secret is too short")
    payload = _encode_segment(
        GatewayClaims.model_validate(claims).model_dump_json().encode()
    )
    signature = hmac.digest(secret.encode("utf-8"), payload.encode("ascii"), "sha256")
    return f"{payload}.{_encode_segment(signature)}"


def _decode_segment(segment: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", segment):
        raise ValueError("Invalid signed context")
    decoded = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    if _encode_segment(decoded) != segment:
        raise ValueError("Invalid signed context")
    return decoded


def verify_gateway_token(authorization: str | None, secret: str) -> GatewayClaims:
    """Verify the signed audience and expiration before processing a run."""
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise ValueError
        token = authorization[7:]
        if len(secret) < 32 or len(token) > 8_192:
            raise ValueError
        payload, encoded_signature = token.split(".")
        expected = hmac.digest(
            secret.encode("utf-8"), payload.encode("ascii"), "sha256"
        )
        if not hmac.compare_digest(expected, _decode_segment(encoded_signature)):
            raise ValueError
        claims = GatewayClaims.model_validate_json(_decode_segment(payload))
        now = int(time.time())
        if not now < claims.exp <= now + MAX_TOKEN_AGE:
            raise ValueError
    except (ValueError, binascii.Error, UnicodeError) as exc:
        raise ValueError("Invalid signed context") from exc
    return claims


def _parse_form_values(forwarded: object) -> dict[str, str] | None:
    """Read only bounded values submitted through a supported form action."""
    if not isinstance(forwarded, dict) or "a2uiAction" not in forwarded:
        return None
    action = A2UIAction.model_validate(forwarded["a2uiAction"]).action
    for name, value in action.context.items():
        if (
            not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}", name)
            or name in {"constructor", "prototype"}
            or len(value) > 500
        ):
            raise ValueError("Invalid form field")
    return action.context


def _parse_draft_hint(hints: RunHints, key: object, value: str) -> None:
    """Accept only the supported Superset draft preferences."""
    if key == "content_locale" and value in ("ar", "en"):
        hints.content_locale = "ar" if value == "ar" else "en"
    elif key == "dashboard_type" and value in ("v1", "v2"):
        hints.dashboard_type = "v1" if value == "v1" else "v2"
    elif key == "uploaded_dataset_action" and value == "draft":
        hints.uploaded_dataset_action = "draft"


def _parse_dashboard_localization(
    forwarded: object, host: Literal["superset", "standalone"], upload_draft: bool
) -> DashboardLocalization | None:
    """Parse this explicit Superset action only when it is the sole intent."""
    if not isinstance(forwarded, dict) or "dashboardLocalization" not in forwarded:
        return None
    if host != "superset" or upload_draft or "a2uiAction" in forwarded:
        raise ValueError("Dashboard localization requires a separate draft request")
    return DashboardLocalization.model_validate(forwarded["dashboardLocalization"])


def _parse_dataset_draft(
    forwarded: object, host: Literal["superset", "standalone"], upload_draft: bool
) -> DatasetDraftRequest | None:
    """Read only an explicit Superset dataset action without a competing intent."""
    if not isinstance(forwarded, dict) or "datasetDraft" not in forwarded:
        return None
    if (
        host != "superset"
        or upload_draft
        or {"dashboardLocalization", "a2uiAction"} & forwarded.keys()
    ):
        raise ValueError("A dataset draft requires a separate Superset request")
    return DatasetDraftRequest.model_validate(forwarded["datasetDraft"])


def _parse_hints(
    raw: object, forwarded: object, host: Literal["superset", "standalone"]
) -> RunHints:
    hints = RunHints()
    if isinstance(raw, list):
        for item in raw[:16]:
            if not isinstance(item, dict) or not isinstance(
                value := item.get("value"), str
            ):
                continue
            key = item.get("description")
            if key == "locale" and value in ("ar", "en"):
                hints.locale = "ar" if value == "ar" else "en"
            elif key == "page" and len(value) <= 120:
                hints.page = value
            elif (
                key
                in (
                    "active_dashboard_id",
                    "active_chart_id",
                    "active_dataset_id",
                    "uploaded_dataset_id",
                )
                and (key != "uploaded_dataset_id" or host == "superset")
                and re.fullmatch(r"[1-9][0-9]{0,9}", value)
                and int(value) <= 2_147_483_647
            ):
                setattr(hints, key, int(value))
            elif host == "superset":
                _parse_draft_hint(hints, key, value)
    if hints.uploaded_dataset_action and hints.uploaded_dataset_id is None:
        raise ValueError("Select a dataset before staging an upload draft")
    hints.dataset_draft = _parse_dataset_draft(
        forwarded, host, hints.uploaded_dataset_action is not None
    )
    hints.dashboard_localization = _parse_dashboard_localization(
        forwarded, host, hints.uploaded_dataset_action is not None
    )
    if hints.dashboard_localization is None:
        hints.form_values = _parse_form_values(forwarded)
    return hints


def _parse_messages(raw: object) -> list[AssistantMessage | UserMessage]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_MESSAGE_COUNT:
        raise ValueError
    messages: list[AssistantMessage | UserMessage] = []
    seen_ids: set[str] = set()
    history_length = 0
    for message in raw:
        if not isinstance(message, dict):
            raise ValueError
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue
        message_id, content = message.get("id"), message.get("content")
        if role == "assistant" and content in (None, ""):
            continue
        if (
            not isinstance(message_id, str)
            or not 1 <= len(message_id) <= 200
            or message_id in seen_ids
            or not isinstance(content, str)
            or not 1 <= len(content) <= MAX_MESSAGE_LENGTH
        ):
            raise ValueError
        history_length += len(content)
        seen_ids.add(message_id)
        if role == "user":
            messages.append(UserMessage(id=message_id, role="user", content=content))
        else:
            messages.append(
                AssistantMessage(id=message_id, role="assistant", content=content)
            )
    if (
        not messages
        or raw[-1].get("role") != "user"
        or history_length > MAX_HISTORY_LENGTH
    ):
        raise ValueError
    return messages


def parse_run(body: bytes, claims: GatewayClaims) -> tuple[RunAgentInput, RunHints]:
    """Bind an AG-UI turn to its gateway claims and discard client capabilities."""
    try:
        incoming = json.loads(body)
        if not isinstance(incoming, dict):
            raise ValueError
        if (
            incoming.get("threadId") != claims.thread_id
            or incoming.get("runId") != claims.run_id
        ):
            raise PermissionError("Signed run context does not match the request")
        messages = _parse_messages(incoming.get("messages"))
        latest = messages[-1] if messages else None
        if (
            not isinstance(latest, UserMessage)
            or not isinstance(latest.content, str)
            or not latest.content.strip()
        ):
            raise ValueError
        hints = _parse_hints(
            incoming.get("context"), incoming.get("forwardedProps"), claims.host
        )
        if hints.page:
            page = json.dumps(hints.page, ensure_ascii=False)
            latest.content += f"\n\nUser-provided page context: {page}"
        if hints.form_values is not None:
            submitted = json.dumps(hints.form_values, ensure_ascii=False)
            latest.content += f"\n\nA2UI form values (user input): {submitted}"
        return (
            RunAgentInput(
                threadId=claims.thread_id, runId=claims.run_id, messages=messages
            ),
            hints,
        )
    except (ValueError, RecursionError) as exc:
        raise ValueError("Invalid AG-UI input") from exc
