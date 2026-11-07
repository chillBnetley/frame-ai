from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
SOURCES_DIR = GOLDEN_DIR / "sources"
IMAGE_NAMES = ("ramp", "detail", "mixed", "alpha")
RECIPE_NAMES = (
    "neutral",
    "tone",
    "color",
    "geometry",
    "detail",
    "curve",
    "hsl",
    "grading",
    "local",
)

RECIPES: dict[str, dict[str, Any]] = {
    "neutral": {},
    "tone": {
        "adjustments": {
            "exposure_ev": 0.5,
            "contrast": 30,
            "highlights": -40,
            "shadows": 35,
        }
    },
    "color": {"adjustments": {"temperature": 30, "tint": -15, "saturation": 20, "vibrance": 45}},
    "geometry": {
        "adjustments": {
            "rotation_deg": 7.5,
            "crop": {"x": 0.1, "y": 0.08, "w": 0.72, "h": 0.78},
        }
    },
    "detail": {
        "adjustments": {
            "clarity": 40,
            "vignette": 35,
            "sharpen": 30,
            "grain": 20,
            "denoise": 25,
        }
    },
    "curve": {
        "adjustments": {"contrast": 8},
        "curve": {
            "master": [
                {"x": 0.0, "y": 0.05},
                {"x": 0.25, "y": 0.2},
                {"x": 0.75, "y": 0.85},
                {"x": 1.0, "y": 0.95},
            ],
            "red": [
                {"x": 0.0, "y": 0.0},
                {"x": 0.5, "y": 0.58},
                {"x": 1.0, "y": 1.0},
            ],
        },
    },
    "hsl": {
        "hsl": {
            "red": {"hue": 15, "saturation": 25, "luminance": 10},
            "orange": {"hue": -10, "saturation": 20, "luminance": 8},
            "green": {"hue": -20, "saturation": -30, "luminance": -10},
            "aqua": {"hue": 10, "saturation": 15, "luminance": 5},
            "blue": {"hue": 20, "saturation": 30, "luminance": -12},
            "magenta": {"hue": -15, "saturation": -20, "luminance": 6},
        },
    },
    "grading": {
        "colorGrading": {
            "shadows": {"hue": 220, "saturation": 35},
            "midtones": {"hue": 160, "saturation": 10},
            "highlights": {"hue": 45, "saturation": 40},
            "balance": 10,
            "blending": 60,
        },
    },
    "local": {
        "adjustments": {"contrast": 6},
        "masks": [
            {
                "id": "mask_warm",
                "x": 0.08,
                "y": 0.1,
                "width": 0.4,
                "height": 0.45,
                "feather": 20,
            },
            {
                "id": "mask_cool",
                "shape": "ellipse",
                "x": 0.52,
                "y": 0.45,
                "width": 0.4,
                "height": 0.45,
                "feather": 30,
                "opacity": 80,
            },
            {
                "id": "mask_invert",
                "x": 0.3,
                "y": 0.55,
                "width": 0.4,
                "height": 0.35,
                "feather": 10,
                "inverted": True,
            },
        ],
        "localAdjustments": [
            {
                "id": "local_warm",
                "maskId": "mask_warm",
                "adjustments": {
                    "exposureEv": 0.35,
                    "temperature": 25,
                    "saturation": 15,
                },
            },
            {
                "id": "local_cool",
                "maskId": "mask_cool",
                "adjustments": {
                    "exposureEv": -0.3,
                    "temperature": -20,
                    "tint": 8,
                    "clarity": 20,
                },
            },
            {
                "id": "local_shadow",
                "maskId": "mask_invert",
                "adjustments": {"shadows": 25, "vibrance": 30},
            },
        ],
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


def _alpha() -> Image.Image:
    width, height = 192, 128
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    u = x / (width - 1)
    v = y / (height - 1)
    red = 0.12 + 0.72 * u
    green = 0.10 + 0.62 * v
    blue = 0.68 - 0.42 * u + 0.18 * v
    data = np.stack([red, green, blue], axis=-1)
    pixels = np.clip(np.rint(data * 255.0), 0, 255).astype(np.uint8)

    # A smooth transparent border with semi-transparent falloff and an opaque
    # centre: corners are fully transparent, the inner 70% stays fully opaque.
    edge = np.minimum(np.minimum(x, width - 1 - x), np.minimum(y, height - 1 - y))
    falloff = np.clip(edge / (min(width, height) * 0.16), 0.0, 1.0)
    smooth = falloff * falloff * (3.0 - 2.0 * falloff)
    alpha = np.rint(smooth * 255.0).astype(np.uint8)
    rgba = np.dstack([pixels, alpha])
    return Image.fromarray(rgba, mode="RGBA")


_BUILDERS = {"ramp": _ramp, "detail": _detail, "mixed": _mixed, "alpha": _alpha}


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
