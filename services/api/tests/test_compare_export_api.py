from __future__ import annotations

import hashlib
import io
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from numpy.typing import NDArray
from PIL import Image

from app.core.config import Settings
from app.imaging.output import srgb_icc_profile
from app.main import create_app
from app.models.recipe import (
    Adjustments,
    EditRecipe,
    HslAdjustments,
    HslBand,
    LocalAdjustment,
    LocalAdjustments,
    UserMask,
)
from app.repositories.db import connect
from app.services.export_service import estimate_export_peak_mb, render_image
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
    adjustments: dict[str, object] | None = None,
    extra_recipe: dict[str, object] | None = None,
) -> dict[str, object]:
    recipe: dict[str, object] = {
        "adjustments": adjustments if adjustments is not None else {"exposureEv": exposure}
    }
    if extra_recipe is not None:
        recipe.update(extra_recipe)
    response = client.post(
        f"/api/v1/sessions/{session['sessionId']}/revisions",
        json={
            "recipe": recipe,
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
    max_edge: int | None = None,
    color_space: str | None = None,
):
    body: dict[str, object] = {"revisionId": revision_id, "format": image_format}
    if quality is not None:
        body["quality"] = quality
    if max_edge is not None:
        body["maxEdge"] = max_edge
    if color_space is not None:
        body["colorSpace"] = color_space
    return client.post(f"/api/v1/sessions/{session['sessionId']}/export", json=body)


def _gradient_png(size: tuple[int, int] = (640, 480)) -> bytes:
    columns = np.linspace(0.0, 255.0, size[0], dtype=np.float32)
    rows = np.linspace(0.0, 255.0, size[1], dtype=np.float32)
    channels = np.dstack(
        [
            np.tile(columns, (size[1], 1)),
            np.tile(255.0 - columns, (size[1], 1)),
            np.repeat(rows[:, None], size[0], axis=1),
        ]
    )
    image = Image.fromarray(np.rint(channels).astype(np.uint8), "RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _decoded(response: object) -> tuple[tuple[int, int], NDArray[np.uint8]]:
    with Image.open(io.BytesIO(response.content)) as image:  # type: ignore[union-attr]
        return image.size, np.asarray(image.convert("RGB"), dtype=np.uint8)


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
    assert "x-export-warning" not in response.headers
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
    assert service.admission.snapshot().max_concurrency == 1
    held = 1.0
    assert service.admission.try_acquire(held)
    try:
        response = _export(client, session, session["activeRevisionId"])
    finally:
        service.admission.release(held)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "server_busy"
    assert response.headers["retry-after"] == "2"
    assert service.admission.snapshot().active == 0

    retry = _export(client, session, session["activeRevisionId"])
    assert retry.status_code == 200


def test_export_is_rejected_when_active_exports_fill_the_memory_budget(tmp_path):
    settings = _settings(tmp_path, export_max_concurrency=4, export_max_rss_mb=200)
    with TestClient(create_app(settings)) as busy_client:
        session = _session(busy_client)
        service = busy_client.app.state.export_service
        # A full-canvas 640x480 export estimates about 163 MB, so a 60 MB
        # reservation fills the 200 MB budget even though slots are free.
        held = 60.0
        assert service.admission.try_acquire(held)
        try:
            assert service.admission.snapshot().reserved_mb == 60.0
            response = _export(busy_client, session, session["activeRevisionId"])
        finally:
            service.admission.release(held)

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "server_busy"
        assert service.admission.snapshot().active == 0

        retry = _export(busy_client, session, session["activeRevisionId"])
        assert retry.status_code == 200
        assert service.admission.snapshot().active == 0


def test_over_budget_export_reports_413_before_the_busy_check(tmp_path):
    settings = _settings(tmp_path, export_max_rss_mb=100)
    with TestClient(create_app(settings)) as busy_client:
        session = _session(busy_client)
        service = busy_client.app.state.export_service
        held = 1.0
        assert service.admission.try_acquire(held)
        try:
            response = _export(busy_client, session, session["activeRevisionId"])
        finally:
            service.admission.release(held)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "export_too_large"


def test_two_exports_render_simultaneously_when_concurrency_allows(tmp_path, monkeypatch):
    settings = _settings(tmp_path, export_max_concurrency=2)
    both_inside = threading.Barrier(2, timeout=15)
    real_render = render_image

    def overlapping_render(*args, **kwargs):
        both_inside.wait()
        return real_render(*args, **kwargs)

    monkeypatch.setattr("app.services.export_service.render_image", overlapping_render)
    with TestClient(create_app(settings)) as parallel_client:
        session = _session(parallel_client)
        revision_id = session["activeRevisionId"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(
                pool.map(
                    lambda _: _export(parallel_client, session, revision_id),
                    range(2),
                )
            )

    assert [response.status_code for response in responses] == [200, 200]
    assert all(response.headers["x-export-width"] == "640" for response in responses)


def test_default_settings_keep_exports_serial(tmp_path):
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as serial_client:
        service = serial_client.app.state.export_service
        assert service.admission.snapshot().max_concurrency == 1
        assert service.admission.snapshot().max_total_mb == settings.export_max_rss_mb


def test_export_estimate_uses_the_planned_source_size(tmp_path):
    settings = _settings(tmp_path, export_max_rss_mb=152)
    with TestClient(create_app(settings)) as sizing_client:
        session = _session(sizing_client)
        revision_id = _commit(sizing_client, session)["activeRevisionId"]
        full = _export(sizing_client, session, revision_id)
        downscaled = _export(sizing_client, session, revision_id, max_edge=320)

    full_details = full.json()["error"]["details"]
    downscaled_details = downscaled.json()["error"]["details"]
    assert full_details["pixels"] == 640 * 480
    assert downscaled_details["pixels"] == 320 * 240
    assert downscaled_details["maxEdge"] == 320
    assert downscaled_details["estimatedPeakMb"] < full_details["estimatedPeakMb"]


def test_a_downscaled_export_fits_a_budget_the_full_size_exceeds(tmp_path):
    settings = _settings(tmp_path, export_max_rss_mb=180)
    with TestClient(create_app(settings)) as fit_client:
        session = _session(fit_client)
        revision_id = _commit(fit_client, session)["activeRevisionId"]
        full = _export(fit_client, session, revision_id)
        downscaled = _export(fit_client, session, revision_id, max_edge=320)

    assert full.status_code == 413
    assert downscaled.status_code == 200
    assert downscaled.headers["x-export-width"] == "320"
    assert downscaled.headers["x-export-height"] == "240"


def _settings(tmp_path, **overrides) -> Settings:
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


def test_export_estimate_separates_neutral_and_full_recipes():
    adjusted = EditRecipe(adjustments=Adjustments(exposure_ev=0.5))
    hsl = EditRecipe(hsl=HslAdjustments(blue=HslBand(hue=20)))

    neutral = estimate_export_peak_mb(40_000_000, EditRecipe())
    full = estimate_export_peak_mb(40_000_000, adjusted)
    with_hsl = estimate_export_peak_mb(40_000_000, hsl)

    assert neutral < 3072
    assert full > 3072
    assert with_hsl == pytest.approx(full)


def test_default_budget_matches_the_measured_export_peaks():
    adjusted = EditRecipe(adjustments=Adjustments(exposure_ev=0.5))

    neutral_40 = estimate_export_peak_mb(40_000_000, EditRecipe())
    full_40 = estimate_export_peak_mb(40_000_000, adjusted)
    full_24 = estimate_export_peak_mb(24_000_000, adjusted)
    full_12 = estimate_export_peak_mb(12_000_000, adjusted)

    # G4 measured 40 MP neutral at 1635 MB, 24 MP neutral at 1043 MB, 24 MP
    # full at 2907 MB and 40 MP full at 4793 MB after the curve LUT; Task 8
    # measured 12 MP full at 2578 MB. The estimate stays above every one of
    # them, which keeps the default 3072 MB cut-off between 12 MP and 24 MP
    # full-recipe exports.
    assert neutral_40 < 3072
    assert full_12 < 3072
    assert full_24 > 3072
    assert full_40 > 3072


def test_export_estimate_floors_at_the_neutral_cost_of_the_original_decode():
    recipe = EditRecipe(adjustments=Adjustments(exposure_ev=0.5))
    original = 40_000_000
    planned = 640 * 480

    floored = estimate_export_peak_mb(planned, recipe, decode_pixels=original)
    neutral_original = estimate_export_peak_mb(original, EditRecipe(), decode_pixels=original)

    # Decoding reads the whole original even when the plan renders 0.3 MP, so a
    # downscaled export can never plan below a neutral pass over that decode.
    assert floored == pytest.approx(neutral_original)
    assert floored > estimate_export_peak_mb(planned, recipe)
    assert estimate_export_peak_mb(original, recipe, decode_pixels=original) > floored


def test_export_estimate_adds_a_surcharge_for_active_local_adjustments():
    mask = UserMask(id="mask_bench", x=0.1, y=0.1, width=0.3, height=0.3)
    local = LocalAdjustment(
        id="local_bench",
        mask_id="mask_bench",
        adjustments=LocalAdjustments(exposure_ev=0.5),
    )
    idle = LocalAdjustment(
        id="local_idle",
        mask_id="mask_bench",
        adjustments=LocalAdjustments(),
    )
    active = EditRecipe(
        adjustments=Adjustments(exposure_ev=0.5),
        masks=(mask,),
        local_adjustments=(local,),
    )
    inactive = EditRecipe(
        adjustments=Adjustments(exposure_ev=0.5),
        masks=(mask,),
        local_adjustments=(idle,),
    )
    base = estimate_export_peak_mb(24_000_000, EditRecipe(adjustments=Adjustments(exposure_ev=0.5)))

    assert estimate_export_peak_mb(24_000_000, inactive) == pytest.approx(base)
    assert estimate_export_peak_mb(24_000_000, active) > 3072
    assert estimate_export_peak_mb(12_000_000, active) < 3072


def test_export_beyond_the_memory_budget_returns_413(tmp_path):
    settings = _settings(tmp_path, export_max_rss_mb=160)
    with TestClient(create_app(settings)) as client:
        session = _session(client)
        response = _export(client, session, session["activeRevisionId"])

    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == "export_too_large"
    assert error["details"]["pixels"] == 640 * 480
    assert error["details"]["limitMb"] == 160
    assert error["details"]["estimatedPeakMb"] > 160
    assert "x-export-warning" not in response.headers


def test_large_export_denoise_reports_the_simplified_warning(tmp_path):
    settings = _settings(tmp_path, export_denoise_simplify_pixels=1)
    with TestClient(create_app(settings)) as client:
        session = _session(client)
        revision = client.post(
            f"/api/v1/sessions/{session['sessionId']}/revisions",
            json={
                "recipe": {"adjustments": {"denoise": 50}},
                "parentRevisionId": session["activeRevisionId"],
            },
        )
        assert revision.status_code == 201, revision.text
        active_revision = revision.json()["activeRevisionId"]

        response = _export(client, session, active_revision)

        assert response.status_code == 200, response.text
        assert response.headers["x-export-warning"] == "denoise_simplified"


def test_downscaled_export_is_measured_against_the_planned_pixels(tmp_path):
    settings = _settings(tmp_path, export_denoise_simplify_pixels=200_000)
    with TestClient(create_app(settings)) as client:
        session = _session(client)
        revision = client.post(
            f"/api/v1/sessions/{session['sessionId']}/revisions",
            json={
                "recipe": {"adjustments": {"denoise": 50}},
                "parentRevisionId": session["activeRevisionId"],
            },
        )
        assert revision.status_code == 201, revision.text
        active_revision = revision.json()["activeRevisionId"]

        full = _export(client, session, active_revision)
        assert full.status_code == 200, full.text
        assert full.headers["x-export-warning"] == "denoise_simplified"

        downscaled = _export(client, session, active_revision, max_edge=320)
        assert downscaled.status_code == 200, downscaled.text
        assert "x-export-warning" not in downscaled.headers
        assert downscaled.headers["x-export-width"] == "320"


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
    assert compare["warnings"] == []
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


def test_compare_original_side_applies_geometry_without_tone_adjustments(
    client: TestClient,
):
    session = _session(client, make_image(size=(1200, 700), color=(90, 110, 130)))
    session = _commit(
        client,
        session,
        adjustments={
            "exposureEv": 0.8,
            "rotationDeg": 9.0,
            "crop": {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5},
        },
    )

    response = client.get(
        f"/api/v1/sessions/{session['sessionId']}/compare",
        params={"maxEdge": 800},
    )

    assert response.status_code == 200, response.text
    compare = response.json()
    assert (compare["original"]["width"], compare["original"]["height"]) == (
        compare["revision"]["width"],
        compare["revision"]["height"],
    )
    assert compare["original"]["previewUrl"] != compare["revision"]["previewUrl"]

    original = client.get(compare["original"]["previewUrl"])
    edited = client.get(compare["revision"]["previewUrl"])
    assert original.status_code == 200
    assert edited.status_code == 200
    original_pixels = np.asarray(Image.open(io.BytesIO(original.content)), dtype=np.float32)
    edited_pixels = np.asarray(Image.open(io.BytesIO(edited.content)), dtype=np.float32)
    assert edited_pixels.shape == original_pixels.shape
    assert edited_pixels.mean() > original_pixels.mean() + 10


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


def test_export_applies_a_full_recipe(client: TestClient):
    session = _session(client)
    initial = session["activeRevisionId"]
    session = _commit(
        client,
        session,
        adjustments={
            "exposureEv": 0.4,
            "contrast": 12,
            "highlights": -20,
            "shadows": 15,
            "temperature": 8,
            "tint": -4,
            "saturation": 10,
            "vibrance": 12,
            "clarity": 20,
            "vignette": 10,
            "denoise": 10,
            "sharpen": 15,
            "grain": 10,
            "rotationDeg": 2.0,
            "crop": {"x": 0.05, "y": 0.05, "w": 0.9, "h": 0.9},
        },
    )

    edited = _export(client, session, session["activeRevisionId"])
    neutral = _export(client, session, initial)

    assert edited.status_code == 200, edited.text
    assert neutral.status_code == 200, neutral.text
    assert "x-export-warning" not in edited.headers
    with Image.open(io.BytesIO(edited.content)) as image:
        width, height = image.size
        assert 0 < width < 640
        assert 0 < height < 480
        edited_pixels = np.asarray(image.convert("RGB"), dtype=np.float32)
    with Image.open(io.BytesIO(neutral.content)) as image:
        neutral_pixels = cv2.resize(
            np.asarray(image.convert("RGB"), dtype=np.float32),
            (edited_pixels.shape[1], edited_pixels.shape[0]),
            interpolation=cv2.INTER_AREA,
        )
    assert np.abs(edited_pixels - neutral_pixels).mean() > 5


def test_export_applies_local_adjustments_through_masks(client: TestClient):
    session = _session(client)
    session = _commit(
        client,
        session,
        adjustments={},
        extra_recipe={
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
        },
    )

    response = _export(client, session, session["activeRevisionId"])
    assert response.status_code == 200, response.text
    assert "x-export-warning" not in response.headers
    with Image.open(io.BytesIO(response.content)) as image:
        width, height = image.size
        pixels = np.asarray(image.convert("RGB"), dtype=np.float32)
    left_mean = float(pixels[:, : width // 4].mean())
    right_mean = float(pixels[:, width * 3 // 4 :].mean())
    assert left_mean > right_mean + 20


def test_export_with_a_missing_mask_is_untouched_and_warns(client: TestClient):
    session = _session(client)
    initial = session["activeRevisionId"]
    session = _commit(
        client,
        session,
        adjustments={},
        extra_recipe={
            "localAdjustments": [
                {
                    "id": "local_bright",
                    "maskId": "mask_missing",
                    "adjustments": {"exposureEv": 1.5},
                }
            ]
        },
    )

    edited = _export(client, session, session["activeRevisionId"])
    neutral = _export(client, session, initial)

    assert edited.status_code == 200, edited.text
    assert edited.headers["x-export-warning"] == "local_mask_missing:mask_missing"
    with Image.open(io.BytesIO(edited.content)) as image:
        edited_pixels = np.asarray(image.convert("RGB"), dtype=np.float32)
    with Image.open(io.BytesIO(neutral.content)) as image:
        neutral_pixels = np.asarray(image.convert("RGB"), dtype=np.float32)
    assert np.abs(edited_pixels - neutral_pixels).max() <= 3


def test_export_max_edge_returns_the_exact_requested_long_edge(client: TestClient):
    session = _session(client, _gradient_png())
    committed = _commit(client, session, exposure=0.5)
    revision_id = committed["activeRevisionId"]

    for image_format, suffix in (("jpeg", ".jpg"), ("png", ".png")):
        response = _export(
            client,
            committed,
            revision_id,
            image_format=image_format,
            max_edge=320,
        )
        assert response.status_code == 200, response.text
        assert response.headers["x-export-width"] == "320"
        assert response.headers["x-export-height"] == "240"
        expected_name = f"frame-{str(revision_id).replace('-', '')[:8]}{suffix}"
        assert response.headers["content-disposition"] == (
            f'attachment; filename="{expected_name}"'
        )
        size, _ = _decoded(response)
        assert size == (320, 240)


def test_export_max_edge_is_measured_on_the_rendered_canvas(client: TestClient):
    session = _session(client, _gradient_png((600, 400)))
    committed = _commit(
        client,
        session,
        adjustments={
            "rotationDeg": 7.5,
            "crop": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.7},
        },
    )
    revision_id = committed["activeRevisionId"]

    full = _export(client, committed, revision_id, image_format="png")
    downscaled = _export(client, committed, revision_id, image_format="png", max_edge=200)

    assert full.status_code == 200 and downscaled.status_code == 200
    full_size, _ = _decoded(full)
    scaled_size, _ = _decoded(downscaled)
    assert max(scaled_size) == 200
    assert scaled_size != full_size
    assert abs(scaled_size[0] / scaled_size[1] - full_size[0] / full_size[1]) < 0.02
    assert downscaled.headers["x-export-width"] == str(scaled_size[0])
    assert downscaled.headers["x-export-height"] == str(scaled_size[1])


def test_export_max_edge_above_the_canvas_is_not_upscaled(client: TestClient):
    session = _session(client, _gradient_png())
    committed = _commit(client, session, exposure=0.0, adjustments={})
    revision_id = committed["activeRevisionId"]

    full = _export(client, committed, revision_id, image_format="png")
    oversized = _export(client, committed, revision_id, image_format="png", max_edge=4096)

    assert _decoded(full)[0] == _decoded(oversized)[0] == (640, 480)


@pytest.mark.parametrize("max_edge", [63, 100_001, 0, -1])
def test_export_rejects_max_edge_outside_the_supported_range(client: TestClient, max_edge: int):
    session = _session(client)
    response = client.post(
        f"/api/v1/sessions/{session['sessionId']}/export",
        json={
            "revisionId": session["activeRevisionId"],
            "format": "jpeg",
            "maxEdge": max_edge,
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize("color_space", [None, "sRGB"])
def test_export_output_declares_and_embeds_srgb(client: TestClient, color_space: str | None):
    session = _session(client)
    body: dict[str, object] = {
        "revisionId": session["activeRevisionId"],
        "format": "jpeg",
    }
    if color_space is not None:
        body["colorSpace"] = color_space

    response = client.post(f"/api/v1/sessions/{session['sessionId']}/export", json=body)

    assert response.status_code == 200, response.text
    with Image.open(io.BytesIO(response.content)) as exported:
        assert exported.mode == "RGB"
        assert exported.info["icc_profile"] == srgb_icc_profile()


@pytest.mark.parametrize("color_space", ["AdobeRGB", "DisplayP3", "srgb", "RGB"])
def test_export_rejects_any_output_colour_space_other_than_srgb(
    client: TestClient, color_space: str
):
    session = _session(client)

    response = client.post(
        f"/api/v1/sessions/{session['sessionId']}/export",
        json={
            "revisionId": session["activeRevisionId"],
            "format": "jpeg",
            "colorSpace": color_space,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_export_downscaled_matches_the_full_export_resized_to_the_same_canvas(
    client: TestClient,
):
    session = _session(client, _gradient_png())
    committed = _commit(client, session, exposure=0.5, adjustments={"contrast": 20})
    revision_id = committed["activeRevisionId"]

    full = _export(client, committed, revision_id, image_format="png")
    downscaled = _export(client, committed, revision_id, image_format="png", max_edge=320)

    _, full_pixels = _decoded(full)
    _, scaled_pixels = _decoded(downscaled)
    reference = cv2.resize(full_pixels, (320, 240), interpolation=cv2.INTER_AREA)
    mean_diff = float(np.abs(reference.astype(np.int16) - scaled_pixels.astype(np.int16)).mean())
    max_diff = int(np.abs(reference.astype(np.int16) - scaled_pixels.astype(np.int16)).max())
    # Measured 2026-11-04 on a 640x480 gradient with exposure +0.5 / contrast 20:
    # mean 0.205 gray levels, max 1 gray level against the full export resized
    # to the same canvas.
    assert mean_diff <= 1.0, f"measured mean diff {mean_diff:.3f}, max {max_diff}"
    assert max_diff <= 2, f"measured max diff {max_diff}"


def test_export_ignores_the_recipe_output_block(client: TestClient):
    session = _session(client)
    committed = _commit(
        client,
        session,
        extra_recipe={"output": {"format": "png", "quality": 40, "colorSpace": "sRGB"}},
    )

    response = _export(client, committed, committed["activeRevisionId"], image_format="jpeg")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/jpeg"
    size, _ = _decoded(response)
    assert size == (640, 480)


@pytest.mark.parametrize("image_format", ["jpeg", "png"])
def test_export_output_is_eight_bit_rgb_without_alpha(client: TestClient, image_format: str):
    session = _session(client)
    committed = _commit(client, session, exposure=0.5)

    for max_edge in (None, 200):
        response = _export(
            client,
            committed,
            committed["activeRevisionId"],
            image_format=image_format,
            max_edge=max_edge,
        )
        assert response.status_code == 200, response.text
        with Image.open(io.BytesIO(response.content)) as exported:
            assert exported.mode == "RGB"
            if image_format == "png":
                # IHDR: bit depth at byte 24, colour type 2 means truecolor RGB.
                assert response.content[24] == 8
                assert response.content[25] == 2
            else:
                assert exported.bits == 8
            assert exported.info.get("transparency") is None
            assert len(exported.getexif()) == 0


def test_encoder_failure_returns_a_json_envelope_without_image_bytes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    session = _session(client)

    def explode(*_args: object, **_kwargs: object) -> bytes:
        raise OSError("encoder exploded")

    monkeypatch.setattr("app.services.export_service.encode_image", explode)

    response = _export(client, session, session["activeRevisionId"])

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert "content-disposition" not in response.headers
    assert not response.content.startswith((b"\xff\xd8", b"\x89PNG"))
    error = response.json()["error"]
    assert error["code"] == "encode_failed"
    assert "encoder" not in error["message"].lower()
