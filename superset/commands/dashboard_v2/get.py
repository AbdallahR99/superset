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
"""Read side of the Dashboard v2 document."""

from __future__ import annotations

from typing import Any

from superset import security_manager
from superset.commands.base import BaseCommand
from superset.commands.dashboard_v2.exceptions import (
    DashboardV2ForbiddenError,
    DashboardV2NotFoundError,
)
from superset.daos.dashboard import EmbeddedDashboardDAO
from superset.dashboard_v2.access import can_read_document
from superset.dashboard_v2.document import (
    document_revision,
    load_stored_document,
    without_revision,
)
from superset.exceptions import SupersetSecurityException
from superset.models.dashboard import Dashboard, is_uuid


def resolve_dashboard(ref: str, embedded_only: bool = False) -> Dashboard | None:
    """
    A dashboard by embedded uuid, dashboard uuid, slug or integer pk (in that
    order) — the one address shape every block endpoint accepts.

    :param ref: The reference taken from the URL
    :param embedded_only: Accept an embedded uuid and nothing else
    """
    if is_uuid(ref) and (embedded := EmbeddedDashboardDAO.find_by_id(ref)) is not None:
        return embedded.dashboard
    if embedded_only:
        return None
    return Dashboard.get(ref)


def load_v2_dashboard(
    ref: str, embedded_only: bool = False
) -> tuple[Dashboard, dict[str, Any]]:
    """
    Resolve ``ref`` to an accessible v2 dashboard and its stored document.

    Looks the row up directly and gates it with ``raise_for_access`` — the
    same object-level check for guests and logged-in users alike; the list
    base filter is not an access check for a single dashboard — and then with
    the document read rule of :mod:`superset.dashboard_v2.access`, since a v2
    dashboard has no member charts for ``raise_for_access`` to judge by.

    :raises DashboardV2NotFoundError: If nothing matches or it is not a v2
        dashboard
    :raises DashboardV2ForbiddenError: If the caller may not read it
    """
    dashboard = resolve_dashboard(ref, embedded_only)
    if dashboard is None:
        raise DashboardV2NotFoundError(ref)
    try:
        dashboard.raise_for_access()
    except SupersetSecurityException as ex:
        raise DashboardV2ForbiddenError() from ex
    stored = load_stored_document(dashboard.json_metadata)
    if stored is None:
        raise DashboardV2NotFoundError(ref)
    if not can_read_document(dashboard, stored):
        raise DashboardV2ForbiddenError()
    return dashboard, stored


def serialize_dashboard(dashboard: Dashboard, stored: dict[str, Any]) -> dict[str, Any]:
    """
    The API representation of a v2 dashboard.

    The revision travels beside the document, not inside it. The domains an
    embed is allowed on are configuration for editors and are withheld from
    embedded guests.
    """
    embedded = dashboard.embedded[0] if dashboard.embedded else None
    embedded_summary: dict[str, Any] | None = None
    if embedded:
        embedded_summary = {"uuid": str(embedded.uuid)}
        if not security_manager.is_guest_user():
            embedded_summary["allowed_domains"] = embedded.allowed_domains
    return {
        "id": dashboard.id,
        "uuid": str(dashboard.uuid),
        "dashboard_title": dashboard.dashboard_title,
        "changed_on": dashboard.changed_on,
        "revision": document_revision(stored),
        "document": without_revision(stored),
        "embedded": embedded_summary,
    }


class GetDashboardV2Command(BaseCommand):
    """Load a v2 dashboard by embedded uuid, dashboard uuid, slug or pk."""

    def __init__(self, ref: str, embedded_only: bool = False) -> None:
        self._ref = ref
        self._embedded_only = embedded_only

    def run(self) -> dict[str, Any]:
        """Return the serialized dashboard, enforcing object-level access."""
        dashboard, stored = load_v2_dashboard(self._ref, self._embedded_only)
        return serialize_dashboard(dashboard, stored)

    def validate(self) -> None:
        """Nothing to validate ahead of the lookup."""
