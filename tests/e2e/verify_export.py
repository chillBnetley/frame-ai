#!/usr/bin/env python3
"""Validate an E2E JPEG export: decodable, correct size, no metadata, sRGB ICC."""

from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageCms


def fail(message: str) -> int:
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=True))
    return 1


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) != 4:
        return fail("usage: verify_export.py <export.jpg> <width> <height>")

    path = Path(sys.argv[1])
    expected_width = int(sys.argv[2])
    expected_height = int(sys.argv[3])
    if not path.is_file():
        return fail(f"export file not found: {path}")

    try:
        with Image.open(path) as image:
            image.load()
            if image.format != "JPEG":
                return fail(f"expected JPEG, got {image.format}")
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
    except OSError as exc:
        return fail(f"cannot decode export: {exc}")

    print(
        json.dumps(
            {
                "ok": True,
                "width": expected_width,
                "height": expected_height,
                "exif_keys": [],
                "icc_description": description,
                "bytes": path.stat().st_size,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
