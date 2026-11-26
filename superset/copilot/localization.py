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

"""Stored Copilot presentation metadata for dashboard captions."""

from collections.abc import Mapping

LOCALIZATION_KEY = "nxtbi_localization"


def localized_caption(
    metadata: object,
    canonical: str | None,
    locale: str | None,
    chart_id: int | None = None,
) -> str | None:
    """Resolve a generated caption for the viewer when its source still matches."""
    language = (locale or "").replace("-", "_").split("_", 1)[0].lower()
    if language not in {"en", "ar"} or not isinstance(metadata, Mapping):
        return None
    localization = metadata.get(LOCALIZATION_KEY)
    if not isinstance(localization, dict):
        return None
    if language == localization.get("sourceLocale"):
        return None
    if chart_id is None:
        entry = localization.get("title")
    else:
        widgets = localization.get("widgets")
        entry = widgets.get(str(chart_id)) if isinstance(widgets, dict) else None
    if not canonical or not isinstance(entry, dict) or entry.get("source") != canonical:
        return None
    translations = entry.get("translations")
    caption = translations.get(language) if isinstance(translations, dict) else None
    if isinstance(caption, str) and caption.strip() and len(caption) <= 256:
        return caption
    return None


def localized_document_title(
    document: object, canonical: str | None, locale: str
) -> str | None:
    """Resolve a V2 title from its validated document root's presentation props."""
    nodes = document.get("nodes") if isinstance(document, dict) else None
    root = nodes.get("root") if isinstance(nodes, dict) else None
    props = root.get("props") if isinstance(root, dict) else None
    if not isinstance(props, dict):
        return None
    return localized_caption(
        {LOCALIZATION_KEY: props.get("nxtbiLocalization")}, canonical, locale
    )
