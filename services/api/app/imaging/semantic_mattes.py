from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from app.imaging.semantic_models import PREPROCESS_VERSION

logger = logging.getLogger("frame_ai.semantic")

MATTE_PREPROCESS_VERSION = PREPROCESS_VERSION


def matte_id(
    image_sha256: str,
    model_id: str,
    model_version: str,
    semantic_class: str,
    edge: int,
    preprocess_version: str = MATTE_PREPROCESS_VERSION,
) -> str:
    parts = (
        image_sha256.lower(),
        model_id,
        model_version,
        semantic_class,
        str(int(edge)),
        preprocess_version,
    )
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def write_matte(
    root: Path,
    identifier: str,
    raw: NDArray[np.uint8],
    metadata: dict[str, Any],
) -> Path:
    """Atomically write the grayscale PNG and its sidecar metadata."""

    root.mkdir(parents=True, exist_ok=True)
    array = np.ascontiguousarray(raw, dtype=np.uint8)
    success, encoded = cv2.imencode(".png", array)
    if not success:
        raise OSError("the semantic matte could not be encoded")
    path = root / f"{identifier}.png"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(encoded.tobytes())
    os.replace(temporary, path)
    sidecar = root / f"{identifier}.json"
    side_temporary = sidecar.with_name(sidecar.name + ".tmp")
    side_temporary.write_text(
        json.dumps({**metadata, "width": int(array.shape[1]), "height": int(array.shape[0])}),
        encoding="utf-8",
    )
    os.replace(side_temporary, sidecar)
    return path


def read_matte(
    root: Path | None,
    identifier: str,
    expected_sha256: str,
) -> NDArray[np.uint8] | None:
    """Load a matte after verifying its raw-pixel SHA-256 and sidecar size."""

    if root is None:
        return None
    path = root / f"{identifier}.png"
    try:
        payload = path.read_bytes()
    except OSError:
        return None
    decoded = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if decoded is None or decoded.dtype != np.uint8 or decoded.ndim != 2:
        return None
    raw = np.ascontiguousarray(decoded, dtype=np.uint8)
    if hashlib.sha256(raw.tobytes()).hexdigest() != expected_sha256:
        return None
    sidecar = root / f"{identifier}.json"
    try:
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        metadata = None
    if isinstance(metadata, dict):
        width = metadata.get("width")
        height = metadata.get("height")
        if (
            isinstance(width, int)
            and isinstance(height, int)
            and (width, height) != (raw.shape[1], raw.shape[0])
        ):
            return None
    return raw


def purge_mattes_for_image(root: Path, image_sha256: str) -> int:
    if not root.is_dir():
        return 0
    removed = 0
    for sidecar in root.glob("*.json"):
        try:
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(metadata, dict) or metadata.get("imageSha256") != image_sha256:
            continue
        png = sidecar.with_suffix(".png")
        try:
            png.unlink(missing_ok=True)
        except OSError:
            # Keep the sidecar so a later sweep can retry the orphaned matte.
            logger.warning("semantic_matte_delete_failed matte_id=%s", sidecar.stem)
            continue
        removed += 1
        try:
            sidecar.unlink(missing_ok=True)
            removed += 1
        except OSError:
            logger.warning("semantic_matte_delete_failed matte_id=%s", sidecar.stem)
    return removed


__all__ = [
    "MATTE_PREPROCESS_VERSION",
    "matte_id",
    "purge_mattes_for_image",
    "read_matte",
    "write_matte",
]
