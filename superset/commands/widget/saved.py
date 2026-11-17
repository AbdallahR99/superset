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
"""Create, read, update and delete saved widgets."""

from __future__ import annotations

from functools import partial
from typing import Any

from superset_core.widgets import Widget

from superset import security_manager
from superset.commands.base import BaseCommand
from superset.commands.widget.exceptions import (
    SavedWidgetCreateFailedError,
    SavedWidgetDeleteFailedError,
    SavedWidgetForbiddenError,
    SavedWidgetNotFoundError,
    SavedWidgetUpdateFailedError,
    WidgetInvalidError,
)
from superset.commands.widget.utils import (
    load_saved_widget,
    raise_for_widget_authoring,
    raise_for_widget_ownership,
    validate_widget_props,
)
from superset.daos.saved_widget import SavedWidgetDAO
from superset.models.saved_widget import SavedWidget
from superset.utils import json
from superset.utils.core import get_user_id
from superset.utils.decorators import on_error, transaction
from superset.widgets.data import widget_dataset_id

# Bounds of the saved-widget list. A caller that names no page size gets the
# largest page, so a short list still arrives in one call.
DEFAULT_LIST_PAGE_SIZE = 25
MAX_LIST_PAGE_SIZE = 100
MAX_LIST_PAGE = 100000


def _props_attributes(
    widget_cls: type[Widget], props: dict[str, Any]
) -> dict[str, Any]:
    """The stored props and the dataset the widget type reads from them."""
    return {
        "props": json.dumps(props),
        "dataset_id": widget_dataset_id(widget_cls, props),
    }


class CreateSavedWidgetCommand(BaseCommand):
    """Store a new saved widget owned by the caller."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._properties = data.copy()
        self._widget_cls: type[Widget] | None = None

    @transaction(on_error=partial(on_error, reraise=SavedWidgetCreateFailedError))
    def run(self) -> SavedWidget:
        self.validate()
        assert self._widget_cls is not None
        return SavedWidgetDAO.create(
            attributes={
                "widget_type": self._properties["widget_type"],
                "title": self._properties.get("title"),
                **_props_attributes(self._widget_cls, self._properties["props"]),
            }
        )

    def validate(self) -> None:
        if security_manager.is_guest_user():
            raise SavedWidgetForbiddenError()
        self._widget_cls = validate_widget_props(
            self._properties.get("widget_type"), self._properties.get("props")
        )
        raise_for_widget_authoring(self._widget_cls, self._properties["props"])


class UpdateSavedWidgetCommand(BaseCommand):
    """Change the props or title of a saved widget the caller owns."""

    def __init__(self, ref: str, data: dict[str, Any]) -> None:
        self._ref = ref
        self._properties = data.copy()
        self._model: SavedWidget | None = None
        self._widget_cls: type[Widget] | None = None

    @transaction(on_error=partial(on_error, reraise=SavedWidgetUpdateFailedError))
    def run(self) -> SavedWidget:
        self.validate()
        assert self._model is not None
        attributes: dict[str, Any] = {}
        if "props" in self._properties:
            assert self._widget_cls is not None
            attributes.update(
                _props_attributes(self._widget_cls, self._properties["props"])
            )
        if "title" in self._properties:
            attributes["title"] = self._properties["title"]
        return SavedWidgetDAO.update(self._model, attributes=attributes)

    def validate(self) -> None:
        self._model = SavedWidgetDAO.find_by_uuid(self._ref)
        if self._model is None:
            raise SavedWidgetNotFoundError(self._ref)
        raise_for_widget_ownership(self._model)
        if "props" in self._properties:
            self._widget_cls = validate_widget_props(
                self._model.widget_type, self._properties["props"]
            )
            raise_for_widget_authoring(self._widget_cls, self._properties["props"])


class DeleteSavedWidgetCommand(BaseCommand):
    """Delete a saved widget the caller owns."""

    def __init__(self, ref: str) -> None:
        self._ref = ref
        self._model: SavedWidget | None = None

    @transaction(on_error=partial(on_error, reraise=SavedWidgetDeleteFailedError))
    def run(self) -> None:
        self.validate()
        assert self._model is not None
        SavedWidgetDAO.delete([self._model])

    def validate(self) -> None:
        self._model = SavedWidgetDAO.find_by_uuid(self._ref)
        if self._model is None:
            raise SavedWidgetNotFoundError(self._ref)
        raise_for_widget_ownership(self._model)


class GetSavedWidgetCommand(BaseCommand):
    """Load one saved widget the caller may read."""

    def __init__(self, ref: str) -> None:
        self._ref = ref

    def run(self) -> SavedWidget:
        return load_saved_widget(self._ref)

    def validate(self) -> None:
        pass


class ListSavedWidgetsCommand(BaseCommand):
    """
    One page of the saved widgets the caller may read.

    Admins read every saved widget; anyone else their own plus those binding
    a dataset they can read, which is the rule ``GetSavedWidgetCommand``
    applies to a single widget. Guests get no list. After ``run()`` the total
    number of readable widgets is in ``count``.
    """

    def __init__(self, page: int = 0, page_size: int = MAX_LIST_PAGE_SIZE) -> None:
        self._page = page
        self._page_size = page_size
        self.count = 0

    def run(self) -> list[SavedWidget]:
        self.validate()
        widgets, self.count = SavedWidgetDAO.find_readable(
            get_user_id(),
            see_all=bool(security_manager.is_admin()),
            page=self._page,
            page_size=self._page_size,
        )
        return widgets

    def validate(self) -> None:
        if security_manager.is_guest_user():
            raise SavedWidgetForbiddenError()
        if (
            isinstance(self._page, bool)
            or not isinstance(self._page, int)
            or not 0 <= self._page <= MAX_LIST_PAGE
        ):
            raise WidgetInvalidError(
                f"page must be an integer between 0 and {MAX_LIST_PAGE}."
            )
        if (
            isinstance(self._page_size, bool)
            or not isinstance(self._page_size, int)
            or not 1 <= self._page_size <= MAX_LIST_PAGE_SIZE
        ):
            raise WidgetInvalidError(
                f"page_size must be an integer between 1 and {MAX_LIST_PAGE_SIZE}."
            )
