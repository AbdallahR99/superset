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
"""HTTP contract of ``/api/v1/dashboard_v2/``: the feature flag gate,
revisions and optimistic concurrency, document validation, and object-level
authorization."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pytest_mock import MockerFixture
from sqlalchemy.orm.session import Session

from superset import security_manager
from superset.errors import ErrorLevel, SupersetError, SupersetErrorType
from superset.exceptions import SupersetSecurityException
from superset.utils import json
from tests.unit_tests.dashboard_v2.conftest import make_document, stored_document

BASE = "/api/v1/dashboard_v2/"


def _denied() -> SupersetSecurityException:
    return SupersetSecurityException(
        SupersetError(
            message="denied",
            error_type=SupersetErrorType.DASHBOARD_SECURITY_ACCESS_ERROR,
            level=ErrorLevel.ERROR,
        )
    )


def _post(client: Any, document: dict[str, Any], title: str = "Sales") -> Any:
    return client.post(BASE, json={"dashboard_title": title, "document": document})


def _put(
    client: Any,
    pk: int,
    document: dict[str, Any],
    *,
    if_match: str | None = None,
    base_revision: int | None = None,
    title: str | None = None,
) -> Any:
    body: dict[str, Any] = {"document": document}
    if base_revision is not None:
        body["base_revision"] = base_revision
    if title is not None:
        body["dashboard_title"] = title
    headers = {"If-Match": if_match} if if_match is not None else {}
    return client.put(f"{BASE}{pk}", json=body, headers=headers)


def _create(client: Any, *children: str) -> int:
    response = _post(client, make_document(*children))
    assert response.status_code == 201, response.get_json()
    return response.get_json()["id"]


# --------------------------------------------------------------------------
# Feature flag
# --------------------------------------------------------------------------

GATED_ROUTES = [
    ("GET", f"{BASE}1"),
    ("GET", f"{BASE}embedded/{uuid.uuid4()}"),
    ("POST", BASE),
    ("PUT", f"{BASE}1"),
    ("GET", "/api/v1/widgets/types"),
    ("GET", "/api/v1/widgets/type/markdown/control-schema"),
    ("POST", "/api/v1/widgets/type/markdown/validate"),
    ("GET", "/api/v1/widget/"),
    ("POST", "/api/v1/widget/"),
    ("GET", f"/api/v1/widget/{uuid.uuid4()}"),
    ("PUT", f"/api/v1/widget/{uuid.uuid4()}"),
    ("DELETE", f"/api/v1/widget/{uuid.uuid4()}"),
    ("POST", "/api/v1/widget/data"),
    ("POST", "/api/v1/widget/values"),
    ("GET", "/dashboard/v2/new/"),
    ("GET", "/dashboard/v2/1/"),
]


@pytest.mark.parametrize("method, path", GATED_ROUTES)
def test_every_route_is_404_while_the_flag_is_off(
    client: Any, full_api_access: None, method: str, path: str
) -> None:
    """With ``DASHBOARD_V2`` off (the default) the routes do not exist, even
    for a caller holding every permission."""
    response = client.open(path, method=method, json={})

    assert response.status_code == 404


@pytest.mark.parametrize("method, path", GATED_ROUTES)
def test_the_flag_is_checked_before_authentication(
    client: Any, method: str, path: str
) -> None:
    """An anonymous caller learns nothing about the routes either: 404, not a
    401 or a login redirect."""
    response = client.open(path, method=method, json={})

    assert response.status_code == 404


def test_routes_are_reachable_once_the_flag_is_on(
    client: Any, dashboard_v2_enabled: None, editor: None, v2_session: Session
) -> None:
    assert client.get(f"{BASE}12345").status_code == 404  # no such dashboard
    assert client.get("/api/v1/widgets/types").status_code == 200
    validate = client.post(
        "/api/v1/widgets/type/markdown/validate", json={"control_values": {}}
    )
    assert validate.status_code == 200


def test_flag_on_still_requires_authentication(
    client: Any, dashboard_v2_enabled: None
) -> None:
    assert client.get(f"{BASE}1").status_code == 401
    assert _post(client, make_document()).status_code == 401
    assert _put(client, 1, make_document(), base_revision=1).status_code == 401


# --------------------------------------------------------------------------
# Revisions and optimistic concurrency
# --------------------------------------------------------------------------


def test_create_returns_the_initial_revision(
    client: Any, dashboard_v2_enabled: None, editor: None, v2_session: Session
) -> None:
    response = _post(client, make_document("node_1", "node_2"))

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["result"]["revision"] == 1
    assert payload["result"]["dashboard_title"] == "Sales"
    assert response.headers["ETag"] == '"1"'
    # The revision travels beside the document, not inside it.
    assert payload["result"]["document"] == make_document("node_1", "node_2")
    assert stored_document(v2_session, payload["id"])["revision"] == 1


def test_get_returns_the_revision(
    client: Any, dashboard_v2_enabled: None, editor: None, v2_session: Session
) -> None:
    pk = _create(client)

    response = client.get(f"{BASE}{pk}")

    assert response.status_code == 200
    assert response.get_json()["result"]["revision"] == 1
    assert response.headers["ETag"] == '"1"'


@pytest.mark.parametrize("if_match", ['"1"', 'W/"1"', "1"])
def test_put_with_if_match_bumps_the_revision(
    client: Any,
    dashboard_v2_enabled: None,
    editor: None,
    v2_session: Session,
    if_match: str,
) -> None:
    pk = _create(client)

    response = _put(
        client, pk, make_document("node_1", "node_2"), if_match=if_match, title="New"
    )

    assert response.status_code == 200, response.get_json()
    result = response.get_json()["result"]
    assert result["revision"] == 2
    assert result["dashboard_title"] == "New"
    assert set(result["document"]["nodes"]) == {"root", "node_1", "node_2"}
    assert response.headers["ETag"] == '"2"'
    assert stored_document(v2_session, pk)["revision"] == 2


def test_put_with_base_revision_field_bumps_the_revision(
    client: Any, dashboard_v2_enabled: None, editor: None, v2_session: Session
) -> None:
    pk = _create(client)

    first = _put(client, pk, make_document("a"), base_revision=1)
    second = _put(client, pk, make_document("b"), base_revision=2)

    assert first.get_json()["result"]["revision"] == 2
    assert second.get_json()["result"]["revision"] == 3
    assert set(stored_document(v2_session, pk)["nodes"]) == {"root", "b"}


def test_stale_revision_is_rejected_with_409(
    client: Any, dashboard_v2_enabled: None, editor: None, v2_session: Session
) -> None:
    pk = _create(client)
    assert _put(client, pk, make_document("fresh"), if_match='"1"').status_code == 200

    response = _put(client, pk, make_document("stale"), if_match='"1"')

    assert response.status_code == 409
    payload = response.get_json()
    assert payload["current_revision"] == 2
    assert "message" in payload
    assert response.headers["ETag"] == '"2"'
    # Nothing was overwritten.
    stored = stored_document(v2_session, pk)
    assert stored["revision"] == 2
    assert set(stored["nodes"]) == {"root", "fresh"}


def test_second_of_two_saves_from_the_same_base_is_rejected(
    client: Any, dashboard_v2_enabled: None, editor: None, v2_session: Session
) -> None:
    """Two editors load revision 1 and both save: one wins, the other gets a
    conflict and has to reload."""
    pk = _create(client)

    alice = _put(client, pk, make_document("alice"), base_revision=1)
    bob = _put(client, pk, make_document("bob"), base_revision=1)

    assert alice.status_code == 200
    assert bob.status_code == 409
    assert bob.get_json()["current_revision"] == 2
    assert set(stored_document(v2_session, pk)["nodes"]) == {"root", "alice"}

    # After reloading, Bob saves on top of Alice's revision.
    retry = _put(client, pk, make_document("alice", "bob"), base_revision=2)
    assert retry.status_code == 200
    assert retry.get_json()["result"]["revision"] == 3


def test_a_revision_ahead_of_the_stored_one_is_rejected(
    client: Any, dashboard_v2_enabled: None, editor: None, v2_session: Session
) -> None:
    pk = _create(client)

    response = _put(client, pk, make_document(), base_revision=5)

    assert response.status_code == 409
    assert response.get_json()["current_revision"] == 1


def test_put_without_a_base_revision_is_428(
    client: Any, dashboard_v2_enabled: None, editor: None, v2_session: Session
) -> None:
    pk = _create(client)

    response = _put(client, pk, make_document("other"))

    assert response.status_code == 428
    assert "If-Match" in response.get_json()["message"]
    assert set(stored_document(v2_session, pk)["nodes"]) == {"root", "node_1"}


@pytest.mark.parametrize("if_match", ["*", '"abc"', '"1", "2"', "", '"-1"'])
def test_malformed_if_match_is_400(
    client: Any,
    dashboard_v2_enabled: None,
    editor: None,
    v2_session: Session,
    if_match: str,
) -> None:
    pk = _create(client)

    response = _put(client, pk, make_document(), if_match=if_match)

    assert response.status_code == 400
    assert stored_document(v2_session, pk)["revision"] == 1


def test_disagreeing_if_match_and_base_revision_is_400(
    client: Any, dashboard_v2_enabled: None, editor: None, v2_session: Session
) -> None:
    pk = _create(client)

    response = _put(client, pk, make_document(), if_match='"1"', base_revision=2)

    assert response.status_code == 400


@pytest.mark.parametrize("base_revision", ["1", 1.5, -1, True])
def test_non_integer_base_revision_is_400(
    client: Any,
    dashboard_v2_enabled: None,
    editor: None,
    v2_session: Session,
    base_revision: Any,
) -> None:
    pk = _create(client)

    response = client.put(
        f"{BASE}{pk}",
        json={"document": make_document(), "base_revision": base_revision},
    )

    assert response.status_code == 400


def test_a_document_stored_without_a_revision_is_at_revision_zero(
    client: Any, dashboard_v2_enabled: None, editor: None, v2_session: Session
) -> None:
    from superset.models.dashboard import Dashboard

    dashboard = Dashboard(
        dashboard_title="older",
        json_metadata=json.dumps({"v2_document": make_document()}),
    )
    v2_session.add(dashboard)
    v2_session.commit()

    assert client.get(f"{BASE}{dashboard.id}").get_json()["result"]["revision"] == 0
    response = _put(client, dashboard.id, make_document("next"), base_revision=0)
    assert response.status_code == 200
    assert response.get_json()["result"]["revision"] == 1


def test_update_keeps_the_rest_of_json_metadata(
    client: Any, dashboard_v2_enabled: None, editor: None, v2_session: Session
) -> None:
    from superset.models.dashboard import Dashboard

    pk = _create(client)
    dashboard = v2_session.get(Dashboard, pk)
    metadata = json.loads(dashboard.json_metadata)
    metadata["color_scheme"] = "supersetColors"
    dashboard.json_metadata = json.dumps(metadata)
    v2_session.commit()

    assert _put(client, pk, make_document("x"), base_revision=1).status_code == 200

    v2_session.expire_all()
    stored = json.loads(v2_session.get(Dashboard, pk).json_metadata)
    assert stored["color_scheme"] == "supersetColors"
    assert stored["v2_document"]["revision"] == 2


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def _cyclic() -> dict[str, Any]:
    return {
        "version": 1,
        "nodes": {
            "root": {"type": "grid", "children": ["a"]},
            "a": {"type": "filter.bar", "children": ["b"]},
            "b": {"type": "filter.bar", "children": ["a"]},
        },
    }


def _many(count: int) -> dict[str, Any]:
    return make_document(*[f"n{index}" for index in range(count)])


@pytest.mark.parametrize(
    "document, message",
    [
        (_cyclic(), "own ancestor"),
        (
            {"nodes": {"root": {"type": "grid", "children": ["root"]}}},
            "own ancestor",
        ),
        (
            {"nodes": {"root": {"type": "grid", "children": ["ghost"]}}},
            "unknown children",
        ),
        (
            make_document("a", orphan={"type": "markdown"}),
            "not reachable",
        ),
        ({"nodes": {"a": {"type": "markdown"}}}, "root container"),
        (
            {
                "nodes": {
                    "root": {"type": "grid", "children": ["a"]},
                    "a": {"type": "no-such-widget"},
                }
            },
            "unknown type 'no-such-widget'",
        ),
        (
            {
                "nodes": {
                    "root": {"type": "grid", "children": ["a"]},
                    "a": {"type": "tabs", "children": []},
                }
            },
            "unknown type 'tabs'",
        ),
        (_many(600), "the limit is 500"),
        (
            {"version": 99, "nodes": {"root": {"type": "grid", "children": []}}},
            "version",
        ),
        ({"nodes": []}, "document.nodes"),
    ],
)
def test_invalid_documents_are_422_on_create_and_update(
    client: Any,
    dashboard_v2_enabled: None,
    editor: None,
    v2_session: Session,
    document: dict[str, Any],
    message: str,
) -> None:
    pk = _create(client)

    created = _post(client, document)
    updated = _put(client, pk, document, base_revision=1)

    for response in (created, updated):
        assert response.status_code == 422, response.get_json()
        assert message in response.get_json()["message"]
    assert stored_document(v2_session, pk)["revision"] == 1


def test_deeply_nested_containers_are_422(
    client: Any, dashboard_v2_enabled: None, editor: None, v2_session: Session
) -> None:
    nodes: dict[str, Any] = {"root": {"type": "grid", "children": ["n1"]}}
    for index in range(1, 40):
        nodes[f"n{index}"] = {
            "type": "filter.bar",
            "children": [f"n{index + 1}"] if index < 39 else [],
        }

    response = _post(client, {"nodes": nodes})

    assert response.status_code == 422
    assert "deeper than 16 levels" in response.get_json()["message"]


def test_invalid_widget_props_are_422_with_per_node_errors(
    client: Any, dashboard_v2_enabled: None, editor: None, v2_session: Session
) -> None:
    document = make_document(
        "ok", bad={"type": "metric-tile", "props": {"decimals": "not-an-int"}}
    )
    document["nodes"]["root"]["children"].append("bad")

    response = _post(client, document)

    assert response.status_code == 422
    errors = response.get_json()["errors"]
    assert set(errors) == {"bad"}
    assert ["decimals"] in [error["loc"] for error in errors["bad"]]


def test_limits_come_from_config(
    client: Any,
    app: Any,
    mocker: MockerFixture,
    dashboard_v2_enabled: None,
    editor: None,
    v2_session: Session,
) -> None:
    mocker.patch.dict(
        app.config, {"DASHBOARD_V2_MAX_NODES": 3, "DASHBOARD_V2_MAX_DEPTH": 1}
    )

    assert _post(client, make_document("a", "b")).status_code == 201
    too_many = _post(client, make_document("a", "b", "c"))
    assert too_many.status_code == 422
    assert "the limit is 3" in too_many.get_json()["message"]


def test_oversized_body_is_413(
    client: Any,
    app: Any,
    mocker: MockerFixture,
    dashboard_v2_enabled: None,
    editor: None,
    v2_session: Session,
) -> None:
    pk = _create(client)
    mocker.patch.dict(app.config, {"DASHBOARD_V2_MAX_DOCUMENT_BYTES": 2000})
    document = make_document()
    document["nodes"]["node_1"]["props"]["content"] = "x" * 5000

    created = _post(client, document)
    updated = _put(client, pk, document, base_revision=1)

    assert created.status_code == 413
    assert updated.status_code == 413
    assert "2000 bytes" in created.get_json()["message"]
    assert stored_document(v2_session, pk)["revision"] == 1


@pytest.mark.parametrize(
    "raw",
    [
        # Two nodes sharing an id would otherwise collapse silently.
        '{"dashboard_title": "t", "document": {"nodes": {"root": {"type": "grid",'
        ' "children": []}, "root": {"type": "grid", "children": []}}}}',
        '{"dashboard_title": "t", "document": {"nodes": {"root": {"type": "grid",'
        ' "children": [], "layout": {"gap": NaN}}}}}',
        '{"dashboard_title": "t", "document": {"nodes": {"root": {"type": "grid",'
        ' "children": [], "layout": {"gap": Infinity}}}}}',
        '{"dashboard_title": "t", "document": ' + "[" * 100_000 + "}",
        "not json at all",
        '["an", "array"]',
        "",
    ],
)
def test_bodies_that_are_not_strict_json_are_400(
    client: Any,
    dashboard_v2_enabled: None,
    editor: None,
    v2_session: Session,
    raw: str,
) -> None:
    """Duplicate ids, non-JSON numbers and parser-exhausting nesting are
    refused as a client error, never as a 500."""
    pk = _create(client)

    created = client.post(BASE, data=raw, content_type="application/json")
    updated = client.put(
        f"{BASE}{pk}",
        data=raw,
        content_type="application/json",
        headers={"If-Match": '"1"'},
    )

    assert created.status_code == 400, created.get_json()
    assert updated.status_code == 400, updated.get_json()


def test_unknown_body_fields_and_missing_title_are_400(
    client: Any, dashboard_v2_enabled: None, editor: None, v2_session: Session
) -> None:
    missing_title = client.post(BASE, json={"document": make_document()})
    unknown_field = client.post(
        BASE,
        json={
            "dashboard_title": "t",
            "document": make_document(),
            "owners": [1],
        },
    )

    assert missing_title.status_code == 400
    assert unknown_field.status_code == 400


# --------------------------------------------------------------------------
# Authorization
# --------------------------------------------------------------------------


def test_non_editor_cannot_overwrite(
    client: Any,
    mocker: MockerFixture,
    dashboard_v2_enabled: None,
    editor: None,
    v2_session: Session,
) -> None:
    pk = _create(client)
    check = mocker.patch.object(
        security_manager, "raise_for_editorship", side_effect=_denied()
    )

    response = _put(client, pk, make_document("hijacked"), base_revision=1)

    assert response.status_code == 403
    check.assert_called_once()
    stored = stored_document(v2_session, pk)
    assert stored["revision"] == 1
    assert set(stored["nodes"]) == {"root", "node_1"}


def test_editorship_is_checked_before_the_revision(
    client: Any,
    mocker: MockerFixture,
    dashboard_v2_enabled: None,
    editor: None,
    v2_session: Session,
) -> None:
    """A caller who may not edit learns nothing about the current revision."""
    pk = _create(client)
    mocker.patch.object(security_manager, "raise_for_editorship", side_effect=_denied())

    response = _put(client, pk, make_document(), base_revision=99)

    assert response.status_code == 403
    assert "current_revision" not in response.get_json()


def test_user_without_access_cannot_load(
    client: Any,
    mocker: MockerFixture,
    dashboard_v2_enabled: None,
    editor: None,
    v2_session: Session,
) -> None:
    pk = _create(client)
    check = mocker.patch.object(
        security_manager, "raise_for_access", side_effect=_denied()
    )

    response = client.get(f"{BASE}{pk}")

    assert response.status_code == 403
    assert "document" not in json.dumps(response.get_json())
    assert check.call_args.kwargs["dashboard"].id == pk


def test_route_permissions_are_enforced(
    client: Any,
    mocker: MockerFixture,
    dashboard_v2_enabled: None,
    v2_session: Session,
) -> None:
    """Without ``can read`` / ``can write on Dashboard`` the routes refuse the
    caller before any command runs."""
    mocker.patch(
        "flask_appbuilder.security.decorators.verify_jwt_in_request",
        return_value=True,
    )
    mocker.patch.object(security_manager, "is_item_public", return_value=False)
    has_access = mocker.patch.object(security_manager, "has_access", return_value=False)

    assert client.get(f"{BASE}1").status_code in (401, 403)
    assert _post(client, make_document()).status_code in (401, 403)
    assert _put(client, 1, make_document(), base_revision=1).status_code in (401, 403)
    assert {call.args for call in has_access.call_args_list} == {
        ("can_read", "Dashboard"),
        ("can_write", "Dashboard"),
    }


def test_unknown_and_non_v2_dashboards_are_404(
    client: Any, dashboard_v2_enabled: None, editor: None, v2_session: Session
) -> None:
    from superset.models.dashboard import Dashboard

    legacy = Dashboard(dashboard_title="legacy", json_metadata=json.dumps({}))
    v2_session.add(legacy)
    v2_session.commit()

    assert client.get(f"{BASE}99999").status_code == 404
    assert client.get(f"{BASE}{legacy.id}").status_code == 404
    assert _put(client, 99999, make_document(), base_revision=1).status_code == 404
    assert _put(client, legacy.id, make_document(), base_revision=0).status_code == 404
    assert json.loads(v2_session.get(Dashboard, legacy.id).json_metadata) == {}


def test_embedded_route_only_resolves_embedded_uuids(
    client: Any,
    mocker: MockerFixture,
    dashboard_v2_enabled: None,
    editor: None,
    v2_session: Session,
) -> None:
    from superset.models.dashboard import Dashboard
    from superset.models.embedded_dashboard import EmbeddedDashboard

    pk = _create(client)
    dashboard = v2_session.get(Dashboard, pk)
    embedded = EmbeddedDashboard(dashboard_id=pk, allow_domain_list="https://a.example")
    v2_session.add(embedded)
    v2_session.commit()

    by_embedded = client.get(f"{BASE}embedded/{embedded.uuid}")
    assert by_embedded.status_code == 200
    result = by_embedded.get_json()["result"]
    assert result["id"] == pk
    assert result["embedded"] == {
        "uuid": str(embedded.uuid),
        "allowed_domains": ["https://a.example"],
    }
    # The generic route accepts the embedded uuid as well.
    assert client.get(f"{BASE}{embedded.uuid}").status_code == 200
    # The embedded route accepts nothing but an embedded uuid.
    assert client.get(f"{BASE}embedded/{pk}").status_code == 404
    assert client.get(f"{BASE}embedded/{dashboard.uuid}").status_code == 404

    # A guest is not told which domains the embed is allowed on.
    mocker.patch.object(security_manager, "is_guest_user", return_value=True)
    guest = client.get(f"{BASE}embedded/{embedded.uuid}").get_json()["result"]
    assert guest["embedded"] == {"uuid": str(embedded.uuid)}
