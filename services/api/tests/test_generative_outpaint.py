from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.ai.providers.generative_mock import MockGenerativeProvider
from app.core.config import Settings
from app.core.errors import AppError
from app.core.identity import OwnerScope
from app.imaging.generative_outpaint import (
    OutpaintGeometry,
    build_outpaint_canvas,
    compute_outpaint_geometry,
    parse_aspect_ratio,
    restore_outpaint_protected_region,
)
from app.models.generative import (
    GenerativeOutpaintAlignment,
    GenerativeOutpaintParams,
    GenerativeParams,
    GenerativeTaskRequest,
    GenerativeTaskStatus,
    GenerativeTaskType,
)
from app.services.generative_service import GenerativeTaskService
from tests.conftest import make_image, upload

OWNER = OwnerScope("local")


def _new_session(client: TestClient) -> dict[str, object]:
    response = upload(client, make_image(size=(64, 48)))
    assert response.status_code == 201, response.text
    image_id = str(response.json()["imageId"])
    created = client.post("/api/v1/sessions", json={"imageId": image_id})
    assert created.status_code == 201, created.text
    session = created.json()
    session["imageId"] = image_id
    return session


def _make_service(client: TestClient, settings: Settings) -> GenerativeTaskService:
    base = client.app.state.generative_service
    return GenerativeTaskService(
        settings,
        base.sessions,
        MockGenerativeProvider(),
        base.repository,
        base.store,
        base.assets,
        executor=ThreadPoolExecutor(max_workers=1),
    )


def test_parse_aspect_ratio_valid_formats():
    assert parse_aspect_ratio("16:9") == (16, 9)
    assert parse_aspect_ratio("9:16") == (9, 16)
    assert parse_aspect_ratio("1:1") == (1, 1)
    assert parse_aspect_ratio("4/3") == (4, 3)
    assert parse_aspect_ratio("21:9") == (21, 9)
    assert parse_aspect_ratio("1.5") == (1500, 1000)
    assert parse_aspect_ratio(" 16 : 9 ") == (16, 9)


def test_parse_aspect_ratio_invalid_formats():
    with pytest.raises(ValueError, match="empty"):
        parse_aspect_ratio("")
    with pytest.raises(ValueError, match="Invalid"):
        parse_aspect_ratio("0:0")
    with pytest.raises(ValueError, match="Invalid"):
        parse_aspect_ratio("abc:def")
    with pytest.raises(ValueError, match="Invalid"):
        parse_aspect_ratio("-1:1")


def test_compute_outpaint_geometry_margins_only():
    params = GenerativeOutpaintParams(top=10, bottom=20, left=5, right=15)
    geo = compute_outpaint_geometry(100, 80, params)
    assert geo.base_width == 100
    assert geo.base_height == 80
    assert geo.target_width == 120
    assert geo.target_height == 110
    assert geo.offset_x == 5
    assert geo.offset_y == 10
    assert geo.left == 5
    assert geo.right == 15
    assert geo.top == 10
    assert geo.bottom == 20
    assert geo.total_expanded_pixels == (120 * 110) - (100 * 80)


def test_compute_outpaint_geometry_aspect_ratio_wider():
    # 100x100 -> target 16:9 -> target width = ceil(100 * 16 / 9) = 178
    params = GenerativeOutpaintParams(
        aspect_ratio="16:9",
        alignment=GenerativeOutpaintAlignment.CENTER,
    )
    geo = compute_outpaint_geometry(100, 100, params)
    assert geo.target_height == 100
    assert geo.target_width == 178
    assert geo.left == 39
    assert geo.right == 39
    assert geo.top == 0
    assert geo.bottom == 0

    # Test left alignment (anchored left -> expands right)
    params_left = GenerativeOutpaintParams(
        aspect_ratio="16:9",
        alignment=GenerativeOutpaintAlignment.LEFT,
    )
    geo_left = compute_outpaint_geometry(100, 100, params_left)
    assert geo_left.left == 0
    assert geo_left.right == 78


def test_compute_outpaint_geometry_aspect_ratio_taller():
    # 100x100 -> target 9:16 -> target height = ceil(100 * 16 / 9) = 178
    params = GenerativeOutpaintParams(
        aspect_ratio="9:16",
        alignment=GenerativeOutpaintAlignment.CENTER,
    )
    geo = compute_outpaint_geometry(100, 100, params)
    assert geo.target_width == 100
    assert geo.target_height == 178
    assert geo.top == 39
    assert geo.bottom == 39
    assert geo.left == 0
    assert geo.right == 0

    # Test top alignment (anchored top -> expands bottom)
    params_top = GenerativeOutpaintParams(
        aspect_ratio="9:16",
        alignment=GenerativeOutpaintAlignment.TOP,
    )
    geo_top = compute_outpaint_geometry(100, 100, params_top)
    assert geo_top.top == 0
    assert geo_top.bottom == 78


def test_compute_outpaint_geometry_rejects_zero_expansion():
    params = GenerativeOutpaintParams()
    with pytest.raises(ValueError, match="expanding at least one edge"):
        compute_outpaint_geometry(100, 100, params)


def test_compute_outpaint_geometry_rejects_excessive_expansion():
    params = GenerativeOutpaintParams(top=500, bottom=500, left=500, right=500)
    with pytest.raises(ValueError, match="exceeds maximum allowed"):
        compute_outpaint_geometry(50, 50, params, max_scale=4.0)


def test_build_outpaint_canvas_places_base_image_accurately():
    base = np.full((40, 60, 3), 120, dtype=np.uint8)
    base[10:20, 10:20] = [200, 50, 50]  # distinct spot
    geo = OutpaintGeometry(
        base_width=60,
        base_height=40,
        target_width=100,
        target_height=80,
        offset_x=20,
        offset_y=20,
    )
    canvas, mask = build_outpaint_canvas(base, geo)
    assert canvas.shape == (80, 100, 3)
    assert mask.shape == (80, 100)

    # Base rectangle in canvas is exact
    placed_base = canvas[20:60, 20:80]
    assert np.array_equal(placed_base, base)

    # Mask is 0 inside base rectangle and 255 outside
    assert np.all(mask[20:60, 20:80] == 0)
    assert np.all(mask[:20, :] == 255)
    assert np.all(mask[60:, :] == 255)
    assert np.all(mask[:, :20] == 255)
    assert np.all(mask[:, 80:] == 255)


def test_build_outpaint_canvas_embeds_inner_mask():
    base = np.zeros((40, 60, 3), dtype=np.uint8)
    inner = np.zeros((40, 60), dtype=np.uint8)
    inner[5:15, 5:15] = 255  # marked inner editable region
    geo = OutpaintGeometry(
        base_width=60,
        base_height=40,
        target_width=80,
        target_height=60,
        offset_x=10,
        offset_y=10,
    )
    _, mask = build_outpaint_canvas(base, geo, inner_mask=inner)
    assert mask[10 + 5, 10 + 5] == 255
    assert mask[10 + 20, 10 + 20] == 0
    assert mask[2, 2] == 255


def test_restore_outpaint_protected_region_restores_byte_identity():
    base = np.full((40, 60, 3), 99, dtype=np.uint8)
    geo = OutpaintGeometry(
        base_width=60,
        base_height=40,
        target_width=100,
        target_height=80,
        offset_x=20,
        offset_y=20,
    )
    # Simulated provider output with alterations in both base and outer areas
    generated = np.random.randint(0, 255, size=(80, 100, 3), dtype=np.uint8)
    restored, warnings = restore_outpaint_protected_region(base, generated, geo)

    assert "protected_region_restored" in warnings
    assert "outpaint_region_extended" in warnings
    # Base region must be strictly restored
    assert np.array_equal(restored[20:60, 20:80], base)
    # Outer region remains what was generated
    assert np.array_equal(restored[:20, :], generated[:20, :])


def test_restore_outpaint_protected_region_with_inner_mask():
    base = np.full((40, 60, 3), 50, dtype=np.uint8)
    inner = np.zeros((40, 60), dtype=np.uint8)
    inner[10:20, 10:20] = 255  # editable subregion
    geo = OutpaintGeometry(
        base_width=60,
        base_height=40,
        target_width=80,
        target_height=60,
        offset_x=10,
        offset_y=10,
    )
    # Generated image has variation in the outer area
    generated = np.random.randint(50, 200, size=(60, 80, 3), dtype=np.uint8)
    generated[10:50, 10:70] = 180
    restored, _ = restore_outpaint_protected_region(base, generated, geo, inner_mask=inner)

    # Protected portion inside base region is byte-identical
    base_rect = restored[10:50, 10:70]
    assert np.all(base_rect[0:10, 0:10] == 50)
    # Editable inner portion accepts generated changes
    assert np.all(base_rect[10:20, 10:20] == 180)


def test_restore_outpaint_protected_region_rejects_wrong_dimensions():
    base = np.zeros((40, 60, 3), dtype=np.uint8)
    geo = OutpaintGeometry(
        base_width=60,
        base_height=40,
        target_width=100,
        target_height=80,
        offset_x=20,
        offset_y=20,
    )
    bad_generated = np.zeros((70, 90, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="do not match target canvas"):
        restore_outpaint_protected_region(base, bad_generated, geo)


def test_restore_outpaint_protected_region_rejects_blank_output():
    base = np.full((40, 60, 3), 100, dtype=np.uint8)
    geo = OutpaintGeometry(
        base_width=60,
        base_height=40,
        target_width=100,
        target_height=80,
        offset_x=20,
        offset_y=20,
    )
    blank_generated = np.zeros((80, 100, 3), dtype=np.uint8)  # pure black -> std=0
    with pytest.raises(ValueError, match="lacks visible variation"):
        restore_outpaint_protected_region(base, blank_generated, geo)


def test_outpaint_task_lifecycle_end_to_end(client: TestClient, settings: Settings):
    session = _new_session(client)
    service = _make_service(client, settings)
    try:
        created, deduplicated = service.create(
            GenerativeTaskRequest(
                session_id=UUID(str(session["sessionId"])),
                task_type=GenerativeTaskType.OUTPAINT,
                instruction="expand horizons",
                params=GenerativeParams(
                    outpaint=GenerativeOutpaintParams(
                        top=10,
                        bottom=10,
                        left=16,
                        right=16,
                    )
                ),
            ),
            owner=OWNER,
            idempotency_key=None,
        )
        assert deduplicated is False
        task_id = str(created.task_id)

        # Wait for task execution
        deadline = time.monotonic() + 10.0
        status = None
        while time.monotonic() < deadline:
            st = service.status(task_id, owner=OWNER)
            if st.status is GenerativeTaskStatus.SUCCEEDED:
                status = st
                break
            time.sleep(0.05)
        assert status is not None
        assert status.status is GenerativeTaskStatus.SUCCEEDED
        assert len(status.results) == 1
        result = status.results[0]
        # Original size: 64x48. Expanded: (64+32) x (48+20) = 96 x 68
        assert result.width == 96
        assert result.height == 68
        assert "outpaint_region_extended" in result.warnings
        assert "protected_region_restored" in result.warnings

        # Candidate image downloadable and dimensions match
        path, mime = service.result_image(str(result.result_id), owner=OWNER)
        assert mime == "image/png"
        with Image.open(path) as img:
            assert img.size == (96, 68)
            result_arr = np.asarray(img.convert("RGB"))

        # Verify byte identity for the original 64x48 photo inside [top:top+48, left:left+64]
        original = service.assets.resolve(str(session["imageId"]))
        with Image.open(original.path) as orig_img:
            orig_arr = np.asarray(orig_img.convert("RGB"))
        assert np.array_equal(result_arr[10 : 10 + 48, 16 : 16 + 64], orig_arr)

        # Accept candidate result
        session_state = service.accept_result(str(result.result_id), owner=OWNER)
        assert session_state.active_revision_id != session["activeRevisionId"]
        assert session_state.revision.base_generated_asset_id is not None

        # Verify asset resolver resolves new dimensions
        resolved = service.assets.resolve(
            str(session["imageId"]),
            str(session_state.revision.base_generated_asset_id),
        )
        assert resolved.width == 96
        assert resolved.height == 68
    finally:
        service.shutdown()


def test_outpaint_task_rejects_missing_outpaint_params(client: TestClient, settings: Settings):
    session = _new_session(client)
    service = _make_service(client, settings)
    try:
        with pytest.raises(AppError) as excinfo:
            service.create(
                GenerativeTaskRequest(
                    session_id=UUID(str(session["sessionId"])),
                    task_type=GenerativeTaskType.OUTPAINT,
                    instruction="expand without params",
                    params=GenerativeParams(outpaint=None),
                ),
                owner=OWNER,
                idempotency_key=None,
            )
        assert excinfo.value.code == "generative_outpaint_params_required"
    finally:
        service.shutdown()


def test_outpaint_task_rejects_oversized_target_canvas(client: TestClient, settings: Settings):
    session = _new_session(client)
    service = _make_service(client, settings)
    try:
        with pytest.raises(AppError) as excinfo:
            service.create(
                GenerativeTaskRequest(
                    session_id=UUID(str(session["sessionId"])),
                    task_type=GenerativeTaskType.OUTPAINT,
                    instruction="expand to galaxy",
                    params=GenerativeParams(
                        outpaint=GenerativeOutpaintParams(
                            top=4000,
                            bottom=4000,
                            left=4000,
                            right=4000,
                        )
                    ),
                ),
                owner=OWNER,
                idempotency_key=None,
            )
        assert excinfo.value.code in ("generative_outpaint_invalid", "generative_input_too_large")
    finally:
        service.shutdown()
