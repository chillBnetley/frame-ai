from __future__ import annotations

import io
import threading
import time
from pathlib import Path
from uuid import UUID

import cv2
import numpy as np
import pytest
import tifffile
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


def _transparent_png(size: tuple[int, int] = (80, 60)) -> bytes:
    width, height = size
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    alpha = np.clip(
        np.minimum(np.minimum(x, width - 1 - x), np.minimum(y, height - 1 - y))
        / (min(width, height) * 0.25),
        0.0,
        1.0,
    )
    rgba = np.dstack(
        [
            np.full((height, width), 200.0),
            np.full((height, width), 100.0),
            np.full((height, width), 60.0),
            alpha * 255.0,
        ]
    )
    image = Image.fromarray(np.clip(np.rint(rgba), 0, 255).astype(np.uint8), "RGBA")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _png16(size: tuple[int, int] = (64, 48), *, alpha: bool = False) -> bytes:
    width, height = size
    total = width * height
    ramp = (
        (np.arange(total, dtype=np.uint32) * 65535 // max(total - 1, 1))
        .astype(np.uint16)
        .reshape(height, width)
    )
    rgb = np.stack([ramp, (65535 - ramp).astype(np.uint16), ramp // 2], axis=-1)
    if alpha:
        coverage = np.linspace(0, 65535, width, dtype=np.uint16)
        coverage = np.repeat(coverage[None, :], height, axis=0)
        rgba = np.dstack([rgb, coverage])
        source = np.dstack([rgba[..., 2::-1], rgba[..., 3]])
    else:
        source = rgb[..., ::-1]
    success, encoded = cv2.imencode(".png", np.ascontiguousarray(source))
    assert bool(success)
    return encoded.tobytes()


def _tiff16(size: tuple[int, int] = (64, 48)) -> bytes:
    width, height = size
    total = width * height
    ramp = (
        (np.arange(total, dtype=np.uint32) * 65535 // max(total - 1, 1))
        .astype(np.uint16)
        .reshape(height, width)
    )
    values = np.stack([ramp, (65535 - ramp).astype(np.uint16), ramp // 2], axis=-1)
    buffer = io.BytesIO()
    tifffile.imwrite(buffer, values, photometric="rgb", compression="deflate")
    return buffer.getvalue()


def _session_from(
    client: TestClient,
    payload: bytes,
    filename: str,
    content_type: str,
) -> dict[str, object]:
    image = upload(client, payload, filename, content_type)
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
    bit_depth: int | None = None,
):
    body: dict[str, object] = {
        "sessionId": session["sessionId"],
        "revisionId": revision_id if revision_id is not None else session["activeRevisionId"],
        "format": image_format,
    }
    if max_edge is not None:
        body["maxEdge"] = max_edge
    if bit_depth is not None:
        body["bitDepth"] = bit_depth
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


def test_async_png_export_download_preserves_alpha(client: TestClient):
    payload = _transparent_png()
    image = upload(client, payload, "alpha.png", "image/png")
    assert image.status_code == 201, image.text
    session = client.post(
        "/api/v1/sessions",
        json={"imageId": image.json()["imageId"]},
    ).json()

    created = _submit(client, session, image_format="png", max_edge=None)
    assert created.status_code == 202, created.text
    job_id = created.json()["jobId"]
    finished = _wait_for(client, job_id)

    assert finished["status"] == "succeeded"
    assert str(finished["filename"]).endswith(".png")
    result = client.get(f"/api/v1/exports/{job_id}/result")
    assert result.status_code == 200, result.text
    assert result.headers["content-type"] == "image/png"
    with Image.open(io.BytesIO(result.content)) as exported:
        assert exported.mode == "RGBA"
        assert exported.size == (80, 60)
        alpha = np.asarray(exported.getchannel("A"), dtype=np.uint8)
    assert alpha.min() == 0
    assert alpha.max() == 255
    assert 0.0 < float((alpha == 0).mean()) < 0.5


def test_async_16_bit_png_export_is_really_16_bit(client: TestClient):
    session = _session_from(client, _png16((64, 48)), "photo16.png", "image/png")

    created = _submit(client, session, image_format="png", max_edge=None, bit_depth=16)

    assert created.status_code == 202, created.text
    assert created.json()["bitDepth"] == 16
    job_id = created.json()["jobId"]
    finished = _wait_for(client, job_id)
    assert finished["status"] == "succeeded"
    assert finished["bitDepth"] == 16
    assert str(finished["filename"]).endswith(".png")

    result = client.get(f"/api/v1/exports/{job_id}/result")
    assert result.status_code == 200, result.text
    assert result.headers["content-type"] == "image/png"
    assert result.headers["x-export-bit-depth"] == "16"
    # PNG IHDR carries bit depth 16 and truecolour, not truecolour-alpha.
    assert result.content[24] == 16
    assert result.content[25] == 2
    decoded = cv2.imdecode(np.frombuffer(result.content, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    assert decoded is not None
    assert decoded.dtype == np.uint16
    assert decoded.shape == (48, 64, 3)
    # An 8-bit export can only ever carry 256 levels.
    assert np.unique(decoded).size > 1000


def test_async_16_bit_tiff_export_is_really_16_bit(client: TestClient):
    session = _session_from(client, _tiff16((64, 48)), "photo16.tiff", "image/tiff")

    created = _submit(client, session, image_format="tiff", max_edge=None, bit_depth=16)

    assert created.status_code == 202, created.text
    assert created.json()["bitDepth"] == 16
    job_id = created.json()["jobId"]
    finished = _wait_for(client, job_id)
    assert finished["status"] == "succeeded"
    assert finished["bitDepth"] == 16
    assert str(finished["filename"]).endswith(".tiff")

    result = client.get(f"/api/v1/exports/{job_id}/result")
    assert result.status_code == 200, result.text
    assert result.headers["content-type"] == "image/tiff"
    assert result.headers["x-export-bit-depth"] == "16"
    array = tifffile.imread(io.BytesIO(result.content))
    assert array.dtype == np.uint16
    assert array.shape == (48, 64, 3)
    assert np.unique(array).size > 1000
    with tifffile.TiffFile(io.BytesIO(result.content)) as tif:
        page = tif.pages[0]
        assert page.compression == 32946
        assert page.tags[34675].value  # embedded ICC profile
        assert page.tags[258].value == (16, 16, 16)


def test_async_16_bit_png_export_preserves_alpha(client: TestClient):
    session = _session_from(client, _png16((80, 60), alpha=True), "alpha16.png", "image/png")

    created = _submit(client, session, image_format="png", max_edge=None, bit_depth=16)
    assert created.status_code == 202, created.text
    job_id = created.json()["jobId"]
    assert _wait_for(client, job_id)["status"] == "succeeded"
    result = client.get(f"/api/v1/exports/{job_id}/result")
    assert result.status_code == 200, result.text
    assert result.content[24] == 16
    assert result.content[25] == 6
    decoded = cv2.imdecode(np.frombuffer(result.content, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    assert decoded is not None
    assert decoded.dtype == np.uint16
    assert decoded.shape == (60, 80, 4)
    alpha = decoded[..., 3]
    assert int(alpha.min()) == 0
    assert int(alpha.max()) == 65535


def test_async_16_bit_denoise_is_skipped_with_a_warning(client: TestClient):
    session = _session_from(client, _png16((64, 48)), "photo16.png", "image/png")
    revision = client.post(
        f"/api/v1/sessions/{session['sessionId']}/revisions",
        json={
            "recipe": {"adjustments": {"denoise": 50}},
            "parentRevisionId": session["activeRevisionId"],
        },
    )
    assert revision.status_code == 201, revision.text

    created = _submit(
        client,
        session,
        revision_id=revision.json()["activeRevisionId"],
        image_format="png",
        max_edge=None,
        bit_depth=16,
    )

    assert created.status_code == 202, created.text
    job_id = created.json()["jobId"]
    finished = _wait_for(client, job_id)
    assert finished["status"] == "succeeded"
    assert finished["bitDepth"] == 16
    assert finished["warnings"] == ["denoise_skipped_for_16bit"]
    result = client.get(f"/api/v1/exports/{job_id}/result")
    assert result.status_code == 200, result.text
    assert result.headers["x-export-warning"] == "denoise_skipped_for_16bit"


def test_16_bit_jpeg_is_rejected_before_a_job_is_created(client: TestClient):
    session = _session_from(client, _png16((64, 48)), "photo16.png", "image/png")
    revision_id = session["activeRevisionId"]

    async_response = _submit(client, session, image_format="jpeg", bit_depth=16)

    assert async_response.status_code == 422
    assert client.app.state.export_jobs.active_sessions() == frozenset()

    sync_response = client.post(
        f"/api/v1/sessions/{session['sessionId']}/export",
        json={"revisionId": revision_id, "format": "jpeg", "bitDepth": 16},
    )
    assert sync_response.status_code == 422


def test_16_bit_export_surcharge_pushes_it_over_the_memory_budget(tmp_path: Path):
    eight_settings = _settings(tmp_path / "eight", export_max_rss_mb=170)
    with TestClient(create_app(eight_settings)) as eight_client:
        session = _session(eight_client)
        eight = eight_client.post(
            f"/api/v1/sessions/{session['sessionId']}/export",
            json={"revisionId": session["activeRevisionId"], "format": "png"},
        )

    sixteen_settings = _settings(tmp_path / "sixteen", export_max_rss_mb=170)
    with TestClient(create_app(sixteen_settings)) as sixteen_client:
        session16 = _session_from(sixteen_client, _png16((640, 480)), "photo16.png", "image/png")
        sixteen = sixteen_client.post(
            f"/api/v1/sessions/{session16['sessionId']}/export",
            json={
                "revisionId": session16["activeRevisionId"],
                "format": "png",
                "bitDepth": 16,
            },
        )

    assert eight.status_code == 200
    assert sixteen.status_code == 413
    assert sixteen.json()["error"]["code"] == "export_too_large"


def test_sync_16_bit_png_export_serves_16_bit_samples(client: TestClient):
    session = _session_from(client, _png16((64, 48)), "photo16.png", "image/png")

    response = client.post(
        f"/api/v1/sessions/{session['sessionId']}/export",
        json={
            "revisionId": session["activeRevisionId"],
            "format": "png",
            "bitDepth": 16,
        },
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-export-bit-depth"] == "16"
    assert str(response.headers["content-disposition"]).endswith('.png"')
    decoded = cv2.imdecode(np.frombuffer(response.content, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    assert decoded is not None
    assert decoded.dtype == np.uint16
    assert np.unique(decoded).size > 1000


def test_explicit_8_bit_matches_the_default_export_bytes(client: TestClient):
    session = _session(client)
    url = f"/api/v1/sessions/{session['sessionId']}/export"
    revision_id = session["activeRevisionId"]

    for image_format, expected_type in (("png", "image/png"), ("tiff", "image/tiff")):
        default = client.post(url, json={"revisionId": revision_id, "format": image_format})
        explicit = client.post(
            url,
            json={"revisionId": revision_id, "format": image_format, "bitDepth": 8},
        )

        assert default.status_code == 200, default.text
        assert explicit.status_code == 200, explicit.text
        assert default.headers["content-type"] == expected_type
        assert default.content == explicit.content
        assert default.headers["x-export-bit-depth"] == "8"
        assert explicit.headers["x-export-bit-depth"] == "8"


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
