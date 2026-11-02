from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Annotated, Literal, Self, TypeAlias

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
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


def _json_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("must be a JSON number")
    return float(value)


def _max_two_decimals(value: float) -> float:
    exponent = Decimal(repr(value)).as_tuple().exponent
    if isinstance(exponent, int) and exponent < -2:
        raise ValueError("at most two decimal places are allowed")
    return value


_JsonNumber = BeforeValidator(_json_number)
_TwoDecimals = AfterValidator(_max_two_decimals)

EV3: TypeAlias = Annotated[
    float, _JsonNumber, Field(allow_inf_nan=False, ge=-3, le=3), _TwoDecimals
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
    exposure_ev: EV3 = 0.0
    contrast: B100 = 0.0
    highlights: B100 = 0.0
    shadows: B100 = 0.0
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


Note = Annotated[str, Field(max_length=200)]


class EditRecipe(_Strict):
    schema_version: Literal["1.0"] = "1.0"
    style_id: StyleId = "natural"
    style_strength: U100 = 0.0
    adjustments: Adjustments = Field(default_factory=Adjustments)
    rationale: list[Note] = Field(default_factory=list, max_length=8)
    warnings: list[Note] = Field(default_factory=list, max_length=8)


def default_recipe() -> EditRecipe:
    return EditRecipe()


def _normalized_float(value: float) -> float:
    return value + 0.0


def canonical_adjustments_json(adjustments: Adjustments) -> str:
    payload = adjustments.model_dump(mode="json")
    crop = payload.get("crop")
    if isinstance(crop, dict):
        normalized_crop = {str(key): _normalized_float(float(value)) for key, value in crop.items()}
        payload["crop"] = (
            None if normalized_crop == {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0} else normalized_crop
        )
    for key, value in payload.items():
        if isinstance(value, float):
            payload[key] = _normalized_float(value)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_recipe_json(recipe: EditRecipe) -> str:
    payload: dict[str, object] = {
        "schema_version": recipe.schema_version,
        "style_id": recipe.style_id,
        "style_strength": _normalized_float(recipe.style_strength),
        "adjustments": json.loads(canonical_adjustments_json(recipe.adjustments)),
        "rationale": list(recipe.rationale),
        "warnings": list(recipe.warnings),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def recipe_hash(recipe: EditRecipe) -> str:
    return hashlib.sha256(canonical_recipe_json(recipe).encode("utf-8")).hexdigest()


def render_key(
    image_sha256: str,
    adjustments: Adjustments,
    *,
    edge: int,
    quality: RenderQuality,
    engine_version: str,
) -> str:
    canonical = "|".join(
        (
            image_sha256.lower(),
            engine_version,
            canonical_adjustments_json(adjustments),
            str(edge),
            quality,
        )
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
