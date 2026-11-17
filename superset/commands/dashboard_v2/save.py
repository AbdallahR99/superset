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
silently overwrites another's save. The write itself is a compare-and-swap
(see :mod:`superset.dashboard_v2.storage`), and the representation a save
answers with is built inside the transaction that stored it.
"""

from __future__ import annotations

import logging
import uuid as uuid_module
from typing import Any

from flask import current_app
from marshmallow import ValidationError
from pydantic import BaseModel, ValidationError as PydanticValidationError
from sqlalchemy.exc import SQLAlchemyError

from superset import db, security_manager
from superset.commands.base import BaseCommand
from superset.commands.dashboard_v2.exceptions import (
    DashboardV2ConflictError,
    DashboardV2ForbiddenError,
    DashboardV2InvalidError,
    DashboardV2NotFoundError,
    DashboardV2SaveFailedError,
)
from superset.commands.dashboard_v2.get import serialize_dashboard
from superset.commands.utils import populate_subjects
from superset.daos.dashboard import DashboardDAO
from superset.dashboard_v2.access import can_read_document
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
from superset.dashboard_v2.node_types import (
    accepted_extension_types,
    STRUCTURAL_CONTAINER_TYPES,
)
from superset.dashboard_v2.storage import (
    compare_and_swap_json_metadata,
    is_concurrent_write_failure,
    MAX_WRITE_ATTEMPTS,
    read_current_json_metadata,
)
from superset.exceptions import SupersetSecurityException
from superset.models.dashboard import Dashboard
from superset.models.helpers import skip_visibility_filter
from superset.utils import json
from superset.utils.core import get_user_id
from superset.utils.decorators import transaction
from superset.widgets.registry import registry

logger = logging.getLogger(__name__)

_MISSING = "missing"


def _model_errors(
    model: type[BaseModel], props: dict[str, Any]
) -> list[dict[str, Any]]:
    """Pydantic's errors for ``props``, each with a string ``loc`` tuple."""
    try:
        model.model_validate(props)
    except PydanticValidationError as ex:
        return [
            {
                "loc": [str(part) for part in error.get("loc", ())],
                "message": error.get("msg", ""),
                "type": error.get("type", ""),
            }
            for error in ex.errors()
        ]
    return []


def _present_prop_errors(
    model: type[BaseModel], props: dict[str, Any]
) -> list[dict[str, Any]]:
    """
    Validation errors of the props that are present.

    A required prop that is simply absent is not reported: a widget that was
    placed but not configured yet has to be saveable.
    """
    return [
        {"loc": error["loc"], "message": error["message"]}
        for error in _model_errors(model, props)
        if error["type"] != _MISSING
    ]


def _registered_widget_errors(
    widget_cls: Any, props: dict[str, Any]
) -> list[dict[str, Any]]:
    """
    A registered widget type's commit-time validation, minus the complaints
    about required props that are absent.
    """
    if not (errors := widget_cls.validate_control_values(props)):
        return []
    controls = getattr(widget_cls, "controls_class", None)
    if controls is None:
        return errors
    missing = {
        tuple(error["loc"])
        for error in _model_errors(controls, props)
        if error["type"] == _MISSING
    }
    return [error for error in errors if tuple(error.get("loc", ())) not in missing]


def validate_widget_props(widgets: list[DocumentWidget]) -> dict[str, Any]:
    """
    Validate the props of every non-grid node by the rules of its type.

    A structural container is checked against its own small model and has to
    be a container; a registered widget against its control model, for the
    props that are present; an extension widget without a backend class has
    nothing beyond the generic JSON checks every node already passed.

    :returns: Validation errors keyed by node id; empty when all props pass
    """
    errors: dict[str, Any] = {}
    for widget in widgets:
        node_errors: list[dict[str, Any]] = []
        if (model := STRUCTURAL_CONTAINER_TYPES.get(widget.widget_type)) is not None:
            if not widget.is_container:
                node_errors.append(
                    {
                        "loc": ["children"],
                        "message": "A container must have a children array.",
                    }
                )
            node_errors.extend(_present_prop_errors(model, widget.props))
        elif (widget_cls := registry.get(widget.widget_type)) is not None:
            node_errors = _registered_widget_errors(widget_cls, widget.props)
        if node_errors:
            errors[widget.node_id] = node_errors
    return errors


def _submitted_types(document: Any) -> set[str]:
    """The node types named by a not yet validated document."""
    nodes = document.get("nodes") if isinstance(document, dict) else None
    if not isinstance(nodes, dict):
        return set()
    return {
        node_type
        for node in nodes.values()
        if isinstance(node, dict) and isinstance(node_type := node.get("type"), str)
    }


def normalize_and_validate(document: Any) -> dict[str, Any]:
    """
    Validate a submitted document against the structural rules, the configured
    limits and the node types the server accepts: the widget registry, the
    structural containers, and the widget types of installed extensions.

    :returns: The normalized document, without a revision
    :raises DashboardV2InvalidError: If anything about the document is invalid
    """
    known_types = set(registry) | set(STRUCTURAL_CONTAINER_TYPES)
    known_types |= accepted_extension_types(_submitted_types(document) - known_types)
    try:
        stored, widgets = normalize_document(document, known_types=known_types)
    except DocumentValidationError as ex:
        raise DashboardV2InvalidError(str(ex)) from ex
    if errors := validate_widget_props(widgets):
        raise DashboardV2InvalidError("Widget props failed validation.", errors)
    return stored


def prepare_imported_document(
    document: Any, existing_json_metadata: str | None
) -> dict[str, Any]:
    """
    The document to store for an imported dashboard: validated exactly like a
    save through the API and stamped with a fresh revision — the initial one
    for a new dashboard, one past the stored revision when the import
    overwrites a v2 dashboard. A revision inside the imported file is ignored.

    :raises DashboardV2InvalidError: If the imported document is invalid
    """
    stored = normalize_and_validate(document)
    existing = load_stored_document(existing_json_metadata)
    revision = INITIAL_REVISION if existing is None else document_revision(existing) + 1
    return with_revision(stored, revision)


def _raise_for_database_error(ex: Exception) -> None:
    """
    ``on_error`` of the save transactions: a transaction the database aborted
    because of a concurrent one is a conflict, any other database error a
    failed save; everything else propagates unchanged.
    """
    if isinstance(ex, SQLAlchemyError):
        if is_concurrent_write_failure(ex):
            raise DashboardV2ConflictError(None) from ex
        logger.exception("Dashboard v2 save failed")
        raise DashboardV2SaveFailedError() from ex
    raise ex


def _stored_revision(pk: int) -> int | None:
    """The stored revision, or ``None`` when it cannot be read."""
    try:
        stored = load_stored_document(read_current_json_metadata(pk, lock=False))
    except SQLAlchemyError:
        db.session.rollback()  # pylint: disable=consider-using-transaction
        return None
    return document_revision(stored) if stored is not None else None


class CreateDashboardV2Command(BaseCommand):
    """
    Create a dashboard holding a v2 document at the initial revision.

    With a client-generated ``uuid`` the create is idempotent: a repeat by the
    caller who created the dashboard returns the stored dashboard instead of
    creating a second one.
    """

    def __init__(self, data: dict[str, Any]) -> None:
        self._properties = data.copy()
        self._stored: dict[str, Any] = {}
        self._uuid: uuid_module.UUID | None = self._properties.pop("uuid", None)
        #: Whether :meth:`run` created a dashboard (``False`` for a repeat).
        self.created = False

    def run(self) -> dict[str, Any]:
        """
        Create the dashboard with the caller as its editor.

        :returns: The serialized dashboard as stored by this transaction, or
            the existing one for a repeated ``uuid``
        """
        try:
            return self._create()
        except DashboardV2SaveFailedError:
            # Two creates racing on one uuid: the loser fails on the unique
            # constraint after the winner committed.
            if self._uuid is not None and (existing := self._find_existing()):
                return existing
            raise

    @transaction(on_error=_raise_for_database_error)
    def _create(self) -> dict[str, Any]:
        self.validate()
        if self._uuid is not None and (existing := self._find_existing()):
            return existing
        revised = with_revision(self._stored, INITIAL_REVISION)
        attributes: dict[str, Any] = {
            "dashboard_title": self._properties["dashboard_title"],
            "json_metadata": write_stored_document(json.dumps({}), revised),
            "editors": self._properties["editors"],
        }
        if self._uuid is not None:
            attributes["uuid"] = self._uuid
        if viewers := self._properties.get("viewers"):
            attributes["viewers"] = viewers
        dashboard = DashboardDAO.create(attributes=attributes)
        db.session.flush()
        if after_create := current_app.config.get("AFTER_ASSET_CREATE"):
            after_create(dashboard, "dashboard")
        self.created = True
        return serialize_dashboard(dashboard, revised)

    def _find_existing(self) -> dict[str, Any] | None:
        """
        The dashboard already stored under the requested uuid, serialized, or
        ``None`` when the uuid is free.

        :raises DashboardV2InvalidError: If the uuid belongs to a dashboard
            this caller did not create, cannot read, that is not a v2
            dashboard, or that is in the trash
        """
        # The uuid is unique across every row, the soft-deleted ones included,
        # so the lookup has to see them too: a uuid held by a dashboard in the
        # trash is taken, and is refused here instead of by the constraint.
        with skip_visibility_filter(db.session, Dashboard):
            dashboard = (
                db.session.query(Dashboard)
                .filter(Dashboard.uuid == self._uuid)
                .one_or_none()
            )
        if dashboard is None:
            return None
        stored = load_stored_document(dashboard.json_metadata)
        user_id = get_user_id()
        if (
            stored is None
            or dashboard.deleted_at is not None
            or user_id is None
            or dashboard.created_by_fk != user_id
            or not can_read_document(dashboard, stored)
        ):
            raise DashboardV2InvalidError("A dashboard with this uuid already exists.")
        return serialize_dashboard(dashboard, stored)

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

    def run(self) -> dict[str, Any]:
        """
        Store the document at ``base_revision + 1``.

        The write is a compare-and-swap on the value the revision was read
        from, so of two saves racing from the same base exactly one is stored
        and the other is refused, with or without row locks.

        :returns: The serialized dashboard as stored by this transaction
        :raises DashboardV2ConflictError: If the stored revision is not the
            one the change was based on, or the database aborted the save in
            favour of a concurrent transaction
        """
        try:
            return self._update()
        except DashboardV2ConflictError as ex:
            if ex.current_revision is None:
                ex.current_revision = _stored_revision(self._pk)
            raise

    @transaction(on_error=_raise_for_database_error)
    def _update(self) -> dict[str, Any]:
        self.validate()
        assert self._model is not None
        revised = with_revision(self._stored, self._base_revision + 1)
        json_metadata = self._swap_document(revised)
        attributes: dict[str, Any] = {"json_metadata": json_metadata}
        if title := self._properties.get("dashboard_title"):
            attributes["dashboard_title"] = title
        # The row is already written (and, from here on, write-locked by this
        # transaction); the model is updated as well so the session's copy,
        # the audit columns and the change history agree with it.
        dashboard = DashboardDAO.update(self._model, attributes=attributes)
        db.session.flush()
        return serialize_dashboard(dashboard, revised)

    def _swap_document(self, revised: dict[str, Any]) -> str:
        """
        Compare-and-swap ``json_metadata`` to hold ``revised``.

        A swap that fails although the revision still matches lost against a
        writer of some other metadata key; it is retried on the fresh value so
        that writer's change is kept.

        :returns: The ``json_metadata`` that was stored
        :raises DashboardV2ConflictError: If the stored revision is not the
            base revision, or the swap keeps losing
        """
        for _ in range(MAX_WRITE_ATTEMPTS):
            current_json = read_current_json_metadata(self._pk)
            current = load_stored_document(current_json)
            if current is None:
                raise DashboardV2NotFoundError(str(self._pk))
            if (revision := document_revision(current)) != self._base_revision:
                raise DashboardV2ConflictError(revision)
            new_json = write_stored_document(current_json, revised)
            if compare_and_swap_json_metadata(self._pk, current_json, new_json):
                return new_json
        raise DashboardV2ConflictError(None)

    def validate(self) -> None:
        """
        Check existence, editorship, the revision and the document, in that
        order, before anything is written.
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
        if (revision := document_revision(current)) != self._base_revision:
            raise DashboardV2ConflictError(revision)
        self._stored = normalize_and_validate(self._properties["document"])
