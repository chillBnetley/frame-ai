from __future__ import annotations

import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.core.identity import OwnerScope
from app.imaging.generative_removal import (
    restore_removal_protected_region,
    simulate_object_removal,
    validate_removal_mask,
)
from tests.conftest import make_image, upload

OWNER = OwnerScope("local")


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
) -> dict[str, object]:
    if region is None:
        region = {"x": 0.3, "y": 0.3, "width": 0.4, "height": 0.4}
    payload = {
        "sessionId": session_id,
        "kind": "rect",
        "definition": {"region": region},
    }
    resp = client.post("/api/v1/generative/masks", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Unit tests: validate_removal_mask
# ---------------------------------------------------------------------------


def test_validate_removal_mask_valid():
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[20:40, 20:40] = 255
    validate_removal_mask(mask)


def test_validate_removal_mask_non_2d():
    mask = np.zeros((100, 100, 1), dtype=np.uint8)
    with pytest.raises(ValueError, match="2D grayscale"):
        validate_removal_mask(mask)


def test_validate_removal_mask_empty():
    mask = np.zeros((0, 0), dtype=np.uint8)
    with pytest.raises(ValueError, match="empty"):
        validate_removal_mask(mask)


def test_validate_removal_mask_no_active_pixels():
    mask = np.zeros((100, 100), dtype=np.uint8)
    with pytest.raises(ValueError, match="no active pixels"):
        validate_removal_mask(mask)


def test_validate_removal_mask_excessive_coverage():
    mask = np.full((100, 100), 255, dtype=np.uint8)
    with pytest.raises(ValueError, match="exceeds maximum allowable"):
        validate_removal_mask(mask)


# ---------------------------------------------------------------------------
# Unit tests: restore_removal_protected_region
# ---------------------------------------------------------------------------


def test_restore_removal_protected_region_preserves_exact_bytes():
    np.random.seed(42)
    input_pixels = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[30:70, 30:70] = 255

    # Simulate model output with different texture in the masked area
    output_pixels = input_pixels.copy()
    output_pixels[30:70, 30:70] = np.random.randint(50, 200, (40, 40, 3), dtype=np.uint8)
    # Intentionally corrupt an outside protected pixel
    output_pixels[5, 5] = (output_pixels[5, 5].astype(np.int32) + 50) % 255

    restored, warnings = restore_removal_protected_region(input_pixels, output_pixels, mask)
    assert "protected_region_restored" in warnings

    # Protected region must match input_pixels exactly (100% byte identity)
    outside = mask == 0
    np.testing.assert_array_equal(restored[outside], input_pixels[outside])
    # Corrupted pixel outside mask must have been restored
    np.testing.assert_array_equal(restored[5, 5], input_pixels[5, 5])
    # Inside region must have changed
    assert not np.array_equal(restored[30:70, 30:70], input_pixels[30:70, 30:70])


def test_restore_removal_rejects_no_visible_change():
    input_pixels = np.full((100, 100, 3), 128, dtype=np.uint8)
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[20:40, 20:40] = 255

    # Output identical to input
    output_pixels = input_pixels.copy()
    with pytest.raises(ValueError, match="no visible change"):
        restore_removal_protected_region(input_pixels, output_pixels, mask)


def test_restore_removal_rejects_blank_output():
    input_pixels = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[20:60, 20:60] = 255

    # Output in masked area has std 0 (completely flat color)
    output_pixels = input_pixels.copy()
    output_pixels[20:60, 20:60] = 100
    with pytest.raises(ValueError, match="lacks visible variation"):
        restore_removal_protected_region(input_pixels, output_pixels, mask)


# ---------------------------------------------------------------------------
# Unit tests: simulate_object_removal
# ---------------------------------------------------------------------------


def test_simulate_object_removal():
    input_pixels = np.full((100, 100, 3), 120, dtype=np.uint8)
    # Add a bright object
    input_pixels[40:60, 40:60] = 240
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[38:62, 38:62] = 255

    removed = simulate_object_removal(input_pixels, mask)
    assert removed.shape == input_pixels.shape
    # Outside the mask region should remain essentially unchanged
    np.testing.assert_array_equal(removed[:30, :30], input_pixels[:30, :30])
    # Inside the removed object should no longer be 240
    assert not np.array_equal(removed[40:60, 40:60], input_pixels[40:60, 40:60])


# ---------------------------------------------------------------------------
# End-to-end API Integration tests
# ---------------------------------------------------------------------------


def test_removal_task_requires_mask(client: TestClient):
    session = _new_session(client)
    response = client.post(
        "/api/v1/generative/tasks",
        json={
            "sessionId": session["sessionId"],
            "taskType": "remove",
            "instruction": "remove unwanted object",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "generative_mask_required"


def test_removal_task_lifecycle_accept(client: TestClient):
    session = _new_session(client)
    session_id = str(session["sessionId"])
    mask_view = _create_rect_mask(client, session_id)
    mask_id = mask_view["maskId"]

    # Submit task
    response = client.post(
        "/api/v1/generative/tasks",
        json={
            "sessionId": session_id,
            "taskType": "remove",
            "instruction": "erase tourist from background",
            "maskId": mask_id,
        },
    )
    assert response.status_code == 201, response.text
    created = response.json()
    task_id = created["taskId"]

    # Poll until completed
    for _ in range(50):
        status_resp = client.get(f"/api/v1/generative/tasks/{task_id}")
        assert status_resp.status_code == 200
        task_data = status_resp.json()
        if task_data["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)

    assert task_data["status"] == "succeeded", task_data
    assert len(task_data["results"]) == 1
    result = task_data["results"][0]
    assert result["status"] == "candidate"
    assert result["width"] == 100
    assert result["height"] == 100
    assert "protected_region_restored" in result["warnings"]

    # Check result image is retrievable
    result_id = result["resultId"]
    img_resp = client.get(f"/api/v1/generative/results/{result_id}/image")
    assert img_resp.status_code == 200
    assert img_resp.headers["content-type"] == "image/png"

    # Accept the candidate result
    accept_resp = client.post(f"/api/v1/generative/results/{result_id}/accept")
    assert accept_resp.status_code == 200
    updated_session = accept_resp.json()

    # Verify new revision was created and pointers advanced
    rev = updated_session["revision"]
    assert rev["source"] == "ai"
    assert rev["generativeTaskId"] == task_id
    assert rev["baseGeneratedAssetId"] is not None


def test_removal_task_lifecycle_reject(client: TestClient):
    session = _new_session(client)
    session_id = str(session["sessionId"])
    mask_view = _create_rect_mask(client, session_id)
    mask_id = mask_view["maskId"]

    # Submit task
    response = client.post(
        "/api/v1/generative/tasks",
        json={
            "sessionId": session_id,
            "taskType": "remove",
            "instruction": "erase glare",
            "maskId": mask_id,
        },
    )
    assert response.status_code == 201
    task_id = response.json()["taskId"]

    # Poll until succeeded
    for _ in range(50):
        status_resp = client.get(f"/api/v1/generative/tasks/{task_id}")
        task_data = status_resp.json()
        if task_data["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)

    assert task_data["status"] == "succeeded"
    result_id = task_data["results"][0]["resultId"]

    # Reject result
    reject_resp = client.post(f"/api/v1/generative/results/{result_id}/reject")
    assert reject_resp.status_code == 200
    assert reject_resp.json()["status"] == "rejected"
