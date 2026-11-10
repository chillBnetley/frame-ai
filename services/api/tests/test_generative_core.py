from __future__ import annotations

import hashlib
import time

import numpy as np
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.repositories.db import connect
from app.services.generative_service import composite_protected_region
from tests.conftest import make_image, upload

TERMINAL = {"succeeded", "failed", "cancelled", "expired"}


def _new_session(client: TestClient) -> dict[str, object]:
    response = upload(client, make_image())
    assert response.status_code == 201, response.text
    image_id = str(response.json()["imageId"])
    created = client.post("/api/v1/sessions", json={"imageId": image_id})
    assert created.status_code == 201, created.text
    return created.json()


def _create_task(
    client: TestClient,
    session: dict[str, object],
    *,
    instruction: str = "warm the scene slightly",
    idempotency_key: str | None = None,
):
    headers = {} if idempotency_key is None else {"Idempotency-Key": idempotency_key}
    return client.post(
        "/api/v1/generative/tasks",
        json={
            "sessionId": session["sessionId"],
            "taskType": "local_edit",
            "instruction": instruction,
            "params": {"candidates": 1},
        },
        headers=headers,
    )


def _wait_for_task(client: TestClient, task_id: str, timeout: float = 10.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/generative/tasks/{task_id}")
        assert response.status_code == 200, response.text
        payload = response.json()
        if payload["status"] in TERMINAL:
            return payload
        time.sleep(0.02)
    raise AssertionError(f"task {task_id} did not finish")


def _run_task(client: TestClient, session: dict[str, object], **kwargs) -> dict[str, object]:
    created = _create_task(client, session, **kwargs)
    assert created.status_code == 201, created.text
    return _wait_for_task(client, created.json()["taskId"])


def test_capabilities_describe_the_mock_provider(client: TestClient):
    response = client.get("/api/v1/generative/capabilities")
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "mock"
    assert payload["isMock"] is True
    assert payload["supportedTaskTypes"] == ["local_edit"]
    assert payload["supportsMask"] is True
    assert "Mock" in payload["declaredRetention"]


def test_local_edit_runs_accepts_and_preserves_the_original(
    client: TestClient,
    settings: Settings,
):
    session = _new_session(client)
    image_row = _image_row(settings, str(session["imageId"]))
    original_path = settings.data_dir / str(image_row["storage_key"])
    original_hash = hashlib.sha256(original_path.read_bytes()).hexdigest()

    task = _run_task(client, session)
    assert task["status"] == "succeeded", task
    assert task["isMock"] is True
    assert len(task["results"]) == 1
    result = task["results"][0]
    assert result["status"] == "candidate"
    assert "mock_output" in result["warnings"]

    image = client.get(result["imageUrl"])
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.content

    accepted = client.post(f"/api/v1/generative/results/{result['resultId']}/accept")
    assert accepted.status_code == 200, accepted.text
    state = accepted.json()
    assert state["revision"]["source"] == "ai"
    assert state["revision"]["generativeTaskId"] == task["taskId"]
    assert state["revision"]["baseGeneratedAssetId"] is not None

    replacement = hashlib.sha256(original_path.read_bytes()).hexdigest()
    assert replacement == original_hash

    render = client.post(
        f"/api/v1/sessions/{session['sessionId']}/render",
        json={"recipe": state["revision"]["recipe"], "quality": "final"},
    )
    assert render.status_code == 200, render.text
    compare = client.get(f"/api/v1/sessions/{session['sessionId']}/compare")
    assert compare.status_code == 200, compare.text
    export = client.post(
        f"/api/v1/sessions/{session['sessionId']}/export",
        json={"revisionId": state["activeRevisionId"], "format": "png"},
    )
    assert export.status_code == 200, export.text
    assert export.headers["content-type"] == "image/png"


def test_later_color_edit_and_reset_keep_the_generated_base(
    client: TestClient,
    settings: Settings,
):
    session = _new_session(client)
    task = _run_task(client, session)
    result = task["results"][0]
    accepted = client.post(f"/api/v1/generative/results/{result['resultId']}/accept")
    assert accepted.status_code == 200, accepted.text
    first = accepted.json()
    base_id = first["revision"]["baseGeneratedAssetId"]
    assert base_id is not None

    edited = client.post(
        f"/api/v1/sessions/{session['sessionId']}/revisions",
        json={
            "recipe": {"adjustments": {"exposureEv": 0.25}},
            "parentRevisionId": first["activeRevisionId"],
        },
    )
    assert edited.status_code == 201, edited.text
    edited_state = edited.json()
    assert edited_state["revision"]["baseGeneratedAssetId"] == base_id
    assert edited_state["revision"]["generativeTaskId"] is None
    assert edited_state["revision"]["source"] == "user"

    reset = client.post(f"/api/v1/sessions/{session['sessionId']}/reset")
    assert reset.status_code == 200, reset.text
    reset_state = reset.json()
    assert reset_state["revision"]["baseGeneratedAssetId"] == base_id
    assert reset_state["revision"]["generativeTaskId"] is None

    render = client.post(
        f"/api/v1/sessions/{session['sessionId']}/render",
        json={"recipe": reset_state["revision"]["recipe"], "quality": "final"},
    )
    assert render.status_code == 200, render.text


def test_accepting_twice_returns_the_same_revision(client: TestClient):
    session = _new_session(client)
    task = _run_task(client, session)
    result = task["results"][0]

    first = client.post(f"/api/v1/generative/results/{result['resultId']}/accept")
    second = client.post(f"/api/v1/generative/results/{result['resultId']}/accept")
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["activeRevisionId"] == second.json()["activeRevisionId"]


def test_rejecting_a_result_leaves_the_active_revision_untouched(client: TestClient):
    session = _new_session(client)
    before = client.get(f"/api/v1/sessions/{session['sessionId']}").json()
    task = _run_task(client, session)
    result = task["results"][0]

    rejected = client.post(f"/api/v1/generative/results/{result['resultId']}/reject")
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"

    after = client.get(f"/api/v1/sessions/{session['sessionId']}").json()
    assert after["activeRevisionId"] == before["activeRevisionId"]


def test_duplicate_task_is_deduplicated_and_idempotency_is_enforced(client: TestClient):
    session = _new_session(client)
    first = _create_task(client, session, instruction="same instruction")
    assert first.status_code == 201, first.text
    task_id = first.json()["taskId"]
    _wait_for_task(client, task_id)

    duplicate = _create_task(client, session, instruction="same instruction")
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["taskId"] == task_id
    assert duplicate.json()["deduplicated"] is True

    keyed = _create_task(client, session, instruction="keyed instruction", idempotency_key="key-1")
    assert keyed.status_code == 201, keyed.text
    _wait_for_task(client, keyed.json()["taskId"])
    reuse = _create_task(client, session, instruction="different", idempotency_key="key-1")
    assert reuse.status_code == 409
    assert reuse.json()["error"]["code"] == "idempotency_key_reuse"


def test_accept_refuses_when_the_base_revision_changed(client: TestClient):
    session = _new_session(client)
    task = _run_task(client, session)
    result = task["results"][0]

    edited = client.post(
        f"/api/v1/sessions/{session['sessionId']}/revisions",
        json={
            "recipe": {"adjustments": {"exposureEv": 0.4}},
            "parentRevisionId": session["activeRevisionId"],
        },
    )
    assert edited.status_code == 201, edited.text

    accepted = client.post(f"/api/v1/generative/results/{result['resultId']}/accept")
    assert accepted.status_code == 409
    assert accepted.json()["error"]["code"] == "generative_base_changed"


def test_deleting_the_image_purges_generated_rows_and_files(
    client: TestClient,
    settings: Settings,
):
    session = _new_session(client)
    task = _run_task(client, session)
    result = task["results"][0]
    accepted = client.post(f"/api/v1/generative/results/{result['resultId']}/accept")
    assert accepted.status_code == 200, accepted.text

    connection = connect(settings.database_path)
    try:
        asset = connection.execute(
            "SELECT storage_key FROM generated_asset WHERE result_id = ?",
            (result["resultId"],),
        ).fetchone()
        result_key = connection.execute(
            "SELECT storage_key FROM generative_result WHERE id = ?",
            (result["resultId"],),
        ).fetchone()
    finally:
        connection.close()
    assert asset is not None and result_key is not None
    asset_path = settings.data_dir / str(asset["storage_key"])
    result_path = settings.data_dir / str(result_key["storage_key"])
    assert asset_path.is_file()
    assert result_path.is_file()

    deleted = client.delete(f"/api/v1/images/{session['imageId']}")
    assert deleted.status_code == 204
    assert not asset_path.exists()
    assert not result_path.exists()

    connection = connect(settings.database_path)
    try:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) AS total FROM {table}").fetchone()["total"]
            for table in ("generative_task", "generative_result", "generated_asset")
        }
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        connection.close()
    assert counts == {"generative_task": 0, "generative_result": 0, "generated_asset": 0}
    assert foreign_keys == []


def test_protected_region_composite_keeps_outside_pixels_identical():
    rng = np.random.default_rng(7)
    source = rng.integers(0, 256, size=(12, 16, 3), dtype=np.uint8)
    generated = rng.integers(0, 256, size=(12, 16, 3), dtype=np.uint8)
    mask = np.zeros((12, 16), dtype=np.uint8)
    mask[3:9, 4:12] = 255

    output = composite_protected_region(source, generated, mask)

    assert np.array_equal(output[mask == 0], source[mask == 0])
    assert np.array_equal(output[mask == 255], generated[mask == 255])


def test_generative_task_rejects_unsupported_types(client: TestClient):
    session = _new_session(client)
    response = client.post(
        "/api/v1/generative/tasks",
        json={
            "sessionId": session["sessionId"],
            "taskType": "outpaint",
            "instruction": "extend the frame",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "generative_capability_unsupported"


def test_result_image_is_not_found_for_a_missing_result(client: TestClient):
    missing = "2a3f4b5c-6d7e-4f80-9a1b-2c3d4e5f6a7b"
    response = client.get(f"/api/v1/generative/results/{missing}/image")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "generative_result_not_found"


def _image_row(settings: Settings, image_id: str) -> dict[str, object]:
    connection = connect(settings.database_path)
    try:
        row = connection.execute(
            "SELECT * FROM image_asset WHERE id = ?",
            (image_id,),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    return dict(row)
