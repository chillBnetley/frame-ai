from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TypeAlias
from uuid import UUID

from pydantic import ValidationError

from app.ai.base import DecisionRequest, VisionRequest
from app.ai.contracts import (
    AnalysisOptions,
    ColorHarmony,
    ColorResult,
    ColorTemperature,
    CompositionBalance,
    ContrastLevel,
    DecisionResult,
    ExposureQuality,
    IssueCandidate,
    IssueSelection,
    IssueType,
    LightingDirection,
    LightingResult,
    LightingType,
    MeasurementSummary,
    NegativeSpace,
    NoiseLevel,
    Occlusion,
    RecommendationResult,
    SaturationLevel,
    SceneLabel,
    SceneResult,
    SharpnessQuality,
    SubjectPosition,
    SubjectRole,
    TechnicalQualityResult,
    VisionResult,
)
from app.ai.errors import ProviderError
from app.ai.factory import ProviderBundle
from app.analysis.decision_validation import (
    ISSUE_GUIDANCE,
    DecisionValidationError,
    ValidatedDecision,
    validate_decision,
)
from app.analysis.diagnosis import (
    CandidateSet,
    DiagnosisContext,
    build_candidates,
    sample_regions,
)
from app.analysis.features import extract_features
from app.analysis.preprocessing import PreprocessedImage, preprocess_image
from app.analysis.regions import RegionAssignment, build_regions
from app.core.config import Settings
from app.core.errors import AppError
from app.imaging.analyzer import ANALYZER_VERSION
from app.imaging.loader import load_image
from app.models.analysis_report import (
    REPORT_PROMPT_VERSION,
    REPORT_SCHEMA_VERSION,
    AnalysisReport,
    CastMeasurement,
    ClippingMeasurement,
    ColorMeasurement,
    CompositionMeasurement,
    CompositionReport,
    DetailMeasurement,
    EngineInfo,
    IssueReport,
    LuminanceMeasurement,
    MeasurementsReport,
    RecommendationReport,
    ReportImage,
)
from app.models.analysis_task import AnalysisTaskRecord, TaskStage, TaskStatus
from app.repositories.analysis_repo import SqliteAnalysisRepository
from app.services.image_service import ImageService

logger = logging.getLogger("frame_ai.analysis")

SCENE_DISABLED_LIMITATION = "场景识别已关闭，未输出场景判断。"
LIGHTING_DISABLED_LIMITATION = "光线分析已关闭，未输出光线判断。"
COLOR_DISABLED_LIMITATION = "色彩分析已关闭，未输出色彩判断。"
COMPOSITION_DISABLED_LIMITATION = "构图分析已关闭，未输出构图判断。"
QUALITY_DISABLED_LIMITATION = "质量诊断已关闭，未输出技术质量与问题诊断。"

CandidateBuilder: TypeAlias = Callable[[DiagnosisContext], CandidateSet]


class AnalysisOutputError(ValueError):
    """Raised when model output cannot be grounded in the supplied evidence."""


class AnalysisTimeout(Exception):
    """The whole-task budget ran out before a report could be produced."""


class AnalysisOrchestrator:
    def __init__(
        self,
        settings: Settings,
        images: ImageService,
        providers: ProviderBundle,
        repository: SqliteAnalysisRepository,
        *,
        candidate_builder: CandidateBuilder = build_candidates,
    ) -> None:
        self._settings = settings
        self._images = images
        self._providers = providers
        self._repository = repository
        self._candidate_builder = candidate_builder

    def run(self, task_id: str) -> None:
        task = self._repository.get(task_id)
        if task is None or task.status is not TaskStatus.PENDING:
            return
        started = self._repository.mark_started(task_id)
        if started is None:
            logger.info("analysis_claim_lost analysis_id=%s", task_id)
            return
        deadline = time.monotonic() + self._settings.analysis_timeout_seconds

        stage = "preprocessing"
        stage_started = time.perf_counter()
        try:
            self._check_deadline(deadline)
            preprocessed = preprocess_image(
                self._images,
                started.image_id,
                max_edge=self._settings.analysis_max_edge,
                max_pixels=self._settings.max_image_pixels,
                max_bytes=self._settings.analysis_max_input_bytes,
            )
            if preprocessed.original_sha256 != started.image_sha256:
                raise AppError(
                    409,
                    "original_changed",
                    "The original image changed before analysis started.",
                )
            self._log_stage(started, stage, stage_started)

            stage = "vision"
            stage_started = time.perf_counter()
            self._repository.set_stage(task_id, TaskStage.VISION)
            self._check_deadline(deadline)
            measurements = self._measurements(preprocessed)
            vision = self._providers.vision.analyze(
                VisionRequest(
                    image=preprocessed.image,
                    options=started.options,
                    measurements=measurements,
                )
            )
            self._log_stage(started, stage, stage_started)

            stage = "features"
            stage_started = time.perf_counter()
            self._repository.set_stage(task_id, TaskStage.FEATURES)
            self._check_deadline(deadline)
            loaded = load_image(
                preprocessed.image.data,
                max_pixels=self._settings.max_image_pixels,
                preserve_alpha=False,
            )
            measurements = extract_features(
                loaded,
                display_width=preprocessed.original_width,
                display_height=preprocessed.original_height,
            )
            assignment = build_regions(
                vision.subjects,
                subject_detection=started.options.subject_detection,
            )
            region_samples = sample_regions(loaded, assignment)
            self._log_stage(started, stage, stage_started)

            stage = "diagnosis"
            stage_started = time.perf_counter()
            self._repository.set_stage(task_id, TaskStage.DIAGNOSIS)
            self._check_deadline(deadline)
            candidate_set = self._candidate_builder(
                DiagnosisContext(
                    vision=vision,
                    measurements=measurements,
                    options=started.options,
                    assignment=assignment,
                    region_samples=region_samples,
                )
            )
            decision = self._providers.decision.diagnose(
                DecisionRequest(
                    vision=vision,
                    measurements=measurements,
                    candidates=candidate_set.candidates,
                    options=started.options,
                )
            )
            validated = validate_decision(
                decision,
                candidate_set.candidates,
                tuple(region.id for region in assignment.regions),
            )
            report = build_analysis_report(
                task=started,
                settings=self._settings,
                providers=self._providers,
                preprocessed=preprocessed,
                measurements=measurements,
                vision=vision,
                decision=decision,
                assignment=assignment,
                candidate_set=candidate_set,
                validated=validated,
            )
            self._log_stage(started, stage, stage_started)
        except AppError as exc:
            self._fail(task_id, exc.code, exc.message)
        except ProviderError as exc:
            self._fail(task_id, _safe_provider_code(exc.code), exc.message)
        except AnalysisTimeout:
            self._fail(
                task_id,
                "analysis_timeout",
                "The analysis did not finish within its time budget.",
            )
        except ValidationError:
            self._fail(
                task_id,
                "analysis_invalid_output",
                "The analysis output did not pass the required schema.",
            )
        except (AnalysisOutputError, DecisionValidationError):
            self._fail(
                task_id,
                "analysis_invalid_output",
                "The analysis output did not pass validation.",
            )
        except Exception as exc:
            logger.error(
                "analysis_failed analysis_id=%s error_type=%s",
                task_id,
                type(exc).__name__,
            )
            self._fail(task_id, "analysis_failed", "The analysis could not be completed.")
        else:
            report_json = report.model_dump_json(by_alias=True)
            try:
                persisted = self._repository.complete_with_result(
                    task_id,
                    schema_version=REPORT_SCHEMA_VERSION,
                    is_mock=self._providers.is_mock,
                    report_json=report_json,
                )
            except Exception as exc:
                logger.error(
                    "analysis_result_persist_failed analysis_id=%s error_type=%s",
                    task_id,
                    type(exc).__name__,
                )
                self._fail(task_id, "analysis_failed", "The analysis could not be stored.")
                return
            if not persisted:
                logger.warning("analysis_result_dropped analysis_id=%s claim=lost", task_id)
                return
            logger.info(
                "analysis_completed analysis_id=%s image_id=%s attempts=%s is_mock=%s",
                task_id,
                started.image_id,
                started.attempts,
                self._providers.is_mock,
            )

    def _check_deadline(self, deadline: float) -> None:
        if time.monotonic() >= deadline:
            raise AnalysisTimeout

    def _measurements(self, preprocessed: PreprocessedImage) -> MeasurementSummary:
        loaded = load_image(
            preprocessed.image.data,
            max_pixels=self._settings.max_image_pixels,
            preserve_alpha=False,
        )
        return extract_features(
            loaded,
            display_width=preprocessed.original_width,
            display_height=preprocessed.original_height,
        )

    def _log_stage(
        self,
        task: AnalysisTaskRecord,
        stage: str,
        started: float,
    ) -> None:
        logger.info(
            "analysis_stage analysis_id=%s image_id=%s stage=%s duration_ms=%s",
            task.id,
            task.image_id,
            stage,
            round((time.perf_counter() - started) * 1000.0),
        )

    def _fail(self, task_id: str, code: str, message: str) -> None:
        logger.warning("analysis_failed analysis_id=%s error_code=%s", task_id, code)
        try:
            recorded = self._repository.mark_failed(task_id, code, message)
        except Exception:
            logger.error("analysis_failure_not_recorded analysis_id=%s", task_id)
            return
        if not recorded:
            logger.warning("analysis_failure_skipped analysis_id=%s claim=lost", task_id)


def _safe_provider_code(code: str) -> str:
    if code.endswith("_invalid_output"):
        return "analysis_invalid_output"
    return code


def build_analysis_report(
    *,
    task: AnalysisTaskRecord,
    settings: Settings,
    providers: ProviderBundle,
    preprocessed: PreprocessedImage,
    measurements: MeasurementSummary,
    vision: VisionResult,
    decision: DecisionResult,
    assignment: RegionAssignment,
    candidate_set: CandidateSet,
    validated: ValidatedDecision,
) -> AnalysisReport:
    options = task.options
    option_limitations = _option_limitations(options)
    limitations = _dedupe(
        (
            *preprocessed.limitations,
            *vision.limitations,
            *assignment.limitations,
            *candidate_set.limitations,
            *validated.limitations,
            *option_limitations,
        )
    )
    issues = _map_issues(
        validated.selections,
        candidate_set.candidates,
        validated.recommendations,
    )
    if not options.quality_diagnosis:
        issues = ()
    recommendations = (
        tuple(
            RecommendationReport(
                category=recommendation.category,
                priority=recommendation.priority,
                description=recommendation.description,
                target_regions=recommendation.target_regions,
            )
            for recommendation in validated.recommendations
        )
        if options.quality_diagnosis
        else ()
    )
    return AnalysisReport(
        analysis_id=UUID(task.id),
        image=ReportImage(
            id=UUID(task.image_id),
            width=preprocessed.original_width,
            height=preprocessed.original_height,
            aspect_ratio=measurements.aspect_ratio,
            sha256=task.image_sha256,
        ),
        engine=EngineInfo(
            vision_provider=settings.vision_provider,
            vision_model=providers.vision.model,
            decision_provider=settings.decision_provider,
            decision_model=providers.decision.model,
            prompt_version=REPORT_PROMPT_VERSION,
            analyzer_version=ANALYZER_VERSION,
            is_mock=providers.is_mock,
        ),
        scene=(
            vision.scene
            if options.scene_recognition
            else SceneResult(primary=SceneLabel.OTHER, confidence=0.0)
        ),
        subjects=assignment.subjects,
        regions=assignment.regions,
        lighting=(
            vision.lighting
            if options.lighting_analysis
            else LightingResult(
                direction=LightingDirection.UNKNOWN,
                type=LightingType.UNKNOWN,
                contrast=ContrastLevel.UNKNOWN,
                confidence=0.0,
            )
        ),
        color=(
            vision.color
            if options.color_analysis
            else ColorResult(
                temperature=ColorTemperature.UNKNOWN,
                saturation=SaturationLevel.UNKNOWN,
                harmony=ColorHarmony.UNKNOWN,
                confidence=0.0,
            )
        ),
        composition=(
            CompositionReport(
                balance=vision.composition.balance,
                subject_position=vision.composition.subject_position,
                negative_space=vision.composition.negative_space,
                occlusion=vision.composition.occlusion,
                subject_area_ratio=_primary_subject_area(assignment),
                horizon_tilt_deg=measurements.horizon_tilt_deg,
                confidence=vision.composition.confidence,
            )
            if options.composition_analysis
            else CompositionReport(
                balance=CompositionBalance.UNKNOWN,
                subject_position=SubjectPosition.UNKNOWN,
                negative_space=NegativeSpace.UNKNOWN,
                occlusion=Occlusion.UNKNOWN,
                subject_area_ratio=None,
                horizon_tilt_deg=None,
                confidence=0.0,
            )
        ),
        technical_quality=(
            decision.technical_quality
            if options.quality_diagnosis
            else TechnicalQualityResult(
                exposure=ExposureQuality.UNKNOWN,
                sharpness=SharpnessQuality.UNKNOWN,
                noise=NoiseLevel.UNKNOWN,
                confidence=0.0,
            )
        ),
        measurements=MeasurementsReport(
            luminance=LuminanceMeasurement(
                mean=measurements.luminance_mean,
                std=measurements.luminance_std,
                p1=measurements.luminance_p1,
                p5=measurements.luminance_p5,
                p50=measurements.luminance_p50,
                p95=measurements.luminance_p95,
                p99=measurements.luminance_p99,
                histogram32=measurements.histogram32,
            ),
            clipping=ClippingMeasurement(
                highlights_pct=measurements.highlights_pct,
                shadows_pct=measurements.shadows_pct,
            ),
            color=ColorMeasurement(
                mean_rgb=measurements.mean_rgb_linear,
                cast=CastMeasurement(
                    temperature=measurements.cast_temperature,
                    tint=measurements.cast_tint,
                ),
                saturation_mean=measurements.saturation_mean,
                saturation_p95=measurements.saturation_p95,
                saturation_p10=measurements.saturation_p10,
                saturation_p50=measurements.saturation_p50,
                saturation_p90=measurements.saturation_p90,
                color_concentration=measurements.color_concentration,
                rgb_histogram=measurements.rgb_histogram,
                hsv_histogram=measurements.hsv_histogram,
            ),
            detail=DetailMeasurement(
                sharpness=measurements.sharpness,
                noise_estimate=measurements.noise_estimate,
                gradient_anisotropy=measurements.gradient_anisotropy,
            ),
            composition=CompositionMeasurement(
                edge_density_grid_3x3=measurements.edge_density_grid_3x3,
                brightness_centroid=(
                    measurements.brightness_centroid_x,
                    measurements.brightness_centroid_y,
                ),
                horizon_tilt_deg=measurements.horizon_tilt_deg,
            ),
        ),
        issues=issues,
        recommendations=recommendations,
        limitations=limitations,
        created_at=task.created_at,
        completed_at=datetime.now(UTC),
    )


def _map_issues(
    selections: tuple[IssueSelection, ...],
    candidates: tuple[IssueCandidate, ...],
    recommendations: tuple[RecommendationResult, ...],
) -> tuple[IssueReport, ...]:
    by_id = {candidate.id: candidate for candidate in candidates}
    issues: list[IssueReport] = []
    for index, selection in enumerate(selections, start=1):
        candidate = by_id.get(selection.candidate_id)
        if candidate is None:
            raise AnalysisOutputError("The decision referenced an unknown issue candidate.")
        issues.append(
            IssueReport(
                id=f"issue_{index:03d}",
                type=candidate.type,
                severity=selection.severity,
                confidence=selection.confidence,
                evidence=selection.evidence,
                suggestion=_suggestion(
                    candidate.type,
                    selection.region_ids,
                    recommendations,
                ),
                region_ids=selection.region_ids,
            )
        )
    return tuple(issues)


def _suggestion(
    issue_type: IssueType,
    region_ids: tuple[str, ...],
    recommendations: tuple[RecommendationResult, ...],
) -> str:
    category, fallback = ISSUE_GUIDANCE[issue_type]
    targets = set(region_ids)
    for recommendation in recommendations:
        if recommendation.category is category and set(recommendation.target_regions) == targets:
            return recommendation.description
    return fallback


def _primary_subject_area(assignment: RegionAssignment) -> float | None:
    primary = next(
        (subject for subject in assignment.subjects if subject.role is SubjectRole.PRIMARY),
        None,
    )
    if primary is None:
        return None
    return round(primary.bbox.width * primary.bbox.height, 4)


def _option_limitations(options: AnalysisOptions) -> tuple[str, ...]:
    limitations: list[str] = []
    if not options.scene_recognition:
        limitations.append(SCENE_DISABLED_LIMITATION)
    if not options.lighting_analysis:
        limitations.append(LIGHTING_DISABLED_LIMITATION)
    if not options.color_analysis:
        limitations.append(COLOR_DISABLED_LIMITATION)
    if not options.composition_analysis:
        limitations.append(COMPOSITION_DISABLED_LIMITATION)
    if not options.quality_diagnosis:
        limitations.append(QUALITY_DISABLED_LIMITATION)
    return tuple(limitations)


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return tuple(ordered)


__all__ = [
    "AnalysisOrchestrator",
    "AnalysisOutputError",
    "CandidateBuilder",
    "build_analysis_report",
]
