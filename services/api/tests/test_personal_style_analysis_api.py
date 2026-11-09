from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.models.personal_style import (
    PersonalStyleDefinition,
    PersonalStyleSource,
    build_default_personal_profile,
)
from app.repositories.personal_style_repo import SqlitePersonalStyleRepository
from tests.conftest import make_image, upload

PREFIX = "/api/v1/personal-styles"


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        max_upload_bytes=1024 * 1024,
        max_image_pixels=1_000_000,
        allowed_origins="http://testserver",
        allowed_hosts="testserver",
        log_level="WARNING",
        api_auth_enabled=False,
        vision_provider="mock",
        decision_provider="mock",
        mock_scenario="street",
        analysis_max_concurrency=1,
    )


@pytest.fixture
def analysis_client(tmp_path: Path):
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        yield client, settings


def _create_style(client: TestClient, *, name: str = "克制的城市") -> str:
    response = client.post(
        PREFIX,
        json={
            "name": name,
            "description": "低饱和的街头叙事。",
            "source": "photos",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["style"]["id"])


def _upload_image(client: TestClient) -> str:
    response = upload(client, make_image("PNG", (96, 64), (120, 80, 40)))
    assert response.status_code == 201, response.text
    return str(response.json()["imageId"])


def _add_reference(client: TestClient, style_id: str, image_id: str) -> dict[str, object]:
    response = client.post(
        f"{PREFIX}/{style_id}/references",
        json={"imageIds": [image_id], "consent": True},
    )
    assert response.status_code == 201, response.text
    return response.json()["references"][0]


def _wait_for_analysis(
    client: TestClient,
    style_id: str,
    *,
    timeout: float = 20.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"{PREFIX}/{style_id}/analysis")
        assert response.status_code == 200, response.text
        body = response.json()
        statuses = [item["status"] for item in body["references"]]
        assert "failed" not in statuses, body
        if statuses and all(status == "completed" for status in statuses):
            return body
        time.sleep(0.05)
    raise AssertionError("personal style analysis timed out")


def test_analysis_extracts_and_persists_visual_features(analysis_client) -> None:
    client, settings = analysis_client
    style_id = _create_style(client)
    image_id = _upload_image(client)
    reference = _add_reference(client, style_id, image_id)

    started = client.post(f"{PREFIX}/{style_id}/analyze", json={})
    assert started.status_code == 202, started.text
    assert started.json()["totalCount"] == 1

    completed = _wait_for_analysis(client, style_id)
    item = completed["references"][0]
    assert completed["completedCount"] == 1
    assert item["referenceId"] == reference["id"]
    assert item["status"] == "completed"
    assert item["featureAvailable"] is True
    assert item["analysisId"]
    assert item["confidence"] is not None
    assert item["anomalyCount"] >= 0

    features_response = client.get(
        f"{PREFIX}/{style_id}/references/{reference['id']}/features"
    )
    assert features_response.status_code == 200, features_response.text
    features = features_response.json()
    assert features["schemaVersion"] == "visual-dna-photo/1"
    assert features["extractorVersion"] == "visual-dna/1"
    assert features["imageId"] == image_id
    assert features["isMock"] is True
    assert features["color"]["saturationMean"] >= 0.0
    assert features["tone"]["luminanceStd"] >= 0.0
    assert features["light"]["direction"]
    assert features["texture"]["sharpness"] >= 0.0
    assert features["scene"]["primary"]
    assert features["readings"]
    assert any(reading["editable"] is False for reading in features["readings"])
    assert any(reading["origin"] == "derived" for reading in features["readings"])

    stored = SqlitePersonalStyleRepository(settings.database_path).get_feature(
        style_id,
        str(reference["id"]),
        owner_id="local",
    )
    assert stored is not None
    assert stored.image_sha256 == features["imageSha256"]

    again = client.get(
        f"{PREFIX}/{style_id}/references/{reference['id']}/features"
    ).json()
    assert again["analysisId"] == features["analysisId"]


def test_status_before_analysis_requires_an_analysis_run(analysis_client) -> None:
    client, _ = analysis_client
    style_id = _create_style(client)
    image_id = _upload_image(client)
    _add_reference(client, style_id, image_id)

    status = client.get(f"{PREFIX}/{style_id}/analysis")
    assert status.status_code == 200
    body = status.json()
    assert body["totalCount"] == 1
    assert body["completedCount"] == 0
    assert body["references"][0]["status"] == "analysis_required"
    assert body["references"][0]["featureAvailable"] is False


def test_analyze_requires_references(analysis_client) -> None:
    client, _ = analysis_client
    style_id = _create_style(client)
    response = client.post(f"{PREFIX}/{style_id}/analyze", json={})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "personal_style_reference_required"


def test_analyze_rejects_an_unknown_reference(analysis_client) -> None:
    client, _ = analysis_client
    style_id = _create_style(client)
    response = client.post(
        f"{PREFIX}/{style_id}/analyze",
        json={"referenceIds": ["00000000-0000-0000-0000-000000000000"]},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "personal_style_reference_not_found"


def test_missing_image_is_reported_without_deleting_the_style(analysis_client) -> None:
    client, _ = analysis_client
    style_id = _create_style(client)
    image_id = _upload_image(client)
    reference = _add_reference(client, style_id, image_id)
    assert client.delete(f"/api/v1/images/{image_id}").status_code == 204

    response = client.post(f"{PREFIX}/{style_id}/analyze", json={})
    assert response.status_code == 202, response.text
    assert response.json()["references"][0]["status"] == "missing"

    status = client.get(f"{PREFIX}/{style_id}/analysis").json()
    assert status["references"][0]["status"] == "missing"
    assert client.get(f"{PREFIX}/{style_id}").status_code == 200
    assert client.get(
        f"{PREFIX}/{style_id}/references/{reference['id']}/features"
    ).status_code == 409


def test_removing_a_reference_removes_its_features(analysis_client) -> None:
    client, _ = analysis_client
    style_id = _create_style(client)
    image_id = _upload_image(client)
    reference = _add_reference(client, style_id, image_id)
    client.post(f"{PREFIX}/{style_id}/analyze", json={})
    _wait_for_analysis(client, style_id)

    assert (
        client.delete(f"{PREFIX}/{style_id}/references/{reference['id']}").status_code
        == 204
    )
    assert client.get(
        f"{PREFIX}/{style_id}/references/{reference['id']}/features"
    ).status_code == 404
    status = client.get(f"{PREFIX}/{style_id}/analysis").json()
    assert status["references"] == []
    assert status["totalCount"] == 0


def test_force_analysis_replaces_the_stored_feature_record(analysis_client) -> None:
    client, _ = analysis_client
    style_id = _create_style(client)
    image_id = _upload_image(client)
    reference = _add_reference(client, style_id, image_id)
    client.post(f"{PREFIX}/{style_id}/analyze", json={})
    first = _wait_for_analysis(client, style_id)
    first_analysis_id = first["references"][0]["analysisId"]

    forced = client.post(f"{PREFIX}/{style_id}/analyze", json={"force": True})
    assert forced.status_code == 202, forced.text
    second = _wait_for_analysis(client, style_id)
    assert second["completedCount"] == 1
    assert second["references"][0]["analysisId"] != first_analysis_id

    features = client.get(
        f"{PREFIX}/{style_id}/references/{reference['id']}/features"
    ).json()
    assert features["analysisId"] == second["references"][0]["analysisId"]


def test_analysis_and_feature_endpoints_are_owner_scoped(analysis_client) -> None:
    client, settings = analysis_client
    repository = SqlitePersonalStyleRepository(settings.database_path)
    profile = build_default_personal_profile(
        style_id="personal_fedcba987654",
        name="别人的风格",
        description="不属于当前用户。",
        source=PersonalStyleSource.CUSTOM,
    )
    repository.create(profile, PersonalStyleDefinition(), owner_id="someone-else")

    assert client.get(f"{PREFIX}/{profile.id}/analysis").status_code == 404
    assert client.post(f"{PREFIX}/{profile.id}/analyze", json={}).status_code == 404


def test_a_reference_cannot_be_read_through_another_style(analysis_client) -> None:
    client, _ = analysis_client
    first_style = _create_style(client, name="风格 A")
    second_style = _create_style(client, name="风格 B")
    image_id = _upload_image(client)
    reference = _add_reference(client, first_style, image_id)
    client.post(f"{PREFIX}/{first_style}/analyze", json={})
    _wait_for_analysis(client, first_style)

    response = client.get(
        f"{PREFIX}/{second_style}/references/{reference['id']}/features"
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "personal_style_reference_not_found"
