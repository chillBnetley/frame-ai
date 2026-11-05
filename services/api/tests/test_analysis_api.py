from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.ai.contracts import AnalysisOptions
from app.core.config import Settings
from app.main import create_app
from app.models.analysis_task import AnalysisTaskRecord, TaskStage, TaskStatus
from tests.conftest import image_row, make_image, upload


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "data_dir": tmp_path / "data",
        "max_upload_bytes": 1024 * 1024,
        "max_image_pixels": 1_000_000,
        "allowed_origins": "http://testserver",
        "allowed_hosts": "testserver",
        "log_level": "WARNING",
        "vision_provider": "mock",
        "decision_provider": "mock",
        "mock_scenario": "portrait",
        "analysis_max_concurrency": 1,
        "analysis_max_attempts": 2,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def analysis_settings(tmp_path: Path) -> Settings:
    return _settings(tmp_path)


@pytest.fixture
def analysis_client(analysis_settings: Settings):
    with TestClient(create_app(analysis_settings)) as client:
        yield client


def _upload_image(client: TestClient) -> str:
    response = upload(client, make_image("PNG", (96, 64), (120, 80, 40)))
    assert response.status_code == 201
    return str(response.json()["imageId"])


def _wait(client: TestClient, analysis_id: str, timeout: float = 20.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    payload: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/analysis/{analysis_id}")
        assert response.status_code == 200, response.text
        payload = response.json()
        if payload["status"] in {"completed", "failed"}:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"analysis timed out with status={payload.get('status')}")


def test_create_and_read_the_full_analysis_report(analysis_client: TestClient):
    image_id = _upload_image(analysis_client)

    created = analysis_client.post("/api/v1/analysis", json={"imageId": image_id})
    assert created.status_code == 202, created.text
    body = created.json()
    assert body["deduplicated"] is False
    assert body["status"] in {"pending", "processing"}
    analysis_id = body["analysisId"]

    status = _wait(analysis_client, analysis_id)
    assert status["status"] == "completed"
    assert status["stage"] == "completed"
    assert status["isMock"] is True
    assert status["resultAvailable"] is True
    assert status["error"] is None

    report = status["result"]
    assert report["analysisId"] == analysis_id
    assert report["schemaVersion"] == "stage3/1"
    assert report["image"]["id"] == image_id
    assert report["engine"]["isMock"] is True
    assert report["scene"]["primary"] == "portrait"
    assert report["scene"]["confidence"] > 0.0
    assert report["color"]["harmony"] in {"harmonious", "moderate", "clashing", "unknown"}
    assert report["composition"]["occlusion"] in {"none", "minor", "significant", "unknown"}
    assert 0.0 <= report["composition"]["subjectAreaRatio"] <= 1.0
    assert len(report["measurements"]["luminance"]["histogram32"]) == 32
    assert [len(channel) for channel in report["measurements"]["color"]["rgbHistogram"]] == [
        32,
        32,
        32,
    ]
    assert [len(channel) for channel in report["measurements"]["color"]["hsvHistogram"]] == [
        16,
        8,
        8,
    ]
    assert report["issues"]
    assert all(issue["suggestion"] for issue in report["issues"])
    assert "low_detail" in {issue["type"] for issue in report["issues"]}
    assert report["regions"][0]["mask"] is None
    assert report["subjects"][0]["regionId"] == report["regions"][0]["id"]

    result = analysis_client.get(f"/api/v1/analysis/{analysis_id}/result")
    assert result.status_code == 200, result.text
    assert result.json()["analysisId"] == analysis_id

    duplicate = analysis_client.post("/api/v1/analysis", json={"imageId": image_id})
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["deduplicated"] is True
    assert duplicate.json()["analysisId"] == analysis_id

    forced = analysis_client.post(
        "/api/v1/analysis",
        json={"imageId": image_id, "force": True},
    )
    assert forced.status_code == 202, forced.text
    assert forced.json()["deduplicated"] is False
    assert forced.json()["analysisId"] != analysis_id

    deleted = analysis_client.delete(f"/api/v1/analysis/{analysis_id}")
    assert deleted.status_code == 204
    assert analysis_client.get(f"/api/v1/analysis/{analysis_id}").status_code == 404
    assert analysis_client.get(f"/api/v1/analysis/{analysis_id}/result").status_code == 404
    assert image_row(analysis_client.app.state.settings, image_id)["id"] == image_id
    assert analysis_client.get(f"/api/v1/images/{image_id}/original").status_code == 200


def test_a_second_worker_on_a_finished_task_leaves_the_report_readable(
    analysis_client: TestClient,
):
    image_id = _upload_image(analysis_client)
    created = analysis_client.post("/api/v1/analysis", json={"imageId": image_id})
    analysis_id = created.json()["analysisId"]
    assert _wait(analysis_client, analysis_id)["status"] == "completed"

    tasks = analysis_client.app.state.analysis_task_service
    tasks.orchestrator.run(analysis_id)

    status = analysis_client.get(f"/api/v1/analysis/{analysis_id}").json()
    assert status["status"] == "completed"
    assert status["error"] is None
    assert analysis_client.get(f"/api/v1/analysis/{analysis_id}/result").status_code == 200


def test_all_disabled_options_are_rejected_with_400(analysis_client: TestClient):
    image_id = _upload_image(analysis_client)

    response = analysis_client.post(
        "/api/v1/analysis",
        json={
            "imageId": image_id,
            "options": {
                "sceneRecognition": False,
                "subjectDetection": False,
                "lightingAnalysis": False,
                "colorAnalysis": False,
                "compositionAnalysis": False,
                "qualityDiagnosis": False,
            },
        },
    )

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "invalid_analysis_options"


def test_same_content_uploaded_as_a_new_asset_gets_a_new_task(analysis_client: TestClient):
    first = upload(analysis_client, make_image("PNG", (96, 64), (120, 80, 40)))
    second = upload(analysis_client, make_image("PNG", (96, 64), (120, 80, 40)))
    assert first.status_code == 201 and second.status_code == 201
    first_id = first.json()["imageId"]
    second_id = second.json()["imageId"]
    assert first_id != second_id

    first_task = analysis_client.post("/api/v1/analysis", json={"imageId": first_id})
    second_task = analysis_client.post("/api/v1/analysis", json={"imageId": second_id})
    assert first_task.status_code == 202
    assert second_task.status_code == 202
    assert first_task.json()["analysisId"] != second_task.json()["analysisId"]
    assert second_task.json()["deduplicated"] is False


def test_unknown_image_and_analysis_are_reported_as_not_found(analysis_client: TestClient):
    missing_image = analysis_client.post(
        "/api/v1/analysis",
        json={"imageId": str(uuid4())},
    )
    assert missing_image.status_code == 404
    assert missing_image.json()["error"]["code"] == "image_not_found"

    missing_analysis = uuid4()
    assert analysis_client.get(f"/api/v1/analysis/{missing_analysis}").status_code == 404
    result = analysis_client.get(f"/api/v1/analysis/{missing_analysis}/result")
    assert result.status_code == 404
    assert result.json()["error"]["code"] == "analysis_not_found"
    assert analysis_client.delete(f"/api/v1/analysis/{missing_analysis}").status_code == 404


def test_processing_task_cannot_be_deleted_or_read_early(analysis_client: TestClient):
    image_id = _upload_image(analysis_client)
    service = analysis_client.app.state.analysis_task_service
    image, _ = analysis_client.app.state.image_service.get_original(image_id)
    now = datetime.now(UTC)
    task = AnalysisTaskRecord(
        id=str(uuid4()),
        image_id=image.id,
        image_sha256=image.sha256,
        options=AnalysisOptions(),
        config_key="manual",
        dedupe_key=str(uuid4()),
        status=TaskStatus.PROCESSING,
        stage=TaskStage.VISION,
        attempts=1,
        created_at=now,
        updated_at=now,
        started_at=now,
    )
    service.repository.create(task)

    status = analysis_client.get(f"/api/v1/analysis/{task.id}")
    assert status.status_code == 200
    assert status.json()["status"] == "processing"
    assert status.json()["resultAvailable"] is False
    assert status.json()["result"] is None

    result = analysis_client.get(f"/api/v1/analysis/{task.id}/result")
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "analysis_not_ready"

    deleted = analysis_client.delete(f"/api/v1/analysis/{task.id}")
    assert deleted.status_code == 409
    assert deleted.json()["error"]["code"] == "analysis_in_progress"

    service.repository.mark_failed(task.id, "analysis_failed", "The analysis failed.")
    assert analysis_client.delete(f"/api/v1/analysis/{task.id}").status_code == 204


def test_disabled_analysis_groups_are_reported_as_unknown(analysis_client: TestClient):
    image_id = _upload_image(analysis_client)

    created = analysis_client.post(
        "/api/v1/analysis",
        json={
            "imageId": image_id,
            "options": {
                "sceneRecognition": False,
                "subjectDetection": True,
                "lightingAnalysis": False,
                "colorAnalysis": False,
                "compositionAnalysis": False,
                "qualityDiagnosis": True,
            },
        },
    )
    assert created.status_code == 202, created.text

    report = _wait(analysis_client, created.json()["analysisId"])["result"]
    assert report["scene"]["primary"] == "other"
    assert report["lighting"]["direction"] == "unknown"
    assert report["color"]["temperature"] == "unknown"
    assert report["composition"]["balance"] == "unknown"
    assert report["composition"]["occlusion"] == "unknown"
    assert report["composition"]["subjectAreaRatio"] is None
    assert report["technicalQuality"]["exposure"] != "unknown"
    assert any("场景识别已关闭" in limitation for limitation in report["limitations"])
    assert any("构图分析已关闭" in limitation for limitation in report["limitations"])


def test_disabled_quality_diagnosis_clears_issues_and_recommendations(
    analysis_client: TestClient,
):
    image_id = _upload_image(analysis_client)

    created = analysis_client.post(
        "/api/v1/analysis",
        json={
            "imageId": image_id,
            "options": {
                "sceneRecognition": True,
                "subjectDetection": True,
                "lightingAnalysis": True,
                "colorAnalysis": True,
                "compositionAnalysis": True,
                "qualityDiagnosis": False,
            },
        },
    )
    assert created.status_code == 202, created.text

    report = _wait(analysis_client, created.json()["analysisId"])["result"]
    assert report["technicalQuality"]["exposure"] == "unknown"
    assert report["issues"] == []
    assert report["recommendations"] == []
    assert any("质量诊断已关闭" in limitation for limitation in report["limitations"])


def test_startup_recovers_an_interrupted_task(analysis_settings: Settings):
    with TestClient(create_app(analysis_settings)) as first:
        image_id = _upload_image(first)
        service = first.app.state.analysis_task_service
        image, _ = first.app.state.image_service.get_original(image_id)
        now = datetime.now(UTC)
        task = AnalysisTaskRecord(
            id=str(uuid4()),
            image_id=image.id,
            image_sha256=image.sha256,
            options=AnalysisOptions(),
            config_key="interrupted",
            dedupe_key=str(uuid4()),
            status=TaskStatus.PROCESSING,
            stage=TaskStage.VISION,
            attempts=1,
            created_at=now,
            updated_at=now,
            started_at=now,
        )
        service.repository.create(task)

    with TestClient(create_app(analysis_settings)) as second:
        status = _wait(second, task.id)
        assert status["status"] == "completed"
        assert status["resultAvailable"] is True
        stored = second.app.state.analysis_task_service.repository.get(task.id)
        assert stored is not None
        assert stored.attempts == 2
