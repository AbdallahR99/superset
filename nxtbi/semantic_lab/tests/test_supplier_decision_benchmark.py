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
"""Benchmark supplier late-delivery decisions with synthetic procurement data."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing

import pytest

CUTOFF = "2026-07-10 17:00:00"
ESCALATION_RATE = 0.50

_DECISION_SCHEMA = """
CREATE TABLE settings (cutoff_utc TEXT NOT NULL, escalation_rate REAL NOT NULL);
CREATE TABLE suppliers (
    workspace TEXT NOT NULL,
    supplier TEXT NOT NULL,
    manager TEXT NOT NULL,
    PRIMARY KEY (workspace, supplier)
);
CREATE TABLE order_lines (
    workspace TEXT NOT NULL,
    supplier TEXT NOT NULL,
    line_id INTEGER NOT NULL,
    due_utc TEXT,
    ordered_qty INTEGER NOT NULL,
    canceled INTEGER NOT NULL,
    buyer TEXT NOT NULL,
    PRIMARY KEY (workspace, supplier, line_id)
);
CREATE TABLE receipt_events (
    workspace TEXT NOT NULL,
    supplier TEXT NOT NULL,
    line_id INTEGER NOT NULL,
    receipt_id TEXT NOT NULL,
    received_utc TEXT NOT NULL,
    received_qty INTEGER NOT NULL
);

CREATE VIEW line_delivery AS
WITH receipts AS (
    -- A retry preserves the receipt ID and the event payload.
    SELECT DISTINCT workspace, supplier, line_id, receipt_id,
                    received_utc, received_qty
    FROM receipt_events
),
receipts_by_line AS (
    SELECT line.workspace, line.supplier, line.line_id, line.ordered_qty, line.buyer,
           COALESCE(SUM(receipt.received_qty)
                    FILTER (WHERE receipt.received_utc <= line.due_utc), 0) AS at_due,
           COALESCE(SUM(receipt.received_qty), 0) AS at_cutoff
    FROM order_lines AS line
    CROSS JOIN settings
    LEFT JOIN receipts AS receipt
        ON receipt.workspace = line.workspace
        AND receipt.supplier = line.supplier
        AND receipt.line_id = line.line_id
        AND receipt.received_utc <= settings.cutoff_utc
    WHERE line.canceled = 0 AND line.due_utc <= settings.cutoff_utc
    GROUP BY line.workspace, line.supplier, line.line_id, line.ordered_qty, line.buyer
)
SELECT workspace, supplier, line_id, buyer, at_due < ordered_qty AS is_late,
       MAX(ordered_qty - at_cutoff, 0) AS outstanding_qty
FROM receipts_by_line;

CREATE VIEW supplier_scores AS
WITH counts AS (
    SELECT supplier.workspace, supplier.supplier, supplier.manager,
           COUNT(line.line_id) AS eligible_lines,
           COALESCE(SUM(line.is_late), 0) AS late_lines
    FROM suppliers AS supplier
    LEFT JOIN line_delivery AS line USING (workspace, supplier)
    GROUP BY supplier.workspace, supplier.supplier, supplier.manager
),
rates AS (
    SELECT *, CAST(late_lines AS REAL) / NULLIF(eligible_lines, 0) AS late_rate
    FROM counts
)
SELECT *, late_rate >= settings.escalation_rate AS escalate
FROM rates CROSS JOIN settings;

CREATE VIEW workspace_scores AS
WITH rates AS (
    SELECT workspace, SUM(eligible_lines) AS eligible_lines,
           SUM(late_lines) AS late_lines,
           CAST(SUM(late_lines) AS REAL) / NULLIF(SUM(eligible_lines), 0) AS late_rate,
           AVG(late_rate) AS supplier_mean
    FROM supplier_scores
    GROUP BY workspace
)
SELECT *, late_rate >= settings.escalation_rate AS escalate
FROM rates CROSS JOIN settings;

CREATE VIEW delivery_exceptions AS
SELECT line.workspace, line.supplier, line.line_id, line.outstanding_qty,
       CASE WHEN line.outstanding_qty > 0 THEN 'incomplete'
            ELSE 'completed late' END AS delivery_status,
       CASE WHEN score.escalate THEN 'supplier review'
            WHEN line.outstanding_qty > 0 THEN 'expedite receipt'
            ELSE 'record delivery exception' END AS action,
       CASE WHEN score.escalate THEN score.manager ELSE line.buyer END AS owner,
       DATE(settings.cutoff_utc,
            CASE WHEN score.escalate THEN '+5 days' ELSE '+1 day' END) AS action_due
FROM line_delivery AS line
JOIN supplier_scores AS score USING (workspace, supplier)
CROSS JOIN settings
WHERE line.is_late;
"""


@pytest.fixture
def procurement() -> Iterator[sqlite3.Connection]:
    """Build a single-use procurement snapshot and decision views."""
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.executescript(_DECISION_SCHEMA)
        connection.execute(
            "INSERT INTO settings VALUES (?, ?)", (CUTOFF, ESCALATION_RATE)
        )
        connection.executemany(
            "INSERT INTO suppliers VALUES (?, ?, ?)",
            [
                ("North", "Aster", "Manager A"),
                ("North", "Birch", "Manager B"),
                ("North", "Cedar", "Manager C"),
                ("North", "Dune", "Manager D"),
                ("South", "Aster", "Manager South"),
            ],
        )
        connection.executemany(
            "INSERT INTO order_lines VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("North", "Aster", 101, "2026-07-08 17:00:00", 10, 0, "Buyer A"),
                ("North", "Aster", 102, "2026-07-08 17:00:00", 10, 0, "Buyer A"),
                ("North", "Aster", 103, "2026-07-09 17:00:00", 10, 0, "Buyer A"),
                ("North", "Aster", 104, CUTOFF, 10, 0, "Buyer A"),
                ("North", "Aster", 105, "2026-07-10 17:00:01", 10, 0, "Buyer A"),
                ("North", "Birch", 201, "2026-07-08 17:00:00", 10, 0, "Buyer B"),
                ("North", "Cedar", 201, "2026-07-08 17:00:00", 10, 0, "Buyer C"),
                ("North", "Cedar", 202, "2026-07-09 17:00:00", 10, 0, "Buyer C"),
                ("North", "Dune", 301, "2026-07-08 17:00:00", 10, 1, "Buyer D"),
                ("North", "Dune", 302, None, 10, 0, "Buyer D"),
                ("South", "Aster", 101, "2026-07-08 17:00:00", 10, 0, "Buyer South"),
            ],
        )
        connection.executemany(
            "INSERT INTO receipt_events VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("North", "Aster", 101, "R1", "2026-07-08 10:00:00", 6),
                ("North", "Aster", 101, "R1", "2026-07-08 10:00:00", 6),
                ("North", "Aster", 101, "R2", "2026-07-10 17:00:01", 4),
                ("North", "Aster", 102, "R1", "2026-07-08 10:00:00", 4),
                ("North", "Aster", 102, "R2", "2026-07-08 17:00:00", 6),
                ("North", "Aster", 103, "R1", "2026-07-09 16:00:00", 10),
                ("North", "Aster", 104, "R1", CUTOFF, 10),
                ("North", "Birch", 201, "R1", "2026-07-09 10:00:00", 10),
                ("North", "Cedar", 201, "R1", "2026-07-08 10:00:00", 6),
                ("North", "Cedar", 202, "R1", "2026-07-09 16:00:00", 10),
                ("South", "Aster", 101, "R1", "2026-07-08 10:00:00", 10),
            ],
        )
        yield connection


def test_supplier_rollup_retains_eligible_line_denominator(
    procurement: sqlite3.Connection,
) -> None:
    """Count each eligible line once and retain suppliers with no eligible lines."""
    assert procurement.execute(
        """
        SELECT workspace, supplier, eligible_lines, late_lines, late_rate, escalate,
               typeof(eligible_lines), typeof(late_rate)
        FROM supplier_scores
        ORDER BY workspace, supplier
        """
    ).fetchall() == [
        ("North", "Aster", 4, 1, 0.25, 0, "integer", "real"),
        ("North", "Birch", 1, 1, 1.0, 1, "integer", "real"),
        ("North", "Cedar", 2, 1, 0.5, 1, "integer", "real"),
        ("North", "Dune", 0, 0, None, None, "integer", "null"),
        ("South", "Aster", 1, 0, 0.0, 0, "integer", "real"),
    ]


def test_workspace_rate_uses_pooled_lines(procurement: sqlite3.Connection) -> None:
    """Prove the supplier average would reverse the workspace threshold decision."""
    (eligible, late, pooled_rate, supplier_mean, escalate) = procurement.execute(
        """
        SELECT eligible_lines, late_lines, late_rate, supplier_mean, escalate
        FROM workspace_scores
        WHERE workspace = 'North'
        """
    ).fetchone()
    assert (eligible, late, escalate) == (7, 3, 0)
    assert pooled_rate == pytest.approx(3 / 7)
    assert supplier_mean == pytest.approx(7 / 12)
    assert pooled_rate < 0.5 < supplier_mean


def test_late_delivery_exceptions_have_an_owner_and_due_date(
    procurement: sqlite3.Connection,
) -> None:
    """Distinguish late completions from open receipts and route each exception."""
    assert procurement.execute(
        """
        SELECT workspace, supplier, line_id, delivery_status, outstanding_qty,
               action, owner, action_due
        FROM delivery_exceptions
        ORDER BY workspace, supplier, line_id
        """
    ).fetchall() == [
        (
            "North",
            "Aster",
            101,
            "incomplete",
            4,
            "expedite receipt",
            "Buyer A",
            "2026-07-11",
        ),
        (
            "North",
            "Birch",
            201,
            "completed late",
            0,
            "supplier review",
            "Manager B",
            "2026-07-15",
        ),
        (
            "North",
            "Cedar",
            201,
            "incomplete",
            4,
            "supplier review",
            "Manager C",
            "2026-07-15",
        ),
    ]


def test_cutoff_advances_outstanding_and_eligibility_together(
    procurement: sqlite3.Connection,
) -> None:
    """Bring a new line and a final partial receipt into the snapshot together."""
    procurement.execute("UPDATE settings SET cutoff_utc = ?", ("2026-07-10 17:00:01",))
    assert procurement.execute(
        """
        SELECT eligible_lines, late_lines, late_rate, escalate
        FROM supplier_scores
        WHERE workspace = 'North' AND supplier = 'Aster'
        """
    ).fetchone() == (5, 2, 0.4, 0)
    assert procurement.execute(
        """
        SELECT line_id, delivery_status, outstanding_qty, action, owner, action_due
        FROM delivery_exceptions
        WHERE workspace = 'North' AND supplier = 'Aster'
        ORDER BY line_id
        """
    ).fetchall() == [
        (
            101,
            "completed late",
            0,
            "record delivery exception",
            "Buyer A",
            "2026-07-11",
        ),
        (105, "incomplete", 10, "expedite receipt", "Buyer A", "2026-07-11"),
    ]
