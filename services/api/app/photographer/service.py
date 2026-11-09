from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import BoundedSemaphore, Lock
from typing import TYPE_CHECKING, TypeVar
from uuid import UUID, uuid4

from pydantic import ValidationError

from app.ai.base import (
    PatchRequest,
    PhotographyPlannerProvider,
    PlannerRequest,
)
from app.ai.contracts import SceneLabel
from app.ai.errors import ProviderError
from app.core.errors import AppError
from app.models.analysis_report import AnalysisReport
from app.models.analysis_task import TaskStatus
from app.models.photographer import (
    MAX_NOTES,
    ConversionModeListResponse,
    CreativeDirection,
    CritiqueApplyRequest,
    CritiqueApplyResponse,
    CritiqueResponse,
    FeedbackAction,
    FeedbackRubric,
    FeedbackSource,
    PatchDraft,
    PhotographerCritiqueRequest,
    PhotographerFeedbackListResponse,
    PhotographerFeedbackRequest,
    PhotographerFeedbackResponse,
    PhotographerPatchRequest,
    PhotographerPatchResponse,
    PhotographerPlanRequest,
    PhotographerPlanResponse,
    PhotographerPreferences,
    PhotographerStyleId,
    PlannerDraft,
    PlannerMode,
    ProviderInfo,
    StyleCategory,
    StyleDefinition,
    StyleListResponse,
)
from app.models.recipe import EditRecipe, recipe_hash, stored_recipe_json
from app.photographer.critique import build_critique
from app.photographer.diagnosis import AnalysisAdvice, diagnose
from app.photographer.direction import determine_direction
from app.photographer.feedback import (
    changed_paths,
    derive_action,
    rubric_values,
    summarize,
)
from app.photographer.generator import generate_recipe
from app.photographer.modes import (
    conversion_mode_infos,
    resolve_conversion_mode,
)
from app.photographer.patch import apply_patch
from app.photographer.styles import STYLE_CATALOG, get_style
from app.photographer.validator import RecipeValidationError, validate_critique
from app.repositories.photographer_repo import (
    MAX_FEEDBACK_SCAN,
    PhotographerFeedbackRecord,
    PhotographerPlanRecord,
    SqlitePhotographerFeedbackRepository,
    SqlitePhotographerPlanRepository,
)

if TYPE_CHECKING:
    from app.services.analysis_task_service import AnalysisTaskService
    from app.services.image_service import ImageService
    from app.services.session_service import SessionService

logger = logging.getLogger("frame_ai.photographer")
_ResultT = TypeVar("_ResultT")
PATCH_MODE = "chat"


class PhotographerService:
    def __init__(
        self,
        planner: PhotographyPlannerProvider,
        *,
        max_concurrency: int = 2,
        analysis: AnalysisTaskService | None = None,
        sessions: SessionService | None = None,
        images: ImageService | None = None,
        plans: SqlitePhotographerPlanRepository | None = None,
        feedback: SqlitePhotographerFeedbackRepository | None = None,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self._planner = planner
        self._planner_lock = Lock()
        self._slots = BoundedSemaphore(max_concurrency)
        self._analysis = analysis
        self._sessions = sessions
        self._images = images
        self._plans = plans
        self._feedback = feedback

    @property
    def planner(self) -> PhotographyPlannerProvider:
        with self._planner_lock:
            return self._planner

    def update_planner(self, planner: PhotographyPlannerProvider) -> None:
        with self._planner_lock:
            self._planner = planner
        logger.info(
            "planner_swapped provider=%s model=%s is_mock=%s",
            planner.name,
            planner.model,
            planner.is_mock,
        )

    def resolve_style(
        self,
        mode: PlannerMode,
        style_id: PhotographerStyleId | None,
    ) -> StyleDefinition | None:
        if mode is PlannerMode.AUTO:
            return None
        if style_id is None:
            raise AppError(422, "style_required", "styleId is required when mode is 'style'.")
        style = get_style(style_id)
        if style is None or not style.enabled:
            raise AppError(404, "style_not_found", "The requested style is not available.")
        return style

    def list_styles(
        self,
        *,
        category: StyleCategory | None = None,
        scene: SceneLabel | None = None,
        include_disabled: bool = False,
    ) -> StyleListResponse:
        styles = tuple(
            style
            for style in STYLE_CATALOG
            if (category is None or style.category is category)
            and (scene is None or scene in style.supported_scenes)
            and (include_disabled or style.enabled)
        )
        return StyleListResponse(styles=styles)

    def style_detail(self, style_id: PhotographerStyleId) -> StyleDefinition:
        style = get_style(style_id)
        if style is None or not style.enabled:
            raise AppError(404, "style_not_found", "The requested style is not available.")
        return style

    def list_conversion_modes(self) -> ConversionModeListResponse:
        return ConversionModeListResponse(modes=conversion_mode_infos())

    def analyze(
        self,
        analysis: AnalysisReport,
        preferences: PhotographerPreferences | None = None,
        *,
        style: StyleDefinition | None = None,
        style_strength: float | None = None,
    ) -> AnalysisAdvice:
        """Deterministic diagnosis and direction; no provider call and no public route."""
        effective = preferences or PhotographerPreferences()
        diagnosis = diagnose(analysis)
        direction = determine_direction(
            analysis,
            diagnosis,
            effective,
            style,
            style_strength=style_strength,
        )
        return AnalysisAdvice(diagnosis=diagnosis, direction=direction)

    def plan(self, request: PhotographerPlanRequest) -> PhotographerPlanResponse:
        analysis_service, sessions, images, plans = self._plan_dependencies()
        session = sessions.get(str(request.session_id))
        image_id = str(session.image_id)
        report = self._require_matching_report(
            analysis_service, images, image_id, request.analysis_id
        )

        style = self.resolve_style(request.mode, request.style_id)
        strength = _style_strength(request, style)
        conversion_mode = resolve_conversion_mode(request.mode, request.conversion_mode)
        current_recipe = session.revision.recipe
        planner_request = PlannerRequest(
            analysis=report,
            recipe=current_recipe,
            preferences=request.preferences,
            mode=request.mode,
            style=style,
            style_strength=strength,
        )

        degraded = False
        fallback_warnings: list[str] = []
        try:
            draft = self.draft_plan(planner_request)
        except AppError as exc:
            if exc.code != "photographer_invalid_output":
                raise
            draft = self._deterministic_draft(report, request.preferences, style, strength)
            degraded = True
            fallback_warnings.append("模型输出不可用，已回退到确定性规则方案。")

        try:
            generated = generate_recipe(
                current_recipe,
                report,
                draft,
                request.preferences,
                style,
                strength,
                conversion_mode=conversion_mode,
            )
        except (RecipeValidationError, ValidationError) as exc:
            if degraded:
                raise _invalid_recipe(exc) from exc
            draft = self._deterministic_draft(report, request.preferences, style, strength)
            try:
                generated = generate_recipe(
                    current_recipe,
                    report,
                    draft,
                    request.preferences,
                    style,
                    strength,
                    conversion_mode=conversion_mode,
                )
            except (RecipeValidationError, ValidationError) as fallback_exc:
                raise _invalid_recipe(fallback_exc) from fallback_exc
            degraded = True
            fallback_warnings.append("模型方案未通过校验，已回退到确定性规则方案。")

        planner = self.planner
        warnings = _merge_notes(fallback_warnings, draft.warnings, generated.warnings)
        limitations = _merge_notes(draft.limitations, generated.limitations)
        response = PhotographerPlanResponse(
            plan_id=uuid4(),
            analysis_id=report.analysis_id,
            session_id=session.session_id,
            image_id=session.image_id,
            mode=request.mode,
            is_mock=planner.is_mock,
            degraded=degraded,
            provider=ProviderInfo(
                name=planner.name,
                model=planner.model,
                prompt_version=planner.prompt_version,
            ),
            diagnosis=draft.diagnosis,
            direction=draft.direction,
            style_id=None if style is None else style.id,
            style_version=None if style is None else style.version,
            style_strength=strength,
            conversion_mode=conversion_mode,
            recipe=generated.recipe,
            changes=generated.changes,
            warnings=warnings,
            limitations=limitations,
            confidence=draft.confidence,
            confidence_note=draft.diagnosis.confidence_note,
        )
        self._persist(plans, response, style, strength)
        logger.info(
            "photographer_plan plan_id=%s session_id=%s analysis_id=%s mode=%s "
            "conversion_mode=%s provider=%s model=%s is_mock=%s degraded=%s changes=%s",
            response.plan_id,
            response.session_id,
            response.analysis_id,
            response.mode.value,
            None if conversion_mode is None else conversion_mode.value,
            planner.name,
            planner.model,
            response.is_mock,
            response.degraded,
            len(response.changes),
        )
        return response

    def patch(self, request: PhotographerPatchRequest) -> PhotographerPatchResponse:
        """Apply one natural-language instruction to the recipe the user is looking at."""
        analysis_service, sessions, images, plans = self._plan_dependencies()
        record = plans.get(str(request.plan_id))
        if record is None:
            raise AppError(
                404,
                "plan_not_found",
                "The referenced photography plan does not exist.",
                {"planId": str(request.plan_id)},
            )
        session = sessions.get(record.session_id)
        image_id = str(session.image_id)
        if record.image_id.lower() != image_id:
            raise AppError(
                409,
                "image_analysis_mismatch",
                "The plan belongs to a different image than the current session.",
                {"imageId": image_id, "planId": record.id},
            )
        report = self._require_matching_report(
            analysis_service, images, image_id, UUID(record.analysis_id)
        )

        current_recipe = _anchor_recipe(record, session.revision.recipe)
        draft = self.draft_adjust(
            PatchRequest(
                analysis=report,
                recipe=current_recipe,
                instruction=request.instruction,
                preferences=request.preferences,
                direction=_stored_direction(record),
            )
        )
        try:
            patched = apply_patch(current_recipe, report, draft, request.preferences)
        except (RecipeValidationError, ValidationError) as exc:
            raise _invalid_recipe(exc) from exc

        planner = self.planner
        response = PhotographerPatchResponse(
            patch_id=uuid4(),
            plan_id=request.plan_id,
            supported=draft.supported,
            recipe=patched.recipe,
            changes=patched.changes,
            reason=draft.reason,
            warnings=patched.warnings,
            limitations=patched.limitations,
            unsupported=patched.unsupported,
        )
        self._persist_patch(plans, record, response, draft)
        # The instruction itself is request-scoped: only its length is logged.
        logger.info(
            "photographer_patch patch_id=%s plan_id=%s session_id=%s supported=%s "
            "instruction_chars=%s changes=%s provider=%s model=%s is_mock=%s",
            response.patch_id,
            record.id,
            record.session_id,
            response.supported,
            len(request.instruction),
            len(response.changes),
            planner.name,
            planner.model,
            planner.is_mock,
        )
        return response

    def critique(self, request: PhotographerCritiqueRequest) -> CritiqueResponse:
        """Deterministic commentary on one completed analysis report."""
        analysis_service, _sessions, images, _plans = self._plan_dependencies()
        report = self._completed_report(analysis_service, request.analysis_id)
        image, _ = images.get_original(str(report.image.id))
        if report.image.sha256.lower() != image.sha256.lower():
            raise AppError(
                409,
                "image_analysis_mismatch",
                "The analysis report does not belong to the stored image.",
                {"imageId": str(report.image.id), "analysisId": str(report.analysis_id)},
            )

        critique = build_critique(report, request.preferences)
        try:
            validate_critique(report, critique)
        except RecipeValidationError as exc:
            raise AppError(
                500,
                "critique_invalid",
                "The generated critique failed evidence validation.",
                {"issues": list(exc.issues)},
            ) from exc
        logger.info(
            "photographer_critique analysis_id=%s is_mock=%s points=%s suggestions=%s",
            report.analysis_id,
            critique.is_mock,
            len(critique.strengths)
            + len(critique.technical.objective)
            + len(critique.technical.possible_issues)
            + len(critique.creative),
            len(critique.suggestions),
        )
        return critique

    def apply_critique(self, request: CritiqueApplyRequest) -> CritiqueApplyResponse:
        """Route one critique suggestion through the same patch validation pipeline."""
        analysis_service, sessions, _images, _plans = self._plan_dependencies()
        session = sessions.get(str(request.session_id))
        image_id = str(session.image_id)
        report = self._resolve_report(analysis_service, None, image_id)

        draft = PatchDraft(
            supported=True,
            adjustments=request.patch,
            reason="按点评建议调整，只移动该建议涉及的参数。",
            limitations=("点评建议只调整全局参数，不会改动曲线、HSL、色彩分级、裁切与蒙版。",),
        )
        try:
            patched = apply_patch(session.revision.recipe, report, draft, request.preferences)
        except (RecipeValidationError, ValidationError) as exc:
            raise _invalid_recipe(exc) from exc

        response = CritiqueApplyResponse(
            patch_id=uuid4(),
            recipe=patched.recipe,
            changes=patched.changes,
            reason=draft.reason,
            warnings=patched.warnings,
            limitations=patched.limitations,
            unsupported=patched.unsupported,
        )
        logger.info(
            "photographer_critique_apply patch_id=%s session_id=%s changes=%s",
            response.patch_id,
            session.session_id,
            len(response.changes),
        )
        return response

    def record_feedback(self, request: PhotographerFeedbackRequest) -> PhotographerFeedbackResponse:
        """Store one user decision. Preference is never presented as measured quality."""
        _analysis, sessions, _images, plans = self._plan_dependencies()
        store = self._feedback_store()

        session = sessions.get(str(request.session_id))
        plan = None
        if request.plan_id is not None:
            plan = plans.get(str(request.plan_id))
            if plan is None:
                raise AppError(404, "plan_not_found", "The referenced plan does not exist.")
            if plan.session_id != str(session.session_id):
                raise AppError(
                    409,
                    "plan_session_mismatch",
                    "The referenced plan belongs to another session.",
                    {"planId": str(request.plan_id)},
                )

        revision = None
        if request.revision_id is not None:
            revision = sessions.get_revision(str(session.session_id), request.revision_id)

        plan_recipe = None if plan is None else _stored_recipe(plan)
        baseline = plan_recipe
        if baseline is None and revision is not None and revision.parent_id is not None:
            baseline = sessions.get_revision(str(session.session_id), revision.parent_id).recipe
        action = derive_action(
            action=request.action,
            plan_recipe=plan_recipe,
            revision_recipe=None if revision is None else revision.recipe,
        )
        paths = () if revision is None else changed_paths(baseline, revision.recipe)

        record = PhotographerFeedbackRecord(
            id=str(uuid4()),
            image_id=str(session.image_id),
            session_id=str(session.session_id),
            plan_id=None if request.plan_id is None else str(request.plan_id),
            revision_id=None if request.revision_id is None else str(request.revision_id),
            source=None if request.source is None else request.source.value,
            action=action.value,
            changed_paths=paths,
            rubric=rubric_values(request.rubric),
            is_mock=plan.is_mock if plan is not None else self.planner.is_mock,
            degraded=False if plan is None else plan.degraded,
            created_at=datetime.now(UTC),
        )
        try:
            stored = store.record(record)
        except sqlite3.Error as exc:
            logger.error(
                "photographer_feedback_store_failed session_id=%s error_type=%s",
                record.session_id,
                type(exc).__name__,
            )
            raise AppError(500, "storage_error", "The feedback could not be saved.") from exc

        logger.info(
            "photographer_feedback id=%s session_id=%s action=%s source=%s changes=%s is_mock=%s",
            stored.id,
            stored.session_id,
            stored.action,
            stored.source,
            len(stored.changed_paths),
            stored.is_mock,
        )
        return _feedback_response(stored)

    def list_feedback(
        self,
        *,
        session_id: UUID | None = None,
        image_id: UUID | None = None,
        plan_id: UUID | None = None,
        limit: int = 50,
    ) -> PhotographerFeedbackListResponse:
        """Newest records first, with a summary over the whole scanned window."""
        store = self._feedback_store()
        records = store.list_recent(
            session_id=None if session_id is None else str(session_id),
            image_id=None if image_id is None else str(image_id),
            plan_id=None if plan_id is None else str(plan_id),
            limit=MAX_FEEDBACK_SCAN,
        )
        return PhotographerFeedbackListResponse(
            items=tuple(_feedback_response(record) for record in records[:limit]),
            summary=summarize(records),
        )

    def delete_feedback(self, feedback_id: UUID) -> None:
        store = self._feedback_store()
        if not store.delete(str(feedback_id)):
            raise AppError(404, "feedback_not_found", "The feedback record does not exist.")
        logger.info("photographer_feedback_deleted id=%s", feedback_id)

    def _feedback_store(self) -> SqlitePhotographerFeedbackRepository:
        if self._feedback is None:
            raise AppError(503, "service_unavailable", "The feedback service is not ready.")
        return self._feedback

    def _plan_dependencies(
        self,
    ) -> tuple[
        AnalysisTaskService,
        SessionService,
        ImageService,
        SqlitePhotographerPlanRepository,
    ]:
        if (
            self._analysis is None
            or self._sessions is None
            or self._images is None
            or self._plans is None
        ):
            raise AppError(
                503,
                "service_unavailable",
                "The photography plan service is not ready.",
            )
        return self._analysis, self._sessions, self._images, self._plans

    def _resolve_report(
        self,
        analysis_service: AnalysisTaskService,
        analysis_id: UUID | None,
        image_id: str,
    ) -> AnalysisReport:
        if analysis_id is None:
            report = analysis_service.latest_completed(image_id)
            if report is None:
                raise AppError(
                    409,
                    "analysis_required",
                    "The image needs a completed analysis before planning.",
                    {"imageId": image_id},
                )
            return report
        return self._completed_report(analysis_service, analysis_id, image_id=image_id)

    def _completed_report(
        self,
        analysis_service: AnalysisTaskService,
        analysis_id: UUID,
        *,
        image_id: str | None = None,
    ) -> AnalysisReport:
        status = analysis_service.status(str(analysis_id))
        if status.status is not TaskStatus.COMPLETED:
            detail: dict[str, str] = {"analysisId": str(analysis_id)}
            if image_id is not None:
                detail["imageId"] = image_id
            raise AppError(
                409,
                "analysis_required",
                "The image needs a completed analysis before planning.",
                detail,
            )
        if status.result is None:
            raise AppError(
                500,
                "analysis_failed",
                "The analysis result is not available.",
            )
        return status.result

    def _require_matching_report(
        self,
        analysis_service: AnalysisTaskService,
        images: ImageService,
        image_id: str,
        analysis_id: UUID | None,
    ) -> AnalysisReport:
        report = self._resolve_report(analysis_service, analysis_id, image_id)
        image, _ = images.get_original(image_id)
        if (
            str(report.image.id).lower() != image_id
            or report.image.sha256.lower() != image.sha256.lower()
        ):
            raise AppError(
                409,
                "image_analysis_mismatch",
                "The analysis report does not belong to the current image.",
                {"imageId": image_id, "analysisId": str(report.analysis_id)},
            )
        return report

    def _deterministic_draft(
        self,
        report: AnalysisReport,
        preferences: PhotographerPreferences,
        style: StyleDefinition | None,
        strength: float | None,
    ) -> PlannerDraft:
        advice = self.analyze(report, preferences, style=style, style_strength=strength)
        return PlannerDraft(
            diagnosis=advice.diagnosis,
            direction=advice.direction,
            confidence=advice.diagnosis.confidence,
        )

    def _persist(
        self,
        plans: SqlitePhotographerPlanRepository,
        response: PhotographerPlanResponse,
        style: StyleDefinition | None,
        strength: float | None,
    ) -> None:
        record = PhotographerPlanRecord(
            id=str(response.plan_id),
            image_id=str(response.image_id),
            session_id=str(response.session_id),
            analysis_id=str(response.analysis_id),
            mode=response.mode.value,
            style_id=None if style is None else style.id,
            style_version=None if style is None else style.version,
            style_strength=strength,
            conversion_mode=(
                None if response.conversion_mode is None else response.conversion_mode.value
            ),
            provider=response.provider.name,
            model=response.provider.model,
            prompt_version=response.provider.prompt_version,
            is_mock=response.is_mock,
            degraded=response.degraded,
            confidence=response.confidence,
            plan_json=response.model_dump_json(by_alias=True),
            recipe_json=stored_recipe_json(response.recipe),
            recipe_hash=recipe_hash(response.recipe),
            created_at=datetime.now(UTC),
        )
        try:
            plans.create(record)
        except sqlite3.Error as exc:
            logger.error(
                "photographer_plan_store_failed plan_id=%s error_type=%s",
                response.plan_id,
                type(exc).__name__,
            )
            raise AppError(
                500,
                "storage_error",
                "The photography plan could not be saved.",
            ) from exc

    def _persist_patch(
        self,
        plans: SqlitePhotographerPlanRepository,
        source: PhotographerPlanRecord,
        response: PhotographerPatchResponse,
        draft: PatchDraft,
    ) -> None:
        planner = self.planner
        record = PhotographerPlanRecord(
            id=str(response.patch_id),
            image_id=source.image_id,
            session_id=source.session_id,
            analysis_id=source.analysis_id,
            mode=PATCH_MODE,
            style_id=None,
            style_version=None,
            style_strength=None,
            provider=planner.name,
            model=planner.model,
            prompt_version=planner.prompt_version,
            is_mock=planner.is_mock,
            degraded=False,
            confidence=draft.confidence,
            plan_json=response.model_dump_json(by_alias=True),
            recipe_json=stored_recipe_json(response.recipe),
            recipe_hash=recipe_hash(response.recipe),
            created_at=datetime.now(UTC),
        )
        try:
            plans.create(record)
        except sqlite3.Error as exc:
            logger.error(
                "photographer_patch_store_failed patch_id=%s error_type=%s",
                response.patch_id,
                type(exc).__name__,
            )
            raise AppError(
                500,
                "storage_error",
                "The photography patch could not be saved.",
            ) from exc

    def draft_plan(self, request: PlannerRequest) -> PlannerDraft:
        planner = self.planner
        return self._invoke("planner", planner, lambda: planner.plan(request))

    def draft_adjust(self, request: PatchRequest) -> PatchDraft:
        planner = self.planner
        return self._invoke("patch", planner, lambda: planner.adjust(request))

    def check_connection(self, *, timeout: float | None = None) -> int:
        planner = self.planner
        return self._invoke("check", planner, lambda: planner.check_connection(timeout=timeout))

    def _invoke(
        self,
        stage: str,
        planner: PhotographyPlannerProvider,
        action: Callable[[], _ResultT],
    ) -> _ResultT:
        with self._slot():
            started = time.perf_counter()
            try:
                result = action()
            except ProviderError as exc:
                latency_ms = round((time.perf_counter() - started) * 1000.0)
                logger.warning(
                    "planner_call provider=%s model=%s stage=%s outcome=error code=%s "
                    "latency_ms=%s",
                    planner.name,
                    planner.model,
                    stage,
                    exc.code,
                    latency_ms,
                )
                raise _map_provider_error(exc) from exc
            latency_ms = round((time.perf_counter() - started) * 1000.0)
            logger.info(
                "planner_call provider=%s model=%s stage=%s outcome=ok latency_ms=%s",
                planner.name,
                planner.model,
                stage,
                latency_ms,
            )
            return result

    @contextmanager
    def _slot(self) -> Iterator[None]:
        if not self._slots.acquire(blocking=False):
            raise AppError(
                503,
                "photographer_busy",
                "Too many photography planning requests are running.",
            )
        try:
            yield
        finally:
            self._slots.release()


def _stored_recipe(record: PhotographerPlanRecord) -> EditRecipe:
    return EditRecipe.model_validate_json(record.recipe_json)


def _feedback_response(record: PhotographerFeedbackRecord) -> PhotographerFeedbackResponse:
    return PhotographerFeedbackResponse(
        id=UUID(record.id),
        session_id=UUID(record.session_id),
        image_id=UUID(record.image_id),
        plan_id=None if record.plan_id is None else UUID(record.plan_id),
        revision_id=None if record.revision_id is None else UUID(record.revision_id),
        source=None if record.source is None else FeedbackSource(record.source),
        action=FeedbackAction(record.action),
        changed_paths=record.changed_paths,
        rubric=None if record.rubric is None else FeedbackRubric.model_validate(record.rubric),
        is_mock=record.is_mock,
        degraded=record.degraded,
        created_at=record.created_at,
    )


def _anchor_recipe(
    record: PhotographerPlanRecord,
    committed: EditRecipe,
) -> EditRecipe:
    """Continue a chat chain from the recipe the previous turn produced.

    A turn anchored on a plan still starts from the committed revision: an
    unaccepted proposal must not overwrite edits the user saved meanwhile.
    """
    if record.mode != PATCH_MODE:
        return committed
    try:
        return EditRecipe.model_validate_json(record.recipe_json)
    except ValidationError:
        return committed


def _stored_direction(record: PhotographerPlanRecord) -> CreativeDirection | None:
    """Reuse the direction from the plan the chat turn continues; chat rows have none."""
    if record.mode == PATCH_MODE:
        return None
    try:
        return PhotographerPlanResponse.model_validate_json(record.plan_json).direction
    except ValidationError:
        return None


def _style_strength(
    request: PhotographerPlanRequest,
    style: StyleDefinition | None,
) -> float | None:
    if style is None:
        return None
    return style.default_strength if request.style_strength is None else request.style_strength


def _merge_notes(*groups: Iterable[str]) -> tuple[str, ...]:
    merged = [note for group in groups for note in group]
    return tuple(dict.fromkeys(merged))[:MAX_NOTES]


def _invalid_recipe(error: RecipeValidationError | ValidationError) -> AppError:
    if isinstance(error, RecipeValidationError):
        issues = list(error.issues)
    else:
        issues = [str(item.get("msg", "invalid recipe")) for item in error.errors()]
    return AppError(
        422,
        "photographer_recipe_invalid",
        "The generated recipe could not be validated.",
        {"issues": issues},
    )


def _map_provider_error(error: ProviderError) -> AppError:
    suffix = error.code
    for prefix in ("planner_", "patch_", "check_"):
        if suffix.startswith(prefix):
            suffix = suffix[len(prefix) :]
            break

    details = {"retryable": error.retryable}
    if suffix == "provider_budget_exceeded":
        return AppError(
            429,
            "photographer_budget_exceeded",
            "The daily model usage limit has been reached.",
            {"retryable": False, **error.details},
        )
    if suffix == "provider_usage_unavailable":
        return AppError(
            503,
            "photographer_usage_unavailable",
            "Usage tracking is temporarily unavailable.",
            {"retryable": False},
        )
    if suffix == "provider_timeout":
        return AppError(
            504,
            "photographer_timeout",
            "The photography model did not respond before the timeout.",
            details,
        )
    if suffix in {"provider_unavailable", "provider_rate_limited"}:
        return AppError(
            503,
            "photographer_unavailable",
            "The photography model is temporarily unavailable.",
            details,
        )
    if suffix in {"invalid_output", "provider_response_too_large"}:
        return AppError(
            502,
            "photographer_invalid_output",
            "The photography model returned an unusable response.",
            details,
        )
    return AppError(
        502,
        "photographer_provider_error",
        "The photography model request failed.",
        details,
    )


__all__ = ["PhotographerService"]
