from __future__ import annotations

import json
from hashlib import sha256

import numpy as np
import pytest
from PIL import Image

from app.imaging.loader import load_image
from app.imaging.params_map import ENGINE_VERSION
from app.imaging.pipeline import render
from app.models.recipe import Adjustments
from tests.golden_support import (
    GOLDEN_DIR,
    IMAGE_NAMES,
    RECIPE_NAMES,
    RECIPES,
    SOURCES_DIR,
    golden_file,
)

MANIFEST = json.loads((GOLDEN_DIR / "manifest.json").read_text(encoding="utf-8"))
CASES = [
    (image_name, recipe_name, golden_file(image_name, recipe_name))
    for image_name in IMAGE_NAMES
    for recipe_name in RECIPE_NAMES
]


def test_manifest_records_engine_version_and_every_case():
    assert MANIFEST["engineVersion"] == ENGINE_VERSION
    assert MANIFEST["tolerance"] == 1
    assert [(case["image"], case["recipe"], case["file"]) for case in MANIFEST["cases"]] == CASES

    for image_name in IMAGE_NAMES:
        payload = (SOURCES_DIR / f"{image_name}.png").read_bytes()
        assert MANIFEST["sources"][image_name] == sha256(payload).hexdigest()


@pytest.mark.parametrize("image_name,recipe_name,file_name", CASES)
def test_golden_images_match_within_one_gray_level(
    image_name: str, recipe_name: str, file_name: str
):
    payload = (SOURCES_DIR / f"{image_name}.png").read_bytes()
    loaded = load_image(payload)
    rendered = render(
        loaded,
        Adjustments(**RECIPES[recipe_name]),
        image_sha256=sha256(payload).hexdigest(),
        quality="export",
    )

    with Image.open(GOLDEN_DIR / file_name) as golden_image:
        golden = np.asarray(golden_image.convert("RGB"), dtype=np.uint8)

    assert golden.shape == rendered.rgb.shape
    difference = np.abs(golden.astype(np.int16) - rendered.rgb.astype(np.int16))
    assert int(difference.max()) <= MANIFEST["tolerance"]
