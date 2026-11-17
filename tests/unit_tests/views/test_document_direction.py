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
"""Tests for the document ``lang``/``dir`` template context and the
``direction`` entry of the common bootstrap payload."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask import current_app, g

from superset.views.base import (
    cached_common_bootstrap_data,
    get_document_locale_template_context,
)


@pytest.fixture
def mock_user() -> None:
    g.user = MagicMock()


def _bootstrap(locale: str | None) -> dict[str, Any]:
    with patch("superset.views.base.menu_data", return_value={}):
        return cached_common_bootstrap_data.uncached(user_id=1, locale=locale)


@pytest.mark.parametrize(
    "locale,expected_lang,expected_dir",
    [
        ("ar", "ar", "rtl"),
        ("fa", "fa", "rtl"),
        ("en", "en", "ltr"),
        ("zh_TW", "zh-TW", "ltr"),
        ("pt_BR", "pt-BR", "ltr"),
    ],
)
def test_document_context_derives_direction_from_locale(
    locale: str, expected_lang: str, expected_dir: str
) -> None:
    """Without a ``direction`` in the payload, it is derived from the locale and
    the ``lang`` attribute uses a hyphenated BCP 47 tag."""
    context = get_document_locale_template_context({"locale": locale})

    assert context == {"html_lang": expected_lang, "html_dir": expected_dir}


def test_document_context_prefers_direction_from_payload() -> None:
    """The server-computed ``common.direction`` wins over the derived value."""
    context = get_document_locale_template_context(
        {"locale": "ar", "direction": "ltr"}
    )

    assert context["html_dir"] == "ltr"
    assert context["html_lang"] == "ar"


@pytest.mark.parametrize("common", [{}, {"locale": None}, {"locale": ""}])
def test_document_context_defaults_to_english_ltr(common: dict[str, Any]) -> None:
    context = get_document_locale_template_context(common)

    assert context == {"html_lang": "en", "html_dir": "ltr"}


def test_document_context_respects_disabled_rtl_layout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(current_app.config, "RTL_LAYOUT_ENABLED", False)

    context = get_document_locale_template_context({"locale": "ar"})

    assert context == {"html_lang": "ar", "html_dir": "ltr"}


@pytest.mark.parametrize(
    "locale,expected",
    [("ar", "rtl"), ("ar-SA", "rtl"), ("en", "ltr"), ("fr", "ltr"), (None, "ltr")],
)
def test_bootstrap_payload_contains_direction(
    mock_user: None, locale: str | None, expected: str
) -> None:
    payload = _bootstrap(locale)

    assert payload["direction"] == expected


def test_bootstrap_direction_follows_rtl_layout_flag(
    mock_user: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(current_app.config, "RTL_LAYOUT_ENABLED", False)

    payload = _bootstrap("ar")

    assert payload["locale"] == "ar"
    assert payload["direction"] == "ltr"
