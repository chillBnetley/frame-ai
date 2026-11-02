from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from app.models.recipe import (
    STYLE_IDS,
    Adjustments,
    Crop,
    EditRecipe,
    canonical_adjustments_json,
    canonical_recipe_json,
    default_recipe,
    recipe_hash,
    render_key,
)

NUMERIC_BOUNDS = {
    "exposure_ev": ("exposureEv", -3.0, 3.0),
    "contrast": ("contrast", -100.0, 100.0),
    "highlights": ("highlights", -100.0, 100.0),
    "shadows": ("shadows", -100.0, 100.0),
    "temperature": ("temperature", -100.0, 100.0),
    "tint": ("tint", -100.0, 100.0),
    "saturation": ("saturation", -100.0, 100.0),
    "vibrance": ("vibrance", -100.0, 100.0),
    "clarity": ("clarity", -100.0, 100.0),
    "sharpen": ("sharpen", 0.0, 100.0),
    "denoise": ("denoise", 0.0, 100.0),
    "vignette": ("vignette", -100.0, 100.0),
    "grain": ("grain", 0.0, 100.0),
    "rotation_deg": ("rotationDeg", -15.0, 15.0),
}


def _error_fields(exc_info: pytest.ExceptionInfo[ValidationError]) -> list[str]:
    return [".".join(str(part) for part in error["loc"]) for error in exc_info.value.errors()]


def _recipe_client(tmp_path) -> TestClient:
    settings = Settings(
        data_dir=tmp_path / "data",
        max_upload_bytes=1024 * 1024,
        max_image_pixels=1_000_000,
        allowed_origins="http://testserver",
        log_level="WARNING",
    )
    app = create_app(settings)

    @app.post("/test/recipe")
    def validate_recipe(recipe: EditRecipe) -> dict[str, object]:
        return recipe.model_dump(mode="json", by_alias=True)

    return TestClient(app)


def test_empty_recipe_matches_default_recipe():
    empty = EditRecipe.model_validate({})
    adjustments_only = EditRecipe.model_validate({"adjustments": {}})

    assert empty == adjustments_only == default_recipe()
    assert empty.schema_version == "1.0"
    assert empty.style_id == "natural"
    assert empty.style_strength == 0.0
    assert empty.adjustments == Adjustments()
    assert empty.rationale == []
    assert empty.warnings == []


def test_numeric_bounds_are_inclusive():
    for name, (alias, low, high) in NUMERIC_BOUNDS.items():
        for value in (low, high):
            adjustments = Adjustments.model_validate({alias: value})
            assert getattr(adjustments, name) == value


def test_numeric_out_of_bounds_are_rejected():
    for alias, low, high in NUMERIC_BOUNDS.values():
        for value in (low - 0.01, high + 0.01):
            with pytest.raises(ValidationError) as exc_info:
                Adjustments.model_validate({alias: value})
            assert alias in _error_fields(exc_info)


@pytest.mark.parametrize("value", [0.123, 0.001, 0.30000000000000004])
def test_more_than_two_decimals_are_rejected(value: float):
    with pytest.raises(ValidationError) as exc_info:
        Adjustments.model_validate({"contrast": value})

    assert "contrast" in _error_fields(exc_info)


@pytest.mark.parametrize("value", [0.25, 3.0, 100.0, -0.5])
def test_values_with_at_most_two_decimals_are_accepted(value: float):
    assert Adjustments.model_validate({"contrast": value})


def test_number_types_are_strict():
    invalid_values: list[object] = [True, "1", None, [], {}]
    for alias, _, _ in NUMERIC_BOUNDS.values():
        for value in invalid_values:
            with pytest.raises(ValidationError):
                Adjustments.model_validate({alias: value})


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_numbers_are_rejected_by_model(value: str):
    with pytest.raises(ValidationError):
        Adjustments.model_validate({"contrast": float(value)})


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_json_is_rejected_with_422(tmp_path, value: str):
    with _recipe_client(tmp_path) as client:
        response = client.post(
            "/test/recipe",
            content=f'{{"adjustments":{{"contrast":{value}}}}}',
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 422
    field = response.json()["error"]["details"]["fields"][0]
    assert field["field"] == "adjustments.contrast"
    assert "input" not in field


@pytest.mark.parametrize("style_id", STYLE_IDS)
def test_supported_styles_are_accepted(style_id: str):
    assert EditRecipe.model_validate({"styleId": style_id}).style_id == style_id


@pytest.mark.parametrize("style_id", ["Film", "sepia", ""])
def test_unknown_styles_are_rejected(style_id: str):
    with pytest.raises(ValidationError):
        EditRecipe.model_validate({"styleId": style_id})


@pytest.mark.parametrize("value", [-0.01, 100.01])
def test_style_strength_bounds_are_enforced(value: float):
    with pytest.raises(ValidationError):
        EditRecipe.model_validate({"styleStrength": value})


@pytest.mark.parametrize("value", [0.0, 100.0])
def test_style_strength_bounds_are_inclusive(value: float):
    assert EditRecipe.model_validate({"styleStrength": value}).style_strength == value


def test_crop_inside_frame_rules():
    assert Crop.model_validate({"x": 0.04, "y": 0.0, "w": 0.96, "h": 1.0})
    assert Adjustments.model_validate({"crop": None}).crop is None

    for crop in (
        {"x": 0.04, "y": 0.0, "w": 0.97, "h": 1.0},
        {"x": 0.0, "y": 0.04, "w": 1.0, "h": 0.97},
        {"x": -0.01, "y": 0.0, "w": 0.5, "h": 0.5},
        {"x": 0.0, "y": -0.01, "w": 0.5, "h": 0.5},
        {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.5},
        {"x": 0.0, "y": 0.0, "w": 0.5, "h": 0.0},
        {"x": 0.0, "y": 0.0, "w": 1.01, "h": 1.0},
    ):
        with pytest.raises(ValidationError):
            Adjustments.model_validate({"crop": crop})


def test_crop_uses_exact_decimal_arithmetic():
    crop = Adjustments.model_validate({"crop": {"x": 0.04, "y": 0.0, "w": 0.96, "h": 1.0}}).crop

    assert crop is not None
    assert crop.x + crop.w == pytest.approx(1.0)


@pytest.mark.parametrize(
    "payload",
    [
        {"unknown": 1},
        {"adjustments": {"unknown": 1}},
        {"adjustments": {"crop": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "extra": 1}}},
    ],
)
def test_unknown_fields_are_rejected(payload: dict[str, object]):
    with pytest.raises(ValidationError):
        EditRecipe.model_validate(payload)


def test_camel_and_snake_case_parse_to_the_same_recipe():
    camel = EditRecipe.model_validate(
        {
            "schemaVersion": "1.0",
            "styleId": "film",
            "styleStrength": 10,
            "adjustments": {"exposureEv": 0.5, "crop": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}},
        }
    )
    snake = EditRecipe.model_validate(
        {
            "schema_version": "1.0",
            "style_id": "film",
            "style_strength": 10,
            "adjustments": {"exposure_ev": 0.5, "crop": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}},
        }
    )

    assert camel == snake
    dumped = camel.model_dump(mode="json", by_alias=True)
    assert dumped["styleId"] == "film"
    assert dumped["adjustments"]["exposureEv"] == 0.5
    assert "exposure_ev" not in dumped["adjustments"]


def test_rationale_and_warnings_length_limits():
    assert EditRecipe.model_validate({"rationale": ["x" * 200] * 8})
    assert EditRecipe.model_validate({"warnings": ["x" * 200] * 8})

    for payload in (
        {"rationale": ["x"] * 9},
        {"rationale": ["x" * 201]},
        {"warnings": ["x"] * 9},
        {"warnings": ["x" * 201]},
    ):
        with pytest.raises(ValidationError):
            EditRecipe.model_validate(payload)


def test_full_frame_crop_is_canonicalized_to_null():
    with_crop = Adjustments.model_validate({"crop": {"x": 0, "y": -0.0, "w": 1, "h": 1}})
    without_crop = Adjustments()

    assert canonical_adjustments_json(with_crop) == canonical_adjustments_json(without_crop)
    assert '"crop":null' in canonical_adjustments_json(with_crop)
    assert recipe_hash(EditRecipe(adjustments=with_crop)) == recipe_hash(
        EditRecipe(adjustments=without_crop)
    )


def test_hashes_are_stable_across_equivalent_inputs():
    left = EditRecipe.model_validate(
        {"adjustments": {"exposure_ev": 0.0, "contrast": 0.0}, "style_strength": 0}
    )
    right = EditRecipe.model_validate(
        {"styleStrength": -0.0, "adjustments": {"contrast": -0.0, "exposureEv": -0.0}}
    )

    assert canonical_recipe_json(left) == canonical_recipe_json(right)
    assert recipe_hash(left) == recipe_hash(right)
    assert "exposure_ev" in canonical_recipe_json(left)
    assert " " not in canonical_recipe_json(left)


def test_render_key_ignores_non_pixel_fields():
    first = EditRecipe.model_validate(
        {"styleId": "film", "styleStrength": 80, "rationale": ["one"]}
    )
    second = EditRecipe.model_validate(
        {"styleId": "natural", "styleStrength": 0, "warnings": ["two"]}
    )
    adjustments = first.adjustments

    key = render_key(
        "a" * 64,
        adjustments,
        edge=1600,
        quality="final",
        engine_version="engine/1",
    )

    assert key == render_key(
        "A" * 64,
        second.adjustments,
        edge=1600,
        quality="final",
        engine_version="engine/1",
    )
    assert key != render_key(
        "b" * 64,
        adjustments,
        edge=1600,
        quality="final",
        engine_version="engine/1",
    )
    assert key != render_key(
        "a" * 64,
        adjustments,
        edge=960,
        quality="draft",
        engine_version="engine/1",
    )
    assert key != render_key(
        "a" * 64,
        adjustments,
        edge=1600,
        quality="final",
        engine_version="engine/2",
    )


def test_validation_error_details_point_at_the_field_and_limit(tmp_path):
    with _recipe_client(tmp_path) as client:
        response = client.post("/test/recipe", json={"adjustments": {"exposureEv": 3.01}})

    assert response.status_code == 422
    body = response.json()
    field = body["error"]["details"]["fields"][0]
    assert field["field"] == "adjustments.exposureEv"
    assert field["limit"] == {"le": 3.0}
    assert "input" not in field

    with _recipe_client(tmp_path) as client:
        response = client.post("/test/recipe", json={"styleStrength": 100.01})

    field = response.json()["error"]["details"]["fields"][0]
    assert field["field"] == "styleStrength"
    assert field["limit"] == {"le": 100.0}
