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
from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_

from superset.daos.base import BaseDAO
from superset.extensions import db
from superset.models.saved_widget import SavedWidget


class SavedWidgetDAO(BaseDAO[SavedWidget]):
    id_column_name = "uuid"

    @classmethod
    def find_by_uuid(cls, ref: str) -> SavedWidget | None:
        """The saved widget with this uuid; ``None`` for a malformed uuid."""
        try:
            parsed = UUID(str(ref))
        except ValueError:
            return None
        return (
            db.session.query(SavedWidget)
            .filter(SavedWidget.uuid == parsed)
            .one_or_none()
        )

    @classmethod
    def find_readable(
        cls,
        user_id: int | None,
        *,
        see_all: bool,
        page: int,
        page_size: int,
    ) -> tuple[list[SavedWidget], int]:
        """
        One page of the saved widgets a caller may read, and how many there
        are in total.

        The filter is the list form of ``raise_for_widget_read``: every widget
        for ``see_all`` (admins); otherwise the caller's own widgets plus those
        binding a dataset the caller can read. The dataset test is the dataset
        list's own access filter, applied in the database so that paging stays
        exact. A widget whose dataset was deleted matches no dataset and is
        listed for its creator and admins only.

        :param user_id: The caller, ``None`` when there is no signed-in user
        :param see_all: Whether the caller reads every saved widget
        :param page: Zero-based page index
        :param page_size: Rows per page
        :returns: The page of widgets and the total number of readable widgets
        """
        # pylint: disable=import-outside-toplevel
        from superset.connectors.sqla.models import SqlaTable
        from superset.daos.dataset import DatasetDAO

        query = db.session.query(SavedWidget)
        if not see_all:
            if user_id is None:
                return [], 0
            # The dataset list's own access filter, as a subquery of ids.
            readable_datasets = DatasetDAO._apply_base_filter(  # pylint: disable=protected-access
                db.session.query(SqlaTable.id)
            )
            query = query.filter(
                or_(
                    SavedWidget.created_by_fk == user_id,
                    SavedWidget.dataset_id.in_(readable_datasets),
                )
            )
        count = query.count()
        widgets = (
            query.order_by(SavedWidget.changed_on.desc(), SavedWidget.uuid)
            .offset(page * page_size)
            .limit(page_size)
            .all()
        )
        return widgets, count
