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
"""Guards for the Arabic catalogue (``ar/LC_MESSAGES/messages.po``).

These tests do not judge the quality of the Arabic text. They keep the
catalogue loadable, keep placeholders intact (a wrong ``%s``/``%d`` breaks the
UI at runtime), require complete plural forms for reviewed entries, and pin the
strings that used to be wrong on the most visible screens.
"""

import collections
import re
from pathlib import Path
from typing import Any

import pytest
from babel.messages.catalog import Catalog, Message
from babel.messages.pofile import read_po

PO_FILE = (
    Path(__file__).resolve().parents[3]
    / "superset"
    / "translations"
    / "ar"
    / "LC_MESSAGES"
    / "messages.po"
)

PLACEHOLDER = re.compile(
    r"%\([^)]+\)[sdif]|%[sdif]|\{[A-Za-z_][A-Za-z0-9_]*\}|</?[A-Za-z][^>]*>"
)

# Digits are Latin in every string (see nxtbi/docs/rtl/04-arabic-catalogue.md).
ARABIC_INDIC_DIGITS = re.compile("[٠-٩۰-۹]")

pytestmark = pytest.mark.skipif(
    not PO_FILE.exists(), reason="Arabic catalogue is not part of this build"
)


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    with open(PO_FILE, "rb") as handle:
        return read_po(handle, locale="ar")


def _entries(catalog: Catalog) -> list[Message]:
    return [message for message in catalog if message.id]


def _ids(message: Message) -> tuple[str, ...]:
    return message.id if isinstance(message.id, tuple) else (message.id,)


def _strings(message: Message) -> tuple[str, ...]:
    return (
        message.string if isinstance(message.string, tuple) else (message.string,)
    )


def _lookup(catalog: Catalog, msgid: Any) -> Message:
    message = catalog.get(msgid)
    assert message is not None, f"{msgid!r} is not in the catalogue"
    return message


def test_catalogue_declares_six_arabic_plural_forms(catalog: Catalog) -> None:
    assert catalog.num_plurals == 6


def test_placeholders_are_preserved(catalog: Catalog) -> None:
    """Every msgstr only uses placeholders its msgid (or msgid_plural) declares,
    and a singular message uses exactly the same set."""
    problems: list[str] = []
    for message in _entries(catalog):
        ids = _ids(message)
        allowed: collections.Counter[str] = collections.Counter()
        for text in ids:
            allowed |= collections.Counter(PLACEHOLDER.findall(text))
        for index, text in enumerate(_strings(message)):
            if not text:
                continue
            found = collections.Counter(PLACEHOLDER.findall(text))
            if found - allowed:
                problems.append(f"{ids[0]!r}[{index}]: {dict(found - allowed)}")
            if len(ids) == 1 and found != allowed:
                problems.append(f"{ids[0]!r}: missing {dict(allowed - found)}")
    assert not problems, "\n".join(problems[:20])


def test_reviewed_plural_entries_have_all_six_forms(catalog: Catalog) -> None:
    """A partial plural falls back to English for n >= 1 (and is wrong at 0)."""
    incomplete = [
        _ids(message)[0]
        for message in _entries(catalog)
        if len(_ids(message)) > 1
        and not message.fuzzy
        and any(not text for text in _strings(message))
    ]
    assert not incomplete, incomplete[:20]


def test_filter_and_list_plurals_are_complete(catalog: Catalog) -> None:
    """Plurals rendered in the dashboard filter bar and in list views."""
    for msgid in (
        ("%s option", "%s options"),
        ("%s row", "%s rows"),
        ("%s column", "%s columns"),
        ("%s item", "%s items"),
        ("%s metric", "%s metrics"),
        ("Drop a column here or click", "Drop columns here or click"),
    ):
        message = _lookup(catalog, msgid)
        forms = _strings(message)
        assert len(forms) == 6 and all(forms), msgid
        assert not message.fuzzy, msgid


def test_arabic_text_uses_latin_digits(catalog: Catalog) -> None:
    offenders = [
        _ids(message)[0]
        for message in _entries(catalog)
        if not message.fuzzy
        and any(ARABIC_INDIC_DIGITS.search(text) for text in _strings(message))
    ]
    assert not offenders, offenders[:20]


@pytest.mark.parametrize(
    "msgid,expected",
    [
        ("Home", "الرئيسية"),
        ("Chart", "مخطط"),
        ("Dashboard", "لوحة المعلومات"),
        ("Dashboards", "لوحات المعلومات"),
        ("Save", "حفظ"),
        ("Cancel", "إلغاء"),
        ("Run", "تشغيل"),
        ("Table", "جدول"),
        ("Mine", "الخاصة بي"),
        ("Sign in", "تسجيل الدخول"),
        ("Select all", "تحديد الكل"),
        ("Current month", "الشهر الحالي"),
        ("Yes", "نعم"),
        ("No", "لا"),
    ],
)
def test_most_visible_strings_are_correct(
    catalog: Catalog, msgid: str, expected: str
) -> None:
    message = _lookup(catalog, msgid)
    assert message.string == expected
    assert not message.fuzzy


def test_applied_filters_placeholder_matches_source(catalog: Catalog) -> None:
    """``%d`` in the translation of a ``%s`` message raised at runtime."""
    message = _lookup(catalog, "Applied filters (%s)")
    assert "%s" in message.string
    assert "%d" not in message.string
