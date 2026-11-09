"""Verified context handed to the planner when a style archive drives the plan."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.models.conversion import ConversionMode
from app.models.photographer import ConversionModeInfo
from app.models.style_fit import (
    DimensionFit,
    FitLevel,
    RecommendedStrength,
    StyleFitConflict,
)
from app.models.style_profile import StyleProfile

if TYPE_CHECKING:
    from app.styles.fit import FitEvaluation


@dataclass(frozen=True, slots=True)
class StyleFitContext:
    """The deterministic adaptation summary that the model must respect."""

    overall_score: float
    overall_level: FitLevel
    dimensions: tuple[DimensionFit, ...]
    conflicts: tuple[StyleFitConflict, ...]
    achievable: tuple[str, ...]
    unachievable: tuple[str, ...]
    limitations: tuple[str, ...]
    recommended_mode: ConversionMode
    recommended_strength: RecommendedStrength
    summary: str

    @classmethod
    def from_evaluation(cls, evaluation: FitEvaluation) -> StyleFitContext:
        return cls(
            overall_score=evaluation.overall_score,
            overall_level=evaluation.overall_level,
            dimensions=evaluation.dimensions,
            conflicts=evaluation.conflicts,
            achievable=evaluation.achievable,
            unachievable=evaluation.unachievable,
            limitations=evaluation.limitations,
            recommended_mode=evaluation.recommended_mode,
            recommended_strength=evaluation.recommended_strength,
            summary=evaluation.summary,
        )

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "overallScore": self.overall_score,
            "overallLevel": self.overall_level.value,
            "summary": self.summary,
            "dimensions": [item.model_dump(mode="json", by_alias=True) for item in self.dimensions],
            "conflicts": [item.model_dump(mode="json", by_alias=True) for item in self.conflicts],
            "achievable": list(self.achievable),
            "unachievable": list(self.unachievable),
            "limitations": list(self.limitations),
            "recommendedMode": self.recommended_mode.value,
            "recommendedStrength": self.recommended_strength.model_dump(mode="json", by_alias=True),
        }


@dataclass(frozen=True, slots=True)
class StyleGenerationContext:
    """Everything the planner needs to interpret one style for one photo version."""

    image_id: str
    image_sha256: str
    profile: StyleProfile
    fit: StyleFitContext
    conversion_mode: ConversionMode
    strength: float
    mode_info: ConversionModeInfo

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "imageId": self.image_id,
            "imageSha256": self.image_sha256,
            "conversionMode": self.conversion_mode.value,
            "styleStrength": self.strength,
            "conversionModeConstraints": self.mode_info.model_dump(mode="json", by_alias=True),
            "styleProfile": self.profile.model_dump(mode="json", by_alias=True),
            "fit": self.fit.to_prompt_payload(),
        }


__all__ = ["StyleFitContext", "StyleGenerationContext"]
