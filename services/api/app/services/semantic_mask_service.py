from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from app.core.config import Settings
from app.core.errors import AppError
from app.imaging.loader import load_proxy, proxy_cache_directory
from app.imaging.semantic_mattes import matte_id, read_matte, write_matte
from app.imaging.semantic_models import (
    SPECS,
    SemanticClass,
    SemanticModelRegistry,
)
from app.services.image_service import ImageService

logger = logging.getLogger("frame_ai.semantic")

SEMANTIC_EDGE = 1280
_UNAVAILABLE = "Semantic masks are not available."
_TIMEOUT = "Semantic mask inference did not finish in time."
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class SemanticMaskResult:
    matte_id: str
    sha256: str
    model_version: str
    semantic_class: SemanticClass
    width: int
    height: int


class SemanticMaskService:
    """Runs local segmentation once per matte id and stores the grayscale result."""

    def __init__(
        self,
        settings: Settings,
        images: ImageService,
        registry: SemanticModelRegistry,
    ) -> None:
        self.settings = settings
        self.images = images
        self.registry = registry
        self.mattes_dir: Path = settings.mattes_dir
        self._semaphore = threading.BoundedSemaphore(settings.semantic_mask_concurrency)
        self._inflight_lock = threading.Lock()
        self._inflight: dict[str, threading.Event] = {}
        self._proxy_cache_dir = proxy_cache_directory(settings.preview_dir)

    def capability(self, semantic_class: SemanticClass) -> bool:
        return (
            self.settings.feature_semantic_masks and self.registry.status(semantic_class).available
        )

    def create(self, image_id: str, semantic_class: SemanticClass) -> SemanticMaskResult:
        if not self.capability(semantic_class):
            raise AppError(503, "semantic_mask_unavailable", _UNAVAILABLE)
        spec = SPECS[semantic_class]
        record, source = self.images.get_original(image_id)
        proxy = load_proxy(
            source,
            original_sha256=record.sha256,
            max_edge=SEMANTIC_EDGE,
            cache_dir=self._proxy_cache_dir,
            max_pixels=self.settings.max_image_pixels,
        )
        edge = max(proxy.width, proxy.height)
        identifier = matte_id(
            record.sha256,
            spec.model_id,
            spec.version,
            semantic_class,
            edge,
        )
        existing = self._existing(identifier)
        if existing is not None:
            return existing
        return self._compute(identifier, record.id, record.sha256, proxy.rgb, semantic_class)

    def _existing(self, identifier: str) -> SemanticMaskResult | None:
        metadata = _read_metadata(self.mattes_dir, identifier)
        if metadata is None:
            return None
        raw_sha256 = metadata.get("rawSha256")
        model_version = metadata.get("modelVersion")
        semantic_class = metadata.get("semanticClass")
        width = metadata.get("width")
        height = metadata.get("height")
        if (
            not isinstance(raw_sha256, str)
            or _HASH_PATTERN.fullmatch(raw_sha256) is None
            or not isinstance(model_version, str)
            or model_version == ""
            or semantic_class not in ("person", "sky")
            or not isinstance(width, int)
            or not isinstance(height, int)
            or width <= 0
            or height <= 0
        ):
            return None
        raw = read_matte(self.mattes_dir, identifier, raw_sha256)
        if raw is None:
            return None
        if (width, height) != (raw.shape[1], raw.shape[0]):
            return None
        return SemanticMaskResult(
            matte_id=identifier,
            sha256=raw_sha256,
            model_version=model_version,
            semantic_class=semantic_class,
            width=width,
            height=height,
        )

    def _compute(
        self,
        identifier: str,
        image_id: str,
        image_sha256: str,
        rgb: NDArray[np.float32],
        semantic_class: SemanticClass,
    ) -> SemanticMaskResult:
        with self._inflight_lock:
            event = self._inflight.get(identifier)
            owner = event is None
            if owner:
                event = threading.Event()
                self._inflight[identifier] = event
        if not owner:
            assert event is not None
            if not event.wait(self.settings.semantic_mask_timeout_seconds):
                raise AppError(504, "semantic_mask_timeout", _TIMEOUT)
            existing = self._existing(identifier)
            if existing is not None:
                return existing
            raise AppError(503, "semantic_mask_unavailable", _UNAVAILABLE)

        started = time.monotonic()
        acquired = self._semaphore.acquire(timeout=self.settings.semantic_mask_timeout_seconds)
        if not acquired:
            self._finish(identifier)
            raise AppError(504, "semantic_mask_timeout", _TIMEOUT)
        try:
            raw = self.registry.infer(semantic_class, rgb)
            if raw is None:
                raise AppError(503, "semantic_mask_unavailable", _UNAVAILABLE)
            elapsed = time.monotonic() - started
            if elapsed > self.settings.semantic_mask_timeout_seconds:
                raise AppError(504, "semantic_mask_timeout", _TIMEOUT)
            raw_sha256 = hashlib.sha256(raw.tobytes()).hexdigest()
            spec = SPECS[semantic_class]
            metadata = {
                "imageSha256": image_sha256,
                "matteId": identifier,
                "rawSha256": raw_sha256,
                "modelId": spec.model_id,
                "modelVersion": spec.version,
                "semanticClass": semantic_class,
            }
            write_matte(self.mattes_dir, identifier, raw, metadata)
        except AppError:
            raise
        except OSError as exc:
            logger.warning(
                "semantic_matte_write_failed image_id=%s matte_id=%s error_type=%s",
                image_id,
                identifier,
                type(exc).__name__,
            )
            raise AppError(503, "semantic_mask_unavailable", _UNAVAILABLE) from None
        finally:
            self._semaphore.release()
            self._finish(identifier)
        logger.info(
            "semantic_matte image_id=%s matte_id=%s class=%s latency_ms=%.1f outcome=ok",
            image_id,
            identifier,
            semantic_class,
            elapsed * 1000.0,
        )
        return SemanticMaskResult(
            matte_id=identifier,
            sha256=raw_sha256,
            model_version=spec.version,
            semantic_class=semantic_class,
            width=int(raw.shape[1]),
            height=int(raw.shape[0]),
        )

    def _finish(self, identifier: str) -> None:
        with self._inflight_lock:
            event = self._inflight.pop(identifier, None)
        if event is not None:
            event.set()


def _read_metadata(root: Path, identifier: str) -> dict[str, object] | None:
    try:
        payload = json.loads((root / f"{identifier}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


__all__ = ["SEMANTIC_EDGE", "SemanticMaskResult", "SemanticMaskService"]
