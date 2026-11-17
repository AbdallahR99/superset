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
Node types a Dashboard v2 document may hold besides the widget registry's.

Two families live here:

* the builder's **structural containers** (``tabs`` with its ``tab`` panes,
  ``collapsible``, ``carousel`` with its ``slide`` panes). They arrange other
  nodes, fetch no data and have no control panel, so they are not widgets in
  the registry sense; each has a small prop model of its own.
* **extension widgets without a backend class**: a type named
  ``extensions.<publisher>.<name>.<type>`` whose extension is installed and
  enabled. The server cannot know such a widget's props, so they only get the
  generic structural validation every node gets.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

logger = logging.getLogger(__name__)

#: Longest label of a tab pane or carousel slide.
MAX_LABEL_LENGTH = 250


class ContainerProps(BaseModel):
    """Props of a structural container; props it does not declare are kept."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class PaneProps(ContainerProps):
    """Props of a ``tab`` pane or a carousel ``slide``."""

    label: StrictStr | None = Field(default=None, max_length=MAX_LABEL_LENGTH)


class CollapsibleProps(ContainerProps):
    """Props of a ``collapsible`` container."""

    collapsed: StrictBool | None = None
    #: Row span the node returns to when expanded again.
    expanded_row_span: float | None = Field(
        default=None, alias="expandedRowSpan", ge=1, strict=True
    )


#: Structural container types and the model their props are validated with.
#: Every node of one of these types has to carry a ``children`` array.
STRUCTURAL_CONTAINER_TYPES: dict[str, type[ContainerProps]] = {
    "tabs": ContainerProps,
    "tab": PaneProps,
    "collapsible": CollapsibleProps,
    "carousel": ContainerProps,
    "slide": PaneProps,
}

# Mirrors ``EXTENSION_WIDGET_TYPE`` of the frontend's extension loader.
_EXTENSION_WIDGET_TYPE = re.compile(r"^extensions\.([^.]+)\.([^.]+)\..+$")


def extension_id_of(node_type: str) -> str | None:
    """
    The id (``publisher.name``) of the extension a widget type is namespaced
    under, or ``None`` when the type is not an extension's.
    """
    if (match := _EXTENSION_WIDGET_TYPE.match(node_type)) is None:
        return None
    return f"{match.group(1)}.{match.group(2)}"


def installed_extension_ids() -> set[str]:
    """
    Ids of the extensions that are installed and allowed to load, or nothing
    while the ``ENABLE_EXTENSIONS`` feature flag is off.
    """
    # pylint: disable=import-outside-toplevel
    from superset.extensions import feature_flag_manager

    if not feature_flag_manager.is_feature_enabled("ENABLE_EXTENSIONS"):
        return set()
    from superset.extensions.utils import get_extensions

    try:
        return set(get_extensions())
    except Exception:  # pylint: disable=broad-except
        # A broken extension bundle must not turn a save into a server error;
        # its widget types are simply not accepted.
        logger.warning("Could not list the installed extensions", exc_info=True)
        return set()


def accepted_extension_types(node_types: Iterable[str]) -> set[str]:
    """
    The members of ``node_types`` that are widget types of an installed,
    enabled extension.

    The installed extensions are only looked up when at least one type is
    namespaced as an extension's.
    """
    candidates = {
        node_type: extension_id
        for node_type in node_types
        if (extension_id := extension_id_of(node_type)) is not None
    }
    if not candidates:
        return set()
    installed = installed_extension_ids()
    return {
        node_type
        for node_type, extension_id in candidates.items()
        if extension_id in installed
    }
