from __future__ import annotations

import hashlib
import json
import time
from io import BytesIO

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import Settings
from app.imaging.generative_local_edit import (
    restore_local_edit_protected_region,
    simulate_local_repaint,
    validate_local_edit_mask,
)
from app.repositories.db import connect
from tests.conftest import make_image, upload

FLAT = (120, 80, 40)


def _new_session(client: TestClient) -> dict[str, object]:
    response = upload(client, make_image(size=(100, 100)))
    assert response.status_code == 201, response.text
    image_id = str(response.json()["imageId"])
    created = client.post("/api/v1/sessions", json={"imageId": image_id})
    assert created.status_code == 201, created.text
    session = created.json()
    session["imageId"] = image_id
    return session


def _create_rect_mask(
    client: TestClient,
    session_id: str,
    region: dict[str, float] | None = None,
) -> str:
    if region is None:
        region = {"x": 0.3, "y": 0.3, "width": 0.4, "height": 0.4}
    response = client.post(
        "/api/v1/generative/masks",
        json={"sessionId": session_id, "kind": "rect", "definition": {"region": region}},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["maskId"])


def _create_task(
    client: TestClient,
    session: dict[str, object],
    *,
    instruction: str = "replace the wall with weathered brick",
    mask_id: str | None = None,
):
    return client.post(
        "/api/v1/generative/tasks",
        json={
            "sessionId": session["sessionId"],
            "taskType": "local_edit",
            "instruction": instruction,
            "maskId": mask_id,
        },
    )


def _wait_for_task(client: TestClient, task_id: str, timeout: float = 10.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    payload: dict[str, object] = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/generative/tasks/{task_id}")
        assert response.status_code == 200, response.text
        payload = response.json()
        if payload["status"] in {"succeeded", "failed", "cancelled", "expired"}:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} did not finish: {payload}")


def _result_pixels(client: TestClient, image_url: str) -> np.ndarray:
    response = client.get(image_url)
    assert response.status_code == 200, response.text
    with Image.open(BytesIO(response.content)) as opened:
        return np.asarray(opened.convert("RGB"))


def _mask_array(client: TestClient, mask_id: str) -> np.ndarray:
    response = client.get(f"/api/v1/generative/masks/{mask_id}/image")
    assert response.status_code == 200, response.text
    with Image.open(BytesIO(response.content)) as opened:
        return np.asarray(opened.convert("L"))


# ---------------------------------------------------------------------------
# validate_local_edit_mask


def test_validate_local_edit_mask_accepts_a_partial_region() -> None:
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[20:60, 10:50] = 255
    validate_local_edit_mask(mask)


def test_validate_local_edit_mask_rejects_non_grayscale() -> None:
    with pytest.raises(ValueError, match="2D grayscale"):
        validate_local_edit_mask(np.zeros((10, 10, 3), dtype=np.uint8))


def test_validate_local_edit_mask_rejects_an_empty_mask() -> None:
    with pytest.raises(ValueError, match="empty"):
        validate_local_edit_mask(np.zeros((0, 0), dtype=np.uint8))


def test_validate_local_edit_mask_rejects_no_active_pixels() -> None:
    with pytest.raises(ValueError, match="no active pixels"):
        validate_local_edit_mask(np.zeros((100, 100), dtype=np.uint8))


def test_validate_local_edit_mask_rejects_full_coverage() -> None:
    with pytest.raises(ValueError, match="exceeds maximum allowable"):
        validate_local_edit_mask(np.full((100, 100), 255, dtype=np.uint8))


# ---------------------------------------------------------------------------
# restore_local_edit_protected_region


def test_restore_local_edit_keeps_unmasked_bytes_identical() -> None:
    rng = np.random.default_rng(11)
    input_pixels = rng.integers(0, 256, size=(100, 100, 3), dtype=np.uint8)
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[30:70, 30:70] = 255

    output_pixels = input_pixels.copy()
    output_pixels[30:70, 30:70] = rng.integers(0, 256, size=(40, 40, 3), dtype=np.uint8)
    # The provider also disturbed protected pixels.
    output_pixels[2, 2] = ((output_pixels[2, 2].astype(np.int32) + 60) % 255).astype(np.uint8)

    restored, warnings = restore_local_edit_protected_region(input_pixels, output_pixels, mask)

    assert warnings == ["protected_region_restored"]
    protected = mask == 0
    assert np.array_equal(restored[protected], input_pixels[protected])
    assert np.array_equal(restored[2, 2], input_pixels[2, 2])
    assert not np.array_equal(restored[30:70, 30:70], input_pixels[30:70, 30:70])


def test_restore_local_edit_blends_the_transition_zone() -> None:
    rng = np.random.default_rng(5)
    input_pixels = np.full((40, 40, 3), 10, dtype=np.uint8)
    output_pixels = rng.integers(120, 256, size=(40, 40, 3), dtype=np.uint8)
    mask = np.zeros((40, 40), dtype=np.uint8)
    mask[10:20, :] = 255
    mask[20:30, :] = 128

    restored, _ = restore_local_edit_protected_region(input_pixels, output_pixels, mask)

    assert np.array_equal(restored[:10], input_pixels[:10])
    assert np.array_equal(restored[10:20], output_pixels[10:20])
    alpha = np.float32(128) / np.float32(255)
    expected = np.rint(10.0 * (1.0 - alpha) + output_pixels[20:30].astype(np.float32) * alpha)
    np.testing.assert_allclose(restored[20:30].astype(np.float32), expected, atol=1.0)
    assert not np.array_equal(restored[20:30], input_pixels[20:30])
    assert not np.array_equal(restored[20:30], output_pixels[20:30])


def test_restore_local_edit_rejects_an_unchanged_edit_area() -> None:
    input_pixels = np.full((60, 60, 3), 90, dtype=np.uint8)
    mask = np.zeros((60, 60), dtype=np.uint8)
    mask[10:30, 10:30] = 255

    with pytest.raises(ValueError, match="no visible change"):
        restore_local_edit_protected_region(input_pixels, input_pixels.copy(), mask)


def test_restore_local_edit_rejects_a_flat_edit_region() -> None:
    rng = np.random.default_rng(3)
    input_pixels = rng.integers(0, 256, size=(60, 60, 3), dtype=np.uint8)
    mask = np.zeros((60, 60), dtype=np.uint8)
    mask[10:40, 10:40] = 255

    output_pixels = input_pixels.copy()
    output_pixels[10:40, 10:40] = 77

    with pytest.raises(ValueError, match="lacks visible variation"):
        restore_local_edit_protected_region(input_pixels, output_pixels, mask)


def test_restore_local_edit_rejects_mismatched_shapes() -> None:
    input_pixels = np.zeros((40, 40, 3), dtype=np.uint8)
    mask = np.zeros((40, 40), dtype=np.uint8)
    mask[5:10, 5:10] = 255

    with pytest.raises(ValueError, match="shapes must match"):
        restore_local_edit_protected_region(input_pixels, np.zeros((20, 20, 3), np.uint8), mask)
    with pytest.raises(ValueError, match="does not match image dimensions"):
        restore_local_edit_protected_region(
            input_pixels,
            input_pixels.copy(),
            np.zeros((30, 30), dtype=np.uint8),
        )
    with pytest.raises(ValueError, match="no editable pixels"):
        restore_local_edit_protected_region(input_pixels, input_pixels.copy(), mask * 0)


# ---------------------------------------------------------------------------
# simulate_local_repaint


def _texture_input() -> np.ndarray:
    return np.full((64, 64, 3), 120, dtype=np.uint8)


def test_simulate_local_repaint_protects_the_unmasked_region() -> None:
    source = _texture_input()
    mask = np.zeros((64, 64), dtype=np.uint8)
    mask[:, 32:] = 255

    repainted = simulate_local_repaint(source, mask, "turn it into brushed steel")

    assert repainted.shape == source.shape
    assert np.array_equal(repainted[:, :32], source[:, :32])
    assert not np.array_equal(repainted[:, 32:], source[:, 32:])
    assert float(np.std(repainted[:, 32:].astype(np.float32))) >= 0.5


def test_simulate_local_repaint_is_driven_by_the_instruction() -> None:
    source = _texture_input()
    mask = np.zeros((64, 64), dtype=np.uint8)
    mask[:, 32:] = 255

    dusk = simulate_local_repaint(source, mask, "make it dusk")
    dusk_again = simulate_local_repaint(source, mask, "MAKE IT DUSK ")
    water = simulate_local_repaint(source, mask, "replace with water")

    assert np.array_equal(dusk, dusk_again)
    assert not np.array_equal(dusk, water)


def test_simulate_local_repaint_rejects_bad_shapes() -> None:
    source = _texture_input()
    with pytest.raises(ValueError, match="HxWx3"):
        simulate_local_repaint(source[:, :, 0], np.zeros((64, 64), np.uint8), "edit")
    with pytest.raises(ValueError, match="does not match image dimensions"):
        simulate_local_repaint(source, np.zeros((32, 32), np.uint8), "edit")


# ---------------------------------------------------------------------------
# API:入参强校验


def test_local_edit_task_requires_a_mask(client: TestClient) -> None:
    session = _new_session(client)
    response = _create_task(client, session, mask_id=None)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "generative_mask_required"


def test_local_edit_task_requires_an_instruction(client: TestClient) -> None:
    session = _new_session(client)
    mask_id = _create_rect_mask(client, str(session["sessionId"]))
    missing = _create_task(client, session, instruction="", mask_id=mask_id)
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "generative_instruction_required"

    blank = _create_task(client, session, instruction="   ", mask_id=mask_id)
    assert blank.status_code == 422
    assert blank.json()["error"]["code"] == "generative_instruction_required"


def test_local_edit_requires_a_mask_that_keeps_a_protected_region(
    client: TestClient,
) -> None:
    session = _new_session(client)
    response = client.post(
        "/api/v1/generative/masks",
        json={
            "sessionId": session["sessionId"],
            "kind": "rect",
            "definition": {"region": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}},
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "generative_mask_coverage"


# ---------------------------------------------------------------------------
# API:生命周期与原图保护


def test_local_edit_task_succeeds_and_restores_protected_pixels(
    client: TestClient,
    settings: Settings,
) -> None:
    session = _new_session(client)
    mask_id = _create_rect_mask(client, str(session["sessionId"]))
    created = _create_task(client, session, mask_id=mask_id)
    assert created.status_code == 201, created.text
    task = _wait_for_task(client, str(created.json()["taskId"]))

    assert task["status"] == "succeeded", task
    assert task["isMock"] is True
    results = task["results"]
    assert len(results) == 1
    result = results[0]
    assert result["status"] == "candidate"
    assert result["width"] == 100
    assert result["height"] == 100
    assert "protected_region_restored" in result["warnings"]
    assert "mock_output" in result["warnings"]

    pixels = _result_pixels(client, str(result["imageUrl"]))
    mask_array = _mask_array(client, mask_id)
    protected = mask_array == 0
    core = mask_array >= 255
    assert np.any(protected) and np.any(core)
    assert np.array_equal(
        pixels[protected],
        np.full((int(protected.sum()), 3), FLAT, dtype=np.uint8),
    )
    assert not np.array_equal(
        pixels[core],
        np.full((int(core.sum()), 3), FLAT, dtype=np.uint8),
    )

    original_path = settings.data_dir / _storage_key(settings, str(session["imageId"]))
    original_hash = hashlib.sha256(original_path.read_bytes()).hexdigest()

    accepted = client.post(f"/api/v1/generative/results/{result['resultId']}/accept")
    assert accepted.status_code == 200, accepted.text
    state = accepted.json()
    revision = state["revision"]
    assert revision["source"] == "ai"
    assert revision["generativeTaskId"] == task["taskId"]
    assert revision["baseGeneratedAssetId"] is not None

    render = client.post(
        f"/api/v1/sessions/{session['sessionId']}/render",
        json={"recipe": revision["recipe"], "quality": "final"},
    )
    assert render.status_code == 200, render.text

    assert hashlib.sha256(original_path.read_bytes()).hexdigest() == original_hash


def test_local_edit_reject_leaves_the_revision_untouched(client: TestClient) -> None:
    session = _new_session(client)
    before = client.get(f"/api/v1/sessions/{session['sessionId']}").json()
    mask_id = _create_rect_mask(client, str(session["sessionId"]))
    created = _create_task(client, session, mask_id=mask_id)
    assert created.status_code == 201, created.text
    task = _wait_for_task(client, str(created.json()["taskId"]))
    assert task["status"] == "succeeded", task

    rejected = client.post(f"/api/v1/generative/results/{task['results'][0]['resultId']}/reject")
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"

    after = client.get(f"/api/v1/sessions/{session['sessionId']}").json()
    assert after["activeRevisionId"] == before["activeRevisionId"]
    assert after["revision"]["baseGeneratedAssetId"] == before["revision"]["baseGeneratedAssetId"]


def test_local_edit_instructions_change_the_candidate(client: TestClient) -> None:
    session = _new_session(client)
    mask_id = _create_rect_mask(client, str(session["sessionId"]))

    digests: list[str] = []
    for instruction in ("make it dusk", "replace with water"):
        created = _create_task(
            client,
            session,
            instruction=instruction,
            mask_id=mask_id,
        )
        assert created.status_code == 201, created.text
        task = _wait_for_task(client, str(created.json()["taskId"]))
        assert task["status"] == "succeeded", task
        pixels = _result_pixels(client, str(task["results"][0]["imageUrl"]))
        digests.append(hashlib.sha256(pixels.tobytes()).hexdigest())

    assert digests[0] != digests[1]


def test_local_edit_plan_targets_the_mask(client: TestClient, settings: Settings) -> None:
    session = _new_session(client)
    mask_id = _create_rect_mask(client, str(session["sessionId"]))
    created = _create_task(client, session, mask_id=mask_id)
    assert created.status_code == 201, created.text
    task_id = str(created.json()["taskId"])

    connection = connect(settings.database_path)
    try:
        row = connection.execute(
            "SELECT plan_json FROM generative_task WHERE id = ?",
            (task_id,),
        ).fetchone()
    finally:
        connection.close()

    assert row is not None
    plan = json.loads(str(row["plan_json"]))
    assert plan["task_type"] == "local_edit"
    assert plan["target"] == "mask"
    assert plan["mask_id"] == mask_id
    assert plan["preserve"] == ["unmasked original photo pixels"]


def _storage_key(settings: Settings, image_id: str) -> str:
    connection = connect(settings.database_path)
    try:
        row = connection.execute(
            "SELECT storage_key FROM image_asset WHERE id = ?",
            (image_id,),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    return str(row["storage_key"])
