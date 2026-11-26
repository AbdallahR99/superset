# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""Presentation-only vocabulary for deterministic dashboard drafts."""

from .contracts import ContentLocale, DashboardDraft, DashboardType, TitleTranslations

_ARABIC = {
    "category": "الفئة",
    "channel": "القناة",
    "city": "المدينة",
    "count": "السجلات",
    "country": "الدولة",
    "order total": "قيمة الطلب",
    "orders": "الطلبات",
    "population": "السكان",
    "quantity": "الكمية",
    "records": "السجلات",
    "region": "المنطقة",
    "revenue": "الإيرادات",
    "sales": "المبيعات",
    "status": "الحالة",
    "total order value": "إجمالي قيمة الطلبات",
}


def arabic_label(value: str) -> str:
    """Translate established captions and preserve unfamiliar authored terms."""
    label = value.casefold()
    if label.startswith("sum of ") and (term := _ARABIC.get(label[7:])):
        return f"مجموع {term}"
    return _ARABIC.get(label, value)


def titles(english: str, arabic: str) -> TitleTranslations:
    """Build two bounded, plain text variants."""
    return TitleTranslations(en=english[:160], ar=arabic[:160])


def localize_draft(
    draft: DashboardDraft, locale: ContentLocale | None, kind: DashboardType | None
) -> DashboardDraft:
    """Select canonical captions without modifying any analytical fields."""
    if locale is None:
        return draft.model_copy(update={"dashboard_type": kind})
    widgets = []
    for widget in draft.widgets:
        translations = widget.title_translations
        title = (
            translations.for_locale(locale) if translations else None
        ) or widget.title
        widgets.append(widget.model_copy(update={"title": title}))
    title = draft.title_translations
    return draft.model_copy(
        update={
            "content_locale": locale,
            "dashboard_type": kind,
            "title": (title.for_locale(locale) if title else None) or draft.title,
            "widgets": widgets,
        }
    )
