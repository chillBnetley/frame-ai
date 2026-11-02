from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.imaging.analyzer import ANALYZER_VERSION
from tests.conftest import image_row, make_image, upload


def _upload_image(client: TestClient, **kwargs) -> str:
    response = upload(client, make_image(**kwargs))
    assert response.status_code == 201
    return str(response.json()["imageId"])


def test_analyze_returns_heuristic_features(client: TestClient):
    image_id = _upload_image(client, size=(1200, 800), color=(120, 100, 80))

    response = client.post(f"/api/v1/images/{image_id}/analyze", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["analyzerVersion"] == ANALYZER_VERSION
    assert body["analysisId"]
    features = body["features"]
    assert features["analyzerVersion"] == ANALYZER_VERSION
    assert features["isHeuristic"] is True
    assert features["size"]["width"] == 1200
    assert features["size"]["height"] == 800
    assert features["size"]["orientation"] == 1
    assert features["size"]["aspectRatio"] == 1.5
    assert len(features["luminance"]["histogram32"]) == 32
    assert len(features["composition"]["edgeDensityGrid3x3"]) == 9
    assert len(features["color"]["meanRgb"]) == 3
    assert features["sceneHints"]["isLowLight"] is False


def test_analyze_reports_display_orientation_and_dimensions(client: TestClient):
    image_id = _upload_image(client, size=(64, 48), exif_orientation=6)

    response = client.post(f"/api/v1/images/{image_id}/analyze")

    assert response.status_code == 200
    size = response.json()["features"]["size"]
    assert size == {"width": 48, "height": 64, "orientation": 6, "aspectRatio": 0.75}


def test_analyze_is_cached_per_image_and_version(client: TestClient, settings: Settings):
    image_id = _upload_image(client)
    first = client.post(f"/api/v1/images/{image_id}/analyze")
    assert first.status_code == 200

    row = image_row(settings, image_id)
    original = settings.data_dir / str(row["storage_key"])
    original.write_bytes(b"corrupted after analysis")

    second = client.post(f"/api/v1/images/{image_id}/analyze", json={"sessionId": str(uuid4())})

    assert second.status_code == 200
    assert second.json() == first.json()


def test_analyze_unknown_or_malformed_image_returns_not_found(client: TestClient):
    missing = client.post(f"/api/v1/images/{uuid4()}/analyze")
    malformed = client.post("/api/v1/images/not-a-uuid/analyze")

    for response in (missing, malformed):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "image_not_found"
        assert response.headers["x-request-id"]


def test_analyze_validates_optional_session_id(client: TestClient):
    image_id = _upload_image(client)

    invalid = client.post(f"/api/v1/images/{image_id}/analyze", json={"sessionId": "nope"})
    valid = client.post(
        f"/api/v1/images/{image_id}/analyze",
        json={"sessionId": str(uuid4())},
    )

    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"
    assert invalid.json()["error"]["details"]["fields"][0]["field"] == "sessionId"
    assert valid.status_code == 200


def test_analyze_response_contains_no_pixel_payloads(client: TestClient):
    image_id = _upload_image(client)

    response = client.post(f"/api/v1/images/{image_id}/analyze")

    text = response.text.lower()
    for forbidden in ("base64", "thumbnail", "imagedata", "pixels", "data:image"):
        assert forbidden not in text
