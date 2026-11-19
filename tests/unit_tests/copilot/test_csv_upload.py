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

"""Coverage for the native Copilot CSV import boundary."""

from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from flask import current_app
from sqlalchemy.orm import Session
from werkzeug.datastructures import FileStorage

from superset.connectors.sqla.models import SqlaTable
from superset.copilot import upload
from superset.models.core import Database
from superset.utils.core import override_user

ORDERS = b"order_id,order_date,order_total,unit_price\n100,2026-01-02,23.75,23.75\n"


def _file(contents: bytes = ORDERS, name: str = "Orders.csv") -> FileStorage:
    """Provide a seekable file with the same interface as a multipart upload."""
    return FileStorage(stream=BytesIO(contents), filename=name)


def test_upload_checks_bytes_and_resets_the_stream() -> None:
    file = _file()
    stem, fingerprint = upload._name_and_fingerprint(file)
    assert stem == "Orders.csv"
    assert len(fingerprint) == 64
    assert file.stream.tell() == 0
    with (
        patch.dict(current_app.config, {"UPLOAD_MAX_FILE_SIZE_BYTES": 20}),
        pytest.raises(upload.CSVUploadError) as too_large,
    ):
        upload._name_and_fingerprint(file)
    assert too_large.value.status == 413
    assert file.stream.tell() == 0
    with pytest.raises(upload.CSVUploadError) as unsupported:
        upload._name_and_fingerprint(_file(name="Orders.xlsx"))
    assert unsupported.value.status == 422


def test_upload_detects_temporal_columns_but_excludes_numeric_identifiers() -> None:
    reader = upload._CSVReader()
    frame = reader.file_to_dataframe(_file())
    assert str(frame["order_date"].dtype).startswith("datetime64")
    assert reader.numeric == ["order_total", "unit_price"]


def test_csv_upload_registers_a_real_table_and_never_replaces_it(
    session: Session, tmp_path: Path
) -> None:
    SqlaTable.metadata.create_all(session.get_bind())
    database = Database(
        database_name="CSV destination",
        sqlalchemy_uri=f"sqlite:///{tmp_path / 'dataset.sqlite'}",
        allow_file_upload=True,
    )
    session.add(database)
    session.commit()
    operation = uuid4()
    actor = MagicMock(id=42, is_anonymous=False)

    with (
        override_user(actor),
        patch.object(
            upload.security_manager, "can_access_all_databases", return_value=True
        ),
        patch.object(upload.security_manager, "can_access_database", return_value=True),
        patch.object(
            upload.security_manager, "can_access_datasource", return_value=True
        ),
    ):
        result = upload.upload_csv_dataset(_file(), operation, actor.id)
        assert (
            upload.upload_csv_dataset(_file(name="Renamed.csv"), operation, actor.id)
            == result
        )
        with pytest.raises(upload.CSVUploadError) as conflicting:
            upload.upload_csv_dataset(
                _file(ORDERS.replace(b"23.75", b"99.00"), name="Renamed.csv"),
                operation,
                actor.id,
            )
    assert conflicting.value.details == {"code": "upload_conflict"}
    table = session.get(SqlaTable, result["id"])
    assert table is not None
    assert table.created_by_fk == actor.id
    assert {metric.metric_name for metric in table.metrics} == {
        "count",
        "avg_order_total",
        "sum_order_total",
        "avg_unit_price",
    }
    assert table.database.has_table(upload.Table(table.table_name, table.schema))
