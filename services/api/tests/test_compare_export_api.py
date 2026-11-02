from __future__ import annotations

import hashlib
import io
from uuid import uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import Settings
from app.repositories.db import connect
from tests.conftest import image_row, make_image, upload


def _gps_jpeg(size: tuple[int, int] = (320, 240), orientation: int = 6) -> bytes:
    image = Image.new("RGB", size, (100, 120, 140))
    exif = Image.Exif()
    exif[274] = orientation
    exif[315] = "FRAME AI test"
    exif[34853] = {
        1: "N",
        2: (40.0, 0.0, 0.0),
        3: "E",
        4: (116.0, 30.0, 0.0),
    }
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95, exif=exif)
    return buffer.getvalue()


def _session(client: TestClient, payload: bytes | None = None) -> dict[str, object]:
    if payload is None:
        payload = make_image(size=(640, 480))
    image = upload(client, payload)
    assert image.status_code == 201, image.text
    response = client.post(
        "/api/v1/sessions",
        json={"imageId": image.json()["imageId"]},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _commit(
    client: TestClient,
    session: dict[str, object],
    *,
    exposure: float = 1.0,
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/sessions/{session['sessionId']}/revisions",
        json={
            "recipe": {"adjustments": {"exposureEv": exposure}},
            "parentRevisionId": session["activeRevisionId"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _row_counts(settings: Settings) -> tuple[int, int]:
    connection = connect(settings.database_path)
    try:
        sessions = connection.execute("SELECT COUNT(*) FROM edit_session").fetchone()[0]
        revisions = connection.execute("SELECT COUNT(*) FROM edit_revision").fetchone()[0]
    finally:
        connection.close()
    return int(sessions), int(revisions)


def _export(
    client: TestClient,
    session: dict[str, object],
    revision_id: object,
    *,
    image_format: str = "jpeg",
    quality: int | None = None,
):
    body: dict[str, object] = {"revisionId": revision_id, "format": image_format}
    if quality is not None:
        body["quality"] = quality
    return client.post(f"/api/v1/sessions/{session['sessionId']}/export", json=body)


def test_export_jpeg_strips_metadata_and_bakes_orientation(
    client: TestClient,
    settings: Settings,
):
    payload = _gps_jpeg()
    image = upload(client, payload, filename="gps.jpg", content_type="image/jpeg")
    assert image.status_code == 201
    image_id = image.json()["imageId"]
    assert (image.json()["width"], image.json()["height"]) == (240, 320)
    session = client.post("/api/v1/sessions", json={"imageId": image_id}).json()
    session = _commit(client, session, exposure=1.0)
    revision_id = str(session["activeRevisionId"])

    undone = client.post(f"/api/v1/sessions/{session['sessionId']}/undo")
    assert undone.status_code == 200
    assert undone.json()["activeRevisionId"] != revision_id

    record = image_row(settings, image_id)
    original_path = (settings.data_dir / str(record["storage_key"])).resolve()
    before = hashlib.sha256(original_path.read_bytes()).hexdigest()

    response = _export(client, session, revision_id)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["x-export-width"] == "240"
    assert response.headers["x-export-height"] == "320"
    assert response.headers["x-content-type-options"] == "nosniff"
    expected_name = f"frame-{revision_id.replace('-', '')[:8]}.jpg"
    assert response.headers["content-disposition"] == f'attachment; filename="{expected_name}"'

    with Image.open(io.BytesIO(response.content)) as exported:
        assert exported.size == (240, 320)
        exif = exported.getexif()
        assert len(exif) == 0
        assert 34853 not in exif
        assert exported.info.get("icc_profile")
        assert "exif" not in exported.info

    assert hashlib.sha256(original_path.read_bytes()).hexdigest() == before


def test_export_png_ignores_quality_and_has_no_metadata_chunks(
    client: TestClient,
    settings: Settings,
):
    session = _session(client)
    session = _commit(client, session, exposure=0.4)
    revision_id = session["activeRevisionId"]

    first = _export(client, session, revision_id, image_format="png", quality=1)
    second = _export(client, session, revision_id, image_format="png", quality=100)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.content == second.content
    assert first.headers["content-type"] == "image/png"
    assert first.headers["content-disposition"].endswith('.png"')
    with Image.open(io.BytesIO(first.content)) as exported:
        assert exported.size == (640, 480)
        assert exported.info.get("icc_profile")
        assert "exif" not in exported.info
        assert "XML:com.adobe.xmp" not in exported.info
        assert not any(key.lower().startswith("text") for key in exported.info)


def test_export_validates_revision_and_payload(client: TestClient):
    session = _session(client)
    other = _session(client)
    foreign_revision = other["activeRevisionId"]
    url = f"/api/v1/sessions/{session['sessionId']}/export"

    assert _export(client, session, str(uuid4())).json()["error"]["code"] == "revision_not_found"
    foreign = _export(client, session, foreign_revision)
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "revision_not_found"

    unknown = client.post(
        f"/api/v1/sessions/{uuid4()}/export",
        json={"revisionId": session["activeRevisionId"], "format": "jpeg"},
    )
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "session_not_found"
    assert (
        client.post(
            "/api/v1/sessions/not-a-uuid/export",
            json={"revisionId": session["activeRevisionId"], "format": "jpeg"},
        ).status_code
        == 404
    )

    assert client.post(url, json={"format": "jpeg"}).status_code == 422
    assert (
        client.post(
            url,
            json={"revisionId": session["activeRevisionId"], "format": "gif"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            url,
            json={"revisionId": session["activeRevisionId"], "format": "jpeg", "quality": 0},
        ).status_code
        == 422
    )
    assert (
        client.post(
            url,
            json={"revisionId": session["activeRevisionId"], "format": "jpeg", "quality": 101},
        ).status_code
        == 422
    )


def test_second_concurrent_export_returns_server_busy(client: TestClient):
    session = _session(client)
    service = client.app.state.export_service
    assert service._slots.acquire(blocking=False)
    try:
        response = _export(client, session, session["activeRevisionId"])
    finally:
        service._slots.release()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "server_busy"
    assert response.headers["retry-after"] == "2"

    retry = _export(client, session, session["activeRevisionId"])
    assert retry.status_code == 200


def test_compare_returns_aligned_original_and_revision_previews(
    client: TestClient,
    settings: Settings,
):
    session = _session(client, make_image(size=(1600, 600), color=(100, 100, 100)))
    session = _commit(client, session, exposure=1.0)
    revision_id = session["activeRevisionId"]
    before = _row_counts(settings)

    response = client.get(
        f"/api/v1/sessions/{session['sessionId']}/compare",
        params={"revisionId": revision_id, "maxEdge": 800},
    )

    assert response.status_code == 200, response.text
    compare = response.json()
    assert (compare["original"]["width"], compare["original"]["height"]) == (800, 300)
    assert (compare["revision"]["width"], compare["revision"]["height"]) == (800, 300)
    assert compare["original"]["previewUrl"] != compare["revision"]["previewUrl"]
    assert _row_counts(settings) == before

    original = client.get(compare["original"]["previewUrl"])
    edited = client.get(compare["revision"]["previewUrl"])
    assert original.status_code == 200
    assert edited.status_code == 200
    original_pixels = np.asarray(Image.open(io.BytesIO(original.content)), dtype=np.float32)
    edited_pixels = np.asarray(Image.open(io.BytesIO(edited.content)), dtype=np.float32)
    assert edited_pixels.mean() > original_pixels.mean() + 10
    with Image.open(io.BytesIO(original.content)) as image:
        assert len(image.getexif()) == 0
        assert "exif" not in image.info
    with Image.open(io.BytesIO(edited.content)) as image:
        assert len(image.getexif()) == 0

    active = client.get(
        f"/api/v1/sessions/{session['sessionId']}/compare",
        params={"maxEdge": 800},
    )
    assert active.status_code == 200
    assert active.json()["revision"]["previewUrl"] == compare["revision"]["previewUrl"]

    missing = client.get(
        f"/api/v1/sessions/{session['sessionId']}/compare",
        params={"revisionId": str(uuid4())},
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "revision_not_found"

    for invalid_edge in (0, 2561):
        assert (
            client.get(
                f"/api/v1/sessions/{session['sessionId']}/compare",
                params={"maxEdge": invalid_edge},
            ).status_code
            == 422
        )


@pytest.mark.parametrize("image_format", ["jpeg", "png"])
def test_export_round_trip_from_history_revision(
    client: TestClient,
    image_format: str,
):
    session = _session(client)
    initial = session["activeRevisionId"]
    session = _commit(client, session, exposure=-0.5)
    revised = session["activeRevisionId"]
    assert client.post(f"/api/v1/sessions/{session['sessionId']}/undo").status_code == 200

    response = _export(client, session, revised, image_format=image_format)

    assert response.status_code == 200, response.text
    assert response.content
    with Image.open(io.BytesIO(response.content)) as exported:
        exported.load()
        assert exported.size == (640, 480)
    initial_export = _export(client, session, initial, image_format=image_format)
    assert initial_export.status_code == 200
    assert initial_export.content != response.content
