"""AI provider package.

Exports are resolved lazily: importing ``app.ai.contracts`` must not pull in
provider protocols, because those import ``app.models.photographer``, which in
turn imports the contracts module. Eager re-exports made a direct import of a
model module (for example ``app.styles.library``) fail with a partially
initialised ``app.models.photographer``.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.ai.base import (
        DecisionRequest,
        ModelImage,
        PatchRequest,
        PhotographyDecisionProvider,
        PhotographyPlannerProvider,
        PlannerRequest,
        VisionProvider,
        VisionRequest,
    )
    from app.ai.contracts import (
        AnalysisOptions,
        DecisionResult,
        MeasurementSummary,
        UsageInfo,
        VisionResult,
    )
    from app.ai.errors import ProviderConfigurationError, ProviderError
    from app.ai.factory import (
        ProviderBundle,
        build_decision_provider,
        build_planner_provider,
        build_provider_bundle,
        build_vision_provider,
    )
    from app.models.photographer import PatchDraft, PlannerDraft

_LAZY_EXPORTS: dict[str, str] = {
    **dict.fromkeys(
        (
            "DecisionRequest",
            "ModelImage",
            "PatchRequest",
            "PhotographyDecisionProvider",
            "PhotographyPlannerProvider",
            "PlannerRequest",
            "VisionProvider",
            "VisionRequest",
        ),
        "app.ai.base",
    ),
    **dict.fromkeys(
        (
            "AnalysisOptions",
            "DecisionResult",
            "MeasurementSummary",
            "UsageInfo",
            "VisionResult",
        ),
        "app.ai.contracts",
    ),
    **dict.fromkeys(
        ("ProviderConfigurationError", "ProviderError"),
        "app.ai.errors",
    ),
    **dict.fromkeys(
        (
            "ProviderBundle",
            "build_decision_provider",
            "build_planner_provider",
            "build_provider_bundle",
            "build_vision_provider",
        ),
        "app.ai.factory",
    ),
    **dict.fromkeys(("PatchDraft", "PlannerDraft"), "app.models.photographer"),
}

__all__ = [
    "AnalysisOptions",
    "DecisionRequest",
    "DecisionResult",
    "MeasurementSummary",
    "ModelImage",
    "PatchDraft",
    "PatchRequest",
    "PhotographyDecisionProvider",
    "PhotographyPlannerProvider",
    "PlannerDraft",
    "PlannerRequest",
    "ProviderBundle",
    "ProviderConfigurationError",
    "ProviderError",
    "UsageInfo",
    "VisionProvider",
    "VisionRequest",
    "VisionResult",
    "build_decision_provider",
    "build_planner_provider",
    "build_provider_bundle",
    "build_vision_provider",
]


def __getattr__(name: str) -> Any:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
