from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageStat

from app.core.config import Settings
from app.imaging.loader import load_proxy
from app.imaging.local_masks import MaskCacheStats, mask_cache_stats
from app.imaging.output import srgb_icc_profile
from app.main import create_app
from app.repositories.db import connect
from app.services.render_service import RenderService
from tests.conftest import make_image, upload

PREVIEW_PATH = re.compile(r"^/api/v1/previews/([0-9a-f]{64})$")


def _session(client: TestClient, size: tuple[int, int] = (1600, 600)) -> dict[str, object]:
    image = upload(client, make_image(size=size))
    assert image.status_code == 201
    response = client.post(
        "/api/v1/sessions",
        json={"imageId": image.json()["imageId"]},
    )
    assert response.status_code == 201
    return response.json()


def _render(
    client: TestClient,
    session: dict[str, object],
    *,
    exposure: float = 0.3,
    quality: str = "final",
    max_edge: int | None = None,
    crop: dict[str, float] | None = None,
    extra_recipe: dict[str, object] | None = None,
) -> dict[str, object]:
    adjustments: dict[str, object] = {"exposureEv": exposure}
    if crop is not None:
        adjustments["crop"] = crop
    recipe: dict[str, object] = {"adjustments": adjustments}
    if extra_recipe is not None:
        recipe.update(extra_recipe)
    body: dict[str, object] = {
        "recipe": recipe,
        "quality": quality,
    }
    if max_edge is not None:
        body["maxEdge"] = max_edge
    response = client.post(f"/api/v1/sessions/{session['sessionId']}/render", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _wait_for_sequence(service: RenderService, session_id: str, seq: int) -> None:
    deadline = time.monotonic() + 10
    latest = service._latest_seq
    while latest.get(session_id, 0) < seq:
        if time.monotonic() > deadline:
            raise AssertionError(f"render sequence {seq} was not recorded")
        time.sleep(0.005)


def _row_counts(settings: Settings) -> tuple[int, int]:
    connection = connect(settings.database_path)
    try:
        sessions = connection.execute("SELECT COUNT(*) FROM edit_session").fetchone()[0]
        revisions = connection.execute("SELECT COUNT(*) FROM edit_revision").fetchone()[0]
    finally:
        connection.close()
    return int(sessions), int(revisions)


def test_render_is_cached_and_served_as_jpeg(
    client: TestClient,
    settings: Settings,
):
    session = _session(client)
    before = _row_counts(settings)

    first = _render(client, session)

    assert first["width"] == 1600
    assert first["height"] == 600
    assert first["quality"] == "final"
    assert first["cacheHit"] is False
    match = PREVIEW_PATH.fullmatch(str(first["previewUrl"]))
    assert match is not None
    preview_id = match.group(1)
    path = settings.preview_dir / f"{preview_id}.jpg"
    assert path.is_file()

    second = _render(client, session)
    assert second["previewUrl"] == first["previewUrl"]
    assert second["cacheHit"] is True
    assert second["width"] == 1600
    assert second["height"] == 600
    assert _row_counts(settings) == before

    response = client.get(str(first["previewUrl"]))
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == (f"private, max-age={settings.preview_ttl_seconds}")
    assert response.content.startswith(b"\xff\xd8")
    with Image.open(BytesIO(response.content)) as image:
        assert image.size == (1600, 600)
        assert image.info.get("exif") is None

    different = _render(client, session, exposure=-0.4)
    assert different["previewUrl"] != first["previewUrl"]
    assert different["cacheHit"] is False


def test_draft_and_explicit_edges_resize_the_preview(client: TestClient):
    session = _session(client)

    draft = _render(client, session, quality="draft")
    assert (draft["width"], draft["height"]) == (960, 360)
    assert draft["quality"] == "draft"

    explicit = _render(client, session, max_edge=800)
    assert (explicit["width"], explicit["height"]) == (800, 300)
    assert explicit["quality"] == "final"

    small_draft = _render(client, session, quality="draft", max_edge=700)
    assert (small_draft["width"], small_draft["height"]) == (700, 262)


def test_curves_change_the_preview_pixels_and_cache_key(client: TestClient):
    session = _session(client)
    url = f"/api/v1/sessions/{session['sessionId']}/render"
    curve = {
        "master": [
            {"x": 0.0, "y": 0.0},
            {"x": 0.5, "y": 0.75},
            {"x": 1.0, "y": 1.0},
        ],
        "blue": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.9}],
    }

    plain = client.post(url, json={"recipe": {}, "quality": "final"})
    assert plain.status_code == 200
    shaped = client.post(
        url,
        json={"recipe": {"curve": curve}, "quality": "final"},
    )
    assert shaped.status_code == 200, shaped.text
    assert shaped.json()["previewUrl"] != plain.json()["previewUrl"]
    assert shaped.json()["cacheHit"] is False

    plain_pixels = client.get(str(plain.json()["previewUrl"]))
    shaped_pixels = client.get(str(shaped.json()["previewUrl"]))
    assert plain_pixels.status_code == 200
    assert shaped_pixels.status_code == 200
    assert plain_pixels.content != shaped_pixels.content

    repeat = client.post(url, json={"recipe": {"curve": curve}, "quality": "final"})
    assert repeat.json()["cacheHit"] is True
    assert repeat.json()["previewUrl"] == shaped.json()["previewUrl"]


def test_hsl_changes_the_preview_pixels_and_cache_key(client: TestClient):
    session = _session(client)
    url = f"/api/v1/sessions/{session['sessionId']}/render"
    hsl = {
        "orange": {"hue": 20, "saturation": 25},
        "blue": {"hue": -15, "luminance": 10},
    }

    plain = client.post(url, json={"recipe": {}, "quality": "final"})
    assert plain.status_code == 200
    shifted = client.post(
        url,
        json={"recipe": {"hsl": hsl}, "quality": "final"},
    )
    assert shifted.status_code == 200, shifted.text
    assert shifted.json()["previewUrl"] != plain.json()["previewUrl"]
    assert shifted.json()["cacheHit"] is False

    plain_pixels = client.get(str(plain.json()["previewUrl"]))
    shifted_pixels = client.get(str(shifted.json()["previewUrl"]))
    assert plain_pixels.status_code == 200
    assert shifted_pixels.status_code == 200
    assert plain_pixels.content != shifted_pixels.content

    repeat = client.post(url, json={"recipe": {"hsl": hsl}, "quality": "final"})
    assert repeat.json()["cacheHit"] is True
    assert repeat.json()["previewUrl"] == shifted.json()["previewUrl"]


def test_grading_changes_the_preview_pixels_and_cache_key(client: TestClient):
    session = _session(client)
    url = f"/api/v1/sessions/{session['sessionId']}/render"
    grading = {
        "shadows": {"hue": 220, "saturation": 30},
        "highlights": {"hue": 45, "saturation": 25},
        "balance": 10,
        "blending": 60,
    }

    plain = client.post(url, json={"recipe": {}, "quality": "final"})
    assert plain.status_code == 200
    graded = client.post(
        url,
        json={"recipe": {"colorGrading": grading}, "quality": "final"},
    )
    assert graded.status_code == 200, graded.text
    assert graded.json()["previewUrl"] != plain.json()["previewUrl"]
    assert graded.json()["cacheHit"] is False

    plain_pixels = client.get(str(plain.json()["previewUrl"]))
    graded_pixels = client.get(str(graded.json()["previewUrl"]))
    assert plain_pixels.status_code == 200
    assert graded_pixels.status_code == 200
    assert plain_pixels.content != graded_pixels.content

    repeat = client.post(
        url,
        json={"recipe": {"colorGrading": grading}, "quality": "final"},
    )
    assert repeat.json()["cacheHit"] is True
    assert repeat.json()["previewUrl"] == graded.json()["previewUrl"]


def test_proxies_live_in_a_separate_cache_directory(
    client: TestClient,
    settings: Settings,
):
    session = _session(client)

    _render(client, session, quality="draft", exposure=0.1)

    proxy_files = list((settings.preview_dir / "proxies").glob("*.png"))
    assert len(proxy_files) == 1
    assert list(settings.preview_dir.glob("*.png")) == []


def test_crop_coordinates_apply_to_the_rendered_canvas(client: TestClient):
    session = _session(client)

    result = _render(
        client,
        session,
        max_edge=800,
        crop={"x": 0.25, "y": 0.25, "w": 0.5, "h": 0.5},
    )

    assert (result["width"], result["height"]) == (400, 150)
    preview = client.get(str(result["previewUrl"]))
    with Image.open(BytesIO(preview.content)) as image:
        assert image.size == (400, 150)


def test_render_rejects_invalid_requests_and_unknown_sessions(client: TestClient):
    session = _session(client)
    url = f"/api/v1/sessions/{session['sessionId']}/render"

    assert client.post(url, json={"recipe": {}, "quality": "export"}).status_code == 422
    assert client.post(url, json={"recipe": {}, "maxEdge": 0}).status_code == 422
    assert client.post(url, json={"recipe": {}, "maxEdge": 2561}).status_code == 422
    assert (
        client.post(
            url,
            json={"recipe": {"adjustments": {"exposureEv": 9}}},
        ).status_code
        == 422
    )
    assert (
        client.post(
            url,
            json={"recipe": {"adjustments": {"exposureEv": True}}},
        ).status_code
        == 422
    )

    invalid_recipes: list[dict[str, object]] = [
        {"curve": {"master": [{"x": 0.5, "y": 0.5}]}},
        {"curve": {"master": [{"x": 0.6, "y": 0}, {"x": 0.4, "y": 1}]}},
        {"curve": {"master": [{"x": round(i / 32, 6), "y": round(i / 32, 6)} for i in range(33)]}},
        {"curve": {"master": [{"x": 0.5, "y": 0.5}, {"x": 0.5, "y": 0.6}]}},
        {"curve": {"master": [{"x": -0.1, "y": 0.0}, {"x": 1.0, "y": 1.0}]}},
        {"hsl": {"red": {"hue": 181}}},
        {"colorGrading": {"balance": 101}},
        {"localAdjustments": [{"id": "bad", "maskId": "full"}]},
        {"localAdjustments": [{"id": "local_a", "maskId": "face"}]},
        {"output": {"quality": 92.5}},
        {"schemaVersion": "3.0"},
    ]
    for recipe in invalid_recipes:
        response = client.post(url, json={"recipe": recipe})
        assert response.status_code == 422, recipe

    unknown = str(uuid4())
    missing = client.post(
        f"/api/v1/sessions/{unknown}/render",
        json={"recipe": {}},
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "session_not_found"
    assert client.post("/api/v1/sessions/not-a-uuid/render", json={"recipe": {}}).status_code == 404

    for invalid in (
        "not-a-preview",
        "a" * 63,
        "A" * 64,
    ):
        response = client.get(f"/api/v1/previews/{invalid}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "preview_expired"


def test_expired_preview_returns_404_and_rerenders(
    client: TestClient,
    settings: Settings,
):
    session = _session(client)
    first = _render(client, session)
    preview_id = PREVIEW_PATH.fullmatch(str(first["previewUrl"])).group(1)  # type: ignore[union-attr]
    (settings.preview_dir / f"{preview_id}.jpg").unlink()

    expired = client.get(str(first["previewUrl"]))
    assert expired.status_code == 404
    assert expired.json()["error"]["code"] == "preview_expired"

    second = _render(client, session)
    assert second["cacheHit"] is False
    assert client.get(str(second["previewUrl"])).status_code == 200


def test_serving_a_preview_renews_its_idle_deadline(
    client: TestClient,
    settings: Settings,
):
    session = _session(client)
    rendered = _render(client, session)
    preview_id = PREVIEW_PATH.fullmatch(str(rendered["previewUrl"])).group(1)  # type: ignore[union-attr]
    path = settings.preview_dir / f"{preview_id}.jpg"
    old = time.time() - 600
    os.utime(path, (old, old))

    response = client.get(str(rendered["previewUrl"]))

    assert response.status_code == 200
    assert path.stat().st_mtime > old + 1


def test_preview_deleted_after_resolve_returns_expired_instead_of_500(
    client: TestClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
):
    session = _session(client)
    rendered = _render(client, session)
    preview_id = PREVIEW_PATH.fullmatch(str(rendered["previewUrl"])).group(1)  # type: ignore[union-attr]
    path = settings.preview_dir / f"{preview_id}.jpg"
    assert path.is_file()
    previews = client.app.state.render_service.previews
    real_touch = previews.touch

    def touch_then_remove(target: Path) -> None:
        real_touch(target)
        # Simulate a TTL/capacity cleanup winning the race after resolve().
        target.unlink()

    monkeypatch.setattr(previews, "touch", touch_then_remove)

    response = client.get(str(rendered["previewUrl"]))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "preview_expired"


def test_preview_touch_failure_still_serves_the_preview(
    client: TestClient,
    monkeypatch,
):
    session = _session(client)
    rendered = _render(client, session)

    def readonly_utime(_path: str, _times: object) -> None:
        raise OSError("read-only filesystem")

    monkeypatch.setattr("app.services.preview_store.os.utime", readonly_utime)

    response = client.get(str(rendered["previewUrl"]))

    assert response.status_code == 200
    assert response.content.startswith(b"\xff\xd8")


def test_startup_cleanup_sweeps_expired_previews_and_proxies(
    settings: Settings,
    tmp_path: Path,
):
    settings.preview_dir.mkdir(parents=True, exist_ok=True)
    now = time.time()
    old = settings.preview_dir / "old-preview.jpg"
    fresh = settings.preview_dir / "fresh-preview.jpg"
    outside = settings.data_dir / "keep.txt"
    proxy_dir = settings.preview_dir / "proxies"
    proxy_dir.mkdir()
    old_proxy = proxy_dir / "old-proxy.png"
    fresh_proxy = proxy_dir / "fresh-proxy.png"
    old.write_bytes(b"old")
    fresh.write_bytes(b"fresh")
    outside.write_bytes(b"keep")
    old_proxy.write_bytes(b"proxy")
    fresh_proxy.write_bytes(b"fresh proxy")
    os.utime(old, (now - 7200, now - 7200))
    os.utime(fresh, (now - 5, now - 5))
    os.utime(outside, (now - 7200, now - 7200))
    os.utime(old_proxy, (now - 7200, now - 7200))
    os.utime(fresh_proxy, (now - 5, now - 5))

    with TestClient(create_app(settings)):
        pass

    assert not old.exists()
    assert fresh.is_file()
    assert outside.is_file()
    assert not old_proxy.exists()
    assert fresh_proxy.is_file()
    assert tmp_path in settings.data_dir.parents


def test_older_queued_render_is_superseded_by_a_newer_sequence(client: TestClient):
    session = _session(client)
    service = client.app.state.render_service
    session_id = str(session["sessionId"])
    url = f"/api/v1/sessions/{session_id}/render"
    assert service._slots.acquire(blocking=False)
    assert service._slots.acquire(blocking=False)
    released = False
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            older = pool.submit(
                client.post,
                url,
                json={"recipe": {"adjustments": {"exposureEv": 0.1}}},
                headers={"X-Render-Seq": "10"},
            )
            _wait_for_sequence(service, session_id, 10)
            newer = pool.submit(
                client.post,
                url,
                json={"recipe": {"adjustments": {"exposureEv": 0.9}}},
                headers={"X-Render-Seq": "20"},
            )
            _wait_for_sequence(service, session_id, 20)
            service._slots.release()
            service._slots.release()
            released = True
            older_response = older.result(timeout=30)
            newer_response = newer.result(timeout=30)
    finally:
        if not released:
            service._slots.release()
            service._slots.release()

    assert older_response.status_code == 409
    assert older_response.json()["error"]["code"] == "render_superseded"
    assert newer_response.status_code == 200
    assert newer_response.json()["cacheHit"] is False


def test_render_slot_timeout_returns_server_busy(
    client: TestClient,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.services.render_service.RENDER_SLOT_TIMEOUT_SECONDS",
        0.05,
    )
    session = _session(client)
    service = client.app.state.render_service
    url = f"/api/v1/sessions/{session['sessionId']}/render"
    assert service._slots.acquire(blocking=False)
    assert service._slots.acquire(blocking=False)
    try:
        response = client.post(
            url,
            json={"recipe": {"adjustments": {"exposureEv": 0.2}}},
        )
    finally:
        service._slots.release()
        service._slots.release()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "server_busy"
    assert response.headers["retry-after"] == "1"


def test_render_applies_local_adjustments_through_masks(client: TestClient):
    session = _session(client, size=(800, 400))
    local_recipe = {
        "masks": [
            {
                "id": "mask_left",
                "x": 0.0,
                "y": 0.0,
                "width": 0.5,
                "height": 1.0,
                "feather": 0.0,
            }
        ],
        "localAdjustments": [
            {
                "id": "local_bright",
                "maskId": "mask_left",
                "adjustments": {"exposureEv": 1.5},
            }
        ],
    }

    neutral = _render(client, session, exposure=0.0)
    masked = _render(client, session, exposure=0.0, extra_recipe=local_recipe)

    assert masked["previewUrl"] != neutral["previewUrl"]
    response = client.get(str(masked["previewUrl"]))
    assert response.status_code == 200
    with Image.open(BytesIO(response.content)) as image:
        width, height = image.size
        left = image.crop((0, 0, width // 4, height))
        right = image.crop((width * 3 // 4, 0, width, height))
        left_mean = sum(ImageStat.Stat(left).mean) / 3.0
        right_mean = sum(ImageStat.Stat(right).mean) / 3.0
    assert left_mean > right_mean + 20


def test_render_reports_dangling_mask_references(client: TestClient):
    session = _session(client, size=(400, 300))
    dangling = {
        "localAdjustments": [
            {
                "id": "local_orphan",
                "maskId": "mask_gone",
                "adjustments": {"exposureEv": 1.0},
            }
        ],
    }

    first = _render(client, session, extra_recipe=dangling)
    assert first["cacheHit"] is False
    assert first["warnings"] == ["local_mask_missing:mask_gone"]

    cached = _render(client, session, extra_recipe=dangling)
    assert cached["cacheHit"] is True
    assert cached["warnings"] == ["local_mask_missing:mask_gone"]

    clean = _render(client, session)
    assert clean["warnings"] == []


def test_preview_jpeg_embeds_srgb_profile_and_carries_no_metadata(client: TestClient):
    session = _session(client, size=(400, 300))

    result = _render(client, session)
    response = client.get(str(result["previewUrl"]))

    assert response.status_code == 200
    with Image.open(BytesIO(response.content)) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"
        assert image.info["icc_profile"] == srgb_icc_profile()
        assert len(image.getexif()) == 0
    assert b"Exif\x00\x00" not in response.content


def test_proxy_cache_decodes_each_edge_once_per_session(client: TestClient, monkeypatch):
    session = _session(client, size=(800, 300))
    service = client.app.state.render_service
    decoded_edges: list[int] = []
    real_load_proxy = load_proxy

    def counting_load_proxy(*args, **kwargs):
        proxy = real_load_proxy(*args, **kwargs)
        decoded_edges.append(int(kwargs["max_edge"]))
        return proxy

    monkeypatch.setattr("app.services.render_service.load_proxy", counting_load_proxy)

    first = _render(client, session, exposure=0.4)
    second = _render(client, session, exposure=-0.3)

    assert first["cacheHit"] is False
    assert second["cacheHit"] is False
    assert decoded_edges == [800]
    stats = service.proxy_cache.stats()
    assert (stats.misses, stats.hits, stats.entries) == (1, 1, 1)


def test_proxy_cache_output_matches_a_cache_disabled_run(
    client: TestClient,
    settings: Settings,
    tmp_path: Path,
):
    session = _session(client, size=(900, 300))
    warm = _render(client, session, exposure=0.6)
    warm_bytes = client.get(str(warm["previewUrl"])).content
    assert client.app.state.render_service.proxy_cache.stats().misses == 1

    cold_settings = settings.model_copy(update={"proxy_cache_mb": 0, "data_dir": tmp_path / "cold"})
    with TestClient(create_app(cold_settings)) as cold_client:
        cold_session = _session(cold_client, size=(900, 300))
        cold_service = cold_client.app.state.render_service
        assert not cold_service.proxy_cache.enabled
        cold = _render(cold_client, cold_session, exposure=0.6)
        assert (cold["width"], cold["height"]) == (warm["width"], warm["height"])
        cold_bytes = cold_client.get(str(cold["previewUrl"])).content

    assert cold_bytes == warm_bytes


def test_render_superseded_while_the_proxy_is_decoding(client: TestClient, monkeypatch):
    session = _session(client, size=(500, 300))
    service = client.app.state.render_service
    session_id = str(session["sessionId"])
    real_load_proxy = load_proxy
    decoded_edges: list[int] = []

    def load_then_supersede(*args, **kwargs):
        proxy = real_load_proxy(*args, **kwargs)
        decoded_edges.append(int(kwargs["max_edge"]))
        if len(decoded_edges) == 1:
            service._note_seq(session_id, 40)
        return proxy

    monkeypatch.setattr("app.services.render_service.load_proxy", load_then_supersede)
    url = f"/api/v1/sessions/{session_id}/render"
    body: dict[str, object] = {"recipe": {"adjustments": {"exposureEv": 0.7}}}

    blocked = client.post(url, json=body, headers={"X-Render-Seq": "10"})

    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "render_superseded"
    assert list(service.previews.directory.glob("*.jpg")) == []

    newer = client.post(url, json=body, headers={"X-Render-Seq": "41"})

    assert newer.status_code == 200
    assert decoded_edges == [500]
    assert service.proxy_cache.stats().hits == 1


def test_the_app_configures_the_mask_cache_for_repeated_local_renders(client: TestClient):
    session = _session(client, size=(600, 400))
    local_recipe = {
        "masks": [
            {
                "id": "mask_left",
                "x": 0.0,
                "y": 0.0,
                "width": 0.5,
                "height": 1.0,
                "feather": 20.0,
            }
        ],
        "localAdjustments": [
            {
                "id": "local_bright",
                "maskId": "mask_left",
                "adjustments": {"exposureEv": 1.0},
            }
        ],
    }
    assert mask_cache_stats() == MaskCacheStats()

    _render(client, session, exposure=0.1, extra_recipe=local_recipe)
    assert mask_cache_stats() == MaskCacheStats(misses=1, entries=1, bytes_used=600 * 400 * 4)

    _render(client, session, exposure=-0.2, extra_recipe=local_recipe)

    assert mask_cache_stats() == MaskCacheStats(
        hits=1, misses=1, entries=1, bytes_used=600 * 400 * 4
    )
