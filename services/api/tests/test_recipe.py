from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from app.models.recipe import (
    MASK_LIMIT,
    STYLE_IDS,
    Adjustments,
    ColorGrading,
    Crop,
    CurveSet,
    EditRecipe,
    HslAdjustments,
    LocalAdjustment,
    OutputSettings,
    UserMask,
    canonical_adjustments_json,
    canonical_recipe_json,
    default_recipe,
    recipe_hash,
    render_key,
)

NUMERIC_BOUNDS = {
    "exposure_ev": ("exposureEv", -5.0, 5.0),
    "contrast": ("contrast", -100.0, 100.0),
    "highlights": ("highlights", -100.0, 100.0),
    "shadows": ("shadows", -100.0, 100.0),
    "whites": ("whites", -100.0, 100.0),
    "blacks": ("blacks", -100.0, 100.0),
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
        allowed_hosts="testserver",
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
    assert empty.schema_version == "2.0"
    assert empty.style_id == "natural"
    assert empty.style_strength == 0.0
    assert empty.adjustments == Adjustments()
    assert empty.curve == CurveSet()
    assert empty.hsl == HslAdjustments()
    assert empty.color_grading == ColorGrading()
    assert empty.local_adjustments == ()
    assert empty.output == OutputSettings()
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


@pytest.mark.parametrize("value", [10**400, -(10**400)])
def test_overflowing_json_integers_are_rejected(value: int):
    with pytest.raises(ValidationError):
        Adjustments.model_validate({"exposureEv": value})


@pytest.mark.parametrize("literal", ["1" * 400, "-" + "1" * 400])
def test_overflowing_json_integers_return_422(tmp_path, literal: str):
    with _recipe_client(tmp_path) as client:
        response = client.post(
            "/test/recipe",
            content=f'{{"adjustments":{{"exposureEv":{literal}}}}}',
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 422
    field = response.json()["error"]["details"]["fields"][0]
    assert field["field"] == "adjustments.exposureEv"
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
            "schemaVersion": "2.0",
            "styleId": "film",
            "styleStrength": 10,
            "adjustments": {"exposureEv": 0.5, "crop": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}},
        }
    )
    snake = EditRecipe.model_validate(
        {
            "schema_version": "2.0",
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


def test_legacy_v1_recipe_is_upgraded():
    legacy = EditRecipe.model_validate(
        {
            "schemaVersion": "1.0",
            "styleId": "film",
            "adjustments": {"exposureEv": 2.5, "contrast": 12},
            "rationale": ["legacy"],
        }
    )

    assert legacy.schema_version == "2.0"
    assert legacy.style_id == "film"
    assert legacy.adjustments.exposure_ev == 2.5
    assert legacy.adjustments.contrast == 12
    assert legacy.adjustments.whites == 0
    assert legacy.adjustments.blacks == 0
    assert legacy.curve == CurveSet()
    assert legacy.hsl == HslAdjustments()
    assert legacy.color_grading == ColorGrading()
    assert legacy.local_adjustments == ()
    assert legacy.output == OutputSettings()
    assert legacy.rationale == ["legacy"]


def test_legacy_v1_snake_case_is_upgraded():
    legacy = EditRecipe.model_validate(
        {"schema_version": "1.0", "adjustments": {"exposure_ev": 1.0}}
    )

    assert legacy.schema_version == "2.0"
    assert legacy.adjustments.exposure_ev == 1.0


def test_unknown_schema_version_is_rejected():
    with pytest.raises(ValidationError):
        EditRecipe.model_validate({"schemaVersion": "3.0"})


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
        {
            "styleId": "film",
            "styleStrength": 80,
            "rationale": ["one"],
            "output": {"format": "png", "quality": 80, "colorSpace": "sRGB"},
        }
    )
    second = EditRecipe.model_validate(
        {
            "styleId": "natural",
            "styleStrength": 0,
            "warnings": ["two"],
            "output": {"format": "jpeg", "quality": 92, "colorSpace": "sRGB"},
        }
    )

    key = render_key(
        "a" * 64,
        first,
        edge=1600,
        quality="final",
        engine_version="engine/1",
    )

    assert key == render_key(
        "A" * 64,
        second,
        edge=1600,
        quality="final",
        engine_version="engine/1",
    )
    assert key != render_key(
        "b" * 64,
        first,
        edge=1600,
        quality="final",
        engine_version="engine/1",
    )
    assert key != render_key(
        "a" * 64,
        first,
        edge=960,
        quality="draft",
        engine_version="engine/1",
    )
    assert key != render_key(
        "a" * 64,
        first,
        edge=1600,
        quality="final",
        engine_version="engine/2",
    )


def test_render_key_includes_pixel_recipe_groups():
    base = EditRecipe()
    key = render_key(
        "a" * 64,
        base,
        edge=1600,
        quality="final",
        engine_version="engine/1",
    )

    variants = (
        EditRecipe.model_validate({"curve": {"master": [{"x": 0, "y": 0}, {"x": 1, "y": 0.8}]}}),
        EditRecipe.model_validate({"hsl": {"red": {"hue": 15}}}),
        EditRecipe.model_validate({"colorGrading": {"shadows": {"hue": 200, "saturation": 20}}}),
        EditRecipe.model_validate(
            {
                "localAdjustments": [
                    {
                        "id": "local_001",
                        "maskId": "full",
                        "adjustments": {"exposureEv": 0.3},
                    }
                ]
            }
        ),
    )
    for variant in variants:
        assert key != render_key(
            "a" * 64,
            variant,
            edge=1600,
            quality="final",
            engine_version="engine/1",
        )


def test_curve_validation():
    valid = CurveSet.model_validate(
        {"master": [{"x": 0.0, "y": 0.0}, {"x": 0.5, "y": 0.4}, {"x": 1.0, "y": 1.0}]}
    )
    assert len(valid.master) == 3
    assert valid.master[1].x == 0.5
    assert CurveSet.model_validate({"master": []}).master == ()

    invalid_payloads = (
        {"master": [{"x": 0.5, "y": 0.5}]},
        {"master": [{"x": 0.6, "y": 0.5}, {"x": 0.4, "y": 0.6}]},
        {"master": [{"x": 0.5, "y": 0.5}, {"x": 0.5, "y": 0.6}]},
        {"master": [{"x": 1.1, "y": 0.5}]},
        {"master": [{"x": 0.5, "y": -0.1}]},
        {"master": [{"x": 0.1234567, "y": 0.5}]},
        {"master": [{"x": round(i / 32, 6), "y": round(i / 32, 6)} for i in range(33)]},
        {"unknown": []},
    )
    for payload in invalid_payloads:
        with pytest.raises(ValidationError):
            CurveSet.model_validate(payload)


def test_hsl_validation():
    hsl = HslAdjustments.model_validate(
        {"red": {"hue": -180, "saturation": 100, "luminance": -100}}
    )
    assert hsl.red.hue == -180
    assert hsl.red.saturation == 100
    assert hsl.blue == hsl.red.__class__()

    for payload in (
        {"red": {"hue": -181}},
        {"red": {"hue": 181}},
        {"red": {"saturation": 101}},
        {"red": {"luminance": -101}},
        {"red": {"hue": True}},
        {"unknown": {}},
    ):
        with pytest.raises(ValidationError):
            HslAdjustments.model_validate(payload)


def test_color_grading_validation():
    grading = ColorGrading.model_validate(
        {"shadows": {"hue": 360, "saturation": 10}, "balance": -25, "blending": 75}
    )
    assert grading.shadows.hue == 360
    assert grading.balance == -25
    assert grading.blending == 75

    for payload in (
        {"shadows": {"hue": 361}},
        {"shadows": {"saturation": 101}},
        {"balance": 101},
        {"blending": -1},
        {"midtones": {"hue": "10"}},
    ):
        with pytest.raises(ValidationError):
            ColorGrading.model_validate(payload)


def test_local_adjustment_validation():
    recipe = EditRecipe.model_validate(
        {
            "localAdjustments": [
                {
                    "id": "local_001",
                    "maskId": "full",
                    "adjustments": {"exposureEv": 0.3, "saturation": -5},
                }
            ]
        }
    )
    assert recipe.local_adjustments[0].id == "local_001"
    assert recipe.local_adjustments[0].enabled is True
    assert recipe.local_adjustments[0].adjustments.exposure_ev == 0.3

    for payload in (
        {"id": "local001", "maskId": "full"},
        {"id": "local_001", "maskId": "mask 001"},
        {"id": "local_001", "maskId": "full", "enabled": "yes"},
        {"id": "local_001", "maskId": "full", "adjustments": {"unknown": 1}},
    ):
        with pytest.raises(ValidationError):
            LocalAdjustment.model_validate(payload)


def test_local_adjustments_are_unique_and_limited():
    item = {
        "id": "local_001",
        "maskId": "full",
        "adjustments": {"exposureEv": 0.2},
    }
    EditRecipe.model_validate({"localAdjustments": [item]})

    with pytest.raises(ValidationError):
        EditRecipe.model_validate({"localAdjustments": [item, item]})

    many = [{**item, "id": f"local_{index:03d}"} for index in range(21)]
    with pytest.raises(ValidationError):
        EditRecipe.model_validate({"localAdjustments": many})


def test_user_mask_validation():
    mask = UserMask.model_validate(
        {
            "id": "mask_001",
            "shape": "ellipse",
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.4,
            "feather": 20,
            "opacity": 80,
            "inverted": True,
        }
    )
    assert mask.shape == "ellipse"
    assert mask.coordinate_space == "source-normalized"
    assert mask.source == "user"
    assert mask.inverted is True

    for payload in (
        {"id": "full", "x": 0, "y": 0, "width": 0.1, "height": 0.1},
        {"id": "mask_001", "x": 0.8, "y": 0, "width": 0.3, "height": 0.1},
        {"id": "mask_001", "x": 0, "y": 0.8, "width": 0.1, "height": 0.3},
        {"id": "mask_001", "x": 0, "y": 0, "width": 0, "height": 0.1},
        {"id": "mask_001", "x": 0, "y": 0, "width": 0.1, "height": 0.1, "shape": "circle"},
        {"id": "mask_001", "x": 0, "y": 0, "width": 0.1, "height": 0.1, "feather": 101},
        {"id": "mask_001", "x": 0, "y": 0, "width": 0.1, "height": 0.1, "opacity": -1},
        {"id": "mask_001", "x": 0, "y": 0, "width": 0.1, "height": 0.1, "inverted": "no"},
        {"id": "mask_001", "x": 0.12345, "y": 0, "width": 0.1, "height": 0.1},
    ):
        with pytest.raises(ValidationError):
            UserMask.model_validate(payload)


def test_masks_are_unique_and_limited():
    mask = {"id": "mask_001", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2}
    EditRecipe.model_validate({"masks": [mask]})

    with pytest.raises(ValidationError):
        EditRecipe.model_validate({"masks": [mask, mask]})

    many = [{**mask, "id": f"mask_{index:03d}"} for index in range(MASK_LIMIT + 1)]
    with pytest.raises(ValidationError):
        EditRecipe.model_validate({"masks": many})


def test_mask_order_is_canonicalized():
    first = EditRecipe.model_validate(
        {
            "masks": [
                {"id": "mask_b", "x": 0.5, "y": 0.1, "width": 0.2, "height": 0.2},
                {"id": "mask_a", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2},
            ]
        }
    )
    second = EditRecipe.model_validate(
        {
            "masks": [
                {"id": "mask_a", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2},
                {"id": "mask_b", "x": 0.5, "y": 0.1, "width": 0.2, "height": 0.2},
            ]
        }
    )

    assert canonical_recipe_json(first) == canonical_recipe_json(second)
    assert recipe_hash(first) == recipe_hash(second)


def test_mask_fields_affect_render_key():
    base = EditRecipe.model_validate(
        {
            "masks": [{"id": "mask_001", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2}],
            "localAdjustments": [
                {
                    "id": "local_001",
                    "maskId": "mask_001",
                    "adjustments": {"exposureEv": 0.3},
                }
            ],
        }
    )
    key = render_key("a" * 64, base, edge=1600, quality="final", engine_version="engine/1")

    for variant in (
        {"x": 0.2},
        {"width": 0.3},
        {"feather": 25},
        {"opacity": 50},
        {"inverted": True},
        {"shape": "ellipse"},
    ):
        mask = base.masks[0].model_dump(mode="json")
        mask.update(variant)
        other = EditRecipe.model_validate({**base.model_dump(mode="json"), "masks": [mask]})
        assert key != render_key(
            "a" * 64, other, edge=1600, quality="final", engine_version="engine/1"
        )


def test_local_v1_rejects_unsupported_fields():
    for field in ("sharpen", "denoise", "vignette", "grain"):
        with pytest.raises(ValidationError):
            EditRecipe.model_validate(
                {
                    "localAdjustments": [
                        {
                            "id": "local_001",
                            "maskId": "full",
                            "adjustments": {field: 5},
                        }
                    ]
                }
            )

    EditRecipe.model_validate(
        {
            "localAdjustments": [
                {
                    "id": "local_001",
                    "maskId": "full",
                    "adjustments": {"clarity": 25, "exposureEv": 0.3},
                }
            ]
        }
    )


def test_revision_identity_ignores_output_and_style_fields():
    base = EditRecipe()
    decorated = EditRecipe.model_validate(
        {
            "styleId": "film",
            "styleStrength": 80,
            "output": {"format": "png", "quality": 80, "colorSpace": "sRGB"},
        }
    )

    assert canonical_recipe_json(decorated) == canonical_recipe_json(base)
    assert recipe_hash(decorated) == recipe_hash(base)
    assert '"output"' not in canonical_recipe_json(decorated)
    assert '"style_id"' not in canonical_recipe_json(decorated)


def test_empty_masks_are_omitted_from_the_hashed_payload():
    assert recipe_hash(EditRecipe()) == (
        "fce36bb1722618b40d2cd27451e410aa964b01035e3e9e18fa73303a62cb47c2"
    )
    assert "masks" not in canonical_recipe_json(EditRecipe())

    local_only = EditRecipe.model_validate(
        {
            "localAdjustments": [
                {
                    "id": "local_001",
                    "maskId": "full",
                    "adjustments": {"exposureEv": 0.3},
                }
            ]
        }
    )
    assert recipe_hash(local_only) == (
        "792060cf353d0138c479b2ec85a5a86ecfc682d49181b585cb0a9f9ba4c82b1e"
    )
    assert "masks" not in canonical_recipe_json(local_only)
    assert (
        render_key(
            "a" * 64,
            local_only,
            edge=1600,
            quality="final",
            engine_version="frame-engine/6",
        )
        == "a20b792c2eae2e2c21d8e82ab9954c4389852bc8ad9dc5b23f4eded7a1556d29"
    )


def test_output_settings_validation():
    assert OutputSettings.model_validate({}) == OutputSettings(
        format="jpeg", quality=92, color_space="sRGB"
    )
    assert (
        OutputSettings.model_validate({"format": "png", "quality": 1, "colorSpace": "sRGB"}).format
        == "png"
    )

    for payload in (
        {"quality": 0},
        {"quality": 101},
        {"quality": True},
        {"format": "tiff"},
        {"colorSpace": "AdobeRGB"},
        {"unknown": 1},
    ):
        with pytest.raises(ValidationError):
            OutputSettings.model_validate(payload)


def test_local_adjustment_order_is_canonicalized():
    first = EditRecipe.model_validate(
        {
            "localAdjustments": [
                {"id": "local_b", "maskId": "full", "adjustments": {"exposureEv": 0.1}},
                {"id": "local_a", "maskId": "full", "adjustments": {"contrast": 5}},
            ]
        }
    )
    second = EditRecipe.model_validate(
        {
            "localAdjustments": [
                {"id": "local_a", "maskId": "full", "adjustments": {"contrast": 5}},
                {"id": "local_b", "maskId": "full", "adjustments": {"exposureEv": 0.1}},
            ]
        }
    )

    assert canonical_recipe_json(first) == canonical_recipe_json(second)
    assert recipe_hash(first) == recipe_hash(second)


def test_negative_zero_is_canonicalized_in_new_groups():
    first = EditRecipe.model_validate(
        {
            "adjustments": {"whites": -0.0},
            "curve": {"master": [{"x": 0.0, "y": -0.0}, {"x": 1.0, "y": 1.0}]},
            "hsl": {"red": {"hue": -0.0}},
            "colorGrading": {"balance": -0.0},
            "localAdjustments": [
                {
                    "id": "local_001",
                    "maskId": "full",
                    "adjustments": {"exposureEv": -0.0},
                }
            ],
        }
    )
    second = EditRecipe.model_validate(
        {
            "adjustments": {"whites": 0.0},
            "curve": {"master": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}]},
            "hsl": {"red": {"hue": 0.0}},
            "colorGrading": {"balance": 0.0},
            "localAdjustments": [
                {
                    "id": "local_001",
                    "maskId": "full",
                    "adjustments": {"exposureEv": 0.0},
                }
            ],
        }
    )

    assert canonical_recipe_json(first) == canonical_recipe_json(second)
    assert recipe_hash(first) == recipe_hash(second)


def test_validation_error_details_point_at_the_field_and_limit(tmp_path):
    with _recipe_client(tmp_path) as client:
        response = client.post("/test/recipe", json={"adjustments": {"exposureEv": 5.01}})

    assert response.status_code == 422
    body = response.json()
    field = body["error"]["details"]["fields"][0]
    assert field["field"] == "adjustments.exposureEv"
    assert field["limit"] == {"le": 5.0}
    assert "input" not in field

    with _recipe_client(tmp_path) as client:
        response = client.post("/test/recipe", json={"styleStrength": 100.01})

    field = response.json()["error"]["details"]["fields"][0]
    assert field["field"] == "styleStrength"
    assert field["limit"] == {"le": 100.0}
