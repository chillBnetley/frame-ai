from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
SOURCES_DIR = GOLDEN_DIR / "sources"
IMAGE_NAMES = ("ramp", "detail", "mixed")
RECIPE_NAMES = ("neutral", "tone", "color", "geometry", "detail")

RECIPES: dict[str, dict[str, Any]] = {
    "neutral": {},
    "tone": {"exposure_ev": 0.5, "contrast": 30, "highlights": -40, "shadows": 35},
    "color": {"temperature": 30, "tint": -15, "saturation": 20, "vibrance": 45},
    "geometry": {
        "rotation_deg": 7.5,
        "crop": {"x": 0.1, "y": 0.08, "w": 0.72, "h": 0.78},
    },
    "detail": {
        "clarity": 40,
        "vignette": 35,
        "sharpen": 30,
        "grain": 20,
        "denoise": 25,
    },
}


def golden_file(image_name: str, recipe_name: str) -> str:
    return f"{image_name}__{recipe_name}.png"


def _ramp() -> Image.Image:
    width, height = 192, 128
    x = np.linspace(0.0, 1.0, width, dtype=np.float32)
    y = np.linspace(0.0, 1.0, height, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)
    red = 0.05 + 0.85 * xx
    green = 0.08 + 0.75 * yy
    blue = 0.15 + 0.55 * (1.0 - xx) + 0.15 * np.sin(np.pi * 3.0 * xx) * (1.0 - yy)
    data = np.stack([red, green, blue], axis=-1)
    return Image.fromarray(np.clip(np.rint(data * 255.0), 0, 255).astype(np.uint8))


def _detail() -> Image.Image:
    width, height = 160, 200
    image = Image.new("RGB", (width, height), (36, 44, 52))
    draw = ImageDraw.Draw(image)
    for row in range(0, height, 20):
        for column in range(0, width, 20):
            if (row // 20 + column // 20) % 2 == 0:
                draw.rectangle((column, row, column + 19, row + 19), fill=(226, 218, 196))
    draw.rectangle((16, 24, 72, 80), fill=(196, 64, 48))
    draw.rectangle((88, 24, 144, 80), fill=(40, 112, 168))
    draw.ellipse((24, 108, 136, 188), fill=(150, 112, 84))
    draw.line((0, 100, width, 100), fill=(238, 238, 238), width=2)
    draw.line((80, 0, 80, height), fill=(24, 24, 24), width=2)
    return image


def _mixed() -> Image.Image:
    width, height = 180, 180
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    center_x, center_y = width / 2.0, height / 2.0
    radius = np.sqrt((x - center_x) ** 2 + (y - center_y) ** 2)
    falloff = np.clip(1.0 - radius / (width * 0.75), 0.0, 1.0)
    red = 0.12 + 0.55 * falloff
    green = 0.16 + 0.42 * falloff + 0.08 * (x / width)
    blue = 0.28 + 0.38 * (1.0 - falloff) + 0.06 * (y / height)
    data = np.stack([red, green, blue], axis=-1)
    image = Image.fromarray(np.clip(np.rint(data * 255.0), 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(image)
    draw.polygon([(18, 20), (74, 34), (42, 76)], fill=(214, 176, 132))
    draw.rectangle((108, 112, 160, 154), fill=(48, 92, 60))
    draw.line((0, 150, width, 150), fill=(232, 206, 168), width=3)
    draw.ellipse((64, 44, 116, 96), outline=(240, 240, 240), width=3)
    return image


_BUILDERS = {"ramp": _ramp, "detail": _detail, "mixed": _mixed}


def build_source(image_name: str) -> Image.Image:
    if image_name not in _BUILDERS:
        raise KeyError(f"unknown golden image: {image_name}")
    return _BUILDERS[image_name]()


def source_bytes(image_name: str) -> bytes:
    buffer = BytesIO()
    build_source(image_name).save(buffer, format="PNG")
    return buffer.getvalue()


def write_sources() -> dict[str, str]:
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    digests: dict[str, str] = {}
    for name in IMAGE_NAMES:
        payload = source_bytes(name)
        (SOURCES_DIR / f"{name}.png").write_bytes(payload)
        digests[name] = sha256(payload).hexdigest()
    return digests
