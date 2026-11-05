from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Annotated, Any, Literal, Self, TypeAlias

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)
from pydantic.alias_generators import to_camel

StyleId = Literal[
    "natural",
    "portrait",
    "landscape",
    "street",
    "documentary",
    "film",
    "cinematic",
]
STYLE_IDS: tuple[StyleId, ...] = (
    "natural",
    "portrait",
    "landscape",
    "street",
    "documentary",
    "film",
    "cinematic",
)
RenderQuality = Literal["draft", "final", "export"]
MaskShape = Literal["rectangle", "ellipse"]
OutputFormat = Literal["jpeg", "png"]
ColorSpace = Literal["sRGB"]
CurveChannel = Literal["master", "red", "green", "blue"]

RECIPE_SCHEMA_VERSION: Literal["2.0"] = "2.0"
LEGACY_RECIPE_SCHEMA_VERSION = "1.0"
CURVE_CHANNELS: tuple[CurveChannel, ...] = ("master", "red", "green", "blue")
CURVE_MAX_POINTS = 32
HSL_BANDS: tuple[str, ...] = (
    "red",
    "orange",
    "yellow",
    "green",
    "aqua",
    "blue",
    "purple",
    "magenta",
)
LOCAL_ADJUSTMENT_LIMIT = 20
MASK_LIMIT = 20
LOCAL_ID_PATTERN = r"^local_[A-Za-z0-9_-]{1,58}$"
MASK_ID_PATTERN = r"^(full|mask_[A-Za-z0-9_-]{1,58})$"
USER_MASK_ID_PATTERN = r"^mask_[A-Za-z0-9_-]{1,58}$"
LOCAL_V1_UNSUPPORTED_FIELDS: tuple[str, ...] = ("sharpen", "denoise", "vignette", "grain")


def _json_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("must be a JSON number")
    try:
        return float(value)
    except OverflowError as exc:
        raise ValueError("number is out of range") from exc


def _max_decimals(places: int) -> AfterValidator:
    def validate(value: float) -> float:
        exponent = Decimal(repr(value)).as_tuple().exponent
        if isinstance(exponent, int) and exponent < -places:
            raise ValueError(f"at most {places} decimal places are allowed")
        return value

    return AfterValidator(validate)


_JsonNumber = BeforeValidator(_json_number)
_TwoDecimals = _max_decimals(2)

EV5: TypeAlias = Annotated[
    float, _JsonNumber, Field(allow_inf_nan=False, ge=-5, le=5), _TwoDecimals
]
B100: TypeAlias = Annotated[
    float, _JsonNumber, Field(allow_inf_nan=False, ge=-100, le=100), _TwoDecimals
]
U100: TypeAlias = Annotated[
    float, _JsonNumber, Field(allow_inf_nan=False, ge=0, le=100), _TwoDecimals
]
ROT: TypeAlias = Annotated[
    float, _JsonNumber, Field(allow_inf_nan=False, ge=-15, le=15), _TwoDecimals
]
UNIT: TypeAlias = Annotated[
    float, _JsonNumber, Field(allow_inf_nan=False, ge=0, le=1), _TwoDecimals
]
PUNIT: TypeAlias = Annotated[
    float, _JsonNumber, Field(allow_inf_nan=False, gt=0, le=1), _TwoDecimals
]
UNIT6: TypeAlias = Annotated[
    float, _JsonNumber, Field(allow_inf_nan=False, ge=0, le=1), _max_decimals(6)
]
UNIT4: TypeAlias = Annotated[
    float, _JsonNumber, Field(allow_inf_nan=False, ge=0, le=1), _max_decimals(4)
]
PUNIT4: TypeAlias = Annotated[
    float, _JsonNumber, Field(allow_inf_nan=False, gt=0, le=1), _max_decimals(4)
]
HUE180: TypeAlias = Annotated[
    float, _JsonNumber, Field(allow_inf_nan=False, ge=-180, le=180), _TwoDecimals
]
HUE360: TypeAlias = Annotated[
    float, _JsonNumber, Field(allow_inf_nan=False, ge=0, le=360), _TwoDecimals
]
LocalIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=LOCAL_ID_PATTERN),
]
MaskIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=MASK_ID_PATTERN),
]
UserMaskIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=USER_MASK_ID_PATTERN),
]


class _Strict(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        alias_generator=to_camel,
        populate_by_name=True,
    )


class Crop(_Strict):
    x: UNIT
    y: UNIT
    w: PUNIT
    h: PUNIT

    @model_validator(mode="after")
    def _inside_frame(self) -> Self:
        if (
            Decimal(repr(self.x)) + Decimal(repr(self.w)) > 1
            or Decimal(repr(self.y)) + Decimal(repr(self.h)) > 1
        ):
            raise ValueError("crop must lie inside the image (x+w<=1 and y+h<=1)")
        return self


class Adjustments(_Strict):
    exposure_ev: EV5 = 0.0
    contrast: B100 = 0.0
    highlights: B100 = 0.0
    shadows: B100 = 0.0
    whites: B100 = 0.0
    blacks: B100 = 0.0
    temperature: B100 = 0.0
    tint: B100 = 0.0
    saturation: B100 = 0.0
    vibrance: B100 = 0.0
    clarity: B100 = 0.0
    sharpen: U100 = 0.0
    denoise: U100 = 0.0
    vignette: B100 = 0.0
    grain: U100 = 0.0
    rotation_deg: ROT = 0.0
    crop: Crop | None = None


class CurvePoint(_Strict):
    x: UNIT6
    y: UNIT6


class CurveSet(_Strict):
    master: tuple[CurvePoint, ...] = Field(default=(), max_length=CURVE_MAX_POINTS)
    red: tuple[CurvePoint, ...] = Field(default=(), max_length=CURVE_MAX_POINTS)
    green: tuple[CurvePoint, ...] = Field(default=(), max_length=CURVE_MAX_POINTS)
    blue: tuple[CurvePoint, ...] = Field(default=(), max_length=CURVE_MAX_POINTS)

    @model_validator(mode="after")
    def _points_are_ordered(self) -> Self:
        for channel in CURVE_CHANNELS:
            points = getattr(self, channel)
            if len(points) == 1:
                raise ValueError(f"{channel} curve must be empty or contain at least two points")
            previous: float | None = None
            for point in points:
                if previous is not None and point.x <= previous:
                    raise ValueError(
                        f"{channel} curve points must be sorted by x with unique x values"
                    )
                previous = point.x
        return self


class HslBand(_Strict):
    hue: HUE180 = 0.0
    saturation: B100 = 0.0
    luminance: B100 = 0.0


class HslAdjustments(_Strict):
    red: HslBand = Field(default_factory=HslBand)
    orange: HslBand = Field(default_factory=HslBand)
    yellow: HslBand = Field(default_factory=HslBand)
    green: HslBand = Field(default_factory=HslBand)
    aqua: HslBand = Field(default_factory=HslBand)
    blue: HslBand = Field(default_factory=HslBand)
    purple: HslBand = Field(default_factory=HslBand)
    magenta: HslBand = Field(default_factory=HslBand)


class ColorGradeZone(_Strict):
    hue: HUE360 = 0.0
    saturation: U100 = 0.0


class ColorGrading(_Strict):
    shadows: ColorGradeZone = Field(default_factory=ColorGradeZone)
    midtones: ColorGradeZone = Field(default_factory=ColorGradeZone)
    highlights: ColorGradeZone = Field(default_factory=ColorGradeZone)
    balance: B100 = 0.0
    blending: U100 = 50.0


class LocalAdjustments(_Strict):
    exposure_ev: EV5 = 0.0
    contrast: B100 = 0.0
    highlights: B100 = 0.0
    shadows: B100 = 0.0
    whites: B100 = 0.0
    blacks: B100 = 0.0
    temperature: B100 = 0.0
    tint: B100 = 0.0
    saturation: B100 = 0.0
    vibrance: B100 = 0.0
    clarity: B100 = 0.0
    sharpen: U100 = 0.0
    denoise: U100 = 0.0
    vignette: B100 = 0.0
    grain: U100 = 0.0

    @model_validator(mode="after")
    def _v1_fields_only(self) -> Self:
        unsupported = [name for name in LOCAL_V1_UNSUPPORTED_FIELDS if getattr(self, name) != 0]
        if unsupported:
            raise ValueError(
                f"{', '.join(unsupported)} is not supported for local adjustments in v1"
            )
        return self


class LocalAdjustment(_Strict):
    id: LocalIdentifier
    mask_id: MaskIdentifier = "full"
    enabled: StrictBool = True
    adjustments: LocalAdjustments = Field(default_factory=LocalAdjustments)


class UserMask(_Strict):
    id: UserMaskIdentifier
    shape: MaskShape = "rectangle"
    source: Literal["user"] = "user"
    coordinate_space: Literal["source-normalized"] = "source-normalized"
    x: UNIT4
    y: UNIT4
    width: PUNIT4
    height: PUNIT4
    feather: U100 = 15.0
    opacity: U100 = 100.0
    inverted: StrictBool = False

    @model_validator(mode="after")
    def _inside_frame(self) -> Self:
        if (
            Decimal(repr(self.x)) + Decimal(repr(self.width)) > 1
            or Decimal(repr(self.y)) + Decimal(repr(self.height)) > 1
        ):
            raise ValueError("mask must lie inside the image (x+width<=1 and y+height<=1)")
        return self


class OutputSettings(_Strict):
    format: OutputFormat = "jpeg"
    quality: StrictInt = Field(default=92, ge=1, le=100)
    color_space: ColorSpace = "sRGB"


Note = Annotated[str, Field(max_length=200)]


class EditRecipe(_Strict):
    schema_version: Literal["2.0"] = RECIPE_SCHEMA_VERSION
    style_id: StyleId = "natural"
    style_strength: U100 = 0.0
    adjustments: Adjustments = Field(default_factory=Adjustments)
    curve: CurveSet = Field(default_factory=CurveSet)
    hsl: HslAdjustments = Field(default_factory=HslAdjustments)
    color_grading: ColorGrading = Field(default_factory=ColorGrading)
    masks: tuple[UserMask, ...] = Field(default=(), max_length=MASK_LIMIT)
    local_adjustments: tuple[LocalAdjustment, ...] = Field(
        default=(),
        max_length=LOCAL_ADJUSTMENT_LIMIT,
    )
    output: OutputSettings = Field(default_factory=OutputSettings)
    rationale: list[Note] = Field(default_factory=list, max_length=8)
    warnings: list[Note] = Field(default_factory=list, max_length=8)

    @model_validator(mode="before")
    @classmethod
    def _upgrade_legacy_recipe(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "schemaVersion" in data:
            version = data["schemaVersion"]
        elif "schema_version" in data:
            version = data["schema_version"]
        else:
            return data
        if version != LEGACY_RECIPE_SCHEMA_VERSION:
            return data
        upgraded = dict(data)
        upgraded.pop("schema_version", None)
        upgraded["schemaVersion"] = RECIPE_SCHEMA_VERSION
        return upgraded

    @model_validator(mode="after")
    def _local_adjustments_are_unique(self) -> Self:
        ids = [item.id for item in self.local_adjustments]
        if len(ids) != len(set(ids)):
            raise ValueError("local adjustment ids must be unique.")
        mask_ids = [mask.id for mask in self.masks]
        if len(mask_ids) != len(set(mask_ids)):
            raise ValueError("mask ids must be unique.")
        return self


def default_recipe() -> EditRecipe:
    return EditRecipe()


def _normalized_float(value: float) -> float:
    return value + 0.0


def _canonicalize(value: Any) -> Any:
    if isinstance(value, float):
        return _normalized_float(value)
    if isinstance(value, dict):
        return {str(key): _canonicalize(entry) for key, entry in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(entry) for entry in value]
    return value


def canonical_adjustments_json(adjustments: Adjustments) -> str:
    payload = adjustments.model_dump(mode="json")
    crop = payload.get("crop")
    if isinstance(crop, dict):
        normalized_crop = {str(key): _normalized_float(float(value)) for key, value in crop.items()}
        payload["crop"] = (
            None if normalized_crop == {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0} else normalized_crop
        )
    return json.dumps(
        _canonicalize(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _canonical_local_adjustments(local_adjustments: tuple[LocalAdjustment, ...]) -> list[Any]:
    payload = _canonicalize([item.model_dump(mode="json") for item in local_adjustments])
    return sorted(payload, key=lambda item: str(item["id"]))


def _canonical_masks(masks: tuple[UserMask, ...]) -> list[Any]:
    payload = _canonicalize([mask.model_dump(mode="json") for mask in masks])
    return sorted(payload, key=lambda item: str(item["id"]))


def stored_recipe_json(recipe: EditRecipe) -> str:
    """Full recipe for persistence; identity is hashed from canonical_recipe_json."""
    return recipe.model_dump_json()


def canonical_recipe_json(recipe: EditRecipe) -> str:
    payload: dict[str, Any] = recipe.model_dump(mode="json")
    # Revision identity covers pixels only. Output preferences are per-request
    # export settings, and the style fields are not applied by the engine yet, so
    # changing them must not create a "new" revision with identical pixels.
    for inert in ("output", "style_id", "style_strength"):
        payload.pop(inert, None)
    payload["adjustments"] = json.loads(canonical_adjustments_json(recipe.adjustments))
    payload["local_adjustments"] = _canonical_local_adjustments(recipe.local_adjustments)
    if recipe.masks:
        payload["masks"] = _canonical_masks(recipe.masks)
    else:
        payload.pop("masks", None)
    return json.dumps(
        _canonicalize(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def pixel_recipe_json(recipe: EditRecipe) -> str:
    """Canonical pixel-affecting fields; excludes metadata and output preferences."""
    payload: dict[str, Any] = {
        "schema_version": recipe.schema_version,
        "adjustments": json.loads(canonical_adjustments_json(recipe.adjustments)),
        "curve": recipe.curve.model_dump(mode="json"),
        "hsl": recipe.hsl.model_dump(mode="json"),
        "color_grading": recipe.color_grading.model_dump(mode="json"),
        "local_adjustments": _canonical_local_adjustments(recipe.local_adjustments),
    }
    if recipe.masks:
        payload["masks"] = _canonical_masks(recipe.masks)
    return json.dumps(
        _canonicalize(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def recipe_hash(recipe: EditRecipe) -> str:
    return hashlib.sha256(canonical_recipe_json(recipe).encode("utf-8")).hexdigest()


def render_key(
    image_sha256: str,
    recipe: EditRecipe,
    *,
    edge: int,
    quality: RenderQuality,
    engine_version: str,
) -> str:
    canonical = "|".join(
        (
            image_sha256.lower(),
            engine_version,
            pixel_recipe_json(recipe),
            str(edge),
            quality,
        )
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "Adjustments",
    "ColorGrading",
    "ColorGradeZone",
    "ColorSpace",
    "Crop",
    "CurvePoint",
    "CurveSet",
    "EditRecipe",
    "HslAdjustments",
    "HslBand",
    "LEGACY_RECIPE_SCHEMA_VERSION",
    "LocalAdjustment",
    "LocalAdjustments",
    "LOCAL_ADJUSTMENT_LIMIT",
    "LOCAL_V1_UNSUPPORTED_FIELDS",
    "MASK_LIMIT",
    "MaskShape",
    "OutputFormat",
    "OutputSettings",
    "RECIPE_SCHEMA_VERSION",
    "RenderQuality",
    "STYLE_IDS",
    "UserMask",
    "canonical_adjustments_json",
    "canonical_recipe_json",
    "default_recipe",
    "pixel_recipe_json",
    "recipe_hash",
    "render_key",
]
