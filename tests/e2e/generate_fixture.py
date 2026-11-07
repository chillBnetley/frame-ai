#!/usr/bin/env python3
"""Generate a deterministic synthetic photo with EXIF for the Phase 2 E2E flow."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

WIDTH = 480
HEIGHT = 320


def build_pixels(variant: int = 0) -> np.ndarray:
    rng = np.random.default_rng(20261102 + variant)
    y, x = np.mgrid[0:HEIGHT, 0:WIDTH].astype(np.float32)
    red = 40.0 + 180.0 * x / (WIDTH - 1)
    green = 35.0 + 150.0 * y / (HEIGHT - 1)
    blue = 90.0 + 110.0 * (1.0 - y / (HEIGHT - 1))
    image = np.stack([red, green, blue], axis=2)
    image += rng.normal(0.0, 6.0, image.shape).astype(np.float32)

    for index in range(6):
        top = 40 + index * 38
        left = 50 + index * 58
        image[top : top + 26, left : left + 82, 0] = 230.0 - index * 18
        image[top : top + 26, left : left + 82, 1] = 60.0 + index * 22
        image[top : top + 26, left : left + 82, 2] = 45.0 + index * 12

    yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH]
    grid = ((xx % 40) < 2) | ((yy % 40) < 2)
    image[grid] *= 0.72

    return np.clip(image, 0.0, 255.0).astype(np.uint8)


def build_alpha(variant: int = 0) -> np.ndarray:
    """RGBA pixels: transparent corners, semi-transparent edges, opaque centre."""
    red, green, blue = np.moveaxis(build_pixels(variant).astype(np.float32), 2, 0)
    y, x = np.mgrid[0:HEIGHT, 0:WIDTH].astype(np.float32)
    edge = np.minimum(
        np.minimum(x, WIDTH - 1 - x),
        np.minimum(y, HEIGHT - 1 - y),
    )
    falloff = np.clip(edge / (min(WIDTH, HEIGHT) * 0.22), 0.0, 1.0)
    alpha = falloff * falloff * (3.0 - 2.0 * falloff) * 255.0
    return np.clip(
        np.rint(np.stack([red, green, blue, alpha], axis=2)),
        0,
        255,
    ).astype(np.uint8)


def build_pixels16(variant: int = 0) -> np.ndarray:
    """16-bit RGB ramp with tens of thousands of distinct levels per channel.

    CV2 writes a real 16-bit PNG; Pillow would truncate it to 8-bit.
    """
    y, x = np.mgrid[0:HEIGHT, 0:WIDTH].astype(np.float32)
    last = HEIGHT * WIDTH - 1
    index = y * WIDTH + x
    red = np.rint(65535.0 * index / last)
    green = np.rint(65535.0 * (last - index) / last)
    scrambled = np.mod(index.astype(np.int64) * 7919, last)
    blue = np.rint(65535.0 * scrambled.astype(np.float32) / last)
    image = np.stack([red, green, blue], axis=2)
    image += float(variant)
    return np.clip(image, 0.0, 65535.0).astype(np.uint16)


def _write_png16(output: Path, rgb: np.ndarray) -> None:
    bgr = np.ascontiguousarray(rgb[:, :, ::-1])
    ok, encoded = cv2.imencode(".png", bgr)
    if not ok:
        raise RuntimeError("cv2 failed to encode the 16-bit fixture PNG")
    output.write_bytes(encoded.tobytes())


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("fixture.jpg")
    variant = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    mode = sys.argv[3] if len(sys.argv) > 3 else "opaque"
    output.parent.mkdir(parents=True, exist_ok=True)

    if mode == "alpha":
        Image.fromarray(build_alpha(variant), mode="RGBA").save(output, format="PNG")
    elif mode == "sixteen":
        _write_png16(output, build_pixels16(variant))
    else:
        image = Image.fromarray(build_pixels(variant), mode="RGB")
        exif = Image.Exif()
        exif[271] = "FRAME AI"
        exif[272] = "E2E Synthetic Camera"
        exif[274] = 1
        exif[306] = "2026:11:02 12:00:00"
        image.save(output, format="JPEG", quality=92, exif=exif)

    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    metadata = {
        "path": str(output.resolve()),
        "sha256": digest,
        "width": WIDTH,
        "height": HEIGHT,
        "bytes": output.stat().st_size,
        "mode": mode,
    }
    print(json.dumps(metadata, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
