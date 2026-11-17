"""Seed the NxtBI demo warehouse (schema ``nxtbi`` in database ``nxtbi_demo``).

Deterministic: the same rows are produced on every run (fixed RNG seed, fixed date
ranges), so dashboards and smoke tests are reproducible. Idempotent: every table is
dropped and recreated inside one transaction.

Environment:
    NXTBI_DEMO_ADMIN_DSN  postgresql://owner:pw@host:5432/nxtbi_demo   (required)
    NXTBI_DEMO_RO_ROLE    role that receives SELECT (default: nxtbi_ro)

Two organisations mirror the NxtBI Keycloak realm (group paths /nxt/<org>/...):
    ministry-of-planning   وزارة التخطيط
    statistics-bureau      الجهاز المركزي للإحصاء
Every fact table carries ``org_slug`` so Superset Row Level Security can isolate tenants.
"""

from __future__ import annotations

import math
import os
import random
import sys
from datetime import date, datetime, timedelta

import psycopg2
from psycopg2.extras import execute_values

SCHEMA = "nxtbi"
PLANNING = "ministry-of-planning"
STATS = "statistics-bureau"
ORG_NAMES = {
    PLANNING: ("Ministry of Planning", "وزارة التخطيط"),
    STATS: ("Statistics Bureau", "الجهاز المركزي للإحصاء"),
}

REGIONS = [
    ("Capital", "العاصمة", 1.00),
    ("Northern", "الشمالية", 0.55),
    ("Southern", "الجنوبية", 0.48),
    ("Eastern", "الشرقية", 0.72),
    ("Western", "الغربية", 0.80),
    ("Central", "الوسطى", 0.62),
]

SECTORS = [
    ("Education", "التعليم", 1.00, ["School Construction", "Teacher Development", "Digital Classrooms"]),
    ("Health", "الصحة", 1.15, ["Primary Care Centers", "Hospital Expansion", "Preventive Programs"]),
    ("Infrastructure", "البنية التحتية", 1.40, ["Road Network", "Water & Sanitation", "Urban Renewal"]),
    ("Housing", "الإسكان", 0.85, ["Affordable Housing", "Housing Finance", "Land Development"]),
    ("Energy", "الطاقة", 0.95, ["Solar Parks", "Grid Modernisation", "Energy Efficiency"]),
    ("Transport", "النقل", 0.90, ["Public Transit", "Rail Corridors", "Ports & Logistics"]),
    ("Digital Government", "الحكومة الرقمية", 0.45, ["Unified Portal", "Data Platform", "Cyber Security"]),
    ("Social Development", "التنمية الاجتماعية", 0.60, ["Youth Employment", "Family Support", "Community Centers"]),
]

PARTNERS = [
    ("CHN", "China", "الصين", "Asia", 1.60),
    ("IND", "India", "الهند", "Asia", 1.05),
    ("USA", "United States", "الولايات المتحدة", "Americas", 1.20),
    ("DEU", "Germany", "ألمانيا", "Europe", 0.85),
    ("JPN", "Japan", "اليابان", "Asia", 0.70),
    ("GBR", "United Kingdom", "المملكة المتحدة", "Europe", 0.55),
    ("TUR", "Türkiye", "تركيا", "Europe", 0.60),
    ("EGY", "Egypt", "مصر", "Middle East & Africa", 0.50),
    ("SAU", "Saudi Arabia", "السعودية", "Middle East & Africa", 0.95),
    ("ARE", "United Arab Emirates", "الإمارات", "Middle East & Africa", 1.10),
    ("KOR", "South Korea", "كوريا الجنوبية", "Asia", 0.65),
    ("BRA", "Brazil", "البرازيل", "Americas", 0.35),
]

COMMODITIES = [
    # name_en, name_ar, import weight, export weight, usd per ton
    ("Machinery", "الآلات والمعدات", 1.30, 0.35, 9500),
    ("Vehicles", "المركبات", 1.10, 0.20, 14000),
    ("Food & Beverages", "الأغذية والمشروبات", 0.95, 0.60, 1800),
    ("Chemicals", "الكيماويات", 0.70, 0.90, 2600),
    ("Petroleum Products", "المنتجات البترولية", 0.40, 1.80, 720),
    ("Metals", "المعادن", 0.65, 0.85, 2100),
    ("Textiles", "المنسوجات", 0.55, 0.30, 5200),
    ("Electronics", "الإلكترونيات", 1.20, 0.25, 32000),
]

SERVICES = {
    PLANNING: [
        ("Project Permit", "تصريح مشروع", 72, 1.0),
        ("Budget Transfer Request", "طلب مناقلة مالية", 48, 0.7),
        ("Tender Registration", "تسجيل مناقصة", 24, 1.2),
        ("Development Grant", "منحة تنموية", 120, 0.5),
    ],
    STATS: [
        ("Data Request", "طلب بيانات", 24, 1.4),
        ("Statistical Certificate", "شهادة إحصائية", 8, 1.1),
        ("Survey Registration", "تسجيل مسح", 48, 0.6),
        ("Census Record Correction", "تصحيح بيانات التعداد", 96, 0.4),
    ],
}

CHANNELS = [("Mobile App", "تطبيق الهاتف", 0.42), ("Web Portal", "البوابة الإلكترونية", 0.33),
            ("Service Center", "مركز الخدمة", 0.15), ("Call Center", "مركز الاتصال", 0.10)]
SEGMENTS = [("Citizen", 0.52), ("Resident", 0.21), ("Business", 0.20), ("Government Entity", 0.07)]
AGE_GROUPS = ["0-9", "10-19", "20-29", "30-39", "40-49", "50-59", "60-69", "70-79", "80+"]
AGE_SHARE = [0.185, 0.170, 0.172, 0.155, 0.118, 0.090, 0.060, 0.035, 0.015]

FIRST_MONTH = date(2023, 1, 1)
LAST_MONTH = date(2026, 10, 1)
REQ_START = date(2025, 1, 1)
REQ_END = date(2026, 11, 15)

DDL = f"""
CREATE SCHEMA IF NOT EXISTS {SCHEMA};

DROP TABLE IF EXISTS {SCHEMA}.budget_execution;
CREATE TABLE {SCHEMA}.budget_execution (
    period_date      date    NOT NULL,
    fiscal_year      integer NOT NULL,
    fiscal_quarter   text    NOT NULL,
    org_slug         text    NOT NULL,
    sector_en        text    NOT NULL,
    sector_ar        text    NOT NULL,
    program_en       text    NOT NULL,
    region_en        text    NOT NULL,
    region_ar        text    NOT NULL,
    allocated_amount numeric(16, 2) NOT NULL,
    committed_amount numeric(16, 2) NOT NULL,
    spent_amount     numeric(16, 2) NOT NULL,
    projects_active  integer NOT NULL,
    projects_delayed integer NOT NULL
);
COMMENT ON TABLE {SCHEMA}.budget_execution IS 'Monthly capital budget execution by sector, programme and region (synthetic demo data).';

DROP TABLE IF EXISTS {SCHEMA}.trade_flows;
CREATE TABLE {SCHEMA}.trade_flows (
    period_date    date NOT NULL,
    org_slug       text NOT NULL,
    flow           text NOT NULL,
    partner_iso3   text NOT NULL,
    partner_en     text NOT NULL,
    partner_ar     text NOT NULL,
    partner_region text NOT NULL,
    commodity_en   text NOT NULL,
    commodity_ar   text NOT NULL,
    value_usd      numeric(16, 2) NOT NULL,
    weight_tons    numeric(14, 2) NOT NULL
);
COMMENT ON TABLE {SCHEMA}.trade_flows IS 'Monthly merchandise trade by partner and commodity group (synthetic demo data).';

DROP TABLE IF EXISTS {SCHEMA}.population;
CREATE TABLE {SCHEMA}.population (
    year_date   date    NOT NULL,
    census_year integer NOT NULL,
    org_slug    text    NOT NULL,
    region_en   text    NOT NULL,
    region_ar   text    NOT NULL,
    gender_en   text    NOT NULL,
    gender_ar   text    NOT NULL,
    age_group   text    NOT NULL,
    age_order   integer NOT NULL,
    population  integer NOT NULL
);
COMMENT ON TABLE {SCHEMA}.population IS 'Mid-year population estimates by region, gender and age group (synthetic demo data).';

DROP TABLE IF EXISTS {SCHEMA}.service_requests;
CREATE TABLE {SCHEMA}.service_requests (
    request_id        bigint PRIMARY KEY,
    created_at        timestamp NOT NULL,
    org_slug          text NOT NULL,
    org_name_en       text NOT NULL,
    org_name_ar       text NOT NULL,
    service_en        text NOT NULL,
    service_ar        text NOT NULL,
    channel_en        text NOT NULL,
    channel_ar        text NOT NULL,
    region_en         text NOT NULL,
    region_ar         text NOT NULL,
    applicant_segment text NOT NULL,
    status            text NOT NULL,
    sla_hours         integer NOT NULL,
    resolution_hours  numeric(8, 1),
    sla_met           boolean,
    satisfaction      smallint
);
COMMENT ON TABLE {SCHEMA}.service_requests IS 'Citizen/business service requests of both organisations; org_slug drives the RLS demo (synthetic demo data).';
CREATE INDEX ON {SCHEMA}.service_requests (created_at);
CREATE INDEX ON {SCHEMA}.service_requests (org_slug);
"""


def months(first: date, last: date):
    d = first
    while d <= last:
        yield d
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def budget_rows(rng: random.Random):
    for m in months(FIRST_MONTH, LAST_MONTH):
        idx = (m.year - FIRST_MONTH.year) * 12 + m.month - 1
        growth = 1.0 + 0.045 * (m.year - FIRST_MONTH.year)
        # spending is back-loaded inside a fiscal year (classic Q4 rush)
        burn = 0.52 + 0.40 * (m.month / 12.0) ** 1.6
        for s_en, s_ar, s_w, programs in SECTORS:
            for p_i, program in enumerate(programs):
                for r_en, r_ar, r_w in REGIONS:
                    base = 1_850_000 * s_w * r_w * growth * (1.0 - 0.18 * p_i)
                    allocated = base * rng.uniform(0.92, 1.08)
                    drag = 0.80 if (s_en == "Housing" and r_en in ("Southern", "Northern")) else 1.0
                    boost = 1.10 if s_en == "Digital Government" else 1.0
                    spent = allocated * min(1.06, burn * drag * boost * rng.uniform(0.86, 1.10))
                    committed = max(spent, allocated * min(1.0, burn * 1.12 * rng.uniform(0.95, 1.08)))
                    active = max(1, round(9 * s_w * r_w * rng.uniform(0.7, 1.3)))
                    delay_rate = 0.10 + 0.05 * math.sin(idx / 5.0) + (0.14 if drag < 1 else 0.0)
                    delayed = min(active, max(0, round(active * delay_rate * rng.uniform(0.5, 1.6))))
                    yield (m, m.year, f"Q{(m.month - 1) // 3 + 1}", PLANNING, s_en, s_ar, program, r_en, r_ar,
                           round(allocated, 2), round(committed, 2), round(spent, 2), active, delayed)


def trade_rows(rng: random.Random):
    for m in months(FIRST_MONTH, LAST_MONTH):
        idx = (m.year - FIRST_MONTH.year) * 12 + m.month - 1
        trend = 1.0 + 0.006 * idx
        season = 1.0 + 0.09 * math.sin(2 * math.pi * (m.month - 2) / 12.0)
        for iso, p_en, p_ar, p_reg, p_w in PARTNERS:
            for c_en, c_ar, w_imp, w_exp, usd_ton in COMMODITIES:
                for flow, w in (("Import", w_imp), ("Export", w_exp)):
                    affinity = 1.0
                    if flow == "Import" and iso in ("CHN", "KOR", "JPN") and c_en in ("Electronics", "Machinery", "Vehicles"):
                        affinity = 1.9
                    if flow == "Export" and iso in ("IND", "CHN", "JPN", "KOR") and c_en == "Petroleum Products":
                        affinity = 2.4
                    if flow == "Import" and iso in ("BRA", "IND", "EGY", "TUR") and c_en == "Food & Beverages":
                        affinity = 1.7
                    shock = 0.78 if (m.year == 2024 and m.month in (2, 3) and p_reg == "Asia") else 1.0
                    value = 4_200_000 * p_w * w * affinity * trend * season * shock * rng.uniform(0.80, 1.22)
                    tons = value / (usd_ton * rng.uniform(0.93, 1.07))
                    yield (m, STATS, flow, iso, p_en, p_ar, p_reg, c_en, c_ar, round(value, 2), round(tons, 2))


def population_rows(rng: random.Random):
    base_total = {"Capital": 2_450_000, "Northern": 980_000, "Southern": 860_000,
                  "Eastern": 1_420_000, "Western": 1_690_000, "Central": 1_130_000}
    growth = {"Capital": 0.027, "Northern": 0.012, "Southern": 0.010,
              "Eastern": 0.019, "Western": 0.021, "Central": 0.015}
    for year in range(2015, 2027):
        for r_en, r_ar, _ in REGIONS:
            total = base_total[r_en] * (1 + growth[r_en]) ** (year - 2015)
            for order, (age, share) in enumerate(zip(AGE_GROUPS, AGE_SHARE), start=1):
                # slow ageing: older cohorts gain share over time
                drift = 1.0 + (order - 4.5) * 0.004 * (year - 2015)
                for g_en, g_ar, g_share in (("Male", "ذكور", 0.515), ("Female", "إناث", 0.485)):
                    if order >= 8:
                        g_share = 1.0 - g_share  # women outlive men in the oldest cohorts
                    pop = total * share * drift * g_share * rng.uniform(0.985, 1.015)
                    yield (date(year, 1, 1), year, STATS, r_en, r_ar, g_en, g_ar, age, order, int(pop))


def weighted(rng: random.Random, items, weight_index):
    return rng.choices(items, weights=[i[weight_index] for i in items], k=1)[0]


def request_rows(rng: random.Random):
    req_id = 100_000
    day = REQ_START
    while day <= REQ_END:
        elapsed = (day - REQ_START).days
        trend = 1.0 + 0.0011 * elapsed
        weekend = 0.32 if day.weekday() in (4, 5) else 1.0  # Friday/Saturday weekend
        season = 1.0 + 0.16 * math.sin(2 * math.pi * (day.timetuple().tm_yday - 60) / 365.0)
        for org in (PLANNING, STATS):
            org_en, org_ar = ORG_NAMES[org]
            volume = (38 if org == PLANNING else 54) * trend * weekend * season
            for _ in range(max(0, int(rng.gauss(volume, volume * 0.14)))):
                req_id += 1
                s_en, s_ar, sla, _w = weighted(rng, SERVICES[org], 3)
                ch_en, ch_ar, _cw = weighted(rng, CHANNELS, 2)
                r_en, r_ar, _rw = weighted(rng, REGIONS, 2)
                segment = weighted(rng, SEGMENTS, 1)[0]
                created = datetime.combine(day, datetime.min.time()) + timedelta(
                    minutes=int(min(1439, max(0, rng.gauss(11.5 * 60, 190)))))
                age_days = (REQ_END - day).days
                roll = rng.random()
                if age_days <= 4 and roll < 0.55:
                    status = "In Progress"
                elif roll < 0.035:
                    status = "Rejected"
                elif roll < 0.085:
                    status = "Escalated"
                else:
                    status = "Completed"
                slow = 1.35 if ch_en in ("Service Center", "Call Center") else 0.90
                digital_gain = max(0.72, 1.0 - 0.00045 * elapsed)  # process improves over time
                res = sat = met = None
                if status != "In Progress":
                    res = round(max(0.3, rng.lognormvariate(math.log(sla * 0.62 * slow * digital_gain), 0.55)), 1)
                    if status == "Escalated":
                        res = round(res * 1.9, 1)
                    met = res <= sla
                    if rng.random() < 0.58:
                        mean = 4.45 if met else 2.9
                        mean -= 0.25 if status == "Rejected" else 0.0
                        sat = int(min(5, max(1, round(rng.gauss(mean, 0.75)))))
                yield (req_id, created, org, org_en, org_ar, s_en, s_ar, ch_en, ch_ar, r_en, r_ar,
                       segment, status, sla, res, met, sat)
        day += timedelta(days=1)


TABLES = [
    ("budget_execution", budget_rows),
    ("trade_flows", trade_rows),
    ("population", population_rows),
    ("service_requests", request_rows),
]


def main() -> int:
    dsn = os.environ.get("NXTBI_DEMO_ADMIN_DSN")
    if not dsn:
        print("NXTBI_DEMO_ADMIN_DSN is required", file=sys.stderr)
        return 2
    ro_role = os.environ.get("NXTBI_DEMO_RO_ROLE", "nxtbi_ro")
    force = os.environ.get("NXTBI_FORCE_SEED", "no").lower() in {"1", "true", "yes"}
    if "--if-missing" in sys.argv and not force:
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = %s "
                        "AND table_name = ANY(%s)", (SCHEMA, [t for t, _ in TABLES]))
            if cur.fetchone()[0] == len(TABLES):
                cur.execute(f"SELECT count(*) FROM {SCHEMA}.service_requests")
                if cur.fetchone()[0] > 0:
                    print(f"schema {SCHEMA} already seeded - skipping (NXTBI_FORCE_SEED=yes to rebuild)")
                    return 0
    rng = random.Random(20261117)
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(DDL)
        for table, generator in TABLES:
            rows = list(generator(rng))
            placeholders = "(" + ",".join(["%s"] * len(rows[0])) + ")"
            execute_values(cur, f"INSERT INTO {SCHEMA}.{table} VALUES %s", rows,
                           template=placeholders, page_size=5000)
            print(f"seeded {SCHEMA}.{table}: {len(rows)} rows")
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ro_role,))
        if cur.fetchone():
            cur.execute(f'GRANT USAGE ON SCHEMA {SCHEMA} TO "{ro_role}"')
            cur.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO "{ro_role}"')
            cur.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} GRANT SELECT ON TABLES TO "{ro_role}"')
            print(f"granted SELECT on schema {SCHEMA} to {ro_role}")
        else:
            print(f"role {ro_role} not found; skipped grants", file=sys.stderr)
        cur.execute(f"ANALYZE {SCHEMA}.budget_execution, {SCHEMA}.trade_flows, "
                    f"{SCHEMA}.population, {SCHEMA}.service_requests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
