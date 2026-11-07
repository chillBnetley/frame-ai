#!/usr/bin/env python3
"""Validate an E2E export: decodable, correct size, no metadata, sRGB ICC.

The optional fourth argument selects the expected output:
``jpeg`` (default), ``alpha-png``, ``alpha-jpeg`` or ``png16``.
"""

from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageCms

EXPECTED_FORMATS = {
    "jpeg": "JPEG",
    "alpha-jpeg": "JPEG",
    "alpha-png": "PNG",
    "png16": "PNG",
}


def fail(message: str) -> int:
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=True))
    return 1


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) not in (4, 5):
        return fail(
            "usage: verify_export.py <export> <width> <height> "
            "[jpeg|alpha-png|alpha-jpeg|png16]"
        )

    path = Path(sys.argv[1])
    expected_width = int(sys.argv[2])
    expected_height = int(sys.argv[3])
    expectation = sys.argv[4] if len(sys.argv) == 5 else "jpeg"
    if expectation not in EXPECTED_FORMATS:
        return fail(f"unknown expectation: {expectation}")
    if not path.is_file():
        return fail(f"export file not found: {path}")

    alpha_summary: dict[str, object] = {}
    unique_levels: int | None = None
    div257_fraction: float | None = None
    bit_depth = 16 if expectation == "png16" else 8
    try:
        with Image.open(path) as image:
            image.load()
            if image.format != EXPECTED_FORMATS[expectation]:
                return fail(f"expected {EXPECTED_FORMATS[expectation]}, got {image.format}")
            if image.size != (expected_width, expected_height):
                return fail(
                    f"expected {expected_width}x{expected_height}, got {image.width}x{image.height}"
                )
            exif = image.getexif()
            exif_keys = sorted(str(key) for key in exif.keys())
            gps = exif.get_ifd(0x8825)
            if exif_keys or gps:
                return fail(f"export still contains EXIF: {exif_keys}, GPS keys: {sorted(gps)}")
            icc = image.info.get("icc_profile")
            if not icc:
                return fail("export has no ICC profile")
            profile = ImageCms.ImageCmsProfile(BytesIO(icc))
            description = ImageCms.getProfileDescription(profile).strip()
            if "srgb" not in description.lower():
                return fail(f"ICC profile is not sRGB: {description!r}")
            mode = image.mode

            if expectation == "alpha-png":
                if mode != "RGBA":
                    return fail(f"expected RGBA PNG, got {mode}")
                alpha = np.asarray(image.getchannel("A"), dtype=np.uint8)
                if alpha.shape != (expected_height, expected_width):
                    return fail(f"alpha shape mismatch: {alpha.shape}")
                if int(alpha[0, 0]) != 0 or int(alpha[-1, -1]) != 0:
                    return fail("transparent corners were rewritten")
                center = alpha[alpha.shape[0] // 2, alpha.shape[1] // 2]
                if int(center) != 255:
                    return fail(f"opaque centre was rewritten: {int(center)}")
                transparent = float((alpha == 0).mean())
                if not 0.0 < transparent < 0.5:
                    return fail(f"alpha coverage looks wrong: {transparent:.3f} transparent")
                if len(np.unique(alpha)) < 3:
                    return fail("alpha was flattened to fewer than three levels")
                alpha_summary = {
                    "min": int(alpha.min()),
                    "max": int(alpha.max()),
                    "transparent_fraction": round(transparent, 4),
                    "levels": int(len(np.unique(alpha))),
                }
            elif expectation == "alpha-jpeg":
                if mode != "RGB":
                    return fail(f"expected RGB JPEG, got {mode}")
                pixels = np.asarray(image, dtype=np.uint8)
                corners = (
                    pixels[0, 0],
                    pixels[0, -1],
                    pixels[-1, 0],
                    pixels[-1, -1],
                )
                if not all(int(value) >= 250 for corner in corners for value in corner):
                    listed = [corner.tolist() for corner in corners]
                    return fail(f"transparent corners are not white: {listed}")
                centre = pixels[pixels.shape[0] // 2, pixels.shape[1] // 2]
                if int(centre.min()) >= 250:
                    return fail(f"opaque centre was composited to white: {centre.tolist()}")
                alpha_summary = {
                    "corner_max_channel": int(max(int(v) for c in corners for v in c)),
                    "centre": [int(v) for v in centre],
                }
            elif expectation == "png16":
                # Pillow truncates 16-bit RGB to 8-bit on load, so inspect the
                # IHDR and samples with cv2/NumPy instead.
                raw = path.read_bytes()
                if not raw.startswith(b"\x89PNG\r\n\x1a\n") or len(raw) < 26:
                    return fail("export is not a PNG")
                ihdr_depth = raw[24]
                ihdr_color_type = raw[25]
                if ihdr_depth != 16:
                    return fail(f"PNG IHDR bit depth is {ihdr_depth}, expected 16")
                if ihdr_color_type != 2:
                    return fail(
                        f"PNG IHDR colour type is {ihdr_color_type}, expected 2 (RGB)"
                    )
                samples = cv2.imdecode(
                    np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_UNCHANGED
                )
                if samples is None:
                    return fail("cv2 cannot decode the PNG")
                if samples.dtype != np.uint16:
                    return fail(f"decoded samples are {samples.dtype}, expected uint16")
                if samples.shape != (expected_height, expected_width, 3):
                    return fail(f"decoded shape mismatch: {samples.shape}")
                levels = np.unique(samples)
                div257 = float(np.mean(levels % 257 == 0))
                if levels.size <= 1000:
                    return fail(f"only {levels.size} distinct 16-bit levels")
                if div257 >= 0.5:
                    return fail(
                        f"{div257:.1%} of 16-bit levels are 8-bit multiples"
                    )
                unique_levels = int(levels.size)
                div257_fraction = round(div257, 5)
    except OSError as exc:
        return fail(f"cannot decode export: {exc}")

    print(
        json.dumps(
            {
                "ok": True,
                "mode": mode,
                "width": expected_width,
                "height": expected_height,
                "exif_keys": [],
                "icc_description": description,
                "bit_depth": bit_depth,
                "unique_levels": unique_levels,
                "div257_fraction": div257_fraction,
                "alpha": alpha_summary,
                "bytes": path.stat().st_size,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
