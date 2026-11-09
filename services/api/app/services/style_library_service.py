from __future__ import annotations

from typing import TYPE_CHECKING

from app.ai.contracts import SceneLabel
from app.core.errors import AppError
from app.models.style_library import (
    RecommendationBasis,
    StyleDetailResponse,
    StyleEnabledResponse,
    StyleFavoriteResponse,
    StyleLibraryItem,
    StyleLibraryListResponse,
    StyleRecentItem,
    StyleRecentResponse,
    StyleRecommendation,
    StyleRecommendedResponse,
    StyleVersionListResponse,
)
from app.models.style_profile import StyleKind, StyleProfile
from app.repositories.photographer_repo import SqlitePhotographerPlanRepository
from app.repositories.style_repo import (
    SqliteStyleProfileRepository,
    StyleProfileNotFoundError,
)
from app.services.report_lookup import completed_report_for_image
from app.styles.vocabulary import SCENE_NAMES

if TYPE_CHECKING:
    from app.services.analysis_task_service import AnalysisTaskService
    from app.services.image_service import ImageService

MAX_RECENT_SCAN = 200
_LIBRARY_REASON = "适合作为风格起点；上传照片并完成分析后可查看适配度。"


def _style_not_found() -> AppError:
    return AppError(404, "style_not_found", "The requested style is not available.")


def _display_key(profile: StyleProfile) -> tuple[int, str, str]:
    return (0 if profile.kind is StyleKind.MASTER else 1, profile.name, profile.id)


def _unavailable() -> AppError:
    return AppError(503, "service_unavailable", "The style library is not ready.")


class StyleLibraryService:
    def __init__(
        self,
        repository: SqliteStyleProfileRepository,
        *,
        plans: SqlitePhotographerPlanRepository | None = None,
        images: ImageService | None = None,
        analysis: AnalysisTaskService | None = None,
    ) -> None:
        self._repository = repository
        self._plans = plans
        self._images = images
        self._analysis = analysis

    def list_styles(
        self,
        *,
        kind: StyleKind | None = None,
        scene: SceneLabel | None = None,
        search: str | None = None,
        include_disabled: bool = False,
    ) -> StyleLibraryListResponse:
        profiles = self._repository.list_profiles(
            kind=kind,
            enabled_only=not include_disabled,
            search=search,
        )
        if scene is not None:
            profiles = [p for p in profiles if scene in p.scene_fit.suitable]
        profiles.sort(key=_display_key)
        favorites = set(self._repository.list_favorites())
        return StyleLibraryListResponse(
            styles=tuple(
                StyleLibraryItem.from_profile(profile, favorite=profile.id in favorites)
                for profile in profiles
            )
        )

    def detail(
        self,
        style_id: str,
        *,
        version: str | None = None,
        include_disabled: bool = False,
    ) -> StyleDetailResponse:
        profile = self._repository.get(style_id, version=version)
        if profile is None:
            raise _style_not_found()
        if version is not None:
            head = self._require_profile(style_id)
            profile = profile.model_copy(update={"enabled": head.enabled})
        if not include_disabled and not profile.enabled:
            raise _style_not_found()
        favorite = style_id in self._repository.list_favorites()
        return StyleDetailResponse(style=profile, favorite=favorite)

    def versions(self, style_id: str) -> StyleVersionListResponse:
        self._require_profile(style_id)
        return StyleVersionListResponse(
            style_id=style_id,
            versions=tuple(self._repository.list_versions(style_id)),
        )

    def set_enabled(self, style_id: str, enabled: bool) -> StyleEnabledResponse:
        try:
            self._repository.set_enabled(style_id, enabled)
        except StyleProfileNotFoundError as exc:
            raise _style_not_found() from exc
        return StyleEnabledResponse(style_id=style_id, enabled=enabled)

    def favorite(self, style_id: str) -> StyleFavoriteResponse:
        try:
            self._repository.add_favorite(style_id)
        except StyleProfileNotFoundError as exc:
            raise _style_not_found() from exc
        return StyleFavoriteResponse(style_id=style_id, favorite=True)

    def unfavorite(self, style_id: str) -> StyleFavoriteResponse:
        self._require_profile(style_id)
        self._repository.remove_favorite(style_id)
        return StyleFavoriteResponse(style_id=style_id, favorite=False)

    def list_favorites(self) -> StyleLibraryListResponse:
        enabled = {
            profile.id: profile for profile in self._repository.list_profiles(enabled_only=True)
        }
        return StyleLibraryListResponse(
            styles=tuple(
                StyleLibraryItem.from_profile(enabled[style_id], favorite=True)
                for style_id in self._repository.list_favorites()
                if style_id in enabled
            )
        )

    def recent(self, *, limit: int = 8) -> StyleRecentResponse:
        if self._plans is None:
            raise _unavailable()
        enabled = {
            profile.id: profile for profile in self._repository.list_profiles(enabled_only=True)
        }
        favorites = set(self._repository.list_favorites())
        styles: list[StyleRecentItem] = []
        for usage in self._plans.list_recent_style_usage(limit=MAX_RECENT_SCAN):
            profile = enabled.get(usage.style_id)
            if profile is None:
                continue
            styles.append(
                StyleRecentItem(
                    style=StyleLibraryItem.from_profile(profile, favorite=profile.id in favorites),
                    last_used_at=usage.last_used_at,
                )
            )
            if len(styles) >= limit:
                break
        return StyleRecentResponse(styles=tuple(styles))

    def recommended(
        self,
        *,
        image_id: str | None = None,
        limit: int = 6,
    ) -> StyleRecommendedResponse:
        profiles = list(self._repository.list_profiles(enabled_only=True))
        basis: RecommendationBasis = "library"
        scene: SceneLabel | None = None
        if image_id is not None:
            scene = self._scene_for_image(image_id)
            matches = [profile for profile in profiles if scene in profile.scene_fit.suitable]
            if matches:
                profiles = matches
                basis = "scene"
        profiles.sort(key=_display_key)
        favorites = set(self._repository.list_favorites())
        reason = (
            f"档案适用场景包含{SCENE_NAMES.get(scene, scene.value)}。"
            if basis == "scene" and scene is not None
            else _LIBRARY_REASON
        )
        return StyleRecommendedResponse(
            basis=basis,
            scene=scene,
            styles=tuple(
                StyleRecommendation(
                    style=StyleLibraryItem.from_profile(profile, favorite=profile.id in favorites),
                    reason=reason,
                )
                for profile in profiles[:limit]
            ),
        )

    def _require_profile(self, style_id: str) -> StyleProfile:
        profile = self._repository.get(style_id)
        if profile is None:
            raise _style_not_found()
        return profile

    def _scene_for_image(self, image_id: str) -> SceneLabel:
        if self._images is None or self._analysis is None:
            raise _unavailable()
        _, report = completed_report_for_image(self._images, self._analysis, image_id)
        return report.scene.primary
