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
"""Tests for ``superset.translations.utils.get_text_direction``."""

from typing import Optional

import pytest
from flask import current_app

from superset.translations.utils import get_text_direction


@pytest.mark.parametrize(
    "locale",
    ["ar", "ar_SA", "ar-EG", "ar_EG", "fa", "he", "ur"],
)
def test_right_to_left_locales(locale: str) -> None:
    assert get_text_direction(locale) == "rtl"


@pytest.mark.parametrize(
    "locale",
    ["en", "en_US", "fr", "zh_TW", "pt_BR", "de", "ja", "ru"],
)
def test_left_to_right_locales(locale: str) -> None:
    assert get_text_direction(locale) == "ltr"


@pytest.mark.parametrize(
    "locale",
    [None, "", "not-a-locale", "xx_YY_ZZ", "12345", "xx", "xx_YY"],
)
def test_unparseable_locale_is_left_to_right(locale: Optional[str]) -> None:
    assert get_text_direction(locale) == "ltr"


def test_locale_object_is_accepted() -> None:
    """Flask-Babel returns ``Locale`` objects; they are stringified."""
    from babel import Locale

    assert get_text_direction(Locale("ar")) == "rtl"  # type: ignore[arg-type]
    assert get_text_direction(Locale("en")) == "ltr"  # type: ignore[arg-type]


def test_rtl_layout_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """``RTL_LAYOUT_ENABLED = False`` keeps every locale left-to-right."""
    monkeypatch.setitem(current_app.config, "RTL_LAYOUT_ENABLED", False)

    assert get_text_direction("ar") == "ltr"
    assert get_text_direction("he") == "ltr"
    assert get_text_direction("en") == "ltr"


def test_rtl_layout_enabled_by_default() -> None:
    assert current_app.config["RTL_LAYOUT_ENABLED"] is True
    assert get_text_direction("ar") == "rtl"
