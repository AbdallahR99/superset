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
Object-level read access to a v2 dashboard's document.

``Dashboard.raise_for_access`` falls back, for a published dashboard without
explicit viewers, to "no member charts, or one member chart's dataset is
accessible". A v2 dashboard never has member charts — its widgets live inline
in the document — so that fallback would admit every authenticated user to a
document full of dataset bindings, SQL metrics and filter literals. The rule
here closes that gap by looking at the datasets the document itself binds.
"""

from __future__ import annotations

from typing import Any

from superset import db, security_manager
from superset.models.dashboard import Dashboard
from superset.widgets.data import widget_dataset_id
from superset.widgets.registry import registry


def bound_dataset_ids(stored: dict[str, Any]) -> set[int]:
    """
    The ids of every dataset a stored document's nodes bind, each resolved
    the way the node's widget type reads it.
    """
    nodes = stored.get("nodes")
    if not isinstance(nodes, dict):
        return set()
    return {
        dataset_id
        for node in nodes.values()
        if isinstance(node, dict)
        and (
            dataset_id := widget_dataset_id(
                registry.get(str(node.get("type"))), node.get("props")
            )
        )
        is not None
    }


def can_access_bound_datasets(dataset_ids: set[int]) -> bool:
    """
    Whether the caller may read every one of the datasets; a dataset that no
    longer exists counts as inaccessible.
    """
    # pylint: disable=import-outside-toplevel
    from superset.connectors.sqla.models import SqlaTable

    datasets = db.session.query(SqlaTable).filter(SqlaTable.id.in_(dataset_ids)).all()
    if {dataset.id for dataset in datasets} != dataset_ids:
        return False
    return all(security_manager.can_access_datasource(dataset) for dataset in datasets)


def can_read_document(dashboard: Dashboard, stored: dict[str, Any]) -> bool:
    """
    Whether the caller, who already passed ``Dashboard.raise_for_access``, may
    read the document.

    Admins, editors, viewers and embedded guests (whose token was matched to
    the dashboard by ``raise_for_access``) may. Anyone else was admitted by
    the datasource fallback alone and needs access to every dataset the
    document binds; a document that binds none is for editors and viewers
    only.
    """
    if security_manager.is_guest_user():
        return True
    if security_manager.is_admin() or security_manager.is_editor(dashboard):
        return True
    if dashboard.viewers and security_manager.is_viewer(dashboard):
        return True
    if not (dataset_ids := bound_dataset_ids(stored)):
        return False
    return can_access_bound_datasets(dataset_ids)
