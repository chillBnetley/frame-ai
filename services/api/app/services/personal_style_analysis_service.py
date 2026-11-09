from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from app.ai.contracts import AnalysisOptions
from app.core.errors import AppError
from app.models.analysis_report import AnalysisReport
from app.models.analysis_task import AnalysisTaskRecord, TaskStatus
from app.models.personal_style import (
    PersonalStyleReference,
    PersonalStyleReferenceStatus,
)
from app.models.visual_dna import (
    PersonalStyleAnalysisResponse,
    PersonalStyleAnalysisStatus,
    PersonalStyleAnalyzeRequest,
    PersonalStyleReferenceAnalysis,
    PhotoVisualFeatures,
)
from app.repositories.personal_style_repo import (
    PersonalStyleFeatureMismatchError,
    PersonalStyleNotFoundError,
    PersonalStyleReferenceNotFoundError,
    SqlitePersonalStyleRepository,
)
from app.visual_dna.extractor import VisualDnaExtractor

if TYPE_CHECKING:
    from app.services.analysis_task_service import AnalysisTaskService

DEFAULT_ANALYSIS_OPTIONS = AnalysisOptions()


def _not_found() -> AppError:
    return AppError(404, "personal_style_not_found", "The personal style is not available.")


def _reference_not_found() -> AppError:
    return AppError(
        404,
        "personal_style_reference_not_found",
        "The reference photo does not belong to this personal style.",
    )


def _feature_not_ready() -> AppError:
    return AppError(
        409,
        "personal_style_feature_not_ready",
        "Run the Visual DNA analysis before reading this photo's features.",
    )


def _reference_required() -> AppError:
    return AppError(
        409,
        "personal_style_reference_required",
        "Add at least one authorised reference photo before analysing.",
    )


class PersonalStyleAnalysisService:
    def __init__(
        self,
        repository: SqlitePersonalStyleRepository,
        *,
        analysis: AnalysisTaskService,
        extractor: VisualDnaExtractor | None = None,
    ) -> None:
        self._repository = repository
        self._analysis = analysis
        self._extractor = extractor or VisualDnaExtractor()

    def analyze(
        self,
        style_id: str,
        request: PersonalStyleAnalyzeRequest,
        *,
        owner_id: str,
    ) -> PersonalStyleAnalysisResponse:
        self._require_style(style_id, owner_id)
        references = self._repository.list_references(style_id, owner_id=owner_id)
        targets = self._targets(references, request.reference_ids)
        if not targets:
            raise _reference_required()
        items = tuple(
            self._analyze_reference(style_id, reference, owner_id=owner_id, force=request.force)
            for reference in targets
        )
        return self._response(style_id, items)

    def status(
        self,
        style_id: str,
        *,
        owner_id: str,
    ) -> PersonalStyleAnalysisResponse:
        """Report per-photo status and read through completed analyses.

        The read-through extraction is deterministic, idempotent, and makes no
        provider call; it only turns a completed stage 3 report into the stored
        Visual DNA feature record.
        """

        self._require_style(style_id, owner_id)
        references = self._repository.list_references(style_id, owner_id=owner_id)
        items = tuple(
            self._status_reference(style_id, reference, owner_id=owner_id)
            for reference in references
        )
        return self._response(style_id, items)

    def features(
        self,
        style_id: str,
        reference_id: str,
        *,
        owner_id: str,
    ) -> PhotoVisualFeatures:
        reference = self._repository.get_reference(
            style_id,
            reference_id,
            owner_id=owner_id,
        )
        if reference is None:
            raise _reference_not_found()
        features = self._repository.get_feature(
            style_id,
            reference_id,
            owner_id=owner_id,
        )
        if features is None:
            raise _feature_not_ready()
        return features

    def _analyze_reference(
        self,
        style_id: str,
        reference: PersonalStyleReference,
        *,
        owner_id: str,
        force: bool,
    ) -> PersonalStyleReferenceAnalysis:
        if (
            reference.status is PersonalStyleReferenceStatus.MISSING
            or reference.image_id is None
        ):
            return self._item(reference, PersonalStyleAnalysisStatus.MISSING)
        image_id = str(reference.image_id)
        report = self._analysis.latest_completed(image_id)
        if (
            report is not None
            and report.image.sha256.lower() == reference.image_sha256
            and not force
        ):
            features = self._extract_and_store(style_id, reference, report, owner_id=owner_id)
            return self._completed_item(reference, features)
        try:
            outcome = self._analysis.create(
                image_id,
                DEFAULT_ANALYSIS_OPTIONS,
                force=force,
            )
        except AppError as exc:
            if exc.status_code == 404:
                self._repository.mark_reference_missing(
                    style_id,
                    str(reference.id),
                    owner_id=owner_id,
                )
                return self._item(reference, PersonalStyleAnalysisStatus.MISSING)
            raise
        self._repository.set_reference_analysis(
            style_id,
            str(reference.id),
            owner_id=owner_id,
            analysis_id=str(outcome.task.id),
        )
        if outcome.task.status is TaskStatus.COMPLETED:
            report = self._analysis.result(str(outcome.task.id))
            features = self._extract_and_store(style_id, reference, report, owner_id=owner_id)
            return self._completed_item(reference, features)
        if outcome.task.status is TaskStatus.FAILED:
            return PersonalStyleReferenceAnalysis(
                reference_id=reference.id,
                image_id=reference.image_id,
                status=PersonalStyleAnalysisStatus.FAILED,
                stage=outcome.task.stage,
                analysis_id=UUID(str(outcome.task.id)),
                error=outcome.task.error_message or "The analysis failed.",
            )
        return PersonalStyleReferenceAnalysis(
            reference_id=reference.id,
            image_id=reference.image_id,
            status=(
                PersonalStyleAnalysisStatus.PROCESSING
                if outcome.task.status is TaskStatus.PROCESSING
                else PersonalStyleAnalysisStatus.PENDING
            ),
            stage=outcome.task.stage,
            analysis_id=UUID(str(outcome.task.id)),
        )

    def _status_reference(
        self,
        style_id: str,
        reference: PersonalStyleReference,
        *,
        owner_id: str,
    ) -> PersonalStyleReferenceAnalysis:
        if (
            reference.status is PersonalStyleReferenceStatus.MISSING
            or reference.image_id is None
        ):
            return self._item(reference, PersonalStyleAnalysisStatus.MISSING)
        current = self._repository.get_feature(
            style_id,
            str(reference.id),
            owner_id=owner_id,
        )
        if current is not None and self._feature_is_current(reference, current):
            return self._completed_item(reference, current)
        if reference.analysis_id is not None:
            task: AnalysisTaskRecord | None
            try:
                task = self._analysis.record(str(reference.analysis_id))
            except AppError as exc:
                if exc.status_code != 404:
                    raise
                task = None
            if task is not None:
                if task.status is TaskStatus.COMPLETED:
                    completed_report = self._analysis.result(task.id)
                    features = self._extract_and_store(
                        style_id,
                        reference,
                        completed_report,
                        owner_id=owner_id,
                    )
                    return self._completed_item(reference, features)
                if task.status is TaskStatus.FAILED:
                    return PersonalStyleReferenceAnalysis(
                        reference_id=reference.id,
                        image_id=reference.image_id,
                        status=PersonalStyleAnalysisStatus.FAILED,
                        stage=task.stage,
                        analysis_id=UUID(task.id),
                        error=task.error_message or "The analysis failed.",
                    )
                return PersonalStyleReferenceAnalysis(
                    reference_id=reference.id,
                    image_id=reference.image_id,
                    status=(
                        PersonalStyleAnalysisStatus.PROCESSING
                        if task.status is TaskStatus.PROCESSING
                        else PersonalStyleAnalysisStatus.PENDING
                    ),
                    stage=task.stage,
                    analysis_id=UUID(task.id),
                )
        latest_report = self._analysis.latest_completed(str(reference.image_id))
        if (
            latest_report is not None
            and latest_report.image.sha256.lower() == reference.image_sha256
        ):
            features = self._extract_and_store(
                style_id,
                reference,
                latest_report,
                owner_id=owner_id,
            )
            return self._completed_item(reference, features)
        return self._item(reference, PersonalStyleAnalysisStatus.ANALYSIS_REQUIRED)

    def _extract_and_store(
        self,
        style_id: str,
        reference: PersonalStyleReference,
        report: AnalysisReport,
        *,
        owner_id: str,
    ) -> PhotoVisualFeatures:
        if report.image.sha256.lower() != reference.image_sha256:
            raise AppError(
                409,
                "image_analysis_mismatch",
                "The analysis report does not belong to the reference photo.",
                {"referenceId": str(reference.id)},
            )
        features = self._extractor.extract(report)
        try:
            self._repository.upsert_feature(
                style_id,
                str(reference.id),
                owner_id=owner_id,
                features=features,
            )
        except PersonalStyleNotFoundError as exc:
            raise _not_found() from exc
        except PersonalStyleReferenceNotFoundError as exc:
            raise _reference_not_found() from exc
        except PersonalStyleFeatureMismatchError as exc:
            raise AppError(
                409,
                "image_analysis_mismatch",
                "The extracted features do not belong to the reference photo.",
            ) from exc
        return features

    def _targets(
        self,
        references: list[PersonalStyleReference],
        requested: tuple[UUID, ...] | None,
    ) -> list[PersonalStyleReference]:
        if requested is None:
            return list(references)
        by_id = {str(reference.id): reference for reference in references}
        missing = [
            str(reference_id)
            for reference_id in requested
            if str(reference_id) not in by_id
        ]
        if missing:
            raise _reference_not_found()
        return [by_id[str(reference_id)] for reference_id in requested]

    def _feature_is_current(
        self,
        reference: PersonalStyleReference,
        features: PhotoVisualFeatures,
    ) -> bool:
        if reference.analysis_id is not None and str(features.analysis_id) != str(
            reference.analysis_id
        ):
            return False
        return (
            features.image_sha256 == reference.image_sha256
            and features.extractor_version == self._extractor.version
        )

    @staticmethod
    def _completed_item(
        reference: PersonalStyleReference,
        features: PhotoVisualFeatures,
    ) -> PersonalStyleReferenceAnalysis:
        return PersonalStyleReferenceAnalysis(
            reference_id=reference.id,
            image_id=reference.image_id,
            status=PersonalStyleAnalysisStatus.COMPLETED,
            analysis_id=features.analysis_id,
            confidence=features.overall_confidence,
            anomaly_count=len(features.anomalies),
            feature_available=True,
        )

    @staticmethod
    def _item(
        reference: PersonalStyleReference,
        status: PersonalStyleAnalysisStatus,
    ) -> PersonalStyleReferenceAnalysis:
        return PersonalStyleReferenceAnalysis(
            reference_id=reference.id,
            image_id=reference.image_id,
            status=status,
            analysis_id=reference.analysis_id,
        )

    @staticmethod
    def _response(
        style_id: str,
        items: tuple[PersonalStyleReferenceAnalysis, ...],
    ) -> PersonalStyleAnalysisResponse:
        completed = sum(
            1 for item in items if item.status is PersonalStyleAnalysisStatus.COMPLETED
        )
        return PersonalStyleAnalysisResponse(
            style_id=style_id,
            references=items,
            completed_count=completed,
            total_count=len(items),
        )

    def _require_style(self, style_id: str, owner_id: str) -> None:
        if self._repository.get(style_id, owner_id=owner_id) is None:
            raise _not_found()


__all__ = ["PersonalStyleAnalysisService"]
