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
"""Errors raised by the Dashboard v2 commands, each carrying its HTTP status."""

from __future__ import annotations

from typing import Any

from flask_babel import lazy_gettext as _

from superset.commands.exceptions import (
    CommandException,
    CreateFailedError,
    ForbiddenError,
    ObjectNotFoundError,
)


class DashboardV2NotFoundError(ObjectNotFoundError):
    """No v2 dashboard the caller may see matches the reference."""

    def __init__(self, identifier: str | None = None) -> None:
        super().__init__("Dashboard v2", identifier)


class DashboardV2ForbiddenError(ForbiddenError):
    """The caller may not read or edit the dashboard."""

    message = _("You don't have access to this dashboard.")


class DashboardV2BadRequestError(CommandException):
    """The request itself is malformed (body is not strict JSON, bad header)."""

    status = 400


class DashboardV2PayloadTooLargeError(CommandException):
    """The request body exceeds the configured document size."""

    status = 413


class DashboardV2InvalidError(CommandException):
    """The document, or the props of one of its widgets, failed validation."""

    status = 422

    def __init__(self, message: str, errors: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or {}


class DashboardV2RevisionRequiredError(CommandException):
    """An update arrived without the revision it was based on."""

    status = 428
    message = _(
        "The revision this change is based on is required: send it in an "
        "If-Match header or as base_revision."
    )


class DashboardV2ConflictError(CommandException):
    """
    The document changed since the revision the update was based on, or the
    database aborted the save in favour of a concurrent transaction.

    ``current_revision`` is the stored revision, or ``None`` when it could not
    be determined.
    """

    status = 409

    def __init__(self, current_revision: int | None) -> None:
        super().__init__(
            _(
                "The dashboard was changed by someone else. Reload it before "
                "saving again."
            )
        )
        self.current_revision = current_revision


class DashboardV2SaveFailedError(CreateFailedError):
    """The document could not be written to the metadata database."""

    message = _("Dashboard v2 could not be saved.")
