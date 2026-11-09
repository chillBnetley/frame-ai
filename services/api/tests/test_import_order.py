from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "statement",
    [
        "from app.styles.library import FAN_HO; print(FAN_HO.id)",
        "from app.models.photographer import PlannerMode; print(PlannerMode.AUTO.value)",
        "from app.models.recipe import EditRecipe; print(EditRecipe().schema_version)",
    ],
)
def test_model_modules_import_without_the_ai_package_first(statement: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", statement],
        cwd=API_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()


def test_lazy_package_exports_still_resolve() -> None:
    import app.ai

    assert app.ai.ProviderBundle.__name__ == "ProviderBundle"
    assert app.ai.PlannerDraft.__name__ == "PlannerDraft"
    assert app.ai.VisionRequest.__name__ == "VisionRequest"
