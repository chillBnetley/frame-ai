from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from app.ai.contracts import BBOX_TOLERANCE, BBox, SubjectResult, SubjectRole
from app.models.analysis_report import RegionInfo, SubjectInfo

MIN_REGION_AREA = 0.0001
NO_SUBJECT_LIMITATION = "未识别到可用的拍摄主体，未生成主体区域。"
SUBJECT_DETECTION_DISABLED_LIMITATION = "主体识别已关闭，未生成主体区域。"
SMALL_REGION_LIMITATION = "已忽略 {count} 个面积过小或无效的主体区域。"
BBOX_APPROXIMATION_LIMITATION = "区域边界框为近似范围，不包含像素级蒙版。"


@dataclass(frozen=True, slots=True)
class RegionAssignment:
    subjects: tuple[SubjectInfo, ...]
    regions: tuple[RegionInfo, ...]
    limitations: tuple[str, ...]


def clamp_bbox(
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    tolerance: float = BBOX_TOLERANCE,
) -> BBox | None:
    if not all(math.isfinite(value) for value in (x, y, width, height)):
        return None

    x0 = min(max(x, 0.0), 1.0)
    y0 = min(max(y, 0.0), 1.0)
    x1 = min(max(x + width, 0.0), 1.0)
    y1 = min(max(y + height, 0.0), 1.0)
    if x1 - x0 <= tolerance or y1 - y0 <= tolerance:
        return None
    return BBox(x=x0, y=y0, width=x1 - x0, height=y1 - y0)


def bbox_area(bbox: BBox) -> float:
    return bbox.width * bbox.height


def bbox_to_pixels(
    bbox: BBox,
    image_width: int,
    image_height: int,
) -> tuple[int, int, int, int]:
    if image_width <= 0 or image_height <= 0:
        raise ValueError("image dimensions must be positive")

    x0 = min(round(bbox.x * image_width), image_width - 1)
    y0 = min(round(bbox.y * image_height), image_height - 1)
    x1 = min(max(round((bbox.x + bbox.width) * image_width), x0 + 1), image_width)
    y1 = min(max(round((bbox.y + bbox.height) * image_height), y0 + 1), image_height)
    return x0, y0, x1 - x0, y1 - y0


def pixels_to_bbox(
    x: float,
    y: float,
    width: float,
    height: float,
    image_width: int,
    image_height: int,
) -> BBox | None:
    if image_width <= 0 or image_height <= 0:
        raise ValueError("image dimensions must be positive")
    return clamp_bbox(
        x / image_width,
        y / image_height,
        width / image_width,
        height / image_height,
    )


def rotate_bbox(bbox: BBox, orientation: int) -> BBox:
    """Map a normalized bbox from the stored orientation to the display orientation."""
    if orientation not in range(1, 9):
        raise ValueError("exif orientation must be between 1 and 8")

    first = _orient(bbox.x, bbox.y, orientation)
    second = _orient(bbox.x + bbox.width, bbox.y + bbox.height, orientation)
    x0, x1 = sorted((first[0], second[0]))
    y0, y1 = sorted((first[1], second[1]))
    rotated = clamp_bbox(x0, y0, x1 - x0, y1 - y0)
    if rotated is None:
        raise ValueError("bbox collapsed after orientation conversion")
    return rotated


def build_regions(
    subjects: Iterable[SubjectResult],
    *,
    subject_detection: bool = True,
    min_area: float = MIN_REGION_AREA,
) -> RegionAssignment:
    limitations: list[str] = []
    if not subject_detection:
        return RegionAssignment((), (), (SUBJECT_DETECTION_DISABLED_LIMITATION,))

    valid: list[tuple[int, SubjectResult, BBox]] = []
    ignored = 0
    for index, subject in enumerate(subjects):
        bbox = clamp_bbox(
            subject.bbox.x,
            subject.bbox.y,
            subject.bbox.width,
            subject.bbox.height,
        )
        if bbox is None or bbox_area(bbox) < min_area:
            ignored += 1
            continue
        valid.append((index, subject, bbox))

    if ignored:
        limitations.append(SMALL_REGION_LIMITATION.format(count=ignored))

    valid.sort(key=lambda item: _sort_key(item[0], item[1], item[2]))

    regions: list[RegionInfo] = []
    placed: list[SubjectInfo] = []
    for position, (_, subject, bbox) in enumerate(valid, start=1):
        region_id = f"region_{position:03d}"
        regions.append(
            RegionInfo(
                id=region_id,
                type=subject.type,
                source="vision",
                confidence=subject.confidence,
                bbox=bbox,
            )
        )
        placed.append(
            SubjectInfo(
                id=f"subject_{position:03d}",
                type=subject.type,
                role=subject.role,
                confidence=subject.confidence,
                bbox=bbox,
                region_id=region_id,
            )
        )

    if regions:
        limitations.append(BBOX_APPROXIMATION_LIMITATION)
    else:
        limitations.append(NO_SUBJECT_LIMITATION)

    return RegionAssignment(tuple(placed), tuple(regions), tuple(limitations))


def _orient(u: float, v: float, orientation: int) -> tuple[float, float]:
    if orientation == 1:
        return u, v
    if orientation == 2:
        return 1.0 - u, v
    if orientation == 3:
        return 1.0 - u, 1.0 - v
    if orientation == 4:
        return u, 1.0 - v
    if orientation == 5:
        return v, u
    if orientation == 6:
        return 1.0 - v, u
    if orientation == 7:
        return 1.0 - v, 1.0 - u
    return v, 1.0 - u


def _sort_key(
    index: int,
    subject: SubjectResult,
    bbox: BBox,
) -> tuple[int, float, int]:
    primary = 0 if subject.role is SubjectRole.PRIMARY else 1
    return primary, -bbox_area(bbox), index


__all__ = [
    "BBOX_APPROXIMATION_LIMITATION",
    "MIN_REGION_AREA",
    "NO_SUBJECT_LIMITATION",
    "RegionAssignment",
    "SMALL_REGION_LIMITATION",
    "SUBJECT_DETECTION_DISABLED_LIMITATION",
    "bbox_area",
    "bbox_to_pixels",
    "build_regions",
    "clamp_bbox",
    "pixels_to_bbox",
    "rotate_bbox",
]
