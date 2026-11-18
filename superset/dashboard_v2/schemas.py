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
"""Request and response schemas of the Dashboard v2 REST API."""

from marshmallow import fields, Schema
from marshmallow.validate import Length, Range

_document_description = (
    "Dashboard v2 document: {version, nodes: {<id>: {type, layout, children, "
    "props, style}}}. A node with children is a container; any other node is a "
    "block addressed by its id."
)
_revision_description = (
    "Monotonically increasing revision of the document. It starts at 1 and "
    "grows by one with every successful update."
)


class DashboardV2PostSchema(Schema):
    """Body of a create request."""

    dashboard_title = fields.String(required=True, validate=Length(min=1, max=500))
    document = fields.Dict(
        required=True, metadata={"description": _document_description}
    )
    uuid = fields.UUID(
        metadata={
            "description": (
                "Client-generated uuid for the new dashboard. Repeating a "
                "create with the same uuid returns the dashboard the caller "
                "already created instead of creating another one."
            )
        },
    )


class DashboardV2PutSchema(Schema):
    """Body of an update request."""

    dashboard_title = fields.String(validate=Length(min=1, max=500))
    document = fields.Dict(
        required=True, metadata={"description": _document_description}
    )
    base_revision = fields.Integer(
        strict=True,
        validate=Range(min=0),
        metadata={
            "description": (
                "Revision the change is based on. Required unless sent in an "
                "If-Match header; the update is refused with 409 when it is "
                "not the stored revision."
            )
        },
    )


class EmbeddedConfigSummarySchema(Schema):
    """Embedding configuration of a dashboard."""

    uuid = fields.String()
    allowed_domains = fields.List(
        fields.String(),
        metadata={"description": "Omitted for embedded guests."},
    )


class DashboardV2ResponseSchema(Schema):
    """A v2 dashboard with its document and the document's revision."""

    id = fields.Integer()
    uuid = fields.String()
    dashboard_title = fields.String()
    published = fields.Boolean()
    can_edit = fields.Boolean()
    can_publish = fields.Boolean()
    changed_on = fields.DateTime(allow_none=True)
    revision = fields.Integer(metadata={"description": _revision_description})
    document = fields.Dict(metadata={"description": _document_description})
    embedded = fields.Nested(EmbeddedConfigSummarySchema, allow_none=True)
