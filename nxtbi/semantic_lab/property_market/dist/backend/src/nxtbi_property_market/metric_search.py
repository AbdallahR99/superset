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

"""Resolve bilingual metric labels against the approved lab catalogue."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Literal

from .model import METRIC_CATALOG


@dataclass(frozen=True)
class MetricCandidate:
    """An approved identifier with user-facing metadata in the requested locale."""

    metric_id: str
    label: str
    definition: str
    unit: str


@dataclass(frozen=True)
class MetricResolution:
    """Matching candidates and whether an analyst needs to clarify the request."""

    status: Literal["matched", "ambiguous", "unmatched"]
    candidates: tuple[MetricCandidate, ...]


def _normalize_label(label: str) -> str:
    """Normalize formatting while preserving the wording of approved aliases."""
    normalized = unicodedata.normalize("NFKC", label).casefold()
    normalized = "".join(
        character
        for character in normalized
        if character != "\u0640"
        and not (
            unicodedata.category(character) == "Mn"
            and unicodedata.name(character, "").startswith("ARABIC ")
        )
    )
    return " ".join(normalized.strip().rstrip("?؟").split())


def resolve_metric(phrase: str, locale: Literal["en", "ar"]) -> MetricResolution:
    """Find all exact catalogue matches, without guessing a missing definition."""
    normalized = _normalize_label(phrase)
    candidates = []
    for metric_id, text in METRIC_CATALOG.items():
        if locale == "ar":
            label, definition, aliases = (
                text.label_ar,
                text.definition_ar,
                text.aliases_ar,
            )
        else:
            label, definition, aliases = (
                text.label_en,
                text.definition_en,
                text.aliases_en,
            )
        if normalized and any(
            normalized == _normalize_label(alias) for alias in (label, *aliases)
        ):
            candidates.append(MetricCandidate(metric_id, label, definition, text.unit))

    if not candidates:
        return MetricResolution("unmatched", ())
    if len(candidates) == 1:
        return MetricResolution("matched", tuple(candidates))
    return MetricResolution("ambiguous", tuple(candidates))
