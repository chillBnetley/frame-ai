#!/usr/bin/env python3
"""Generate a deterministic synthetic photo with EXIF for the Phase 2 E2E flow."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

WIDTH = 480
HEIGHT = 320


def build_pixels() -> np.ndarray:
    rng = np.random.default_rng(20261102)
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


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("fixture.jpg")
    output.parent.mkdir(parents=True, exist_ok=True)

    image = Image.fromarray(build_pixels(), mode="RGB")
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
    }
    print(json.dumps(metadata, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
