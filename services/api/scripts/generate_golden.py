from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.imaging.loader import load_image  # noqa: E402
from app.imaging.output import encode_image  # noqa: E402
from app.imaging.params_map import ENGINE_VERSION  # noqa: E402
from app.imaging.pipeline import render  # noqa: E402
from app.models.recipe import EditRecipe  # noqa: E402
from tests.golden_support import (  # noqa: E402
    GOLDEN_DIR,
    IMAGE_NAMES,
    RECIPE_NAMES,
    RECIPES,
    golden_file,
    source_bytes,
    write_sources,
)

TOLERANCE = 1


def main() -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    source_digests = write_sources()
    cases: list[dict[str, str]] = []

    for image_name in IMAGE_NAMES:
        payload = source_bytes(image_name)
        digest = sha256(payload).hexdigest()
        loaded = load_image(payload)
        for recipe_name in RECIPE_NAMES:
            recipe = EditRecipe.model_validate(RECIPES[recipe_name])
            rendered = render(
                loaded,
                recipe.adjustments,
                image_sha256=digest,
                curve=recipe.curve,
                hsl=recipe.hsl,
                color_grading=recipe.color_grading,
                masks=recipe.masks,
                local_adjustments=recipe.local_adjustments,
                quality="export",
            )
            file_name = golden_file(image_name, recipe_name)
            (GOLDEN_DIR / file_name).write_bytes(encode_image(rendered.rgb, image_format="png"))
            cases.append({"image": image_name, "recipe": recipe_name, "file": file_name})
            print(f"wrote {file_name} ({rendered.width}x{rendered.height})")

    manifest = {
        "engineVersion": ENGINE_VERSION,
        "tolerance": TOLERANCE,
        "sources": source_digests,
        "cases": cases,
    }
    (GOLDEN_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote manifest for {len(cases)} cases (engine {ENGINE_VERSION})")


if __name__ == "__main__":
    main()
