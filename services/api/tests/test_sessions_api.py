from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.conftest import make_image, upload


def _image_id(client: TestClient) -> str:
    response = upload(client, make_image())
    assert response.status_code == 201
    return str(response.json()["imageId"])


def _new_session(client: TestClient) -> dict[str, object]:
    response = client.post("/api/v1/sessions", json={"imageId": _image_id(client)})
    assert response.status_code == 201, response.text
    return response.json()


def _recipe(exposure: float = 0.2) -> dict[str, object]:
    return {"adjustments": {"exposureEv": exposure}}


def _commit(
    client: TestClient,
    session: dict[str, object],
    *,
    exposure: float = 0.2,
    key: str | None = None,
    recipe: dict[str, object] | None = None,
    source: str | None = None,
):
    body: dict[str, object] = {
        "recipe": recipe if recipe is not None else _recipe(exposure),
        "parentRevisionId": session["activeRevisionId"],
    }
    if source is not None:
        body["source"] = source
    headers = {} if key is None else {"Idempotency-Key": key}
    return client.post(
        f"/api/v1/sessions/{session['sessionId']}/revisions",
        json=body,
        headers=headers,
    )


def _get(client: TestClient, session_id: object) -> dict[str, object]:
    response = client.get(f"/api/v1/sessions/{session_id}")
    assert response.status_code == 200, response.text
    return response.json()


def test_session_creation_starts_with_initial_revision(client: TestClient):
    image_id = _image_id(client)

    response = client.post("/api/v1/sessions", json={"imageId": image_id})

    assert response.status_code == 201
    state = response.json()
    assert state["imageId"] == image_id
    assert state["activeRevisionId"] == state["headRevisionId"]
    assert state["canUndo"] is False
    assert state["canRedo"] is False
    revision = state["revision"]
    assert revision["id"] == state["activeRevisionId"]
    assert revision["revisionNo"] == 1
    assert revision["parentId"] is None
    assert revision["source"] == "initial"
    assert revision["recipe"]["styleId"] == "natural"
    assert revision["recipe"]["adjustments"]["exposureEv"] == 0
    assert revision["createdAt"].endswith("Z")

    assert _get(client, state["sessionId"]) == state


def test_commit_creates_active_revision_and_updates_head(client: TestClient):
    session = _new_session(client)

    response = _commit(client, session, exposure=0.4, source="ai")

    assert response.status_code == 201, response.text
    state = response.json()
    assert state["revision"]["revisionNo"] == 2
    assert state["revision"]["source"] == "ai"
    assert state["revision"]["parentId"] == session["activeRevisionId"]
    assert state["revision"]["recipe"]["adjustments"]["exposureEv"] == 0.4
    assert state["activeRevisionId"] == state["revision"]["id"]
    assert state["headRevisionId"] == state["revision"]["id"]
    assert state["canUndo"] is True
    assert state["canRedo"] is False


def test_commit_with_stale_parent_returns_revision_conflict(client: TestClient):
    session = _new_session(client)
    committed = _commit(client, session, exposure=0.4).json()

    stale = client.post(
        f"/api/v1/sessions/{session['sessionId']}/revisions",
        json={
            "recipe": _recipe(0.6),
            "parentRevisionId": session["activeRevisionId"],
        },
    )

    assert stale.status_code == 409
    error = stale.json()["error"]
    assert error["code"] == "revision_conflict"
    assert error["details"]["activeRevisionId"] == committed["activeRevisionId"]
    assert _get(client, session["sessionId"]) == committed


def test_idempotent_replay_returns_the_original_revision(client: TestClient):
    session = _new_session(client)
    key = str(uuid4())

    first = _commit(client, session, exposure=0.4, key=key)
    replay = _commit(client, session, exposure=0.4, key=key)

    assert first.status_code == 201
    assert replay.status_code == 200
    original = first.json()
    assert replay.json() == original

    listing = client.get(f"/api/v1/sessions/{session['sessionId']}/revisions").json()
    assert [item["revisionNo"] for item in listing["items"]] == [2, 1]
    assert listing["items"][0]["source"] == "user"


def test_idempotency_key_reuse_with_different_content_conflicts(
    client: TestClient,
):
    session = _new_session(client)
    key = str(uuid4())

    first = _commit(client, session, exposure=0.4, key=key)
    assert first.status_code == 201
    committed = first.json()

    changed_recipe = _commit(client, session, exposure=-1.5, key=key)
    assert changed_recipe.status_code == 409
    assert changed_recipe.json()["error"]["code"] == "idempotency_key_reuse"

    changed_parent = _commit(client, committed, exposure=0.4, key=key)
    assert changed_parent.status_code == 409
    assert changed_parent.json()["error"]["code"] == "idempotency_key_reuse"

    assert _get(client, session["sessionId"]) == committed
    listing = client.get(f"/api/v1/sessions/{session['sessionId']}/revisions").json()
    assert [item["revisionNo"] for item in listing["items"]] == [2, 1]


def test_undo_redo_and_their_boundaries(client: TestClient):
    session = _new_session(client)
    session = _commit(client, session, exposure=0.4).json()

    undo = client.post(f"/api/v1/sessions/{session['sessionId']}/undo")
    assert undo.status_code == 200
    state = undo.json()
    assert state["activeRevisionId"] == session["revision"]["parentId"]
    assert state["headRevisionId"] == session["headRevisionId"]
    assert state["canUndo"] is False
    assert state["canRedo"] is True

    redo = client.post(f"/api/v1/sessions/{session['sessionId']}/redo")
    assert redo.status_code == 200
    assert redo.json()["activeRevisionId"] == session["activeRevisionId"]
    assert redo.json()["canRedo"] is False

    nothing_redo = client.post(f"/api/v1/sessions/{session['sessionId']}/redo")
    assert nothing_redo.status_code == 409
    assert nothing_redo.json()["error"]["code"] == "nothing_to_redo"

    root = _new_session(client)
    nothing_undo = client.post(f"/api/v1/sessions/{root['sessionId']}/undo")
    assert nothing_undo.status_code == 409
    assert nothing_undo.json()["error"]["code"] == "nothing_to_undo"


def test_undo_with_stale_expected_revision_conflicts(client: TestClient):
    session = _new_session(client)
    initial_id = session["activeRevisionId"]
    session = _commit(client, session, exposure=0.4).json()

    stale = client.post(
        f"/api/v1/sessions/{session['sessionId']}/undo",
        json={"revisionId": initial_id},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "revision_conflict"

    matched = client.post(
        f"/api/v1/sessions/{session['sessionId']}/undo",
        json={"revisionId": session["activeRevisionId"]},
    )
    assert matched.status_code == 200
    assert matched.json()["activeRevisionId"] == initial_id


def test_activate_switches_revision_without_moving_head(client: TestClient):
    session = _new_session(client)
    first = session["activeRevisionId"]
    session = _commit(client, session, exposure=0.4).json()
    second = session["activeRevisionId"]
    session = _commit(client, session, exposure=0.8).json()
    head = session["headRevisionId"]

    activated = client.post(
        f"/api/v1/sessions/{session['sessionId']}/activate",
        json={"revisionId": first},
    )

    assert activated.status_code == 200
    state = activated.json()
    assert state["activeRevisionId"] == first
    assert state["headRevisionId"] == head
    assert state["canRedo"] is True

    missing = client.post(
        f"/api/v1/sessions/{session['sessionId']}/activate",
        json={"revisionId": str(uuid4())},
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "revision_not_found"
    assert state["revision"]["parentId"] is None
    assert second != first


def test_branch_commit_moves_head_and_keeps_the_old_branch(client: TestClient):
    session = _new_session(client)
    initial = session["activeRevisionId"]
    session = _commit(client, session, exposure=0.4).json()
    abandoned = session["activeRevisionId"]

    undone = client.post(f"/api/v1/sessions/{session['sessionId']}/undo").json()
    branch = _commit(client, undone, exposure=-0.6)

    assert branch.status_code == 201
    state = branch.json()
    assert state["revision"]["revisionNo"] == 3
    assert state["revision"]["parentId"] == initial
    assert state["headRevisionId"] == state["activeRevisionId"]
    assert state["canRedo"] is False

    listing = client.get(f"/api/v1/sessions/{session['sessionId']}/revisions").json()
    assert [item["revisionNo"] for item in listing["items"]] == [3, 2, 1]

    switched = client.post(
        f"/api/v1/sessions/{session['sessionId']}/activate",
        json={"revisionId": abandoned},
    )
    assert switched.status_code == 200
    assert switched.json()["canRedo"] is False
    redo = client.post(f"/api/v1/sessions/{session['sessionId']}/redo")
    assert redo.status_code == 409
    assert redo.json()["error"]["code"] == "nothing_to_redo"


def test_reset_is_a_noop_when_the_active_recipe_is_default(client: TestClient):
    session = _new_session(client)

    response = client.post(f"/api/v1/sessions/{session['sessionId']}/reset")

    assert response.status_code == 200
    assert response.json() == session
    listing = client.get(f"/api/v1/sessions/{session['sessionId']}/revisions").json()
    assert len(listing["items"]) == 1


def test_reset_creates_a_default_revision_and_keeps_history(client: TestClient):
    session = _new_session(client)
    session = _commit(client, session, exposure=0.7).json()

    response = client.post(f"/api/v1/sessions/{session['sessionId']}/reset")

    assert response.status_code == 200
    state = response.json()
    assert state["revision"]["revisionNo"] == 3
    assert state["revision"]["source"] == "reset"
    assert state["revision"]["parentId"] == session["activeRevisionId"]
    assert state["revision"]["recipe"]["adjustments"]["exposureEv"] == 0
    assert state["activeRevisionId"] == state["headRevisionId"]
    assert state["canUndo"] is True
    assert state["canRedo"] is False

    again = client.post(f"/api/v1/sessions/{session['sessionId']}/reset")
    assert again.status_code == 200
    assert again.json() == state
    listing = client.get(f"/api/v1/sessions/{session['sessionId']}/revisions").json()
    assert [item["revisionNo"] for item in listing["items"]] == [3, 2, 1]


def test_revision_list_paginates_in_descending_order(client: TestClient):
    session = _new_session(client)
    for exposure in (0.1, 0.2, 0.3):
        session = _commit(client, session, exposure=exposure).json()

    first = client.get(
        f"/api/v1/sessions/{session['sessionId']}/revisions",
        params={"limit": 2},
    )
    assert first.status_code == 200
    page = first.json()
    assert [item["revisionNo"] for item in page["items"]] == [4, 3]
    assert page["nextCursor"] == "3"
    assert all(len(item["recipeHash"]) == 64 for item in page["items"])
    assert page["items"][0]["createdAt"].endswith("Z")

    second = client.get(
        f"/api/v1/sessions/{session['sessionId']}/revisions",
        params={"limit": 2, "cursor": page["nextCursor"]},
    )
    assert second.status_code == 200
    final = second.json()
    assert [item["revisionNo"] for item in final["items"]] == [2, 1]
    assert final["nextCursor"] is None


def test_unknown_resources_and_invalid_payloads(client: TestClient):
    unknown_session = str(uuid4())
    assert client.get(f"/api/v1/sessions/{unknown_session}").status_code == 404
    assert client.get(f"/api/v1/sessions/{unknown_session}").json()["error"]["code"] == (
        "session_not_found"
    )
    assert client.get("/api/v1/sessions/not-a-uuid").status_code == 404
    assert (
        client.post(f"/api/v1/sessions/{unknown_session}/undo").json()["error"]["code"]
        == "session_not_found"
    )

    assert (
        client.post("/api/v1/sessions", json={"imageId": str(uuid4())}).json()["error"]["code"]
        == "image_not_found"
    )

    session = _new_session(client)
    url = f"/api/v1/sessions/{session['sessionId']}/revisions"

    missing_parent = client.post(url, json={"recipe": _recipe()})
    assert missing_parent.status_code == 422

    initial_source = client.post(
        url,
        json={
            "recipe": _recipe(),
            "parentRevisionId": session["activeRevisionId"],
            "source": "initial",
        },
    )
    assert initial_source.status_code == 422

    out_of_range = client.post(
        url,
        json={
            "recipe": {"adjustments": {"exposureEv": 9}},
            "parentRevisionId": session["activeRevisionId"],
        },
    )
    assert out_of_range.status_code == 422

    extra_field = client.post(
        url,
        json={
            "recipe": {"adjustments": {"exposureEv": 0.2, "unknown": 1}},
            "parentRevisionId": session["activeRevisionId"],
        },
    )
    assert extra_field.status_code == 422

    assert (
        client.get(
            f"/api/v1/sessions/{session['sessionId']}/revisions",
            params={"limit": 0},
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"/api/v1/sessions/{session['sessionId']}/revisions",
            params={"cursor": "abc"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/v1/sessions/{unknown_session}/revisions",
            json={"recipe": _recipe(), "parentRevisionId": str(uuid4())},
        ).status_code
        == 404
    )
