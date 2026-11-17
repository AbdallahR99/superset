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
"""
Race-free writes of the ``json_metadata`` column that holds a v2 document.

The document shares one text column with the rest of a dashboard's metadata,
and that column has more than one writer (the Dashboard v2 API, the classic
dashboard update, version restore, import). Every writer that touches a v2
dashboard goes through :func:`compare_and_swap_json_metadata`: an ``UPDATE``
that only matches while the column still holds the value the writer read.
The statement is atomic on every supported database, so a lost update is
impossible without relying on row locks, provided the comparison is exact.

The comparison is exact on SQLite and PostgreSQL, which compare text byte by
byte. MySQL and MariaDB compare text by the column's collation, which by
default ignores case, accents and trailing spaces, so there the statement
compares the UTF-8 bytes of both sides instead (see
:func:`_unchanged_condition`).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.sql.elements import ClauseElement

from superset import db
from superset.dashboard_v2.document import load_stored_document, V2_DOCUMENT_KEY
from superset.models.dashboard import Dashboard
from superset.utils import json

#: How often a writer re-reads and retries after losing a compare-and-swap.
MAX_WRITE_ATTEMPTS = 3

# SQLSTATE classes/codes of a transaction the database aborted because of a
# concurrent one: serialization failure, deadlock, lock not available.
_CONCURRENCY_SQLSTATES = frozenset({"40001", "40P01", "55P03"})
# MySQL/MariaDB error numbers: deadlock, lock wait timeout.
_CONCURRENCY_MYSQL_ERRNOS = frozenset({1205, 1213})
_SQLITE_LOCKED_MESSAGES = ("database is locked", "database table is locked")


def read_current_json_metadata(pk: int, lock: bool = True) -> str | None:
    """
    The committed ``json_metadata`` of a dashboard, read past the session's
    identity map.

    A writer reads with ``lock`` set, which asks for a row lock. Where the
    database has one it returns the latest committed value even under
    snapshot isolation and makes concurrent writers queue instead of
    retrying; where it has none (SQLite) the clause is omitted. Correctness
    rests on the compare-and-swap that follows, not on the lock.
    """
    statement = select(Dashboard.json_metadata).where(Dashboard.id == pk)
    if lock:
        statement = statement.with_for_update()
    return db.session.execute(statement).scalar_one_or_none()


def compare_and_swap_json_metadata(pk: int, expected: str | None, new: str) -> bool:
    """
    Store ``new`` as the dashboard's ``json_metadata`` if, and only if, the
    column still holds ``expected``.

    :returns: Whether the value was stored. ``False`` means another writer
        changed the column after ``expected`` was read; nothing was written.
    """
    table = Dashboard.__table__
    unchanged = _unchanged_condition(expected, db.session.get_bind().dialect.name)
    result = db.session.execute(
        update(table).where(table.c.id == pk, unchanged).values(json_metadata=new)
    )
    return result.rowcount == 1


#: Dialects whose text comparison follows a collation instead of the bytes.
_COLLATING_DIALECTS = frozenset({"mysql", "mariadb"})


def _unchanged_condition(expected: str | None, dialect_name: str) -> ClauseElement:
    """
    The ``WHERE`` condition "``json_metadata`` still holds ``expected``".

    On MySQL and MariaDB ``=`` on a text column follows the column's
    collation, under which values differing only in case, accents or trailing
    spaces are equal. Both sides are therefore converted to ``utf8mb4`` and
    compared as binary strings, which is exact whatever character set and
    collation the column and the connection use.
    """
    column = Dashboard.__table__.c.json_metadata
    if expected is None:
        return column.is_(None)
    if dialect_name in _COLLATING_DIALECTS:
        return text(
            "CAST(CONVERT(dashboards.json_metadata USING utf8mb4) AS BINARY) = "
            "CAST(CONVERT(:expected_json_metadata USING utf8mb4) AS BINARY)"
        ).bindparams(expected_json_metadata=expected)
    return column == expected


def is_concurrent_write_failure(ex: BaseException) -> bool:
    """
    Whether a database error means "another transaction got in the way"
    (serialization failure, deadlock, lock timeout, SQLite busy) rather than
    a defect, so the caller can answer with a conflict instead of a failure.
    """
    if isinstance(ex, StaleDataError):
        return True
    if not isinstance(ex, DBAPIError):
        return False
    original = ex.orig
    sqlstate = getattr(original, "pgcode", None) or getattr(original, "sqlstate", None)
    if isinstance(sqlstate, str) and sqlstate in _CONCURRENCY_SQLSTATES:
        return True
    arguments = getattr(original, "args", ())
    if arguments and arguments[0] in _CONCURRENCY_MYSQL_ERRNOS:
        return True
    message = str(original).lower()
    return any(text in message for text in _SQLITE_LOCKED_MESSAGES)


def write_metadata_keeping_document(pk: int, metadata: dict[str, Any]) -> str | None:
    """
    Store a classic dashboard update's metadata without touching the v2
    document: whatever ``metadata`` holds under ``v2_document`` is replaced by
    the document stored at the time of the write.

    Used by writers other than the Dashboard v2 API, which must neither change
    the document nor roll back a save that happened after they loaded the row.

    :returns: The ``json_metadata`` that was stored, or ``None`` when the
        write kept losing against concurrent writers and nothing was stored
    """
    for _ in range(MAX_WRITE_ATTEMPTS):
        current_json = read_current_json_metadata(pk)
        merged = {
            key: value for key, value in metadata.items() if key != V2_DOCUMENT_KEY
        }
        if (document := load_stored_document(current_json)) is not None:
            merged[V2_DOCUMENT_KEY] = document
        new_json = json.dumps(merged)
        if compare_and_swap_json_metadata(pk, current_json, new_json):
            return new_json
    return None
