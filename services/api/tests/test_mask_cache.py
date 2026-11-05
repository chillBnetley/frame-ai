from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from app.imaging.geometry import crop_bounds, rotation_target_size
from app.imaging.loader import LoadedImage
from app.imaging.local_masks import (
    MASK_CACHE_ENTRY_LIMIT_BYTES,
    MaskCacheStats,
    MaskWeightCache,
    _compute_mask_weights,
    clear_mask_cache,
    configure_mask_cache,
    mask_cache_stats,
    mask_weights,
)
from app.imaging.pipeline import render
from app.models.recipe import Adjustments, Crop, LocalAdjustment, UserMask

SOURCE = (160, 120)


def _mask(mask_id: str = "mask_001", **overrides: object) -> UserMask:
    payload: dict[str, object] = {
        "id": mask_id,
        "x": 0.2,
        "y": 0.3,
        "width": 0.4,
        "height": 0.2,
        "feather": 0,
        "opacity": 100,
    }
    payload.update(overrides)
    return UserMask.model_validate(payload)


def _canvas(source_width: int, source_height: int, rotation_deg: float, crop: Crop | None):
    target_width, target_height = rotation_target_size(source_width, source_height, rotation_deg)
    x0, y0, x1, y1 = crop_bounds(crop, target_width, target_height)
    return x1 - x0, y1 - y0


def _weights(
    mask: UserMask,
    *,
    size: tuple[int, int] = SOURCE,
    rotation_deg: float = 0.0,
    crop: Crop | None = None,
) -> np.ndarray:
    output_width, output_height = _canvas(size[0], size[1], rotation_deg, crop)
    return mask_weights(
        mask,
        output_width=output_width,
        output_height=output_height,
        source_width=size[0],
        source_height=size[1],
        rotation_deg=rotation_deg,
        crop=crop,
    )


@pytest.fixture(autouse=True)
def _enabled_cache():
    configure_mask_cache(64 * 1024 * 1024)
    clear_mask_cache()
    yield
    configure_mask_cache(0)


def test_repeated_weights_come_from_the_cache_and_match_recomputation():
    mask = _mask()

    first = _weights(mask)
    second = _weights(mask)

    stats = mask_cache_stats()
    assert (stats.misses, stats.hits, stats.entries) == (1, 1, 1)
    assert np.array_equal(first, second)
    output_width, output_height = _canvas(*SOURCE, 0.0, None)
    fresh = _compute_mask_weights(
        mask,
        output_width=output_width,
        output_height=output_height,
        source_width=SOURCE[0],
        source_height=SOURCE[1],
        rotation_deg=0.0,
        crop=None,
    )
    assert np.array_equal(first, fresh)
    assert first.tobytes() == fresh.tobytes()


def test_zero_budget_leaves_no_trace_and_matches_the_uncached_path():
    configure_mask_cache(0)

    uncached = _weights(_mask())

    assert mask_cache_stats() == MaskCacheStats()
    configure_mask_cache(64 * 1024 * 1024)
    cached = _weights(_mask())
    assert np.array_equal(uncached, cached)
    assert mask_cache_stats() == MaskCacheStats(misses=1, entries=1, bytes_used=uncached.nbytes)


def test_each_weight_affecting_field_gets_its_own_entry():
    variants = [
        _mask(),
        _mask(x=0.25),
        _mask(y=0.35),
        _mask(width=0.35),
        _mask(height=0.25),
        _mask(feather=40),
        _mask(opacity=60),
        _mask(inverted=True),
        _mask(shape="ellipse"),
    ]
    for variant in variants:
        _weights(variant)
    _weights(_mask(), rotation_deg=7.5)
    _weights(_mask(), crop=Crop(x=0.1, y=0.1, w=0.8, h=0.8))
    _weights(_mask(), size=(200, 120))

    assert mask_cache_stats().entries == len(variants) + 3


def test_renaming_a_mask_does_not_duplicate_the_entry():
    _weights(_mask("mask_left"))
    _weights(_mask("mask_right"))

    stats = mask_cache_stats()
    assert (stats.entries, stats.hits) == (1, 1)


def test_budget_evicts_the_least_recently_used_entry():
    entry_pixels = 64
    entry_bytes = entry_pixels * 4
    cache = MaskWeightCache(entry_bytes * 2)
    first = np.zeros((8, 8), dtype=np.float32)
    second = np.ones((8, 8), dtype=np.float32)
    third = np.full((8, 8), 2.0, dtype=np.float32)

    assert cache.put(("a",), first)
    assert cache.put(("b",), second)
    assert cache.get(("a",)) is not None
    assert cache.put(("c",), third) is True

    # "a" was touched after "b", so "b" is the one that goes.
    assert cache.get(("b",)) is None
    assert cache.stats().entries == 2
    assert cache.stats().bytes_used == entry_bytes * 2


def test_entries_above_the_single_entry_limit_are_refused():
    cache = MaskWeightCache(256 * 1024 * 1024, entry_limit_bytes=1024)

    assert cache.put(("big",), np.zeros((32, 32), dtype=np.float32)) is False
    assert cache.stats().entries == 0
    assert MASK_CACHE_ENTRY_LIMIT_BYTES == 24 * 1024 * 1024


def test_cached_weights_are_read_only_for_callers():
    weights = _weights(_mask())
    replay = _weights(_mask())

    assert weights.flags.writeable is False
    assert replay.flags.writeable is False
    with pytest.raises(ValueError):
        replay[0, 0] = 1.0


def test_clear_drops_entries_and_the_accounted_bytes():
    _weights(_mask())

    clear_mask_cache()

    stats = mask_cache_stats()
    assert stats.entries == 0
    assert stats.bytes_used == 0


def test_threads_competing_for_one_mask_store_a_single_entry():
    mask = _mask()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: _weights(mask), range(8)))

    assert mask_cache_stats().entries == 1
    assert all(np.array_equal(results[0], other) for other in results[1:])


def test_pipeline_output_is_identical_with_the_cache_enabled_and_disabled():
    pixels = np.linspace(0.0, 1.0, SOURCE[0] * SOURCE[1] * 3, dtype=np.float32)
    pixels = pixels.reshape(SOURCE[1], SOURCE[0], 3)
    image = LoadedImage(rgb=np.ascontiguousarray(pixels))
    mask = _mask(feather=30)
    recipe_masks = (mask,)
    locals_ = (
        LocalAdjustment.model_validate(
            {
                "id": "local_001",
                "mask_id": mask.id,
                "adjustments": {"exposureEv": 1.0},
            }
        ),
    )
    adjustments = Adjustments(rotation_deg=3.0, crop=Crop(x=0.05, y=0.05, w=0.9, h=0.9))

    configure_mask_cache(0)
    clear_mask_cache()
    cold = render(
        image,
        adjustments,
        image_sha256="0" * 64,
        masks=recipe_masks,
        local_adjustments=locals_,
        quality="final",
    )

    configure_mask_cache(64 * 1024 * 1024)
    clear_mask_cache()
    warm_first = render(
        image,
        adjustments,
        image_sha256="0" * 64,
        masks=recipe_masks,
        local_adjustments=locals_,
        quality="final",
    )
    warm_second = render(
        image,
        adjustments,
        image_sha256="0" * 64,
        masks=recipe_masks,
        local_adjustments=locals_,
        quality="final",
    )

    assert mask_cache_stats().hits == 1
    assert warm_first.rgb.tobytes() == cold.rgb.tobytes()
    assert warm_second.rgb.tobytes() == cold.rgb.tobytes()
    assert warm_first.warnings == cold.warnings
