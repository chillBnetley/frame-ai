from __future__ import annotations

import logging
import threading
import time
from uuid import uuid4

from app.ai.base import PhotographyPlannerProvider, StyleAuthoringRequest
from app.ai.errors import ProviderError
from app.ai.prompts import STYLE_AUTHORING_PROMPT_VERSION
from app.core.errors import AppError
from app.models.personal_style import (
    PersonalStyleChangeSource,
    PersonalStyleDefinition,
    PersonalStyleDetailResponse,
    PersonalStyleHints,
    PersonalStyleProfile,
    PersonalStyleSource,
)
from app.models.photographer import DirectionConstraint, StyleEnvelope
from app.models.recipe import StyleId
from app.models.style_authoring import (
    CustomStyleParseRequest,
    CustomStyleParseResponse,
    CustomStyleRefineApplyRequest,
    CustomStyleRefineRequest,
    CustomStyleRefineResponse,
    CustomStyleSaveRequest,
    StyleAuthoringDraft,
    StyleAuthoringProviderInfo,
)
from app.models.style_profile import StyleSceneFit, StyleSource
from app.repositories.personal_style_repo import (
    PersonalStyleRecord,
    PersonalStyleVersionConflictError,
    SqlitePersonalStyleRepository,
)
from app.services.personal_style_service import PersonalStyleService
from app.services.provider_settings_service import ProviderSettingsService

logger = logging.getLogger("frame_ai.custom_style")

_CUSTOM_SOURCE = StyleSource(
    title="自然语言自定义风格",
    license="用户私有，不用于模型训练",
)
_AVOID_CONSTRAINTS = {
    "oversaturated": DirectionConstraint.AVOID_EXTREME_SATURATION,
    "crushed_blacks": DirectionConstraint.PRESERVE_SHADOW_DETAIL,
    "clipped_highlights": DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
    "color_cast": DirectionConstraint.AVOID_COLOR_CAST,
    "unnatural_skin": DirectionConstraint.PRESERVE_SKIN_TONE,
    "heavy_filter": DirectionConstraint.NATURAL_LOOK,
    "over_sharpened": DirectionConstraint.NATURAL_LOOK,
    "flat_contrast": DirectionConstraint.AVOID_EXTREME_CONTRAST,
}
_CONFIRMED_OVERRIDES = (
    "name",
    "description",
    "sceneFit.suitable",
    "personal.targets",
    "personal.avoid",
    "personal.protected",
    "traits.color_tendency",
    "traits.color_relationships",
    "traits.color_saturation",
    "traits.light_contrast",
    "traits.light_shadows",
    "traits.light_highlights",
    "traits.light_expression",
    "traits.texture_grain",
    "traits.texture_sharpness",
    "traits.texture_detail",
)


def _not_found() -> AppError:
    return AppError(404, "personal_style_not_found", "The personal style is not available.")


def _next_version(version: str) -> str:
    major, _, minor = version.partition(".")
    return f"{major}.{int(minor) + 1}"


def _engine_style(scenes: tuple[object, ...]) -> StyleId:
    values = {getattr(scene, "value", str(scene)) for scene in scenes}
    if "street" in values:
        return "street"
    if "portrait" in values:
        return "portrait"
    if "landscape" in values or "nature" in values:
        return "landscape"
    if "architecture" in values or "night" in values:
        return "cinematic"
    return "natural"


def _envelope_for(targets: dict[str, float]) -> StyleEnvelope:
    if targets.get("saturation", 0.0) <= -50.0:
        return StyleEnvelope(saturation=100.0, vibrance=40.0, grain=15.0)
    saturation = abs(targets.get("saturation", 0.0)) + 5.0
    contrast = abs(targets.get("contrast", 0.0)) + 5.0
    grain = abs(targets.get("grain", 0.0)) + 5.0
    return StyleEnvelope(
        saturation=min(max(saturation, 25.0), 80.0),
        vibrance=20.0,
        contrast=min(max(contrast, 25.0), 60.0),
        grain=min(max(grain, 15.0), 30.0),
    )


def _profile_from_draft(
    draft: StyleAuthoringDraft,
    *,
    style_id: str,
    version: str,
    base: PersonalStyleProfile | None,
) -> PersonalStyleProfile:
    constraints = tuple(
        dict.fromkeys(
            (
                *(base.constraints if base is not None else ()),
                *draft.protected,
                *(
                    _AVOID_CONSTRAINTS[effect.value]
                    for effect in draft.avoid
                    if effect.value in _AVOID_CONSTRAINTS
                ),
            )
        )
    )[:11]
    source = base.personal.source if base is not None else PersonalStyleSource.CUSTOM
    overrides = tuple(
        dict.fromkeys((*(base.personal.user_overrides if base else ()), *_CONFIRMED_OVERRIDES))
    )[:40]
    personal = PersonalStyleHints(
        source=source,
        confidence=draft.confidence,
        targets=draft.targets,
        scene_targets=base.personal.scene_targets if base is not None else {},
        protected=draft.protected,
        avoid=draft.avoid,
        user_overrides=overrides,
        sample_count=base.personal.sample_count if base is not None else 0,
        anomaly_count=base.personal.anomaly_count if base is not None else 0,
    )
    return PersonalStyleProfile(
        id=style_id,
        version=version,
        name=draft.name,
        description=draft.description,
        philosophy=(
            base.philosophy if base is not None else "由自然语言创建的个人视觉风格。"
        ),
        color=draft.color,
        light=draft.light,
        composition=draft.composition,
        texture=draft.texture,
        scene_fit=StyleSceneFit(
            suitable=draft.suitable_scenes,
            suitable_notes=(
                base.scene_fit.suitable_notes
                if base is not None
                else "由用户描述与自然语言解析共同确定。"
            ),
            unsuitable_notes=draft.unsuitable_notes,
        ),
        post_strategy=(
            base.post_strategy
            if base is not None
            else "通过既有风格决策链把文字意图转化为有界调整。"
        ),
        capture_techniques=(
            base.capture_techniques if base is not None else "用户的自然语言描述。"
        ),
        constraints=constraints,
        preserve_notes=(
            base.preserve_notes
            if base is not None
            else "风格约束来自用户描述；不用于模型训练。"
        ),
        sources=base.sources if base is not None else (_CUSTOM_SOURCE,),
        engine_style=(
            base.engine_style if base is not None else _engine_style(draft.suitable_scenes)
        ),
        envelope=_envelope_for(draft.targets),
        default_strength=min(max(0.35 + 0.4 * draft.confidence, 0.35), 0.75),
        enabled=base.enabled if base is not None else False,
        personal=personal,
    )


class CustomStyleService:
    def __init__(
        self,
        providers: ProviderSettingsService,
        styles: PersonalStyleService,
        repository: SqlitePersonalStyleRepository,
        *,
        max_concurrency: int = 2,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self._providers = providers
        self._styles = styles
        self._repository = repository
        self._slots = threading.BoundedSemaphore(max_concurrency)

    def parse(self, request: CustomStyleParseRequest) -> CustomStyleParseResponse:
        planner = self._providers.bundle.planner
        draft = self._call_authoring(
            planner,
            StyleAuthoringRequest(
                name=request.name,
                description=request.description,
                avoid_text=request.avoid,
                suitable_scenes=request.suitable_scenes,
            ),
        )
        return CustomStyleParseResponse(draft=draft, provider=self._provider_info(planner))

    def save(
        self,
        request: CustomStyleSaveRequest,
        *,
        owner_id: str,
    ) -> PersonalStyleDetailResponse:
        style_id = f"personal_{uuid4().hex[:12]}"
        profile = _profile_from_draft(
            request.draft,
            style_id=style_id,
            version="1.0",
            base=None,
        )
        definition = PersonalStyleDefinition(
            user_overrides={key: True for key in _CONFIRMED_OVERRIDES},
            note=request.note,
        )
        return self._styles.create_from_profile(profile, definition, owner_id=owner_id)

    def refine(
        self,
        style_id: str,
        request: CustomStyleRefineRequest,
        *,
        owner_id: str,
    ) -> CustomStyleRefineResponse:
        record = self._require(style_id, owner_id)
        planner = self._providers.bundle.planner
        draft = self._call_authoring(
            planner,
            StyleAuthoringRequest(
                name=record.profile.name,
                description=record.profile.description,
                base_profile=record.profile,
                instruction=request.instruction,
            ),
        )
        return CustomStyleRefineResponse(
            style_id=style_id,
            current_version=record.head.current_version,
            draft=draft,
            provider=self._provider_info(planner),
        )

    def apply_refine(
        self,
        style_id: str,
        request: CustomStyleRefineApplyRequest,
        *,
        owner_id: str,
    ) -> PersonalStyleDetailResponse:
        record = self._require(style_id, owner_id)
        profile = _profile_from_draft(
            request.draft,
            style_id=style_id,
            version=_next_version(record.head.current_version),
            base=record.profile,
        )
        definition = record.definition.model_copy(
            update={
                "note": request.note or record.definition.note,
                "user_overrides": {
                    **record.definition.user_overrides,
                    **{key: True for key in _CONFIRMED_OVERRIDES},
                },
            }
        )
        try:
            return self._styles.apply_profile_version(
                style_id,
                profile,
                definition,
                owner_id=owner_id,
                change_source=PersonalStyleChangeSource.USER,
                change_note=request.note or "自然语言调整",
            )
        except PersonalStyleVersionConflictError as exc:
            raise AppError(
                409,
                "personal_style_version_conflict",
                "The personal style version conflicts with the stored history.",
            ) from exc

    def _call_authoring(
        self,
        planner: PhotographyPlannerProvider,
        request: StyleAuthoringRequest,
    ) -> StyleAuthoringDraft:
        if not self._slots.acquire(blocking=False):
            raise AppError(
                503,
                "style_authoring_busy",
                "Too many style authoring requests are running.",
            )
        started = time.perf_counter()
        try:
            draft = planner.author_style(request)
        except ProviderError as exc:
            latency_ms = round((time.perf_counter() - started) * 1000.0)
            logger.warning(
                "style_authoring provider=%s model=%s outcome=error code=%s latency_ms=%s",
                planner.name,
                planner.model,
                exc.code,
                latency_ms,
            )
            raise self._map_provider_error(exc) from exc
        finally:
            self._slots.release()
        latency_ms = round((time.perf_counter() - started) * 1000.0)
        logger.info(
            "style_authoring provider=%s model=%s outcome=ok latency_ms=%s",
            planner.name,
            planner.model,
            latency_ms,
        )
        return draft

    @staticmethod
    def _provider_info(planner: PhotographyPlannerProvider) -> StyleAuthoringProviderInfo:
        return StyleAuthoringProviderInfo(
            name=planner.name,
            model=planner.model,
            prompt_version=STYLE_AUTHORING_PROMPT_VERSION,
            is_mock=planner.is_mock,
        )

    @staticmethod
    def _map_provider_error(error: ProviderError) -> AppError:
        suffix = error.code
        for prefix in ("style_authoring_", "planner_", "check_"):
            if suffix.startswith(prefix):
                suffix = suffix[len(prefix) :]
                break
        details = {"retryable": error.retryable, **error.details}
        if suffix == "provider_budget_exceeded":
            return AppError(
                429,
                "style_authoring_budget_exceeded",
                "The daily model usage limit has been reached.",
                {**details, "retryable": False},
            )
        if suffix == "provider_usage_unavailable":
            return AppError(
                503,
                "style_authoring_usage_unavailable",
                "Usage tracking is temporarily unavailable.",
                {**details, "retryable": False},
            )
        if suffix == "timeout":
            return AppError(504, "style_authoring_timeout", "The style model timed out.", details)
        if suffix == "invalid_output":
            return AppError(
                502,
                "style_authoring_invalid_output",
                "The model returned an invalid style draft.",
                details,
            )
        return AppError(
            502,
            "style_authoring_provider_error",
            "The style model request failed.",
            details,
        )

    def _require(self, style_id: str, owner_id: str) -> PersonalStyleRecord:
        record = self._repository.get(style_id, owner_id=owner_id)
        if record is None:
            raise _not_found()
        return record


__all__ = ["CustomStyleService"]
