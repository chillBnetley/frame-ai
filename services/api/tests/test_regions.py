from __future__ import annotations

import math

import pytest

from app.ai.contracts import BBox, SubjectResult, SubjectRole, SubjectType
from app.analysis.regions import (
    BBOX_APPROXIMATION_LIMITATION,
    NO_SUBJECT_LIMITATION,
    SMALL_REGION_LIMITATION,
    SUBJECT_DETECTION_DISABLED_LIMITATION,
    bbox_area,
    bbox_to_pixels,
    build_regions,
    clamp_bbox,
    pixels_to_bbox,
    rotate_bbox,
)


def _subject(
    bbox: tuple[float, float, float, float],
    *,
    role: SubjectRole = SubjectRole.SECONDARY,
    subject_type: SubjectType = SubjectType.OTHER,
    confidence: float = 0.8,
) -> SubjectResult:
    x, y, width, height = bbox
    return SubjectResult(
        type=subject_type,
        role=role,
        confidence=confidence,
        bbox=BBox(x=x, y=y, width=width, height=height),
    )


def test_clamp_bbox_accepts_valid_and_edge_touching_boxes():
    normal = clamp_bbox(0.25, 0.18, 0.35, 0.6)
    assert normal is not None
    assert (normal.x, normal.y, normal.width, normal.height) == pytest.approx(
        (0.25, 0.18, 0.35, 0.6)
    )

    full = clamp_bbox(0.0, 0.0, 1.0, 1.0)
    assert full == BBox(x=0.0, y=0.0, width=1.0, height=1.0)
    assert bbox_area(full) == pytest.approx(1.0)


def test_clamp_bbox_clips_overflow_and_negative_origins():
    overflow = clamp_bbox(0.9, 0.9, 0.5, 0.5)
    assert overflow is not None
    assert (overflow.x, overflow.y, overflow.width, overflow.height) == pytest.approx(
        (0.9, 0.9, 0.1, 0.1)
    )

    negative = clamp_bbox(-0.1, -0.2, 0.5, 0.6)
    assert negative is not None
    assert (negative.x, negative.y, negative.width, negative.height) == pytest.approx(
        (0.0, 0.0, 0.4, 0.4)
    )


@pytest.mark.parametrize(
    "values",
    [
        (0.2, 0.2, 0.0, 0.5),
        (0.2, 0.2, 0.5, 0.0),
        (0.2, 0.2, -0.1, 0.5),
        (0.2, 0.2, 0.5, -0.1),
        (2.0, 2.0, 0.1, 0.1),
        (-2.0, -2.0, 0.1, 0.1),
        (math.nan, 0.2, 0.3, 0.3),
        (0.2, math.inf, 0.3, 0.3),
        (0.2, 0.2, math.nan, 0.3),
    ],
)
def test_clamp_bbox_rejects_degenerate_boxes(values: tuple[float, float, float, float]):
    assert clamp_bbox(*values) is None


def test_clamp_bbox_absorbs_floating_point_overflow():
    bbox = clamp_bbox(0.5, 0.5, 0.5 + 1e-9, 0.5 + 1e-9)
    assert bbox is not None
    assert bbox.width <= 0.5
    assert bbox.height <= 0.5
    assert bbox.x + bbox.width <= 1.0
    assert bbox.y + bbox.height <= 1.0


@pytest.mark.parametrize(
    ("width", "height", "box", "pixels"),
    [
        (4000, 3000, (0.25, 0.5, 0.5, 0.25), (1000, 1500, 2000, 750)),
        (3000, 4000, (0.25, 0.5, 0.5, 0.25), (750, 2000, 1500, 1000)),
        (1000, 1000, (0.1, 0.2, 0.3, 0.4), (100, 200, 300, 400)),
        (5000, 1000, (0.25, 0.5, 0.5, 0.25), (1250, 500, 2500, 250)),
    ],
)
def test_normalized_and_pixel_coordinates_round_trip(
    width: int,
    height: int,
    box: tuple[float, float, float, float],
    pixels: tuple[int, int, int, int],
):
    bbox = BBox(x=box[0], y=box[1], width=box[2], height=box[3])
    assert bbox_to_pixels(bbox, width, height) == pixels

    restored = pixels_to_bbox(*pixels, width, height)
    assert restored is not None
    assert (restored.x, restored.y, restored.width, restored.height) == pytest.approx(box)


def test_pixels_to_bbox_clips_and_rejects_empty_boxes():
    clipped = pixels_to_bbox(-10, -10, 50, 50, 100, 100)
    assert clipped is not None
    assert (clipped.x, clipped.y, clipped.width, clipped.height) == pytest.approx(
        (0.0, 0.0, 0.4, 0.4)
    )

    assert pixels_to_bbox(10, 10, 0, 20, 100, 100) is None
    assert pixels_to_bbox(120, 120, 10, 10, 100, 100) is None


def test_bbox_to_pixels_requires_positive_dimensions():
    bbox = BBox(x=0.0, y=0.0, width=1.0, height=1.0)
    with pytest.raises(ValueError):
        bbox_to_pixels(bbox, 0, 100)
    with pytest.raises(ValueError):
        pixels_to_bbox(0, 0, 10, 10, -1, 100)


@pytest.mark.parametrize(
    ("orientation", "expected"),
    [
        (1, (0.1, 0.2, 0.3, 0.4)),
        (2, (0.6, 0.2, 0.3, 0.4)),
        (3, (0.6, 0.4, 0.3, 0.4)),
        (4, (0.1, 0.4, 0.3, 0.4)),
        (5, (0.2, 0.1, 0.4, 0.3)),
        (6, (0.4, 0.1, 0.4, 0.3)),
        (7, (0.4, 0.6, 0.4, 0.3)),
        (8, (0.2, 0.6, 0.4, 0.3)),
    ],
)
def test_rotate_bbox_maps_source_to_display_orientation(
    orientation: int,
    expected: tuple[float, float, float, float],
):
    bbox = BBox(x=0.1, y=0.2, width=0.3, height=0.4)
    rotated = rotate_bbox(bbox, orientation)
    assert (rotated.x, rotated.y, rotated.width, rotated.height) == pytest.approx(expected)


def test_rotate_bbox_rejects_unknown_orientation():
    bbox = BBox(x=0.1, y=0.2, width=0.3, height=0.4)
    with pytest.raises(ValueError):
        rotate_bbox(bbox, 0)
    with pytest.raises(ValueError):
        rotate_bbox(bbox, 9)


def test_rotated_pixel_box_uses_display_dimensions():
    source_box = pixels_to_bbox(0, 0, 100, 50, 400, 300)
    assert source_box is not None

    rotated = rotate_bbox(source_box, 6)
    assert bbox_to_pixels(rotated, 300, 400) == (250, 0, 50, 100)


def test_build_regions_orders_primary_then_area_and_numbers_ids():
    assignment = build_regions(
        (
            _subject((0.0, 0.0, 0.5, 0.5), subject_type=SubjectType.OTHER),
            _subject(
                (0.0, 0.0, 0.1, 0.1),
                role=SubjectRole.PRIMARY,
                subject_type=SubjectType.PERSON,
                confidence=0.9,
            ),
            _subject(
                (0.2, 0.2, 0.2, 0.2),
                role=SubjectRole.PRIMARY,
                subject_type=SubjectType.BUILDING,
            ),
            _subject((0.4, 0.4, 0.6, 0.6), subject_type=SubjectType.SKY),
        )
    )

    assert [subject.type for subject in assignment.subjects] == [
        SubjectType.BUILDING,
        SubjectType.PERSON,
        SubjectType.SKY,
        SubjectType.OTHER,
    ]
    assert [subject.role for subject in assignment.subjects] == [
        SubjectRole.PRIMARY,
        SubjectRole.PRIMARY,
        SubjectRole.SECONDARY,
        SubjectRole.SECONDARY,
    ]
    assert [region.id for region in assignment.regions] == [
        "region_001",
        "region_002",
        "region_003",
        "region_004",
    ]
    assert [subject.id for subject in assignment.subjects] == [
        "subject_001",
        "subject_002",
        "subject_003",
        "subject_004",
    ]
    assert all(
        subject.region_id == region.id
        for subject, region in zip(assignment.subjects, assignment.regions, strict=True)
    )
    assert assignment.subjects[1].confidence == pytest.approx(0.9)
    assert all(region.mask is None for region in assignment.regions)
    assert all(region.source == "vision" for region in assignment.regions)
    assert BBOX_APPROXIMATION_LIMITATION in assignment.limitations


def test_build_regions_keeps_original_order_for_equal_rank_and_area():
    assignment = build_regions(
        (
            _subject((0.1, 0.1, 0.2, 0.2), subject_type=SubjectType.PERSON),
            _subject((0.5, 0.5, 0.2, 0.2), subject_type=SubjectType.ANIMAL),
        )
    )
    assert [subject.type for subject in assignment.subjects] == [
        SubjectType.PERSON,
        SubjectType.ANIMAL,
    ]


def test_build_regions_drops_tiny_boxes_and_records_limitation():
    assignment = build_regions(
        (
            _subject((0.0, 0.0, 0.5, 0.5)),
            _subject((0.5, 0.5, 0.005, 0.005)),
        )
    )

    assert len(assignment.regions) == 1
    assert SMALL_REGION_LIMITATION.format(count=1) in assignment.limitations
    assert NO_SUBJECT_LIMITATION not in assignment.limitations


def test_build_regions_clips_floating_point_overflow():
    assignment = build_regions((_subject((0.5, 0.5, 0.5 + 1e-7, 0.5 + 1e-7)),))
    assert len(assignment.regions) == 1
    region = assignment.regions[0]
    assert region.bbox.x + region.bbox.width <= 1.0
    assert region.bbox.y + region.bbox.height <= 1.0


def test_build_regions_without_subjects_returns_empty_with_limitation():
    assignment = build_regions(())
    assert assignment.subjects == ()
    assert assignment.regions == ()
    assert assignment.limitations == (NO_SUBJECT_LIMITATION,)


def test_build_regions_discards_all_undersized_subjects():
    assignment = build_regions(
        (
            _subject((0.0, 0.0, 0.001, 0.001)),
            _subject((0.5, 0.5, 0.005, 0.005)),
        )
    )
    assert assignment.subjects == ()
    assert assignment.regions == ()
    assert SMALL_REGION_LIMITATION.format(count=2) in assignment.limitations
    assert NO_SUBJECT_LIMITATION in assignment.limitations


def test_build_regions_honors_disabled_subject_detection():
    assignment = build_regions(
        (_subject((0.0, 0.0, 0.5, 0.5)),),
        subject_detection=False,
    )
    assert assignment.subjects == ()
    assert assignment.regions == ()
    assert assignment.limitations == (SUBJECT_DETECTION_DISABLED_LIMITATION,)
