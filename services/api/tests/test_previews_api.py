from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import Settings
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
) -> dict[str, object]:
    adjustments: dict[str, object] = {"exposureEv": exposure}
    if crop is not None:
        adjustments["crop"] = crop
    body: dict[str, object] = {
        "recipe": {"adjustments": adjustments},
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


def test_startup_cleanup_only_touches_expired_preview_files(
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
    old.write_bytes(b"old")
    fresh.write_bytes(b"fresh")
    outside.write_bytes(b"keep")
    old_proxy.write_bytes(b"proxy")
    os.utime(old, (now - 7200, now - 7200))
    os.utime(fresh, (now - 5, now - 5))
    os.utime(outside, (now - 7200, now - 7200))
    os.utime(old_proxy, (now - 7200, now - 7200))

    with TestClient(create_app(settings)):
        pass

    assert not old.exists()
    assert fresh.is_file()
    assert outside.is_file()
    assert old_proxy.is_file()
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
