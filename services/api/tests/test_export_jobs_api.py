from __future__ import annotations

import io
import threading
import time
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app
from app.models.export import ExportRequest
from app.services import export_service as export_service_module
from tests.conftest import make_image, upload


def _session(client: TestClient, *, size: tuple[int, int] = (640, 480)) -> dict[str, object]:
    image = upload(client, make_image(size=size))
    assert image.status_code == 201, image.text
    response = client.post("/api/v1/sessions", json={"imageId": image.json()["imageId"]})
    assert response.status_code == 201, response.text
    return response.json()


def _submit(
    client: TestClient,
    session: dict[str, object],
    *,
    revision_id: object | None = None,
    image_format: str = "jpeg",
    max_edge: int | None = 320,
):
    body: dict[str, object] = {
        "sessionId": session["sessionId"],
        "revisionId": revision_id if revision_id is not None else session["activeRevisionId"],
        "format": image_format,
    }
    if max_edge is not None:
        body["maxEdge"] = max_edge
    return client.post("/api/v1/exports", json=body)


def _wait_for(
    client: TestClient,
    job_id: str,
    *,
    statuses: frozenset[str] = frozenset({"succeeded", "failed", "cancelled"}),
    timeout: float = 20.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/exports/{job_id}")
        assert response.status_code == 200, response.text
        payload = response.json()
        if payload["status"] in statuses:
            return payload
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not reach {statuses}")


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "data_dir": tmp_path / "data",
        "max_upload_bytes": 1024 * 1024,
        "max_image_pixels": 1_000_000,
        "allowed_origins": "http://testserver",
        "allowed_hosts": "testserver",
        "log_level": "WARNING",
    }
    values.update(overrides)
    return Settings(**values)


def test_export_job_runs_to_completion_and_serves_the_result(
    client: TestClient, settings: Settings
):
    session = _session(client)

    created = _submit(client, session)

    assert created.status_code == 202, created.text
    body = created.json()
    assert body["status"] in {"queued", "running"}
    assert body["filename"] is None
    job_id = body["jobId"]

    finished = _wait_for(client, job_id)

    assert finished["status"] == "succeeded"
    assert finished["width"] == 320
    assert finished["height"] == 240
    assert str(finished["filename"]).endswith(".jpg")
    result = client.get(f"/api/v1/exports/{job_id}/result")
    assert result.status_code == 200, result.text
    assert result.headers["content-type"] == "image/jpeg"
    assert result.headers["content-disposition"] == (
        f'attachment; filename="{finished["filename"]}"'
    )
    assert result.headers["x-export-width"] == "320"
    assert result.headers["x-export-height"] == "240"
    assert result.headers["x-content-type-options"] == "nosniff"
    assert result.headers["content-length"] == str(len(result.content))
    assert "x-export-warning" not in result.headers
    with Image.open(io.BytesIO(result.content)) as exported:
        assert exported.size == (320, 240)
        assert exported.info.get("icc_profile")

    result_files = [path for path in settings.export_dir.iterdir() if path.is_file()]
    assert [path.name for path in result_files] == [f"{job_id}.jpg"]

    assert client.delete(f"/api/v1/exports/{job_id}").status_code == 204
    assert client.delete(f"/api/v1/exports/{job_id}").status_code == 204
    assert client.get(f"/api/v1/exports/{job_id}").json()["status"] == "succeeded"


def test_export_job_rejects_unknown_ids_and_foreign_revisions(client: TestClient):
    session = _session(client)
    other = _session(client)
    unknown_session = client.post(
        "/api/v1/exports",
        json={
            "sessionId": "00000000-0000-0000-0000-000000000000",
            "revisionId": session["activeRevisionId"],
            "format": "jpeg",
        },
    )
    assert unknown_session.status_code == 404
    assert unknown_session.json()["error"]["code"] == "session_not_found"

    foreign = _submit(client, session, revision_id=other["activeRevisionId"])
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "revision_not_found"

    assert client.get("/api/v1/exports/not-a-job").status_code == 404
    assert client.delete("/api/v1/exports/not-a-job").status_code == 404
    assert client.get("/api/v1/exports/not-a-job/result").status_code == 404
    assert (
        client.post(
            "/api/v1/exports",
            json={
                "sessionId": session["sessionId"],
                "revisionId": session["activeRevisionId"],
                "format": "gif",
            },
        ).status_code
        == 422
    )


def test_failed_export_reports_the_error_and_leaves_no_file(tmp_path: Path):
    with TestClient(create_app(_settings(tmp_path, export_max_rss_mb=160))) as client:
        session = _session(client)
        created = _submit(client, session, max_edge=None)
        assert created.status_code == 202, created.text
        job_id = created.json()["jobId"]

        finished = _wait_for(client, job_id)

        assert finished["status"] == "failed"
        assert finished["error"]["code"] == "export_too_large"
        assert finished["error"]["details"]["limitMb"] == 160
        result = client.get(f"/api/v1/exports/{job_id}/result")
        assert result.status_code == 409
        assert result.json()["error"]["code"] == "export_failed"
        assert not list(client.app.state.settings.export_dir.iterdir())


def test_cancelling_a_running_job_releases_the_slot_and_removes_partial_output(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    session = _session(client)
    real_load = export_service_module.load_image
    entered = threading.Event()
    release = threading.Event()

    def blocking_load(*args: object, **kwargs: object):
        entered.set()
        assert release.wait(20), "test did not release the blocked decode"
        return real_load(*args, **kwargs)

    monkeypatch.setattr(export_service_module, "load_image", blocking_load)
    service = client.app.state.export_service
    settings = client.app.state.settings

    created = _submit(client, session)
    assert created.status_code == 202, created.text
    job_id = created.json()["jobId"]
    assert entered.wait(10), "worker never started decoding"

    assert client.delete(f"/api/v1/exports/{job_id}").status_code == 204
    release.set()
    finished = _wait_for(client, job_id)
    assert finished["status"] == "cancelled"
    assert service.admission.snapshot().active == 0
    assert client.app.state.export_jobs.active_sessions() == frozenset()
    assert not list(settings.export_dir.iterdir())

    monkeypatch.setattr(export_service_module, "load_image", real_load)
    retry = _submit(client, session)
    assert retry.status_code == 202, retry.text
    retried = _wait_for(client, retry.json()["jobId"])
    assert retried["status"] == "succeeded"


def test_export_queue_limit_and_cancelling_a_queued_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    with TestClient(
        create_app(_settings(tmp_path, export_max_concurrency=1, export_queue_max=1))
    ) as client:
        session = _session(client)
        real_load = export_service_module.load_image
        entered = threading.Event()
        release = threading.Event()

        def blocking_load(*args: object, **kwargs: object):
            entered.set()
            assert release.wait(20), "test did not release the blocked decode"
            return real_load(*args, **kwargs)

        monkeypatch.setattr(export_service_module, "load_image", blocking_load)

        first = _submit(client, session)
        assert first.status_code == 202, first.text
        assert entered.wait(10), "first job never started decoding"

        second = _submit(client, session)
        assert second.status_code == 202, second.text
        second_id = second.json()["jobId"]
        assert client.get(f"/api/v1/exports/{second_id}").json()["status"] == "queued"

        third = _submit(client, session)
        assert third.status_code == 503
        assert third.json()["error"]["code"] == "server_busy"
        assert third.headers["retry-after"] == "2"

        assert client.delete(f"/api/v1/exports/{second_id}").status_code == 204
        assert client.get(f"/api/v1/exports/{second_id}").json()["status"] == "cancelled"
        assert client.delete(f"/api/v1/exports/{second_id}").status_code == 204

        release.set()
        assert _wait_for(client, first.json()["jobId"])["status"] == "succeeded"


def test_delete_is_rejected_while_a_queued_export_exists(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    session = _session(client)
    real_load = export_service_module.load_image
    entered = threading.Event()
    release = threading.Event()

    def blocking_load(*args: object, **kwargs: object):
        entered.set()
        assert release.wait(20), "test did not release the blocked decode"
        return real_load(*args, **kwargs)

    monkeypatch.setattr(export_service_module, "load_image", blocking_load)
    created = _submit(client, session)
    assert created.status_code == 202, created.text
    assert entered.wait(10), "worker never started decoding"

    response = client.delete(f"/api/v1/images/{session['imageId']}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "resource_busy"
    assert response.json()["error"]["details"]["reasons"] == ["export"]

    release.set()
    _wait_for(client, created.json()["jobId"])


def test_delete_session_purges_its_succeeded_export_result(
    client: TestClient,
    settings: Settings,
):
    session = _session(client)
    created = _submit(client, session)
    assert created.status_code == 202, created.text
    job_id = created.json()["jobId"]
    assert _wait_for(client, job_id)["status"] == "succeeded"
    assert list(settings.export_dir.iterdir())

    assert client.delete(f"/api/v1/sessions/{session['sessionId']}").status_code == 204

    assert client.get(f"/api/v1/exports/{job_id}").status_code == 404
    assert client.get(f"/api/v1/exports/{job_id}/result").status_code == 404
    assert not list(settings.export_dir.iterdir())
    # The tombstoned retry must stay a 204 without resurrecting the job.
    assert client.delete(f"/api/v1/sessions/{session['sessionId']}").status_code == 204
    assert client.get(f"/api/v1/exports/{job_id}").status_code == 404


def test_delete_image_purges_succeeded_exports_for_all_its_sessions(
    client: TestClient,
    settings: Settings,
):
    image = upload(client, make_image(size=(640, 480)))
    assert image.status_code == 201, image.text
    image_id = image.json()["imageId"]
    session_ids: list[str] = []
    job_ids: list[str] = []
    for _ in range(2):
        created = client.post("/api/v1/sessions", json={"imageId": image_id})
        assert created.status_code == 201, created.text
        session = created.json()
        session_ids.append(session["sessionId"])
        submitted = _submit(client, session)
        assert submitted.status_code == 202, submitted.text
        job_id = submitted.json()["jobId"]
        job_ids.append(job_id)
        assert _wait_for(client, job_id)["status"] == "succeeded"
    assert len(list(settings.export_dir.iterdir())) == 2

    assert client.delete(f"/api/v1/images/{image_id}").status_code == 204

    for job_id in job_ids:
        assert client.get(f"/api/v1/exports/{job_id}").status_code == 404
        assert client.get(f"/api/v1/exports/{job_id}/result").status_code == 404
    for session_id in session_ids:
        assert client.get(f"/api/v1/sessions/{session_id}").status_code == 404
    assert not list(settings.export_dir.iterdir())
    assert client.delete(f"/api/v1/images/{image_id}").status_code == 204


def test_failed_concurrent_export_keeps_the_running_session_marked(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    session = _session(client)
    service = client.app.state.export_service
    session_id = str(session["sessionId"])
    request = ExportRequest(
        revision_id=UUID(str(session["activeRevisionId"])),
        format="jpeg",
        max_edge=320,
    )
    real_load = export_service_module.load_image
    first_entered = threading.Event()
    release = threading.Event()
    calls = 0

    def controlled_load(*args: object, **kwargs: object):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_entered.set()
            assert release.wait(20), "test did not release the blocked decode"
            return real_load(*args, **kwargs)
        raise AppError(500, "export_failed", "synthetic concurrent failure")

    monkeypatch.setattr(export_service_module, "load_image", controlled_load)

    errors: list[BaseException] = []

    def run_first_export() -> None:
        try:
            service.export(session_id, request)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    first = threading.Thread(target=run_first_export)
    first.start()
    try:
        assert first_entered.wait(10), "first export never started decoding"
        with pytest.raises(AppError):
            service.export(session_id, request)
        # The failed second call must not clear the first call's marker.
        assert session_id.lower() in service.active_sessions()
        assert client.delete(f"/api/v1/sessions/{session_id}").status_code == 409
    finally:
        release.set()
        first.join(20)

    assert not first.is_alive()
    assert errors == []
    assert service.active_sessions() == frozenset()
    assert client.delete(f"/api/v1/sessions/{session_id}").status_code == 204


def test_delete_discards_a_result_written_after_the_session_was_retired(
    client: TestClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
):
    session = _session(client)
    manager = client.app.state.export_jobs
    deletion = client.app.state.deletion_service
    real_write = manager._write_result
    written = threading.Event()
    release = threading.Event()
    calls = 0

    def blocked_write(job_id: str, result: object) -> Path:
        nonlocal calls
        calls += 1
        path = real_write(job_id, result)  # type: ignore[arg-type]
        if calls == 1:
            written.set()
            assert release.wait(20), "test did not release the result write"
        return path

    monkeypatch.setattr(manager, "_write_result", blocked_write)
    # Simulate the delete-time busy check running before this job registered.
    monkeypatch.setattr(deletion, "_exporting_sessions", lambda: frozenset())

    created = _submit(client, session)
    assert created.status_code == 202, created.text
    job_id = created.json()["jobId"]
    assert written.wait(20), "job never reached the result write"

    assert client.delete(f"/api/v1/sessions/{session['sessionId']}").status_code == 204
    assert client.get(f"/api/v1/exports/{job_id}").status_code == 404
    assert client.get(f"/api/v1/exports/{job_id}/result").status_code == 404

    release.set()
    deadline = time.monotonic() + 20
    while list(settings.export_dir.iterdir()) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not list(settings.export_dir.iterdir())
    assert manager.active_sessions() == frozenset()
    assert client.app.state.export_service.admission.snapshot().active == 0
    assert client.get(f"/api/v1/exports/{job_id}").status_code == 404

    other = _session(client)
    retry = _submit(client, other)
    assert retry.status_code == 202, retry.text
    assert _wait_for(client, retry.json()["jobId"])["status"] == "succeeded"


def test_failed_result_unlink_is_retried_by_a_repeated_session_delete(
    client: TestClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
):
    session = _session(client)
    created = _submit(client, session)
    assert created.status_code == 202, created.text
    job_id = created.json()["jobId"]
    assert _wait_for(client, job_id)["status"] == "succeeded"
    result_path = settings.export_dir / f"{job_id}.jpg"
    assert result_path.is_file()

    real_unlink = Path.unlink
    locked = [True]

    def flaky_unlink(self: Path, *args: object, **kwargs: object) -> None:
        if self == result_path and locked[0]:
            raise PermissionError("synthetic Windows-style lock")
        real_unlink(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

    assert client.delete(f"/api/v1/sessions/{session['sessionId']}").status_code == 204
    assert client.get(f"/api/v1/exports/{job_id}").status_code == 404
    assert client.get(f"/api/v1/exports/{job_id}/result").status_code == 404
    assert result_path.is_file()

    # The session is tombstoned now, so the retry cannot locate the job by id;
    # it must drain the deferred unlink and sweep the result directory instead.
    locked[0] = False
    assert client.delete(f"/api/v1/sessions/{session['sessionId']}").status_code == 204
    assert not result_path.exists()
    assert client.get(f"/api/v1/exports/{job_id}").status_code == 404


def test_repeated_image_delete_retries_a_deferred_result_cleanup(
    client: TestClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
):
    image = upload(client, make_image(size=(640, 480)))
    assert image.status_code == 201, image.text
    image_id = image.json()["imageId"]
    created = client.post("/api/v1/sessions", json={"imageId": image_id})
    assert created.status_code == 201, created.text
    session = created.json()
    submitted = _submit(client, session)
    assert submitted.status_code == 202, submitted.text
    job_id = submitted.json()["jobId"]
    assert _wait_for(client, job_id)["status"] == "succeeded"
    result_path = settings.export_dir / f"{job_id}.jpg"

    real_unlink = Path.unlink
    locked = [True]

    def flaky_unlink(self: Path, *args: object, **kwargs: object) -> None:
        if self == result_path and locked[0]:
            raise PermissionError("synthetic Windows-style lock")
        real_unlink(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

    assert client.delete(f"/api/v1/images/{image_id}").status_code == 204
    assert client.get(f"/api/v1/exports/{job_id}").status_code == 404
    assert result_path.is_file()

    locked[0] = False
    assert client.delete(f"/api/v1/images/{image_id}").status_code == 204
    assert not result_path.exists()
    assert client.get(f"/api/v1/exports/{job_id}").status_code == 404


def test_orphan_sweep_keeps_live_results_and_skips_temporary_files(
    client: TestClient,
    settings: Settings,
):
    session = _session(client)
    created = _submit(client, session)
    assert created.status_code == 202, created.text
    job_id = created.json()["jobId"]
    assert _wait_for(client, job_id)["status"] == "succeeded"
    manager = client.app.state.export_jobs
    live_result = settings.export_dir / f"{job_id}.jpg"
    stale = settings.export_dir / "stale.jpg"
    stale.write_bytes(b"old")
    temporary = settings.export_dir / ".pending.tmp"
    temporary.write_bytes(b"tmp")

    assert manager.retry_cleanup() == 1

    assert live_result.is_file()
    assert not stale.exists()
    assert temporary.is_file()
    assert client.get(f"/api/v1/exports/{job_id}/result").status_code == 200


def test_open_result_survives_a_concurrent_purge(
    client: TestClient,
    settings: Settings,
):
    session = _session(client)
    created = _submit(client, session)
    assert created.status_code == 202, created.text
    job_id = created.json()["jobId"]
    assert _wait_for(client, job_id)["status"] == "succeeded"
    manager = client.app.state.export_jobs

    job, stream, size = manager.open_result(job_id)
    try:
        manager.purge_sessions([str(session["sessionId"])])
        assert client.get(f"/api/v1/exports/{job_id}").status_code == 404
        data = stream.read()
    finally:
        stream.close()
        manager.retry_cleanup()

    assert job.status == "succeeded"
    assert size == len(data)
    assert data
    assert not list(settings.export_dir.iterdir())


def test_result_removed_externally_is_a_404(client: TestClient, settings: Settings):
    session = _session(client)
    created = _submit(client, session)
    assert created.status_code == 202, created.text
    job_id = created.json()["jobId"]
    assert _wait_for(client, job_id)["status"] == "succeeded"
    (settings.export_dir / f"{job_id}.jpg").unlink()

    response = client.get(f"/api/v1/exports/{job_id}/result")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "export_result_missing"


def test_startup_removes_result_files_left_by_a_previous_process(tmp_path: Path):
    settings = _settings(tmp_path)
    settings.export_dir.mkdir(parents=True)
    orphan = settings.export_dir / "stale.jpg"
    orphan.write_bytes(b"old")

    with TestClient(create_app(settings)):
        assert not orphan.exists()
