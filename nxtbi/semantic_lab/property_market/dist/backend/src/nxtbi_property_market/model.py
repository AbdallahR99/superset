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

"""Synthetic property transactions and their approved semantic definitions."""

from dataclasses import dataclass, replace

import pyarrow as pa
from superset_core.semantic_layers.types import (
    AggregationType,
    Dimension,
    Grains,
    Metric,
)

MODEL_TITLE = "Property Market Lab"
MODEL_VERSION = "v1"
MODEL_OWNER = "NxtBI Semantic Lab"

PROPERTY_COLUMNS = ("market_scope", "property_id", "district", "property_type")
TRANSACTION_COLUMNS = (
    "transaction_id",
    "market_scope",
    "property_id",
    "sale_date",
    "registration_date",
    "price",
    "area",
)

SCHEMA_SQL = """
CREATE TABLE properties (
    market_scope TEXT NOT NULL,
    property_id TEXT NOT NULL,
    district TEXT,
    property_type TEXT NOT NULL,
    PRIMARY KEY (market_scope, property_id)
);
CREATE TABLE transactions (
    transaction_id TEXT NOT NULL PRIMARY KEY,
    market_scope TEXT NOT NULL,
    property_id TEXT NOT NULL,
    sale_date TEXT NOT NULL,
    registration_date TEXT NOT NULL,
    price INTEGER NOT NULL CHECK (price >= 0),
    area INTEGER CHECK (area >= 0)
);
"""

PROPERTY_ROWS: tuple[tuple[str, str, str | None, str], ...] = (
    ("nxtbi_lab", "P001", "Marina", "Apartment"),
    ("nxtbi_lab", "P002", "Downtown", "Villa"),
    ("nxtbi_lab", "P003", None, "Apartment"),
    ("comparison", "P001", "Comparison District", "Villa"),
)

TRANSACTION_ROWS: tuple[tuple[str, str, str, str, str, int, int | None], ...] = (
    ("T001", "nxtbi_lab", "P001", "2026-01-05", "2026-01-10", 300_000, 50),
    ("T002", "nxtbi_lab", "P001", "2026-01-20", "2026-02-02", 360_000, 60),
    ("T003", "nxtbi_lab", "P002", "2026-02-04", "2026-02-10", 900_000, 300),
    ("T004", "nxtbi_lab", "P003", "2026-02-27", "2026-03-02", 480_000, 80),
    ("T005", "nxtbi_lab", "P004", "2026-03-12", "2026-03-18", 120_000, None),
    ("T006", "nxtbi_lab", "P002", "2026-03-20", "2026-04-01", 240_000, 120),
)

# A length prefix separates the scope from the property ID without relying on
# a delimiter being absent in the IDs. The left join preserves orphan sales.
MARKET_SELECT_SQL = """
SELECT
    p.district AS district,
    COALESCE(p.property_type, 'Unknown') AS property_type,
    t.sale_date,
    t.registration_date,
    t.price,
    t.area,
    printf('%d:%s%s', length(t.market_scope), t.market_scope, t.property_id)
        AS property_key
FROM transactions AS t
LEFT JOIN properties AS p
    ON p.market_scope = t.market_scope AND p.property_id = t.property_id
WHERE t.market_scope = 'nxtbi_lab'
"""

DIMENSIONS: dict[str, Dimension] = {
    "district": Dimension(
        "district",
        "district",
        pa.string(),
        description="District from the approved property lookup, when available.",
        verbose_name="District",
        metadata={"label_ar": "المنطقة"},
    ),
    "property_type": Dimension(
        "property_type",
        "property_type",
        pa.string(),
        description="Property type, with Unknown for an unmatched property.",
        verbose_name="Property type",
        metadata={"label_ar": "نوع العقار"},
    ),
    "sale_date": Dimension(
        "sale_date",
        "sale_date",
        pa.date32(),
        description="Date the sale occurred.",
        verbose_name="Sale date",
        metadata={"label_ar": "تاريخ البيع"},
    ),
    "registration_date": Dimension(
        "registration_date",
        "registration_date",
        pa.date32(),
        description="Date the sale was registered.",
        verbose_name="Registration date",
        metadata={"label_ar": "تاريخ التسجيل"},
    ),
}

TIME_DIMENSIONS: tuple[Dimension, ...] = tuple(
    replace(dimension, id=f"{dimension.id}_{grain.name.lower()}", grain=grain)
    for dimension in (DIMENSIONS["sale_date"], DIMENSIONS["registration_date"])
    for grain in (Grains.DAY, Grains.MONTH)
)


@dataclass(frozen=True)
class MetricText:
    """Store curated descriptions and search aliases for two authoring languages."""

    label_en: str
    label_ar: str
    definition_en: str
    definition_ar: str
    aliases_en: tuple[str, ...]
    aliases_ar: tuple[str, ...]
    unit: str


METRIC_CATALOG: dict[str, MetricText] = {
    "transaction_count": MetricText(
        label_en="Transaction count",
        label_ar="عدد المعاملات",
        definition_en="Number of recorded sales transactions in the selected scope.",
        definition_ar="عدد معاملات البيع المسجّلة ضمن النطاق المحدد.",
        aliases_en=("number of sales", "sales count"),
        aliases_ar=("عدد المبيعات", "عدد الصفقات"),
        unit="transactions",
    ),
    "average_transaction_price": MetricText(
        label_en="Average transaction price",
        label_ar="متوسط سعر المعاملة",
        definition_en="Arithmetic mean of recorded sale prices in AED.",
        definition_ar="المتوسط الحسابي لأسعار البيع المسجّلة بالدرهم الإماراتي.",
        aliases_en=("average property price", "average sale price"),
        aliases_ar=("متوسط سعر العقار", "متوسط سعر البيع"),
        unit="AED",
    ),
    "weighted_price_per_sqm": MetricText(
        label_en="Price per square meter",
        label_ar="السعر لكل متر مربع",
        definition_en=(
            "Total price divided by total area in square meters. Includes only "
            "sales with positive known area in both totals."
        ),
        definition_ar=(
            "إجمالي أسعار البيع مقسوماً على إجمالي المساحات بالمتر المربع. "
            "يشمل الإجماليان فقط المعاملات ذات المساحة المعروفة والموجبة."
        ),
        aliases_en=(
            "average property price",
            "price per sqm",
            "weighted price per sqm",
        ),
        aliases_ar=("متوسط سعر العقار", "سعر المتر المربع", "سعر المتر"),
        unit="AED/m²",
    ),
    "distinct_property_count": MetricText(
        label_en="Distinct properties sold",
        label_ar="عدد العقارات المباعة دون تكرار",
        definition_en="Number of distinct property identifiers with a recorded sale.",
        definition_ar="عدد معرّفات العقارات غير المكررة التي لها معاملة بيع مسجّلة.",
        aliases_en=("properties sold", "unique properties sold"),
        aliases_ar=("العقارات المباعة", "عدد العقارات المباعة"),
        unit="properties",
    ),
}


def _metric(
    name: str, type_: pa.DataType, sql: str, aggregation: AggregationType
) -> Metric:
    """Bind reviewed text and approved SQL to the same stable member name."""
    text = METRIC_CATALOG[name]
    return Metric(
        name,
        name,
        type_,
        sql,
        description=text.definition_en,
        aggregation=aggregation,
        verbose_name=text.label_en,
        d3format=",.2f" if pa.types.is_floating(type_) else ",d",
        metadata={
            "label_ar": text.label_ar,
            "definition_ar": text.definition_ar,
            "aliases_en": list(text.aliases_en),
            "aliases_ar": list(text.aliases_ar),
            "unit": text.unit,
            "model_owner": MODEL_OWNER,
            "model_version": MODEL_VERSION,
        },
    )


METRICS: dict[str, Metric] = {
    "transaction_count": _metric(
        "transaction_count", pa.int64(), "COUNT(*)", AggregationType.COUNT
    ),
    "average_transaction_price": _metric(
        "average_transaction_price", pa.float64(), "AVG(price)", AggregationType.AVG
    ),
    "weighted_price_per_sqm": _metric(
        "weighted_price_per_sqm",
        pa.float64(),
        "1.0 * SUM(CASE WHEN area > 0 THEN price END) "
        "/ SUM(CASE WHEN area > 0 THEN area END)",
        AggregationType.OTHER,
    ),
    "distinct_property_count": _metric(
        "distinct_property_count",
        pa.int64(),
        "COUNT(DISTINCT property_key)",
        AggregationType.COUNT_DISTINCT,
    ),
}
