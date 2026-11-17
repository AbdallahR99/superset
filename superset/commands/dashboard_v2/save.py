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
Write side of the Dashboard v2 document.

Every save validates the whole document server-side and is guarded by
optimistic concurrency: an update names the revision it was based on and is
refused with a conflict when the stored revision differs, so one editor never
silently overwrites another's save.
"""

from __future__ import annotations

from functools import partial
from typing import Any

from flask import current_app
from marshmallow import ValidationError
from sqlalchemy import select

from superset import db, security_manager
from superset.commands.base import BaseCommand
from superset.commands.dashboard_v2.exceptions import (
    DashboardV2ConflictError,
    DashboardV2ForbiddenError,
    DashboardV2InvalidError,
    DashboardV2NotFoundError,
    DashboardV2SaveFailedError,
)
from superset.commands.utils import populate_subjects
from superset.daos.dashboard import DashboardDAO
from superset.dashboard_v2.document import (
    document_revision,
    DocumentValidationError,
    DocumentWidget,
    INITIAL_REVISION,
    load_stored_document,
    normalize_document,
    with_revision,
    write_stored_document,
)
from superset.exceptions import SupersetSecurityException
from superset.models.dashboard import Dashboard
from superset.utils import json
from superset.utils.decorators import on_error, transaction
from superset.widgets.registry import registry


def validate_widget_props(widgets: list[DocumentWidget]) -> dict[str, Any]:
    """
    Run each registered widget type's commit-time validation over its props.

    :returns: Validation errors keyed by node id; empty when all props pass
    """
    errors: dict[str, Any] = {}
    for widget in widgets:
        widget_cls = registry.get(widget.widget_type)
        if widget_cls is None:
            errors[widget.node_id] = [
                {"loc": ["type"], "message": "Unknown widget type."}
            ]
            continue
        if widget_errors := widget_cls.validate_control_values(widget.props):
            errors[widget.node_id] = widget_errors
    return errors


def normalize_and_validate(document: Any) -> dict[str, Any]:
    """
    Validate a submitted document against the structural rules, the configured
    limits and the widget registry.

    :returns: The normalized document, without a revision
    :raises DashboardV2InvalidError: If anything about the document is invalid
    """
    try:
        stored, widgets = normalize_document(document, known_types=set(registry))
    except DocumentValidationError as ex:
        raise DashboardV2InvalidError(str(ex)) from ex
    if errors := validate_widget_props(widgets):
        raise DashboardV2InvalidError("Widget props failed validation.", errors)
    return stored


class CreateDashboardV2Command(BaseCommand):
    """Create a dashboard holding a v2 document at the initial revision."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._properties = data.copy()
        self._stored: dict[str, Any] = {}

    @transaction(on_error=partial(on_error, reraise=DashboardV2SaveFailedError))
    def run(self) -> Dashboard:
        """Create the dashboard with the caller as its editor."""
        self.validate()
        attributes: dict[str, Any] = {
            "dashboard_title": self._properties["dashboard_title"],
            "json_metadata": write_stored_document(
                json.dumps({}), with_revision(self._stored, INITIAL_REVISION)
            ),
            "editors": self._properties["editors"],
        }
        if viewers := self._properties.get("viewers"):
            attributes["viewers"] = viewers
        dashboard = DashboardDAO.create(attributes=attributes)
        db.session.flush()
        if after_create := current_app.config.get("AFTER_ASSET_CREATE"):
            after_create(dashboard, "dashboard")
        return dashboard

    def validate(self) -> None:
        """Validate the document and resolve the editors and default viewers."""
        self._stored = normalize_and_validate(self._properties["document"])
        exceptions: list[ValidationError] = []
        populate_subjects(self._properties, exceptions)
        if exceptions:
            raise DashboardV2InvalidError(
                "Invalid editors.",
                {"editors": [exception.messages for exception in exceptions]},
            )


class UpdateDashboardV2Command(BaseCommand):
    """
    Replace a v2 dashboard's document, provided it is still at the revision
    the caller based the change on.
    """

    def __init__(self, pk: int, data: dict[str, Any], base_revision: int) -> None:
        self._pk = pk
        self._properties = data.copy()
        self._base_revision = base_revision
        self._model: Dashboard | None = None
        self._stored: dict[str, Any] = {}

    @transaction(on_error=partial(on_error, reraise=DashboardV2SaveFailedError))
    def run(self) -> Dashboard:
        """
        Store the document at ``base_revision + 1``.

        The revision is compared again while the dashboard row is locked, so
        of two saves racing from the same base exactly one is stored and the
        other is refused.

        :raises DashboardV2ConflictError: If the stored revision is not the
            one the change was based on
        """
        self.validate()
        assert self._model is not None
        json_metadata = self._lock_json_metadata()
        current = load_stored_document(json_metadata)
        if current is None:
            raise DashboardV2NotFoundError(str(self._pk))
        self._raise_for_stale_revision(current)
        attributes: dict[str, Any] = {
            "json_metadata": write_stored_document(
                json_metadata, with_revision(self._stored, self._base_revision + 1)
            )
        }
        if title := self._properties.get("dashboard_title"):
            attributes["dashboard_title"] = title
        return DashboardDAO.update(self._model, attributes=attributes)

    def validate(self) -> None:
        """
        Check existence, editorship, the revision and the document, in that
        order, before any lock is taken.
        """
        self._model = DashboardDAO.find_by_id(self._pk)
        current = (
            load_stored_document(self._model.json_metadata)
            if self._model is not None
            else None
        )
        if self._model is None or current is None:
            raise DashboardV2NotFoundError(str(self._pk))
        try:
            security_manager.raise_for_editorship(self._model)
        except SupersetSecurityException as ex:
            raise DashboardV2ForbiddenError() from ex
        self._raise_for_stale_revision(current)
        self._stored = normalize_and_validate(self._properties["document"])

    def _raise_for_stale_revision(self, current: dict[str, Any]) -> None:
        """Refuse the update when the stored document moved past its base."""
        if (revision := document_revision(current)) != self._base_revision:
            raise DashboardV2ConflictError(revision)

    def _lock_json_metadata(self) -> Any:
        """
        Read the committed ``json_metadata`` while holding a row lock that
        lasts until the surrounding transaction ends.

        The locking read returns the latest committed value even when the row
        was loaded earlier in the transaction, and makes a concurrent save
        wait here until this one has committed. SQLite has no row locks and
        ignores the clause.
        """
        return db.session.execute(
            select(Dashboard.json_metadata)
            .where(Dashboard.id == self._pk)
            .with_for_update()
        ).scalar_one_or_none()
