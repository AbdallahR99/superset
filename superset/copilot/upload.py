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

"""Import a browser-selected CSV through Superset's native file upload command."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import PurePosixPath
from typing import TypedDict
from uuid import UUID

import pandas as pd
from flask import current_app
from sqlalchemy import column, func, select
from sqlalchemy.sql import quoted_name
from werkzeug.datastructures import FileStorage

from superset import db, security_manager
from superset.commands.database.exceptions import DatabaseUploadFailed
from superset.commands.database.uploaders.base import UploadCommand
from superset.commands.database.uploaders.csv_reader import CSVReader
from superset.connectors.sqla.models import SqlaTable, SqlMetric
from superset.daos.database import DatabaseDAO
from superset.models.core import Database
from superset.sql.parse import Table
from superset.utils import json
from superset.utils.decorators import transaction
from superset.views.database.validators import schema_allows_file_upload

logger = logging.getLogger(__name__)
CSV_MAX_BYTES = 10 * 1024 * 1024
_UPLOAD_KEY = "nxtbi_copilot_csv"
_ISO_DATE = r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}[^\r\n]*)?"
_METRIC_COLUMN = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]{0,62}\Z")
_IDENTIFIERS = {
    "id",
    "key",
    "code",
    "number",
    "no",
    "ref",
    "reference",
    "sku",
    "zip",
    "postal",
    "phone",
    "year",
    "month",
    "day",
    "lat",
    "lon",
    "latitude",
    "longitude",
}
_ADDITIVE = {"amount", "quantity", "units", "revenue", "sales", "fee", "spent", "spend"}
_TRANSACTIONS = {"order", "line", "invoice", "payment", "transaction", "charge"}
_NON_ADDITIVE = {
    "avg",
    "average",
    "per",
    "unit",
    "rate",
    "pct",
    "percent",
    "ratio",
    "balance",
}


class CSVUploadError(Exception):
    """A public, bounded upload failure without request or connector details."""

    def __init__(self, status: int, message: str, **details: str) -> None:
        """Carry only the explicitly safe response fields."""
        super().__init__(message)
        self.status = status
        self.details = details


class UploadedDataset(TypedDict):
    """Reference the persisted dataset without returning file contents."""

    id: int
    name: str


def _name_and_fingerprint(file: FileStorage) -> tuple[str, str]:
    """Return a safe display name and hash after checking the actual file bytes."""
    filename = PurePosixPath((file.filename or "").replace("\\", "/"))
    allowed = {ext.lower() for ext in current_app.config["ALLOWED_EXTENSIONS"]}
    if filename.suffix.lower() != ".csv" or "csv" not in allowed:
        raise CSVUploadError(422, "Choose a .csv file with a header row.")
    cap = current_app.config.get("UPLOAD_MAX_FILE_SIZE_BYTES")
    maximum = min(CSV_MAX_BYTES, cap) if isinstance(cap, int) else CSV_MAX_BYTES
    digest = hashlib.sha256()
    size = 0
    try:
        while chunk := file.stream.read(min(128 * 1024, maximum - size + 1)):
            size += len(chunk)
            if size > maximum:
                raise CSVUploadError(413, "The CSV exceeds the file size limit.")
            digest.update(chunk)
    finally:
        file.stream.seek(0)
    if not size:
        raise CSVUploadError(422, "The CSV is empty.")
    name = "".join(char for char in filename.stem if char.isprintable()).strip()
    return f"{name[:120] or 'dataset'}.csv", digest.hexdigest()


def _target() -> tuple[Database, str | None]:
    """Resolve one destination authorized by Superset's upload and schema rules."""
    configured = current_app.config.get("NXTBI_COPILOT_CSV_DATABASE")
    candidates: list[tuple[Database, str | None]] = []
    for database in DatabaseDAO.find_all():
        if (
            not database.allow_file_upload
            or (configured and database.database_name != configured)
            or not database.db_engine_spec.supports_file_upload
        ):
            continue
        catalog = database.get_default_catalog()
        if allowed := database.get_schema_access_for_file_upload():
            accessible = security_manager.get_schemas_accessible_by_user(
                database, catalog, allowed, hierarchical=True
            )
            candidates.extend((database, schema) for schema in allowed & accessible)
        elif security_manager.can_access_database(database):
            schema = database.get_default_schema(catalog)
            if schema_allows_file_upload(database, schema, engine_resolved=True):
                candidates.append((database, schema))

    if preferred_schema := current_app.config.get("NXTBI_COPILOT_CSV_SCHEMA"):
        candidates = [entry for entry in candidates if entry[1] == preferred_schema]

    if not candidates:
        raise CSVUploadError(
            409,
            "Ask an administrator to enable an accessible CSV upload destination.",
            code="upload_destination",
        )
    if len(candidates) > 1:
        raise CSVUploadError(
            409,
            "More than one CSV upload destination is available. Ask an administrator "
            "to select one database and schema for Copilot.",
            code="upload_destination",
        )
    return candidates[0]


class _CSVReader(CSVReader):
    """Use the native reader and infer only dates supported by all observed values."""

    def __init__(self) -> None:
        super().__init__({"already_exists": "fail", "skip_blank_lines": True})
        self.attempted_write = False
        self.written = False
        self.numeric: list[str] = []

    def file_to_dataframe(self, file: FileStorage) -> pd.DataFrame:
        """Infer dates from ISO data without changing non-date columns."""
        frame = super().file_to_dataframe(file)
        if frame.empty:
            raise CSVUploadError(422, "The CSV must contain at least one data row.")
        if len(frame.columns) > 256:
            raise CSVUploadError(422, "The CSV must have 256 columns or fewer.")
        for name in frame.select_dtypes(include=["object", "string"]).columns:
            values = frame[name].dropna()
            if (
                values.empty
                or not values.astype("string").str.fullmatch(_ISO_DATE).all()
            ):
                continue
            dates = pd.to_datetime(
                frame[name], format="ISO8601", errors="coerce", utc=True
            )
            if dates.notna().equals(frame[name].notna()):
                frame[name] = dates
        self.numeric = [
            name
            for name in frame.select_dtypes(include="number").columns
            if _METRIC_COLUMN.fullmatch(name)
            and not _IDENTIFIERS.intersection(name.lower().split("_"))
        ][:12]
        return frame

    def read(
        self,
        file: FileStorage,
        database: Database,
        table_name: str,
        schema_name: str | None,
    ) -> None:
        """Record the completed physical write separately from metadata registration."""
        frame = self.file_to_dataframe(file)
        self.attempted_write = True
        self._dataframe_to_database(frame, database, table_name, schema_name)
        self.written = True


def _lookup(database: Database, table: Table) -> SqlaTable | None:
    """Find the active physical dataset for a server-generated name."""
    return db.session.scalars(
        select(SqlaTable).where(
            SqlaTable.database_id == database.id,
            SqlaTable.table_name == table.table,
            SqlaTable.schema == table.schema,
            SqlaTable.catalog == table.catalog,
        )
    ).one_or_none()


def _add_metrics(dataset: SqlaTable, numeric: list[str]) -> None:
    """Create bounded metrics using only reflected columns and SQLAlchemy quoting."""
    columns = {item.column_name for item in dataset.columns}
    dialect = dataset.database.get_dialect()
    metrics = []
    for name in numeric:
        if name not in columns:
            continue
        parts = set(name.lower().split("_"))
        operations = ["avg"]
        if not parts & _NON_ADDITIVE and (
            parts & _ADDITIVE or ("total" in parts and parts & _TRANSACTIONS)
        ):
            operations.append("sum")
        for operation in operations:
            aggregate = func.avg if operation == "avg" else func.sum
            expression = aggregate(column(quoted_name(name, quote=True)))
            label = "Average" if operation == "avg" else "Sum"
            metrics.append(
                SqlMetric(
                    metric_name=f"{operation}_{name}",
                    metric_type=operation,
                    verbose_name=f"{label} of {name}",
                    expression=str(expression.compile(dialect=dialect)),
                )
            )
    dataset.add_missing_metrics(metrics)


@transaction(on_error=None)
def _import_csv(
    database: Database,
    table: Table,
    file: FileStorage,
    reader: _CSVReader,
    actor_id: int,
    fingerprint: str,
    display_name: str,
) -> UploadedDataset:
    """Register the upload and generated metrics in one metadata transaction."""
    if dataset := _lookup(database, table):
        extra = json.loads(dataset.extra or "{}")
        receipt = extra.get(_UPLOAD_KEY) if isinstance(extra, dict) else None
        if (
            dataset.created_by_fk != actor_id
            or not security_manager.can_access_datasource(dataset)
            or not isinstance(receipt, dict)
            or receipt.get("sha256") != fingerprint
            or not isinstance(receipt.get("name"), str)
        ):
            raise CSVUploadError(
                409,
                "This upload conflicts with an existing dataset.",
                code="upload_conflict",
            )
        return {"id": dataset.id, "name": receipt["name"]}

    UploadCommand(database.id, table.table, file, table.schema, reader).run()
    dataset = _lookup(database, table)
    if not dataset or not security_manager.can_access_datasource(dataset):
        raise RuntimeError("Could not verify access to the registered dataset.")
    extra = json.loads(dataset.extra or "{}")
    extra[_UPLOAD_KEY] = {"sha256": fingerprint, "name": display_name}
    dataset.extra = json.dumps(extra)
    if not dataset.description:
        dataset.description = f"Uploaded through Copilot from {display_name}."
    _add_metrics(dataset, reader.numeric)
    return {"id": dataset.id, "name": display_name}


def _table_exists(database: Database, table: Table) -> bool:
    """Check for a concurrent durable write without exposing driver errors."""
    try:
        return database.has_table(table)
    except Exception as ex:  # pylint: disable=broad-except
        logger.warning("Copilot CSV write check ended with %s", type(ex).__name__)
        return False


def upload_csv_dataset(
    file: FileStorage, upload_id: UUID, actor_id: int
) -> UploadedDataset:
    """Import a new, actor-scoped dataset and make identical retries safe."""
    display_name, fingerprint = _name_and_fingerprint(file)
    database, schema = _target()
    # PostgreSQL folds and truncates identifiers. Keep the complete token within
    # its default 63-byte identifier limit and use only ASCII identifier bytes.
    operation = hashlib.sha256(f"{actor_id}:{upload_id}".encode()).hexdigest()[:24]
    name, schema = database.db_engine_spec.normalize_table_name_for_upload(
        f"copilot_csv_{operation}", schema
    )
    table = Table(name, schema, database.get_default_catalog())
    reader = _CSVReader()
    try:
        return _import_csv(
            database, table, file, reader, actor_id, fingerprint, display_name
        )
    except CSVUploadError:
        raise
    except DatabaseUploadFailed as ex:
        if not reader.attempted_write:
            raise CSVUploadError(
                422, "The CSV could not be imported. Check its format."
            ) from ex
        if _table_exists(database, table):
            raise CSVUploadError(
                409,
                "The CSV import is already in progress. Retry shortly.",
                code="upload_conflict",
            ) from ex
        raise CSVUploadError(
            503, "The CSV upload destination could not write the table."
        ) from ex
    except Exception as ex:  # pylint: disable=broad-except
        logger.warning("Copilot CSV registration ended with %s", type(ex).__name__)
        if reader.written:
            raise CSVUploadError(
                500,
                f'Table "{name}" was written. Ask an administrator to check its '
                "dataset registration before importing again.",
                code="upload_registration",
                table=name,
            ) from ex
        raise CSVUploadError(503, "The CSV upload destination is unavailable.") from ex
