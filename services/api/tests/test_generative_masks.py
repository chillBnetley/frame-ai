from __future__ import annotations

from io import BytesIO
from uuid import UUID

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.imaging.generative_masks import (
    decode_mask,
    encode_mask,
    mask_quality,
    mask_sha256,
    rasterize_mask,
    read_mask,
)
from app.models.generative import (
    GenerativeMaskDefinition,
    GenerativeMaskKind,
    GenerativeMaskPoint,
    GenerativeMaskRegion,
    GenerativeMaskStroke,
)
from app.services.generated_asset_store import GeneratedAssetStore
from tests.conftest import make_image, upload


def _brush_stroke(
    x: float = 0.5,
    y: float = 0.5,
    radius: float = 0.15,
    hardness: float = 100,
) -> GenerativeMaskStroke:
    return GenerativeMaskStroke(
        points=[
            GenerativeMaskPoint(x=x - radius / 2, y=y),
            GenerativeMaskPoint(x=x + radius / 2, y=y),
        ],
        radius=radius,
        hardness=hardness,
        mode="add",
    )


def _erase_stroke(
    x: float = 0.5,
    y: float = 0.5,
    radius: float = 0.05,
) -> GenerativeMaskStroke:
    return GenerativeMaskStroke(
        points=[
            GenerativeMaskPoint(x=x, y=y),
            GenerativeMaskPoint(x=x, y=y),
        ],
        radius=radius,
        hardness=100,
        mode="erase",
    )


# ---------------------------------------------------------------------------
# rasterize_mask unit tests


def test_brush_mask_rasterizes_strokes_within_radius() -> None:
    definition = GenerativeMaskDefinition(
        strokes=[_brush_stroke(x=0.5, y=0.5, radius=0.1, hardness=100)],
    )
    mask = rasterize_mask(
        definition,
        GenerativeMaskKind.BRUSH,
        width=100,
        height=100,
        feather=0,
        inverted=False,
    )
    assert mask.shape == (100, 100)
    assert mask.dtype == np.uint8
    center = mask[50, 50]
    assert center == 255
    corner = mask[0, 0]
    assert corner == 0


def test_rect_mask_fills_region() -> None:
    definition = GenerativeMaskDefinition(
        region=GenerativeMaskRegion(x=0.2, y=0.3, width=0.4, height=0.2),
    )
    mask = rasterize_mask(
        definition,
        GenerativeMaskKind.RECT,
        width=100,
        height=100,
        feather=0,
        inverted=False,
    )
    assert mask[40, 40] == 255
    assert mask[10, 10] == 0


def test_ellipse_mask_fills_oval() -> None:
    definition = GenerativeMaskDefinition(
        region=GenerativeMaskRegion(x=0.1, y=0.1, width=0.8, height=0.8),
    )
    mask = rasterize_mask(
        definition,
        GenerativeMaskKind.ELLIPSE,
        width=100,
        height=100,
        feather=0,
        inverted=False,
    )
    assert mask[50, 50] == 255
    assert mask[5, 5] == 0


def test_inverted_mask_flips_pixels() -> None:
    definition = GenerativeMaskDefinition(
        strokes=[_brush_stroke(x=0.5, y=0.5, radius=0.1, hardness=100)],
    )
    mask = rasterize_mask(
        definition,
        GenerativeMaskKind.BRUSH,
        width=100,
        height=100,
        feather=0,
        inverted=True,
    )
    assert mask[50, 50] == 0
    assert mask[0, 0] == 255


def test_feather_blurs_mask_edges() -> None:
    definition = GenerativeMaskDefinition(
        strokes=[_brush_stroke(x=0.5, y=0.5, radius=0.15, hardness=100)],
    )
    sharp = rasterize_mask(
        definition,
        GenerativeMaskKind.BRUSH,
        width=100,
        height=100,
        feather=0,
        inverted=False,
    )
    feathered = rasterize_mask(
        definition,
        GenerativeMaskKind.BRUSH,
        width=100,
        height=100,
        feather=8,
        inverted=False,
    )
    sharp_nonzero = np.count_nonzero(sharp)
    feathered_nonzero = np.count_nonzero(feathered)
    assert feathered_nonzero > sharp_nonzero


def test_expand_dilates_mask_region() -> None:
    definition = GenerativeMaskDefinition(
        strokes=[_brush_stroke(x=0.5, y=0.5, radius=0.05, hardness=100)],
        expand=5,
    )
    mask = rasterize_mask(
        definition,
        GenerativeMaskKind.BRUSH,
        width=100,
        height=100,
        feather=0,
        inverted=False,
    )
    assert mask[50, 60] == 255


def test_erase_stroke_removes_pixels() -> None:
    add = _brush_stroke(x=0.5, y=0.5, radius=0.15, hardness=100)
    erase = _erase_stroke(x=0.5, y=0.5, radius=0.05)
    definition = GenerativeMaskDefinition(strokes=[add, erase])
    mask = rasterize_mask(
        definition,
        GenerativeMaskKind.BRUSH,
        width=100,
        height=100,
        feather=0,
        inverted=False,
    )
    assert mask[50, 50] == 0
    assert mask[50, 30] == 255


def test_semantic_mask_uses_provided_matte() -> None:
    semantic = np.zeros((100, 100), dtype=np.uint8)
    semantic[:, :50] = 255
    definition = GenerativeMaskDefinition(strokes=[])
    mask = rasterize_mask(
        definition,
        GenerativeMaskKind.SEMANTIC,
        width=200,
        height=200,
        feather=0,
        inverted=False,
        semantic=semantic,
    )
    assert mask.shape == (200, 200)
    assert mask[50, 50] == 255
    assert mask[50, 150] == 0


def test_rasterize_rejects_brush_without_strokes() -> None:
    definition = GenerativeMaskDefinition(strokes=[])
    with pytest.raises(ValueError, match="brush mask"):
        rasterize_mask(
            definition,
            GenerativeMaskKind.BRUSH,
            width=100,
            height=100,
            feather=0,
            inverted=False,
        )


def test_rasterize_rejects_geometric_without_region() -> None:
    definition = GenerativeMaskDefinition(strokes=[])
    with pytest.raises(ValueError, match="region"):
        rasterize_mask(
            definition,
            GenerativeMaskKind.RECT,
            width=100,
            height=100,
            feather=0,
            inverted=False,
        )


def test_rasterize_rejects_semantic_without_matte() -> None:
    definition = GenerativeMaskDefinition(
        semantic_class="person",
        strokes=[],
    )
    with pytest.raises(ValueError, match="matte"):
        rasterize_mask(
            definition,
            GenerativeMaskKind.SEMANTIC,
            width=100,
            height=100,
            feather=0,
            inverted=False,
        )


# ---------------------------------------------------------------------------
# mask_quality


def test_mask_quality_measures_coverage() -> None:
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[:10, :10] = 255
    quality = mask_quality(mask)
    assert quality.coverage == pytest.approx(0.01, abs=0.001)
    assert quality.component_count == 1
    assert quality.touches_border is True


def test_mask_quality_detects_disconnected_components() -> None:
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[10:20, 10:20] = 255
    mask[80:90, 80:90] = 255
    quality = mask_quality(mask)
    assert quality.component_count == 2
    assert quality.touches_border is False


# ---------------------------------------------------------------------------
# encode / decode / read


def test_encode_decode_round_trip() -> None:
    mask = np.zeros((50, 80), dtype=np.uint8)
    mask[10:30, 20:60] = 255
    sha = mask_sha256(mask)
    data = encode_mask(mask)
    decoded = decode_mask(data, width=80, height=50, expected_sha256=sha)
    np.testing.assert_array_equal(decoded, mask)


def test_decode_rejects_wrong_dimensions() -> None:
    mask = np.zeros((50, 80), dtype=np.uint8)
    sha = mask_sha256(mask)
    data = encode_mask(mask)
    with pytest.raises(ValueError, match="could not be decoded"):
        decode_mask(data, width=100, height=50, expected_sha256=sha)


def test_decode_rejects_wrong_sha() -> None:
    mask = np.zeros((50, 80), dtype=np.uint8)
    data = encode_mask(mask)
    with pytest.raises(ValueError, match="hash"):
        decode_mask(data, width=80, height=50, expected_sha256="a" * 64)


def test_read_mask_from_disk(tmp_path) -> None:
    mask = np.zeros((40, 60), dtype=np.uint8)
    mask[5:35, 10:50] = 255
    sha = mask_sha256(mask)
    data = encode_mask(mask)
    path = tmp_path / "mask.png"
    path.write_bytes(data)
    loaded = read_mask(path, width=60, height=40, expected_sha256=sha, max_bytes=10_000_000)
    np.testing.assert_array_equal(loaded, mask)


# ---------------------------------------------------------------------------
# API integration tests


def _create_mask(
    client: TestClient,
    session_id: str,
    *,
    kind: str = "brush",
    strokes: list[dict] | None = None,
    region: dict | None = None,
    semantic_class: str | None = None,
    feather: float = 0,
    inverted: bool = False,
    expand: float = 0,
):
    definition: dict = {}
    if strokes is not None:
        definition["strokes"] = strokes
    if region is not None:
        definition["region"] = region
    if semantic_class is not None:
        definition["semanticClass"] = semantic_class
    if expand != 0:
        definition["expand"] = expand
    payload = {
        "sessionId": session_id,
        "kind": kind,
        "definition": definition,
        "feather": feather,
        "inverted": inverted,
    }
    return client.post("/api/v1/generative/masks", json=payload)


def _new_session(client: TestClient) -> dict:
    image = make_image(size=(120, 80), color=(100, 120, 80))
    response = upload(client, image)
    assert response.status_code == 201, response.text
    image_id = str(response.json()["imageId"])
    created = client.post("/api/v1/sessions", json={"imageId": image_id})
    assert created.status_code == 201, created.text
    return created.json()


def test_create_brush_mask_via_api(client: TestClient):
    session = _new_session(client)
    strokes = [
        {
            "points": [
                {"x": 0.3, "y": 0.4},
                {"x": 0.7, "y": 0.4},
            ],
            "radius": 0.1,
            "hardness": 100,
            "mode": "add",
        }
    ]
    response = _create_mask(client, session["sessionId"], strokes=strokes)
    assert response.status_code == 201, response.text
    view = response.json()
    assert view["kind"] == "brush"
    assert view["source"] == "user"
    assert view["width"] == 120
    assert view["height"] == 80
    assert view["imageUrl"].startswith("/api/v1/generative/masks/")
    assert len(view["sha256"]) == 64
    assert view["quality"]["coverage"] > 0
    assert "strokes" in view["definition"]


def test_create_rect_mask_via_api(client: TestClient):
    session = _new_session(client)
    region = {"x": 0.2, "y": 0.3, "width": 0.4, "height": 0.2}
    response = _create_mask(client, session["sessionId"], kind="rect", region=region)
    assert response.status_code == 201, response.text
    view = response.json()
    assert view["kind"] == "rect"


def test_create_ellipse_mask_via_api(client: TestClient):
    session = _new_session(client)
    region = {"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8}
    response = _create_mask(client, session["sessionId"], kind="ellipse", region=region)
    assert response.status_code == 201, response.text
    view = response.json()
    assert view["kind"] == "ellipse"


def test_create_mask_with_feather_via_api(client: TestClient):
    session = _new_session(client)
    strokes = [
        {
            "points": [{"x": 0.5, "y": 0.5}],
            "radius": 0.2,
            "hardness": 100,
            "mode": "add",
        }
    ]
    response = _create_mask(
        client,
        session["sessionId"],
        strokes=strokes,
        feather=8,
    )
    assert response.status_code == 201, response.text
    view = response.json()
    assert view["feather"] == 8


def test_create_inverted_mask_via_api(client: TestClient):
    session = _new_session(client)
    strokes = [
        {
            "points": [{"x": 0.5, "y": 0.5}],
            "radius": 0.2,
            "hardness": 100,
            "mode": "add",
        }
    ]
    response = _create_mask(
        client,
        session["sessionId"],
        strokes=strokes,
        inverted=True,
    )
    assert response.status_code == 201, response.text
    view = response.json()
    assert view["inverted"] is True


def test_create_mask_rejects_brush_without_strokes(client: TestClient):
    session = _new_session(client)
    response = _create_mask(client, session["sessionId"], kind="brush", strokes=[])
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "generative_mask_definition_invalid"


def test_create_mask_rejects_rect_without_region(client: TestClient):
    session = _new_session(client)
    response = _create_mask(client, session["sessionId"], kind="rect")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "generative_mask_definition_invalid"


def test_create_mask_rejects_semantic_without_class(client: TestClient):
    session = _new_session(client)
    response = _create_mask(client, session["sessionId"], kind="semantic", strokes=[])
    assert response.status_code == 422


def test_create_mask_rejects_too_small_coverage(client: TestClient):
    session = _new_session(client)
    strokes = [
        {
            "points": [{"x": 0.5, "y": 0.5}],
            "radius": 0.01,
            "hardness": 100,
            "mode": "add",
        }
    ]
    response = _create_mask(client, session["sessionId"], strokes=strokes)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "generative_mask_coverage"


def test_create_mask_rejects_too_large_coverage(client: TestClient):
    session = _new_session(client)
    region = {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}
    response = _create_mask(client, session["sessionId"], kind="rect", region=region)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "generative_mask_coverage"


def test_create_semantic_person_mask_via_api(client: TestClient):
    session = _new_session(client)
    response = _create_mask(
        client,
        session["sessionId"],
        kind="semantic",
        semantic_class="person",
    )
    if response.status_code == 503:
        pytest.skip("semantic models not available in test environment")
    assert response.status_code == 201, response.text
    view = response.json()
    assert view["kind"] == "semantic"
    assert view["source"] == "semantic"
    assert view["definition"]["semanticClass"] == "person"


def test_list_masks_for_session(client: TestClient):
    session = _new_session(client)
    strokes = [
        {
            "points": [{"x": 0.3, "y": 0.4}, {"x": 0.7, "y": 0.4}],
            "radius": 0.1,
            "hardness": 100,
            "mode": "add",
        }
    ]
    _create_mask(client, session["sessionId"], strokes=strokes)
    _create_mask(client, session["sessionId"], strokes=strokes)
    response = client.get(f"/api/v1/generative/masks?sessionId={session['sessionId']}")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 2


def test_get_mask_metadata(client: TestClient):
    session = _new_session(client)
    strokes = [
        {
            "points": [{"x": 0.5, "y": 0.5}],
            "radius": 0.1,
            "hardness": 100,
            "mode": "add",
        }
    ]
    created = _create_mask(client, session["sessionId"], strokes=strokes)
    mask_id = created.json()["maskId"]
    response = client.get(f"/api/v1/generative/masks/{mask_id}")
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["maskId"] == mask_id


def test_get_mask_image_returns_png(client: TestClient):
    session = _new_session(client)
    strokes = [
        {
            "points": [{"x": 0.5, "y": 0.5}],
            "radius": 0.1,
            "hardness": 100,
            "mode": "add",
        }
    ]
    created = _create_mask(client, session["sessionId"], strokes=strokes)
    mask_id = created.json()["maskId"]
    response = client.get(f"/api/v1/generative/masks/{mask_id}/image")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, no-store"
    img = Image.open(BytesIO(response.content))
    assert img.mode == "L"
    assert img.size == (120, 80)


def test_delete_mask_soft_deletes_record(client: TestClient):
    session = _new_session(client)
    strokes = [
        {
            "points": [{"x": 0.5, "y": 0.5}],
            "radius": 0.1,
            "hardness": 100,
            "mode": "add",
        }
    ]
    created = _create_mask(client, session["sessionId"], strokes=strokes)
    mask_id = created.json()["maskId"]
    response = client.delete(f"/api/v1/generative/masks/{mask_id}")
    assert response.status_code == 204
    get_response = client.get(f"/api/v1/generative/masks/{mask_id}")
    assert get_response.status_code == 404


def test_delete_mask_removes_files_when_unreferenced(client: TestClient, settings):
    session = _new_session(client)
    strokes = [
        {
            "points": [{"x": 0.5, "y": 0.5}],
            "radius": 0.1,
            "hardness": 100,
            "mode": "add",
        }
    ]
    created = _create_mask(client, session["sessionId"], strokes=strokes)
    mask_id = created.json()["maskId"]
    store = GeneratedAssetStore(settings)
    png_key = store.slug_for_mask(mask_id)
    json_key = store.mask_sidecar_key(png_key)
    png_path = store._resolve_key(png_key)
    json_path = store._resolve_key(json_key)
    assert png_path.is_file()
    assert json_path.is_file()
    client.delete(f"/api/v1/generative/masks/{mask_id}")
    assert not png_path.is_file()
    assert not json_path.is_file()


def test_delete_mask_returns_409_when_active_task_references_it(client: TestClient):
    session = _new_session(client)
    strokes = [
        {
            "points": [{"x": 0.5, "y": 0.5}],
            "radius": 0.1,
            "hardness": 100,
            "mode": "add",
        }
    ]
    mask_response = _create_mask(client, session["sessionId"], strokes=strokes)
    mask_id = mask_response.json()["maskId"]
    task_response = client.post(
        "/api/v1/generative/tasks",
        json={
            "sessionId": session["sessionId"],
            "taskType": "local_edit",
            "instruction": "warm the marked region",
            "maskId": mask_id,
        },
    )
    assert task_response.status_code == 201, task_response.text
    delete_response = client.delete(f"/api/v1/generative/masks/{mask_id}")
    assert delete_response.status_code == 409
    assert delete_response.json()["error"]["code"] == "resource_busy"


def test_get_mask_returns_404_for_nonexistent_id(client: TestClient):
    response = client.get(f"/api/v1/generative/masks/{UUID(int=0)}")
    assert response.status_code == 404


def test_delete_mask_returns_404_for_nonexistent_id(client: TestClient):
    response = client.delete(f"/api/v1/generative/masks/{UUID(int=0)}")
    assert response.status_code == 404


def test_mask_image_returns_404_for_nonexistent_id(client: TestClient):
    response = client.get(f"/api/v1/generative/masks/{UUID(int=0)}/image")
    assert response.status_code == 404


def test_create_mask_rejects_invalid_session(client: TestClient):
    strokes = [
        {
            "points": [{"x": 0.5, "y": 0.5}],
            "radius": 0.1,
            "hardness": 100,
            "mode": "add",
        }
    ]
    response = _create_mask(client, str(UUID(int=1)), strokes=strokes)
    assert response.status_code == 404


def test_create_mask_rejects_invalid_stroke_radius(client: TestClient):
    session = _new_session(client)
    strokes = [
        {
            "points": [{"x": 0.5, "y": 0.5}],
            "radius": 0.0,
            "hardness": 100,
            "mode": "add",
        }
    ]
    response = _create_mask(client, session["sessionId"], strokes=strokes)
    assert response.status_code == 422


def test_create_mask_rejects_out_of_bounds_point(client: TestClient):
    session = _new_session(client)
    strokes = [
        {
            "points": [{"x": 1.5, "y": 0.5}],
            "radius": 0.1,
            "hardness": 100,
            "mode": "add",
        }
    ]
    response = _create_mask(client, session["sessionId"], strokes=strokes)
    assert response.status_code == 422


def test_create_mask_rejects_region_outside_image(client: TestClient):
    session = _new_session(client)
    region = {"x": 0.8, "y": 0.8, "width": 0.5, "height": 0.5}
    response = _create_mask(client, session["sessionId"], kind="rect", region=region)
    assert response.status_code == 422


def test_list_masks_isolates_by_session(client: TestClient):
    session1 = _new_session(client)
    session2 = _new_session(client)
    strokes = [
        {
            "points": [{"x": 0.5, "y": 0.5}],
            "radius": 0.1,
            "hardness": 100,
            "mode": "add",
        }
    ]
    _create_mask(client, session1["sessionId"], strokes=strokes)
    _create_mask(client, session2["sessionId"], strokes=strokes)
    response1 = client.get(f"/api/v1/generative/masks?sessionId={session1['sessionId']}")
    response2 = client.get(f"/api/v1/generative/masks?sessionId={session2['sessionId']}")
    assert len(response1.json()["items"]) == 1
    assert len(response2.json()["items"]) == 1


def test_task_uses_sha_verified_mask(client: TestClient):
    session = _new_session(client)
    strokes = [
        {
            "points": [
                {"x": 0.3, "y": 0.3},
                {"x": 0.7, "y": 0.7},
            ],
            "radius": 0.15,
            "hardness": 100,
            "mode": "add",
        }
    ]
    mask_response = _create_mask(client, session["sessionId"], strokes=strokes)
    mask_id = mask_response.json()["maskId"]
    task_response = client.post(
        "/api/v1/generative/tasks",
        json={
            "sessionId": session["sessionId"],
            "taskType": "local_edit",
            "instruction": "warm the marked region",
            "maskId": mask_id,
        },
    )
    assert task_response.status_code == 201, task_response.text
    task = task_response.json()
    assert task["status"] in ("queued", "processing", "succeeded")
