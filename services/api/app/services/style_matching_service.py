from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from app.core.errors import AppError
from app.models.analysis_report import AnalysisReport
from app.models.style_fit import FitLevel, StyleFitAlternative, StyleFitResponse
from app.models.style_profile import StyleKind, StyleProfile
from app.repositories.style_repo import SqliteStyleProfileRepository
from app.services.report_lookup import completed_report_for_image
from app.styles.fit import FitEvaluation, evaluate_style_fit
from app.styles.vocabulary import SCENE_NAMES

if TYPE_CHECKING:
    from app.services.analysis_task_service import AnalysisTaskService
    from app.services.image_service import ImageService

MIN_ALTERNATIVE_SCORE = 50.0


def _style_not_found() -> AppError:
    return AppError(404, "style_not_found", "The requested style is not available.")


class StyleMatchingService:
    def __init__(
        self,
        repository: SqliteStyleProfileRepository,
        *,
        images: ImageService,
        analysis: AnalysisTaskService,
    ) -> None:
        self._repository = repository
        self._images = images
        self._analysis = analysis

    def fit(
        self,
        style_id: str,
        image_id: str,
        *,
        alternatives: int = 3,
    ) -> StyleFitResponse:
        profile = self._repository.get(style_id)
        if profile is None or not profile.enabled:
            raise _style_not_found()
        canonical, report = completed_report_for_image(self._images, self._analysis, image_id)
        evaluation = evaluate_style_fit(profile, report)
        suggestions = self._alternatives(profile.id, report, alternatives)
        limitations = evaluation.limitations
        if not suggestions and evaluation.overall_level in {FitLevel.LOW, FitLevel.UNSUITABLE}:
            limitations = (
                *limitations,
                "当前风格库中没有与该照片场景明显匹配的替代风格。",
            )
        return StyleFitResponse(
            image_id=UUID(canonical),
            analysis_id=report.analysis_id,
            is_mock=report.engine.is_mock,
            style_id=profile.id,
            style_name=profile.name,
            style_kind=profile.kind,
            style_version=profile.version,
            overall_score=evaluation.overall_score,
            overall_level=evaluation.overall_level,
            summary=evaluation.summary,
            dimensions=evaluation.dimensions,
            conflicts=evaluation.conflicts,
            achievable=evaluation.achievable,
            unachievable=evaluation.unachievable,
            recommended_mode=evaluation.recommended_mode,
            recommended_strength=evaluation.recommended_strength,
            alternatives=suggestions,
            limitations=limitations,
        )

    def _alternatives(
        self,
        style_id: str,
        report: AnalysisReport,
        limit: int,
    ) -> tuple[StyleFitAlternative, ...]:
        scored: list[tuple[StyleProfile, FitEvaluation]] = []
        for profile in self._repository.list_profiles(enabled_only=True):
            if profile.id == style_id:
                continue
            evaluation = evaluate_style_fit(profile, report)
            if evaluation.overall_score < MIN_ALTERNATIVE_SCORE:
                continue
            scored.append((profile, evaluation))
        scored.sort(
            key=lambda item: (
                -item[1].overall_score,
                0 if item[0].kind is StyleKind.MASTER else 1,
                item[0].name,
                item[0].id,
            )
        )
        return tuple(
            StyleFitAlternative(
                style_id=profile.id,
                name=profile.name,
                kind=profile.kind,
                score=evaluation.overall_score,
                level=evaluation.overall_level,
                reason=_alternative_reason(profile, report, evaluation),
            )
            for profile, evaluation in scored[:limit]
        )


def _alternative_reason(
    profile: StyleProfile,
    report: AnalysisReport,
    evaluation: FitEvaluation,
) -> str:
    scene = SCENE_NAMES[report.scene.primary]
    if report.scene.primary in profile.scene_fit.suitable:
        return f"场景为{scene}，符合该风格的适用题材；适配度 {evaluation.overall_score:.0f}。"
    return f"综合条件更接近该风格；适配度 {evaluation.overall_score:.0f}。"


__all__ = ["MIN_ALTERNATIVE_SCORE", "StyleMatchingService"]
