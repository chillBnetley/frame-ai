from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.errors import AppError

if TYPE_CHECKING:
    from app.models.analysis_report import AnalysisReport
    from app.services.analysis_task_service import AnalysisTaskService
    from app.services.image_service import ImageService


def completed_report_for_image(
    images: ImageService,
    analysis: AnalysisTaskService,
    image_id: str,
) -> tuple[str, AnalysisReport]:
    """Resolve the latest completed report and prove it belongs to this image."""

    image, _ = images.get_original(image_id)
    canonical = str(image.id).lower()
    report = analysis.latest_completed(canonical)
    if report is None:
        raise AppError(
            409,
            "analysis_required",
            "The image needs a completed analysis before style fit evaluation.",
            {"imageId": canonical},
        )
    if (
        str(report.image.id).lower() != canonical
        or report.image.sha256.lower() != image.sha256.lower()
    ):
        raise AppError(
            409,
            "image_analysis_mismatch",
            "The analysis report does not belong to the current image.",
            {"imageId": canonical, "analysisId": str(report.analysis_id)},
        )
    return canonical, report


__all__ = ["completed_report_for_image"]
