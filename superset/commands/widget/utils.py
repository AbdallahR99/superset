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

from typing import Any

from superset_core.widgets import Widget

from superset import security_manager
from superset.commands.widget.exceptions import (
    SavedWidgetForbiddenError,
    SavedWidgetNotFoundError,
    WidgetInvalidError,
    WidgetSqlForbiddenError,
)
from superset.daos.saved_widget import SavedWidgetDAO
from superset.exceptions import SupersetSecurityException
from superset.models.saved_widget import SavedWidget
from superset.utils.core import get_user_id
from superset.widgets.data import (
    get_table,
    raise_for_widget_sql,
    resolve_widget_semantic_view,
    validate_widget_semantic_members,
    widget_dataset_id,
    widget_semantic_view_id,
    WidgetDataError,
    WidgetSqlNotAllowedError,
)
from superset.widgets.registry import registry


def validate_widget_props(widget_type: Any, props: Any) -> type[Widget]:
    """The registered widget class, once ``props`` pass its commit-time validation."""
    widget_cls = registry.get(str(widget_type))
    if widget_cls is None:
        raise WidgetInvalidError(f"Unknown widget type {widget_type!r}.")
    if not isinstance(props, dict):
        raise WidgetInvalidError("Widget props must be an object.")
    if errors := widget_cls.validate_control_values(props):
        raise WidgetInvalidError("Widget props failed validation.", errors)
    return widget_cls


def raise_for_widget_authoring(
    widget_cls: type[Widget] | None, props: dict[str, Any]
) -> None:
    """
    Check read access to the widget's binding. Native dataset bindings may
    also contain SQL when the caller is allowed to write it. Semantic bindings
    use approved members only.
    """
    if (view_id := widget_semantic_view_id(widget_cls, props)) is not None:
        try:
            view = resolve_widget_semantic_view(view_id)
            validate_widget_semantic_members(view, props)
        except WidgetDataError as ex:
            raise WidgetInvalidError(str(ex)) from ex
        except SupersetSecurityException as ex:
            raise SavedWidgetForbiddenError() from ex
        return
    datasource = None
    if (dataset_id := widget_dataset_id(widget_cls, props)) is not None:
        try:
            datasource = get_table(dataset_id)
        except WidgetDataError as ex:
            raise WidgetInvalidError(str(ex)) from ex
        try:
            security_manager.raise_for_access(datasource=datasource)
        except SupersetSecurityException as ex:
            raise SavedWidgetForbiddenError() from ex
    try:
        raise_for_widget_sql(props, datasource)
    except WidgetSqlNotAllowedError as ex:
        raise WidgetSqlForbiddenError(str(ex)) from ex


def raise_for_widget_read(widget: SavedWidget) -> None:
    """
    Whether the caller may read a saved widget's definition.

    A semantic definition requires current view access. For other definitions,
    a guest must hold a token naming the widget. Signed-in admins and creators
    may read their own definitions. Other readers need access to the native
    dataset the definition binds.
    """
    widget_cls = registry.get(str(widget.widget_type))
    props = widget.props_dict
    if (view_id := widget_semantic_view_id(widget_cls, props)) is not None:
        if security_manager.is_guest_user():
            raise SavedWidgetForbiddenError()
        try:
            resolve_widget_semantic_view(view_id)
        except (SupersetSecurityException, WidgetDataError) as ex:
            raise SavedWidgetForbiddenError() from ex
        return
    if security_manager.is_guest_user():
        if not security_manager.guest_token_names_widget(str(widget.uuid)):
            raise SavedWidgetForbiddenError()
        return
    if security_manager.is_admin():
        return
    user_id = get_user_id()
    if user_id is not None and widget.created_by_fk == user_id:
        return
    dataset_id = widget_dataset_id(widget_cls, props)
    if dataset_id is None:
        raise SavedWidgetForbiddenError()
    try:
        security_manager.raise_for_access(datasource=get_table(dataset_id))
    except (SupersetSecurityException, WidgetDataError) as ex:
        raise SavedWidgetForbiddenError() from ex


def load_saved_widget(ref: str) -> SavedWidget:
    """A saved widget the caller may read (see ``raise_for_widget_read``)."""
    widget = SavedWidgetDAO.find_by_uuid(ref)
    if widget is None:
        raise SavedWidgetNotFoundError(ref)
    raise_for_widget_read(widget)
    return widget


def raise_for_widget_ownership(widget: SavedWidget) -> None:
    """Only a widget's creator or an admin may change or delete it."""
    if security_manager.is_guest_user():
        raise SavedWidgetForbiddenError()
    if security_manager.is_admin():
        return
    user_id = get_user_id()
    if user_id is None or widget.created_by_fk != user_id:
        raise SavedWidgetForbiddenError()


def serialize_saved_widget(widget: SavedWidget) -> dict[str, Any]:
    """Expose semantic binding props only with current view access."""
    props = widget.props_dict
    widget_cls = registry.get(str(widget.widget_type))
    if widget_semantic_view_id(widget_cls, props) is not None:
        try:
            raise_for_widget_read(widget)
        except SavedWidgetForbiddenError:
            # An owner can still see the saved record in its paged list.
            props = {}
    return {
        "uuid": str(widget.uuid),
        "widget_type": widget.widget_type,
        "title": widget.title,
        "props": props,
        "dataset_id": widget.dataset_id,
        "changed_on": widget.changed_on,
    }
