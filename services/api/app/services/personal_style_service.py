from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from app.core.errors import AppError
from app.models.personal_style import (
    PersonalStyleChangeSource,
    PersonalStyleCompareResponse,
    PersonalStyleConsentScope,
    PersonalStyleCreateRequest,
    PersonalStyleDefinition,
    PersonalStyleDetailResponse,
    PersonalStyleFavoriteResponse,
    PersonalStyleFieldChange,
    PersonalStyleItem,
    PersonalStyleListResponse,
    PersonalStyleProfile,
    PersonalStyleReference,
    PersonalStyleReferenceAddRequest,
    PersonalStyleReferenceListResponse,
    PersonalStyleReferenceStatus,
    PersonalStyleSource,
    PersonalStyleStatus,
    PersonalStyleStatusResponse,
    PersonalStyleUpdateRequest,
    PersonalStyleVersionDetailResponse,
    PersonalStyleVersionListResponse,
    PersonalStyleVersionSummary,
    build_default_personal_profile,
)
from app.repositories.personal_style_repo import (
    DuplicatePersonalStyleNameError,
    PersonalStyleListItemRecord,
    PersonalStyleNotFoundError,
    PersonalStyleRecord,
    PersonalStyleVersionConflictError,
    PersonalStyleVersionRecord,
    SqlitePersonalStyleRepository,
)

if TYPE_CHECKING:
    from app.services.analysis_task_service import AnalysisTaskService
    from app.services.image_service import ImageService

MAX_REFERENCES = 20
MAX_COMPARE_CHANGES = 100


def _not_found() -> AppError:
    return AppError(404, "personal_style_not_found", "The personal style is not available.")


def _version_not_found() -> AppError:
    return AppError(
        404,
        "personal_style_version_not_found",
        "The requested personal style version is not available.",
    )


def _reference_not_found() -> AppError:
    return AppError(
        404,
        "personal_style_reference_not_found",
        "The reference photo does not belong to this personal style.",
    )


def _unavailable() -> AppError:
    return AppError(503, "service_unavailable", "The personal style service is not ready.")


def _next_version(version: str) -> str:
    major, _, minor = version.partition(".")
    return f"{major}.{int(minor) + 1}"


def _flatten(value: object, prefix: str, out: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _flatten(item, f"{prefix}.{key}" if prefix else str(key), out)
        return
    out[prefix] = value


def _changed_fields(before: object, after: object) -> tuple[PersonalStyleFieldChange, ...]:
    left: dict[str, Any] = {}
    right: dict[str, Any] = {}
    _flatten(before, "", left)
    _flatten(after, "", right)
    changes: list[PersonalStyleFieldChange] = []
    for path in sorted(set(left) | set(right)):
        old = left.get(path)
        new = right.get(path)
        if old == new:
            continue
        changes.append(PersonalStyleFieldChange(path=path, before=old, after=new))
        if len(changes) >= MAX_COMPARE_CHANGES:
            break
    return tuple(changes)


class PersonalStyleService:
    def __init__(
        self,
        repository: SqlitePersonalStyleRepository,
        *,
        images: ImageService | None = None,
        analysis: AnalysisTaskService | None = None,
    ) -> None:
        self._repository = repository
        self._images = images
        self._analysis = analysis

    def create(
        self,
        request: PersonalStyleCreateRequest,
        *,
        owner_id: str,
    ) -> PersonalStyleDetailResponse:
        style_id = f"personal_{uuid4().hex[:12]}"
        profile = build_default_personal_profile(
            style_id=style_id,
            name=request.name,
            description=request.description,
            source=request.source,
            suitable_scenes=request.suitable_scenes,
            targets=dict(request.targets),
            avoid=request.avoid,
        )
        definition = PersonalStyleDefinition()
        change_source = (
            PersonalStyleChangeSource.CUSTOM
            if request.source is PersonalStyleSource.CUSTOM
            else PersonalStyleChangeSource.USER
        )
        try:
            self._repository.create(
                profile,
                definition,
                owner_id=owner_id,
                change_source=change_source,
            )
        except DuplicatePersonalStyleNameError as exc:
            raise AppError(
                409,
                "personal_style_name_conflict",
                "A personal style with this name already exists.",
            ) from exc
        return self._detail_from(self._require(style_id, owner_id))

    def create_from_profile(
        self,
        profile: PersonalStyleProfile,
        definition: PersonalStyleDefinition,
        *,
        owner_id: str,
        change_source: PersonalStyleChangeSource = PersonalStyleChangeSource.CUSTOM,
        change_note: str | None = None,
    ) -> PersonalStyleDetailResponse:
        try:
            self._repository.create(
                profile,
                definition,
                owner_id=owner_id,
                change_source=change_source,
                change_note=change_note,
            )
        except DuplicatePersonalStyleNameError as exc:
            raise AppError(
                409,
                "personal_style_name_conflict",
                "A personal style with this name already exists.",
            ) from exc
        return self._detail_from(self._require(profile.id, owner_id))

    def apply_profile_version(
        self,
        style_id: str,
        profile: PersonalStyleProfile,
        definition: PersonalStyleDefinition,
        *,
        owner_id: str,
        change_source: PersonalStyleChangeSource,
        change_note: str | None,
    ) -> PersonalStyleDetailResponse:
        self._require(style_id, owner_id)
        self._add_version(
            profile,
            definition,
            owner_id=owner_id,
            change_source=change_source,
            change_note=change_note,
        )
        return self._detail_from(self._require(style_id, owner_id))

    def list(
        self,
        *,
        owner_id: str,
        status: PersonalStyleStatus | None = None,
    ) -> PersonalStyleListResponse:
        records = self._repository.list_records(owner_id=owner_id, status=status)
        return PersonalStyleListResponse(
            styles=tuple(self._item_from(record) for record in records)
        )

    def detail(
        self,
        style_id: str,
        *,
        owner_id: str,
        version: str | None = None,
    ) -> PersonalStyleDetailResponse:
        record = self._repository.get(style_id, owner_id=owner_id, version=version)
        if record is None:
            raise _version_not_found() if version is not None else _not_found()
        return self._detail_from(record)

    def update(
        self,
        style_id: str,
        request: PersonalStyleUpdateRequest,
        *,
        owner_id: str,
    ) -> PersonalStyleDetailResponse:
        record = self._require(style_id, owner_id)
        profile = record.profile
        definition = record.definition
        overrides = dict(definition.user_overrides)

        if request.name is not None:
            profile = profile.model_copy(update={"name": request.name})
            overrides["name"] = request.name
        if request.description is not None:
            profile = profile.model_copy(update={"description": request.description})
            overrides["description"] = request.description
        if request.suitable_scenes is not None:
            if not request.suitable_scenes:
                raise AppError(
                    422,
                    "invalid_scene_fit",
                    "At least one suitable scene is required.",
                )
            scene_fit = profile.scene_fit.model_copy(
                update={"suitable": request.suitable_scenes}
            )
            profile = profile.model_copy(update={"scene_fit": scene_fit})
            overrides["sceneFit.suitable"] = [scene.value for scene in request.suitable_scenes]
        if request.targets is not None:
            personal = profile.personal.model_copy(
                update={
                    "targets": request.targets,
                    "user_overrides": tuple(
                        dict.fromkeys(
                            (*profile.personal.user_overrides, "personal.targets")
                        )
                    ),
                }
            )
            profile = profile.model_copy(update={"personal": personal})
            overrides["personal.targets"] = dict(request.targets)
        if request.avoid is not None:
            personal = profile.personal.model_copy(
                update={
                    "avoid": request.avoid,
                    "user_overrides": tuple(
                        dict.fromkeys((*profile.personal.user_overrides, "personal.avoid"))
                    ),
                }
            )
            profile = profile.model_copy(update={"personal": personal})
            overrides["personal.avoid"] = [effect.value for effect in request.avoid]
        if request.traits is not None:
            changes = request.traits.model_dump(exclude_none=True)
            color_updates: dict[str, Any] = {}
            light_updates: dict[str, Any] = {}
            texture_updates: dict[str, Any] = {}
            for key, value in changes.items():
                if key.startswith("color_"):
                    color_updates[key.removeprefix("color_")] = value
                elif key.startswith("light_"):
                    light_updates[key.removeprefix("light_")] = value
                elif key.startswith("texture_"):
                    texture_updates[key.removeprefix("texture_")] = value
                overrides[f"traits.{key}"] = value
            if color_updates:
                profile = profile.model_copy(
                    update={"color": profile.color.model_copy(update=color_updates)}
                )
            if light_updates:
                profile = profile.model_copy(
                    update={"light": profile.light.model_copy(update=light_updates)}
                )
            if texture_updates:
                profile = profile.model_copy(
                    update={"texture": profile.texture.model_copy(update=texture_updates)}
                )
            personal = profile.personal.model_copy(
                update={
                    "user_overrides": tuple(
                        dict.fromkeys(
                            (
                                *profile.personal.user_overrides,
                                *(f"traits.{key}" for key in changes),
                            )
                        )
                    )
                }
            )
            profile = profile.model_copy(update={"personal": personal})

        updated = profile.model_copy(update={"version": _next_version(record.head.current_version)})
        note = request.note or definition.note
        updated_definition = definition.model_copy(
            update={"user_overrides": overrides, "note": note}
        )
        self._add_version(
            updated,
            updated_definition,
            owner_id=owner_id,
            change_source=PersonalStyleChangeSource.USER,
            change_note=request.note,
        )
        return self._detail_from(self._require(style_id, owner_id))

    def set_status(
        self,
        style_id: str,
        status: PersonalStyleStatus,
        *,
        owner_id: str,
    ) -> PersonalStyleStatusResponse:
        record = self._require(style_id, owner_id)
        if status is PersonalStyleStatus.PUBLISHED:
            references = self._repository.list_references(style_id, owner_id=owner_id)
            if profile_source_is_photos(record) and not any(
                reference.status is PersonalStyleReferenceStatus.ACTIVE
                for reference in references
            ):
                raise AppError(
                    409,
                    "personal_style_reference_required",
                    "Add at least one authorised reference photo before publishing.",
                )
        try:
            self._repository.set_status(style_id, owner_id=owner_id, status=status)
        except PersonalStyleNotFoundError as exc:
            raise _not_found() from exc
        return PersonalStyleStatusResponse(style_id=style_id, status=status)

    def favorite(
        self,
        style_id: str,
        *,
        owner_id: str,
        favorite: bool,
    ) -> PersonalStyleFavoriteResponse:
        self._require(style_id, owner_id)
        try:
            self._repository.set_favorite(style_id, owner_id=owner_id, favorite=favorite)
        except PersonalStyleNotFoundError as exc:
            raise _not_found() from exc
        return PersonalStyleFavoriteResponse(style_id=style_id, favorite=favorite)

    def delete(self, style_id: str, *, owner_id: str, confirm: bool) -> None:
        if not confirm:
            raise AppError(
                409,
                "confirmation_required",
                "Deleting a personal style requires explicit confirmation.",
            )
        outcome = self._repository.delete(style_id, owner_id=owner_id)
        if outcome == "missing":
            raise _not_found()

    def add_references(
        self,
        style_id: str,
        request: PersonalStyleReferenceAddRequest,
        *,
        owner_id: str,
    ) -> PersonalStyleReferenceListResponse:
        if self._images is None:
            raise _unavailable()
        record = self._require(style_id, owner_id)
        existing = self._repository.list_references(style_id, owner_id=owner_id)
        existing_image_ids = {
            str(reference.image_id)
            for reference in existing
            if reference.image_id is not None
        }
        requested = {str(image_id) for image_id in request.image_ids}
        new_count = len(requested - existing_image_ids)
        if len(existing) + new_count > MAX_REFERENCES:
            raise AppError(
                422,
                "too_many_references",
                f"A personal style supports at most {MAX_REFERENCES} reference photos.",
            )
        now = datetime.now(UTC)
        references: list[PersonalStyleReference] = []
        for image_id in request.image_ids:
            image, _ = self._images.get_original(str(image_id))
            report = (
                self._analysis.latest_completed(str(image.id))
                if self._analysis is not None
                else None
            )
            analysis_id = (
                report.analysis_id
                if report is not None
                and report.image.sha256.lower() == image.sha256.lower()
                else None
            )
            references.append(
                PersonalStyleReference(
                    id=uuid4(),
                    image_id=UUID(image.id),
                    image_sha256=image.sha256.lower(),
                    original_name=image.original_name,
                    status=PersonalStyleReferenceStatus.ACTIVE,
                    consent_scope=PersonalStyleConsentScope.ANALYSIS_ONLY,
                    consent_at=now,
                    added_at=now,
                    analysis_id=analysis_id,
                )
            )
        try:
            stored = self._repository.add_references(
                style_id,
                owner_id=owner_id,
                references=references,
            )
        except PersonalStyleNotFoundError as exc:
            raise _not_found() from exc
        return PersonalStyleReferenceListResponse(
            style_id=record.head.id,
            references=tuple(stored),
        )

    def list_references(
        self,
        style_id: str,
        *,
        owner_id: str,
    ) -> PersonalStyleReferenceListResponse:
        record = self._require(style_id, owner_id)
        return PersonalStyleReferenceListResponse(
            style_id=record.head.id,
            references=tuple(self._repository.list_references(style_id, owner_id=owner_id)),
        )

    def remove_reference(self, style_id: str, reference_id: str, *, owner_id: str) -> None:
        self._require(style_id, owner_id)
        try:
            removed = self._repository.remove_reference(
                style_id,
                reference_id,
                owner_id=owner_id,
            )
        except PersonalStyleNotFoundError as exc:
            raise _not_found() from exc
        if not removed:
            raise _reference_not_found()

    def versions(
        self,
        style_id: str,
        *,
        owner_id: str,
    ) -> PersonalStyleVersionListResponse:
        self._require(style_id, owner_id)
        versions = self._repository.list_versions(style_id, owner_id=owner_id)
        return PersonalStyleVersionListResponse(
            style_id=style_id,
            versions=tuple(
                PersonalStyleVersionSummary(
                    version=item.version,
                    change_source=item.change_source,
                    change_note=item.change_note,
                    created_at=item.created_at,
                )
                for item in versions
            ),
        )

    def version_detail(
        self,
        style_id: str,
        version: str,
        *,
        owner_id: str,
    ) -> PersonalStyleVersionDetailResponse:
        record = self._repository.get(style_id, owner_id=owner_id, version=version)
        if record is None:
            raise _version_not_found()
        item = self._version_record(style_id, version, owner_id)
        return PersonalStyleVersionDetailResponse(
            style_id=style_id,
            version=version,
            profile=record.profile,
            definition=record.definition,
            change_source=item.change_source,
            change_note=item.change_note,
            created_at=item.created_at,
        )

    def compare(
        self,
        style_id: str,
        from_version: str,
        to_version: str,
        *,
        owner_id: str,
    ) -> PersonalStyleCompareResponse:
        before = self._repository.get(style_id, owner_id=owner_id, version=from_version)
        after = self._repository.get(style_id, owner_id=owner_id, version=to_version)
        if before is None or after is None:
            raise _version_not_found()
        changes = _changed_fields(
            {
                "profile": before.profile.model_dump(mode="json", by_alias=True),
                "definition": before.definition.model_dump(mode="json", by_alias=True),
            },
            {
                "profile": after.profile.model_dump(mode="json", by_alias=True),
                "definition": after.definition.model_dump(mode="json", by_alias=True),
            },
        )
        return PersonalStyleCompareResponse(
            style_id=style_id,
            from_version=from_version,
            to_version=to_version,
            changes=changes,
        )

    def restore(
        self,
        style_id: str,
        version: str,
        *,
        owner_id: str,
    ) -> PersonalStyleDetailResponse:
        record = self._require(style_id, owner_id)
        target = self._repository.get(style_id, owner_id=owner_id, version=version)
        if target is None:
            raise _version_not_found()
        restored = target.profile.model_copy(
            update={"version": _next_version(record.head.current_version)}
        )
        self._add_version(
            restored,
            target.definition,
            owner_id=owner_id,
            change_source=PersonalStyleChangeSource.RESTORE,
            change_note=f"恢复自版本 {version}",
        )
        return self._detail_from(self._require(style_id, owner_id))

    def _add_version(
        self,
        profile: PersonalStyleProfile,
        definition: PersonalStyleDefinition,
        *,
        owner_id: str,
        change_source: PersonalStyleChangeSource,
        change_note: str | None,
    ) -> None:
        try:
            self._repository.add_version(
                profile,
                definition,
                owner_id=owner_id,
                change_source=change_source,
                change_note=change_note,
            )
        except PersonalStyleNotFoundError as exc:
            raise _not_found() from exc
        except DuplicatePersonalStyleNameError as exc:
            raise AppError(
                409,
                "personal_style_name_conflict",
                "A personal style with this name already exists.",
            ) from exc
        except PersonalStyleVersionConflictError as exc:
            raise AppError(
                409,
                "personal_style_version_conflict",
                "The personal style version conflicts with the stored history.",
            ) from exc

    def _require(self, style_id: str, owner_id: str) -> PersonalStyleRecord:
        record = self._repository.get(style_id, owner_id=owner_id)
        if record is None:
            raise _not_found()
        return record

    def _version_record(
        self,
        style_id: str,
        version: str,
        owner_id: str,
    ) -> PersonalStyleVersionRecord:
        for item in self._repository.list_versions(style_id, owner_id=owner_id):
            if item.version == version:
                return item
        raise _version_not_found()

    def _detail_from(self, record: PersonalStyleRecord) -> PersonalStyleDetailResponse:
        references = self._repository.list_references(record.head.id, owner_id=record.head.owner_id)
        return PersonalStyleDetailResponse(
            style=record.profile,
            definition=record.definition,
            status=record.head.status,
            source=record.head.source,
            favorite=record.head.favorite,
            references=tuple(references),
            created_at=record.head.created_at,
            updated_at=record.head.updated_at,
        )

    @staticmethod
    def _item_from(record: PersonalStyleListItemRecord) -> PersonalStyleItem:
        return PersonalStyleItem(
            id=record.head.id,
            name=record.head.name,
            description=record.head.description,
            source=record.head.source,
            status=record.head.status,
            version=record.head.current_version,
            favorite=record.head.favorite,
            enabled=record.profile.enabled,
            confidence=record.profile.personal.confidence,
            sample_count=record.profile.personal.sample_count,
            reference_count=record.reference_count,
            engine_style=record.profile.engine_style,
            default_strength=record.profile.default_strength,
            signature=(
                record.profile.color.tendency,
                record.profile.light.expression,
                record.profile.texture.grain,
            ),
            suitable_scenes=record.profile.scene_fit.suitable,
            updated_at=record.head.updated_at,
        )


def profile_source_is_photos(record: PersonalStyleRecord) -> bool:
    return record.head.source is PersonalStyleSource.PHOTOS


__all__ = ["MAX_REFERENCES", "PersonalStyleService"]
