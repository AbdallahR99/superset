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
Serve a widget's data or values from a selector: a saved widget ``{"id"}`` or
an inline spec ``{"widget": {"type", "props"}}``. Execution is always handed to
the widget type registered in the widget registry.
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from superset_core.widgets import Widget, WidgetDataNotSupportedError

from superset import security_manager
from superset.commands.base import BaseCommand
from superset.commands.chart.exceptions import ChartDataQueryFailedError
from superset.commands.widget.exceptions import (
    SavedWidgetForbiddenError,
    WidgetDatasetNotFoundError,
    WidgetInvalidError,
    WidgetSqlForbiddenError,
)
from superset.commands.widget.utils import load_saved_widget, validate_widget_props
from superset.exceptions import QueryObjectValidationError, SupersetSecurityException
from superset.widgets.data import (
    FilterValidationError,
    get_table,
    raise_for_widget_sql,
    validate_guest_inline_props,
    widget_dataset_id,
    widget_queries_data,
    WidgetContext,
    WidgetDataError,
    WidgetDatasetMissingError,
    WidgetSqlNotAllowedError,
)
from superset.widgets.registry import registry

T = TypeVar("T")


def resolve_widget(
    selector: dict[str, Any],
) -> tuple[type[Widget], dict[str, Any], WidgetContext]:
    """The widget class, trusted props and context a selector names."""
    if (ref := selector.get("id")) is not None:
        saved = load_saved_widget(str(ref))
        widget_cls = registry.get(str(saved.widget_type))
        if widget_cls is None:
            raise WidgetInvalidError(f"Unknown widget type {saved.widget_type!r}.")
        props = saved.props_dict
        context = WidgetContext(widget_dataset_id(widget_cls, props), str(saved.uuid))
        # Reading a named definition and running its query are distinct grants.
        # Check the binding before dispatch, including for extension widgets.
        if (
            security_manager.is_guest_user()
            and widget_queries_data(widget_cls)
            and not security_manager.guest_widget_grants_dataset(context)
        ):
            raise SavedWidgetForbiddenError()
        return widget_cls, props, context

    spec = selector.get("widget")
    if not isinstance(spec, dict):
        raise WidgetInvalidError("Provide a saved widget id or an inline widget.")
    inline_props = spec.get("props")
    widget_cls = validate_widget_props(spec.get("type"), inline_props)
    assert isinstance(inline_props, dict)
    context = WidgetContext(widget_dataset_id(widget_cls, inline_props))
    if security_manager.is_guest_user():
        # Default deny: a guest may only send an inline definition for a
        # dataset its token grants through an explicit ``dataset`` resource,
        # and only a SQL-free one. A dashboard or widget resource and the
        # ``datasets`` allowlist never grant one. A definition with no dataset
        # to check against (a type the host cannot bind) is refused rather
        # than handed to the widget unvalidated.
        if context.dataset_id is None or not (
            security_manager.guest_widget_grants_dataset(context)
        ):
            raise SavedWidgetForbiddenError()
        validate_guest_inline_props(inline_props, get_table(context.dataset_id))
    else:
        # SQL needs the caller's own read access to the dataset, as an ad-hoc
        # SQL metric does in Explore. Whether a dimension is a column or a SQL
        # expression is only known against the dataset's own columns, so the
        # dataset is always the reference.
        raise_for_widget_sql(
            inline_props,
            get_table(context.dataset_id) if context.dataset_id is not None else None,
        )
    return widget_cls, inline_props, context


def _execute(run: Callable[[], T]) -> T:
    try:
        return run()
    except WidgetDataNotSupportedError as ex:
        raise WidgetInvalidError("This widget has no data to fetch.") from ex
    except WidgetSqlNotAllowedError as ex:
        # A permission problem, not a malformed request.
        raise WidgetSqlForbiddenError(str(ex)) from ex
    except WidgetDatasetMissingError as ex:
        raise WidgetDatasetNotFoundError(str(ex)) from ex
    except (FilterValidationError, WidgetDataError) as ex:
        raise WidgetInvalidError(str(ex)) from ex
    except QueryObjectValidationError as ex:
        raise WidgetInvalidError(str(ex.message)) from ex
    except ChartDataQueryFailedError as ex:
        # The query layer catches its own validation errors and reports them in
        # the payload, so they arrive here as a failed query rather than as a
        # QueryObjectValidationError. A widget naming a column its dataset does
        # not have is the caller's mistake; 500 tells an embedding host nothing.
        raise WidgetInvalidError(str(ex.message)) from ex
    except SupersetSecurityException as ex:
        raise SavedWidgetForbiddenError() from ex


class WidgetDataCommand(BaseCommand):
    def __init__(self, selector: dict[str, Any], filters: Any) -> None:
        self._selector = selector
        self._filters = filters

    def run(self) -> dict[str, Any]:
        self.validate()

        def fetch() -> dict[str, Any]:
            widget_cls, props, context = resolve_widget(self._selector)
            return widget_cls.fetch_data(props, self._filters, context)

        return _execute(fetch)

    def validate(self) -> None:
        if not isinstance(self._filters, list):
            raise WidgetInvalidError("filters must be a list")


class WidgetValuesCommand(BaseCommand):
    def __init__(self, selector: dict[str, Any]) -> None:
        self._selector = selector

    def run(self) -> list[Any]:
        def fetch() -> list[Any]:
            widget_cls, props, context = resolve_widget(self._selector)
            return widget_cls.fetch_values(props, context)

        return _execute(fetch)

    def validate(self) -> None:
        pass
