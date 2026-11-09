from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.conftest import make_image, upload

PREFIX = "/api/v1/styles"


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        max_upload_bytes=1024 * 1024,
        max_image_pixels=1_000_000,
        allowed_origins="http://testserver",
        allowed_hosts="testserver",
        log_level="WARNING",
        vision_provider="mock",
        decision_provider="mock",
        mock_scenario="portrait",
        analysis_max_concurrency=1,
        analysis_max_attempts=2,
    )


@pytest.fixture
def fit_client(tmp_path: Path):
    with TestClient(create_app(_settings(tmp_path))) as client:
        yield client


def _upload_image(client: TestClient) -> str:
    response = upload(client, make_image("PNG", (96, 64), (120, 80, 40)))
    assert response.status_code == 201, response.text
    return str(response.json()["imageId"])


def _analyze(client: TestClient, image_id: str) -> str:
    created = client.post("/api/v1/analysis", json={"imageId": image_id})
    assert created.status_code == 202, created.text
    analysis_id = str(created.json()["analysisId"])
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        status = client.get(f"/api/v1/analysis/{analysis_id}")
        assert status.status_code == 200, status.text
        if status.json()["status"] in {"completed", "failed"}:
            assert status.json()["status"] == "completed", status.text
            return analysis_id
        time.sleep(0.05)
    raise AssertionError("analysis timed out")


def test_fit_returns_five_dimensions_and_alternatives(fit_client: TestClient) -> None:
    image_id = _upload_image(fit_client)
    analysis_id = _analyze(fit_client, image_id)

    response = fit_client.get(
        f"{PREFIX}/steve_mccurry/fit",
        params={"image_id": image_id, "alternatives": 2},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schemaVersion"] == "stage6/1"
    assert body["engineVersion"] == "style-fit/1"
    assert body["imageId"] == image_id
    assert body["analysisId"] == analysis_id
    assert body["styleId"] == "steve_mccurry"
    assert body["styleKind"] == "master"
    assert body["styleVersion"] == "1.0"
    assert body["isMock"] is True
    assert 0.0 <= body["overallScore"] <= 100.0
    assert body["overallLevel"] in {"high", "medium", "low", "unsuitable"}
    assert body["summary"]
    assert body["recommendedMode"] in {"natural", "style", "creative"}
    strength = body["recommendedStrength"]
    assert strength["minimum"] <= strength["default"] <= strength["maximum"]
    assert [item["dimension"] for item in body["dimensions"]] == [
        "color",
        "light",
        "scene",
        "composition",
        "subject",
    ]
    assert all(item["basis"] and item["evidenceRefs"] for item in body["dimensions"])
    assert len(body["alternatives"]) == 2
    assert all(item["styleId"] != "steve_mccurry" for item in body["alternatives"])
    assert all(item["score"] >= 50.0 for item in body["alternatives"])
    assert "recommended_strength" not in body


def test_fit_rejects_unusable_images_and_unknown_or_disabled_styles(
    fit_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_id = _upload_image(fit_client)

    missing = fit_client.get(f"{PREFIX}/steve_mccurry/fit", params={"image_id": image_id})
    assert missing.status_code == 409
    assert missing.json()["error"]["code"] == "analysis_required"

    unknown_image = fit_client.get(f"{PREFIX}/steve_mccurry/fit", params={"image_id": str(uuid4())})
    assert unknown_image.status_code == 404
    assert unknown_image.json()["error"]["code"] == "image_not_found"

    unknown_style = fit_client.get(f"{PREFIX}/missing_style/fit", params={"image_id": image_id})
    assert unknown_style.status_code == 404
    assert unknown_style.json()["error"]["code"] == "style_not_found"

    fit_client.post(f"{PREFIX}/fan_ho/enabled", json={"enabled": False})
    disabled = fit_client.get(f"{PREFIX}/fan_ho/fit", params={"image_id": image_id})
    assert disabled.status_code == 404

    _analyze(fit_client, image_id)
    analysis = fit_client.app.state.analysis_task_service
    stored = analysis.latest_completed(image_id)
    assert stored is not None
    other_id = _upload_image(fit_client)
    monkeypatch.setattr(analysis, "latest_completed", lambda _image_id: stored)

    mismatch = fit_client.get(f"{PREFIX}/steve_mccurry/fit", params={"image_id": other_id})
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "image_analysis_mismatch"


def test_fit_validates_query_parameters(fit_client: TestClient) -> None:
    image_id = _upload_image(fit_client)

    assert (
        fit_client.get(f"{PREFIX}/steve_mccurry/fit", params={"image_id": image_id}).status_code
        == 409
    )
    invalid_alternatives = fit_client.get(
        f"{PREFIX}/steve_mccurry/fit",
        params={"image_id": image_id, "alternatives": 6},
    )
    assert invalid_alternatives.status_code == 422
    assert fit_client.get(f"{PREFIX}/Steve!/fit", params={"image_id": image_id}).status_code == 422


def test_fit_supports_genre_archives(fit_client: TestClient) -> None:
    image_id = _upload_image(fit_client)
    _analyze(fit_client, image_id)

    response = fit_client.get(f"{PREFIX}/bw_documentary/fit", params={"image_id": image_id})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["styleId"] == "bw_documentary"
    assert body["styleKind"] == "genre"
    assert len(body["dimensions"]) == 5
    assert body["recommendedMode"] in {"natural", "style", "creative"}


def test_fit_contract_uses_camel_case(fit_client: TestClient) -> None:
    image_id = _upload_image(fit_client)
    _analyze(fit_client, image_id)

    body: dict[str, Any] = fit_client.get(
        f"{PREFIX}/fan_ho/fit", params={"image_id": image_id}
    ).json()

    assert "overallScore" in body
    assert "recommendedMode" in body
    assert "recommendedStrength" in body
    assert "styleId" in body
    assert "overall_score" not in body
    assert "recommended_strength" not in body
    for item in body["dimensions"]:
        assert "evidenceRefs" in item
        assert "evidence_refs" not in item
