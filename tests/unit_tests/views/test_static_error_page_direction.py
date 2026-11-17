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
"""The branded static error pages follow the language and direction of the
session locale, like the application shell they stand in for."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from flask import Flask
from flask.testing import FlaskClient
from flask_babel import Babel

from superset.views.error_handling import (
    localize_static_page,
    set_app_error_handlers,
)

STATIC_PAGE = (
    '<!doctype html><html lang="en"><head><title>404</title></head>'
    '<body><section lang="en" dir="auto">Page not found</section></body></html>'
)


def _client_for_locale(locale: str, tmp_path: Path, **config: bool) -> FlaskClient:
    """A bare app with the error handlers and a built ``404.html`` on disk."""
    assets = tmp_path / "static" / "assets"
    assets.mkdir(parents=True)
    (assets / "404.html").write_text(STATIC_PAGE, encoding="utf-8")

    test_app = Flask(__name__)
    test_app.config["DEBUG"] = False
    test_app.config.update(config)
    Babel(test_app, locale_selector=lambda: locale)
    set_app_error_handlers(test_app)
    return test_app.test_client()


@pytest.mark.parametrize(
    "locale,expected_tag",
    [
        ("ar", '<html lang="ar" dir="rtl">'),
        ("fa", '<html lang="fa" dir="rtl">'),
        ("fr", '<html lang="fr" dir="ltr">'),
        ("pt_BR", '<html lang="pt-BR" dir="ltr">'),
    ],
)
def test_404_page_carries_the_locale_language_and_direction(
    locale: str, expected_tag: str, tmp_path: Path
) -> None:
    client = _client_for_locale(locale, tmp_path)

    with patch("superset.views.error_handling.files", return_value=tmp_path):
        response = client.get("/no-matching-route", headers={"Accept": "text/html"})

    body = response.get_data(as_text=True)
    assert response.status_code == 404
    assert response.content_type.startswith("text/html")
    assert expected_tag in body
    assert '<html lang="en">' not in body
    # The rest of the document is served as built.
    assert body.replace(expected_tag, '<html lang="en">') == STATIC_PAGE


def test_localized_404_page_is_not_cacheable(tmp_path: Path) -> None:
    """The file's validators cannot tell one locale's variant from another's."""
    client = _client_for_locale("ar", tmp_path)

    with patch("superset.views.error_handling.files", return_value=tmp_path):
        response = client.get("/no-matching-route", headers={"Accept": "text/html"})

    assert response.headers["Cache-Control"] == "no-store"
    assert "ETag" not in response.headers
    assert "Last-Modified" not in response.headers


def test_english_404_page_is_served_as_built(tmp_path: Path) -> None:
    client = _client_for_locale("en", tmp_path)

    with patch("superset.views.error_handling.files", return_value=tmp_path):
        response = client.get("/no-matching-route", headers={"Accept": "text/html"})

    assert response.status_code == 404
    assert response.get_data(as_text=True) == STATIC_PAGE


def test_404_page_stays_left_to_right_when_rtl_layout_is_disabled(
    tmp_path: Path,
) -> None:
    client = _client_for_locale("ar", tmp_path, RTL_LAYOUT_ENABLED=False)

    with patch("superset.views.error_handling.files", return_value=tmp_path):
        response = client.get("/no-matching-route", headers={"Accept": "text/html"})

    assert '<html lang="ar" dir="ltr">' in response.get_data(as_text=True)


def test_missing_404_page_falls_back_to_json_for_a_right_to_left_locale(
    tmp_path: Path,
) -> None:
    client = _client_for_locale("ar", tmp_path)
    (tmp_path / "static" / "assets" / "404.html").unlink()

    with patch("superset.views.error_handling.files", return_value=tmp_path):
        response = client.get("/no-matching-route", headers={"Accept": "text/html"})

    assert response.status_code == 404
    assert response.content_type.startswith("application/json")


@pytest.mark.parametrize(
    "html",
    [
        '<html lang="en"><body></body></html>',
        "<html><body></body></html>",
        '<HTML LANG="en" class="x"><body></body></html>',
    ],
)
def test_localize_static_page_replaces_the_opening_tag(html: str) -> None:
    localized = localize_static_page(html, "ar", "rtl")

    assert localized == '<html lang="ar" dir="rtl"><body></body></html>'


def test_localize_static_page_leaves_a_document_without_html_tag_alone() -> None:
    assert localize_static_page("<p>plain</p>", "ar", "rtl") == "<p>plain</p>"


def test_localize_static_page_escapes_attribute_values() -> None:
    localized = localize_static_page("<html>", 'a"><script>', "rtl")

    assert "<script>" not in localized
    assert localized.startswith('<html lang="a&quot;&gt;&lt;script&gt;"')
