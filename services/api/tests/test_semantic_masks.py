from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.core.config import Settings
from app.imaging import semantic_models
from app.imaging.geometry import crop_bounds, rotation_matrix, rotation_target_size
from app.imaging.loader import load_image
from app.imaging.local_masks import (
    _cache_key,
    apply_local_adjustments,
    configure_semantic_mattes,
)
from app.imaging.pipeline import render
from app.imaging.semantic_mattes import (
    matte_id,
    purge_mattes_for_image,
    read_matte,
    write_matte,
)
from app.imaging.semantic_models import (
    PERSON_SPEC,
    SemanticModelRegistry,
    ascii_cache_root,
    file_matches,
)
from app.models.recipe import (
    Crop,
    EditRecipe,
    LocalAdjustment,
    LocalAdjustments,
    UserMask,
    canonical_recipe_json,
    recipe_hash,
    render_key,
)
from app.services.semantic_mask_service import SemanticMaskService
from tests.conftest import make_image, upload
from tests.golden_support import SOURCES_DIR

WIDTH = 48
HEIGHT = 32
IMAGE_SHA = "a" * 64


def _write_semantic_matte(
    root: Path,
    *,
    image_sha: str = IMAGE_SHA,
    semantic_class: str = "person",
    width: int = WIDTH,
    height: int = HEIGHT,
    model_version: str = "1",
) -> tuple[str, str, np.ndarray]:
    raw = np.zeros((height, width), dtype=np.uint8)
    raw[:, : width // 2] = 255
    raw_sha = hashlib.sha256(raw.tobytes()).hexdigest()
    identifier = matte_id(
        image_sha,
        "mediapipe-selfie-segmentation",
        model_version,
        semantic_class,
        max(width, height),
    )
    write_matte(
        root,
        identifier,
        raw,
        {
            "imageSha256": image_sha,
            "matteId": identifier,
            "rawSha256": raw_sha,
            "modelId": "mediapipe-selfie-segmentation",
            "modelVersion": model_version,
            "semanticClass": semantic_class,
        },
    )
    return identifier, raw_sha, raw


def _semantic_mask(
    identifier: str,
    raw_sha: str,
    *,
    opacity: float = 100.0,
    inverted: bool = False,
) -> UserMask:
    return UserMask.model_validate(
        {
            "id": "mask_semantic",
            "shape": "semantic",
            "source": "semantic",
            "semanticClass": "person",
            "matteId": identifier,
            "matteSha256": raw_sha,
            "modelVersion": "1",
            "x": 0,
            "y": 0,
            "width": 1,
            "height": 1,
            "opacity": opacity,
            "inverted": inverted,
        }
    )


def _local(mask_id: str = "mask_semantic") -> LocalAdjustment:
    return LocalAdjustment(
        id="local_semantic",
        mask_id=mask_id,
        adjustments=LocalAdjustments(exposure_ev=1.0),
    )


def test_bundled_person_model_loads_from_the_ascii_cache():
    registry = SemanticModelRegistry(Path("unused"))

    status = registry.status("person")

    assert status.available is True
    assert status.version == "1"
    net = registry.load("person")
    assert net is not None
    target = registry._prepare_ascii("person", PERSON_SPEC)
    assert target is not None
    assert os.fspath(target).isascii()
    assert (
        target
        == ascii_cache_root(Path("unused")) / PERSON_SPEC.sha256 / "selfie_segmentation.tflite"
    )
    assert file_matches(target, PERSON_SPEC.bytes, PERSON_SPEC.sha256)


def test_missing_or_tampered_models_are_reported_unavailable(tmp_path: Path):
    registry = SemanticModelRegistry(tmp_path)
    assert registry.status("sky").available is False

    tampered = tmp_path / "tampered.tflite"
    tampered.write_bytes(b"not the model")
    assert file_matches(tampered, PERSON_SPEC.bytes, PERSON_SPEC.sha256) is False


def test_person_inference_is_deterministic():
    registry = SemanticModelRegistry(Path("unused"))
    rgb = np.linspace(0.1, 0.9, HEIGHT * WIDTH * 3, dtype=np.float32).reshape(HEIGHT, WIDTH, 3)

    first = registry.infer("person", rgb)
    second = registry.infer("person", rgb)

    assert first is not None and second is not None
    assert first.dtype == np.uint8 and first.shape == (HEIGHT, WIDTH)
    assert (
        hashlib.sha256(first.tobytes()).hexdigest() == hashlib.sha256(second.tobytes()).hexdigest()
    )


def test_matte_store_verifies_raw_hash_dimensions_and_purges(tmp_path: Path):
    identifier, raw_sha, raw = _write_semantic_matte(tmp_path)

    loaded = read_matte(tmp_path, identifier, raw_sha)
    assert loaded is not None
    assert np.array_equal(loaded, raw)
    assert read_matte(tmp_path, identifier, "b" * 64) is None

    sidecar = tmp_path / f"{identifier}.json"
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    metadata["width"] = raw.shape[1] + 1
    sidecar.write_text(json.dumps(metadata), encoding="utf-8")
    assert read_matte(tmp_path, identifier, raw_sha) is None

    assert purge_mattes_for_image(tmp_path, IMAGE_SHA) == 2
    assert not (tmp_path / f"{identifier}.png").exists()
    assert not sidecar.exists()


def _base_rgb() -> np.ndarray:
    return np.full((HEIGHT, WIDTH, 3), 0.3, dtype=np.float32)


def _apply(mask: UserMask) -> tuple[np.ndarray, tuple[str, ...]]:
    return apply_local_adjustments(
        _base_rgb(),
        (_local(mask.id),),
        (mask,),
        source_width=WIDTH,
        source_height=HEIGHT,
        rotation_deg=0.0,
        crop=None,
    )


def test_semantic_matte_drives_the_mask_weight_and_opacity(tmp_path: Path):
    configure_semantic_mattes(tmp_path)
    identifier, raw_sha, _ = _write_semantic_matte(tmp_path)
    base = _base_rgb()

    result, warnings = _apply(_semantic_mask(identifier, raw_sha))
    assert warnings == ()
    assert not np.array_equal(result[:, 5], base[:, 5])
    np.testing.assert_array_equal(result[:, -5], base[:, -5])

    half, _ = _apply(_semantic_mask(identifier, raw_sha, opacity=50))
    np.testing.assert_allclose(half[:, 5], (base[:, 5] + result[:, 5]) / 2.0, atol=1e-6)

    inverted, _ = _apply(_semantic_mask(identifier, raw_sha, inverted=True))
    np.testing.assert_allclose(inverted[:, 5], base[:, 5], atol=1e-6)
    assert not np.array_equal(inverted[:, -5], base[:, -5])


def test_missing_or_tampered_matte_is_skipped_with_a_warning(tmp_path: Path):
    configure_semantic_mattes(tmp_path)
    identifier, raw_sha, _ = _write_semantic_matte(tmp_path)
    (tmp_path / f"{identifier}.png").unlink()

    result, warnings = _apply(_semantic_mask(identifier, raw_sha))

    np.testing.assert_array_equal(result, _base_rgb())
    assert f"local_matte_missing:{identifier}" in warnings


def test_semantic_weights_follow_rotation_and_crop(tmp_path: Path):
    configure_semantic_mattes(tmp_path)
    identifier, raw_sha, _ = _write_semantic_matte(tmp_path)
    mask = _semantic_mask(identifier, raw_sha)

    target_width, target_height = rotation_target_size(WIDTH, HEIGHT, 90.0)
    rotated_rgb = np.full((target_height, target_width, 3), 0.3, dtype=np.float32)
    rotated, _ = apply_local_adjustments(
        rotated_rgb,
        (_local(mask.id),),
        (mask,),
        source_width=WIDTH,
        source_height=HEIGHT,
        rotation_deg=90.0,
        crop=None,
    )
    assert rotated.shape == rotated_rgb.shape
    matrix = rotation_matrix(WIDTH, HEIGHT, 90.0, target_width, target_height)
    inverse = np.asarray(cv2.invertAffineTransform(matrix), dtype=np.float64)

    def expected_affected(column: int, row: int) -> bool:
        source_x = inverse[0, 0] * column + inverse[0, 1] * row + inverse[0, 2]
        source_y = inverse[1, 0] * column + inverse[1, 1] * row + inverse[1, 2]
        px = (source_x + 0.5) / WIDTH
        py = (source_y + 0.5) / HEIGHT
        return 0.0 <= px <= 1.0 and 0.0 <= py <= 1.0 and px < 0.5

    for column, row in (
        (2, 2),
        (target_width - 3, 2),
        (2, target_height - 3),
        (target_width - 3, target_height - 3),
    ):
        changed = not np.array_equal(rotated[row, column], rotated_rgb[row, column])
        assert changed == bool(expected_affected(column, row))

    left_crop = Crop(x=0.05, y=0.05, w=0.4, h=0.4)
    x0, y0, x1, y1 = crop_bounds(left_crop, WIDTH, HEIGHT)
    left_rgb = np.full((y1 - y0, x1 - x0, 3), 0.3, dtype=np.float32)
    left, _ = apply_local_adjustments(
        left_rgb,
        (_local(mask.id),),
        (mask,),
        source_width=WIDTH,
        source_height=HEIGHT,
        rotation_deg=0.0,
        crop=left_crop,
    )
    assert not np.array_equal(left, left_rgb)

    right_crop = Crop(x=0.55, y=0.05, w=0.4, h=0.4)
    x0, y0, x1, y1 = crop_bounds(right_crop, WIDTH, HEIGHT)
    right_rgb = np.full((y1 - y0, x1 - x0, 3), 0.3, dtype=np.float32)
    right, _ = apply_local_adjustments(
        right_rgb,
        (_local(mask.id),),
        (mask,),
        source_width=WIDTH,
        source_height=HEIGHT,
        rotation_deg=0.0,
        crop=right_crop,
    )
    np.testing.assert_array_equal(right, right_rgb)


def test_semantic_cache_key_includes_matte_identity(tmp_path: Path):
    configure_semantic_mattes(tmp_path)
    identifier, raw_sha, _ = _write_semantic_matte(tmp_path)
    mask = _semantic_mask(identifier, raw_sha)
    other = mask.model_copy(update={"matte_sha256": "b" * 64})

    first = _cache_key(
        mask,
        output_width=WIDTH,
        output_height=HEIGHT,
        source_width=WIDTH,
        source_height=HEIGHT,
        rotation_deg=0.0,
        crop=None,
    )
    second = _cache_key(
        other,
        output_width=WIDTH,
        output_height=HEIGHT,
        source_width=WIDTH,
        source_height=HEIGHT,
        rotation_deg=0.0,
        crop=None,
    )

    assert first != second
    assert raw_sha in first
    assert "person" in first


def test_semantic_masks_do_not_touch_alpha(tmp_path: Path):
    payload = (SOURCES_DIR / "alpha.png").read_bytes()
    loaded = load_image(payload)
    assert loaded.alpha is not None
    matte_root = tmp_path / "mattes"
    raw = np.full((loaded.height, loaded.width), 128, dtype=np.uint8)
    raw_sha = hashlib.sha256(raw.tobytes()).hexdigest()
    identifier = matte_id(
        hashlib.sha256(payload).hexdigest(),
        "mediapipe-selfie-segmentation",
        "1",
        "person",
        max(loaded.width, loaded.height),
    )
    write_matte(
        matte_root,
        identifier,
        raw,
        {
            "imageSha256": hashlib.sha256(payload).hexdigest(),
            "rawSha256": raw_sha,
            "modelVersion": "1",
            "semanticClass": "person",
        },
    )
    configure_semantic_mattes(matte_root)
    base = render(
        loaded,
        EditRecipe().adjustments,
        image_sha256=hashlib.sha256(payload).hexdigest(),
        quality="export",
    )
    layered = render(
        loaded,
        EditRecipe().adjustments,
        image_sha256=hashlib.sha256(payload).hexdigest(),
        masks=(_semantic_mask(identifier, raw_sha),),
        local_adjustments=(_local(),),
        quality="export",
    )

    assert layered.alpha is not None and base.alpha is not None
    assert np.array_equal(layered.alpha, base.alpha)
    assert not np.array_equal(layered.rgb, base.rgb)


def test_semantic_fields_are_identity_but_manual_masks_stay_unchanged(tmp_path: Path):
    identifier, raw_sha, _ = _write_semantic_matte(tmp_path)
    semantic = EditRecipe(masks=(_semantic_mask(identifier, raw_sha),))
    renamed = EditRecipe(
        masks=(_semantic_mask(identifier, raw_sha).model_copy(update={"opacity": 50.0}),)
    )

    assert recipe_hash(semantic) != recipe_hash(renamed)
    assert "semantic_class" in canonical_recipe_json(semantic)
    assert "source" in canonical_recipe_json(semantic)
    assert render_key("a" * 64, semantic, edge=800, quality="draft", engine_version="e") != (
        render_key("a" * 64, renamed, edge=800, quality="draft", engine_version="e")
    )


class _SlowRegistry:
    def __init__(self) -> None:
        self.calls = 0
        self.lock = threading.Lock()

    def infer(self, kind: str, rgb: np.ndarray) -> np.ndarray:
        with self.lock:
            self.calls += 1
        threading.Event().wait(0.1)
        return np.full(rgb.shape[:2], 128, dtype=np.uint8)


def _service(tmp_path: Path, registry: object) -> SemanticMaskService:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        feature_semantic_masks=True,
    )
    return SemanticMaskService(settings, object(), registry)  # type: ignore[arg-type]


def test_single_flight_runs_inference_once_for_the_same_matte(tmp_path: Path):
    registry = _SlowRegistry()
    service = _service(tmp_path, registry)
    rgb = _base_rgb()
    results: list[object] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            results.append(service._compute("f" * 64, "image", IMAGE_SHA, rgb, "person"))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert registry.calls == 1
    assert len(results) == 2
    assert results[0] == results[1]


def test_semantic_endpoint_is_gated_by_the_feature_flag(tmp_path: Path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        allowed_origins="http://testserver",
        allowed_hosts="testserver",
        feature_semantic_masks=False,
    )
    with TestClient(create_app(settings)) as client:
        image = upload(client, make_image("PNG", (64, 48), (120, 80, 40)))
        response = client.post(
            f"/api/v1/images/{image.json()['imageId']}/semantic-masks",
            json={"semanticClass": "person"},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "semantic_mask_unavailable"


def test_semantic_endpoint_returns_reuses_and_cleans_up_mattes(tmp_path: Path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        allowed_origins="http://testserver",
        allowed_hosts="testserver",
        feature_semantic_masks=True,
    )
    with TestClient(create_app(settings)) as client:
        image = upload(client, make_image("PNG", (64, 48), (120, 80, 40)))
        image_id = image.json()["imageId"]
        first = client.post(
            f"/api/v1/images/{image_id}/semantic-masks",
            json={"semanticClass": "person"},
        )
        assert first.status_code == 201, first.text
        body = first.json()
        assert body["semanticClass"] == "person"
        assert body["modelVersion"] == "1"
        raw = read_matte(settings.mattes_dir, body["matteId"], body["sha256"])
        assert raw is not None
        assert raw.shape == (body["height"], body["width"])
        path = settings.mattes_dir / f"{body['matteId']}.png"
        assert path.is_file()

        second = client.post(
            f"/api/v1/images/{image_id}/semantic-masks",
            json={"semanticClass": "person"},
        )
        assert second.status_code == 201
        assert second.json()["matteId"] == body["matteId"]

        sky = client.post(
            f"/api/v1/images/{image_id}/semantic-masks",
            json={"semanticClass": "sky"},
        )
        assert sky.status_code == 503
        assert sky.json()["error"]["code"] == "semantic_mask_unavailable"

        assert client.delete(f"/api/v1/images/{image_id}").status_code == 204
        assert not path.exists()


class _NoSemaphore:
    def acquire(self, timeout: float) -> bool:
        return False

    def release(self) -> None:
        return None


def test_semaphore_timeout_maps_to_a_504(tmp_path: Path):
    from app.core.errors import AppError

    service = _service(tmp_path, _SlowRegistry())
    service._semaphore = _NoSemaphore()  # type: ignore[assignment]

    with pytest.raises(AppError) as error:
        service._compute("f" * 64, "image", IMAGE_SHA, _base_rgb(), "person")

    assert error.value.status_code == 504
    assert error.value.code == "semantic_mask_timeout"


def test_malformed_sidecar_is_recomputed_without_a_server_error(tmp_path: Path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        allowed_origins="http://testserver",
        allowed_hosts="testserver",
        feature_semantic_masks=True,
    )
    with TestClient(create_app(settings)) as client:
        image = upload(client, make_image("PNG", (64, 48), (120, 80, 40)))
        image_id = image.json()["imageId"]
        first = client.post(
            f"/api/v1/images/{image_id}/semantic-masks",
            json={"semanticClass": "person"},
        )
        assert first.status_code == 201
        identifier = first.json()["matteId"]
        sidecar = settings.mattes_dir / f"{identifier}.json"

        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        metadata.pop("modelVersion")
        sidecar.write_text(json.dumps(metadata), encoding="utf-8")
        missing_version = client.post(
            f"/api/v1/images/{image_id}/semantic-masks",
            json={"semanticClass": "person"},
        )
        assert missing_version.status_code == 201, missing_version.text

        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        metadata["semanticClass"] = "bogus"
        sidecar.write_text(json.dumps(metadata), encoding="utf-8")
        invalid_class = client.post(
            f"/api/v1/images/{image_id}/semantic-masks",
            json={"semanticClass": "person"},
        )
        assert invalid_class.status_code == 201, invalid_class.text


def test_purge_keeps_the_sidecar_when_the_png_cannot_be_deleted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    identifier, _, _ = _write_semantic_matte(tmp_path)
    png = tmp_path / f"{identifier}.png"
    sidecar = tmp_path / f"{identifier}.json"
    real_unlink = Path.unlink

    def broken(self: Path, *args: object, **kwargs: object) -> None:
        if self == png:
            raise OSError("matte locked")
        real_unlink(self, *args, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(Path, "unlink", broken)
        assert purge_mattes_for_image(tmp_path, IMAGE_SHA) == 0

    assert png.exists()
    assert sidecar.exists()
    assert purge_mattes_for_image(tmp_path, IMAGE_SHA) == 2
    assert not png.exists()
    assert not sidecar.exists()


class _SlowRaisingRegistry:
    def infer(self, kind: str, rgb: np.ndarray) -> np.ndarray:
        threading.Event().wait(0.1)
        raise RuntimeError("inference failed")


def test_waiter_returns_503_when_the_owner_inference_raises(tmp_path: Path):
    from app.core.errors import AppError

    service = _service(tmp_path, _SlowRaisingRegistry())
    errors: list[BaseException] = []
    identifier = "f" * 64

    def owner() -> None:
        try:
            service._compute(identifier, "image", IMAGE_SHA, _base_rgb(), "person")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=owner)
    thread.start()
    deadline = time.monotonic() + 2.0
    while identifier not in service._inflight:
        if time.monotonic() > deadline:
            pytest.fail("the owner thread did not start inference in time")
        threading.Event().wait(0.01)
    with pytest.raises(AppError) as error:
        service._compute(identifier, "image", IMAGE_SHA, _base_rgb(), "person")
    thread.join(timeout=10)

    assert len(errors) == 1
    assert error.value.status_code == 503
    assert service._inflight == {}


class _SlowButSuccessfulRegistry:
    def infer(self, kind: str, rgb: np.ndarray) -> np.ndarray:
        threading.Event().wait(0.15)
        return np.full(rgb.shape[:2], 128, dtype=np.uint8)


def test_elapsed_timeout_returns_504_without_writing_a_matte(tmp_path: Path):
    from app.core.errors import AppError

    service = _service(tmp_path, _SlowButSuccessfulRegistry())
    service.settings.semantic_mask_timeout_seconds = 0.05

    with pytest.raises(AppError) as error:
        service._compute("f" * 64, "image", IMAGE_SHA, _base_rgb(), "person")

    assert error.value.status_code == 504
    assert error.value.code == "semantic_mask_timeout"
    assert list(service.mattes_dir.glob("*")) == []


def test_waiter_timeout_returns_504(tmp_path: Path):
    from app.core.errors import AppError

    service = _service(tmp_path, _SlowRegistry())
    service.settings.semantic_mask_timeout_seconds = 0.02
    service._inflight["f" * 64] = threading.Event()

    with pytest.raises(AppError) as error:
        service._compute("f" * 64, "image", IMAGE_SHA, _base_rgb(), "person")

    assert error.value.status_code == 504
    assert error.value.code == "semantic_mask_timeout"


def test_unwritable_model_cache_disables_the_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from fastapi.testclient import TestClient

    from app.main import create_app

    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(
        semantic_models,
        "ascii_cache_root",
        lambda data_dir: blocker / "models",
    )
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        allowed_origins="http://testserver",
        allowed_hosts="testserver",
        feature_semantic_masks=True,
    )
    with TestClient(create_app(settings)) as client:
        config = client.get("/api/v1/config").json()
        assert config["features"]["semanticMasks"] == {
            "enabled": True,
            "person": False,
            "sky": False,
        }
        image = upload(client, make_image("PNG", (64, 48), (120, 80, 40)))
        response = client.post(
            f"/api/v1/images/{image.json()['imageId']}/semantic-masks",
            json={"semanticClass": "person"},
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "semantic_mask_unavailable"


def test_posix_non_ascii_paths_fall_back_to_ascii_cache(tmp_path: Path):
    non_ascii = tmp_path / "中文数据"
    home_ascii = Path("C:/Users/Public/frame-b8-home")
    xdg_ascii = Path("C:/Users/Public/frame-b8-posix-cache")
    expected_home = home_ascii / ".cache" / "frame-ai" / "models"

    assert semantic_models._posix_ascii_cache_root(non_ascii, str(xdg_ascii), home_ascii) == (
        xdg_ascii / "frame-ai" / "models"
    )
    # A non-ASCII XDG path must fall through to an ASCII home cache.
    assert (
        semantic_models._posix_ascii_cache_root(non_ascii, str(tmp_path / "中文缓存"), home_ascii)
        == expected_home
    )
    # No XDG set uses the home cache.
    assert semantic_models._posix_ascii_cache_root(non_ascii, None, home_ascii) == expected_home
    # XDG and home are both non-ASCII: the final /tmp candidate is used.
    assert semantic_models._posix_ascii_cache_root(
        non_ascii,
        str(tmp_path / "中文缓存"),
        tmp_path / "中文home",
    ) == Path("/tmp/frame-ai-models")


def test_semantic_mask_combines_with_b7_layer_blending(tmp_path: Path):
    configure_semantic_mattes(tmp_path)
    identifier, raw_sha, _ = _write_semantic_matte(tmp_path)
    semantic = UserMask.model_validate(
        {
            "id": "mask_semantic",
            "shape": "semantic",
            "source": "semantic",
            "semanticClass": "person",
            "matteId": identifier,
            "matteSha256": raw_sha,
            "modelVersion": "1",
            "x": 0,
            "y": 0,
            "width": 1,
            "height": 1,
        }
    )
    semantic_layer = LocalAdjustment(
        id="local_semantic",
        mask_id=semantic.id,
        order=0,
        blendMode="multiply",
        opacity=60,
        adjustments=LocalAdjustments(exposure_ev=1.0),
    )
    full_layer = LocalAdjustment(
        id="local_full",
        mask_id="full",
        order=1,
        blendMode="screen",
        opacity=80,
        adjustments=LocalAdjustments(contrast=20.0),
    )

    forward, warnings = apply_local_adjustments(
        _base_rgb(),
        (semantic_layer, full_layer),
        (semantic,),
        source_width=WIDTH,
        source_height=HEIGHT,
        rotation_deg=0.0,
        crop=None,
    )
    reverse, _ = apply_local_adjustments(
        _base_rgb(),
        (
            full_layer.model_copy(update={"order": 0}),
            semantic_layer.model_copy(update={"order": 1}),
        ),
        (semantic,),
        source_width=WIDTH,
        source_height=HEIGHT,
        rotation_deg=0.0,
        crop=None,
    )

    assert warnings == ()
    assert not np.array_equal(forward, reverse)
    assert forward.dtype == np.float32
    assert np.isfinite(forward).all()
