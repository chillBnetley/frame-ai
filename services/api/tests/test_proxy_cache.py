from __future__ import annotations

import threading

import numpy as np
from numpy.typing import NDArray

from app.imaging.loader import PROXY_VERSION, LoadedImage
from app.services.proxy_cache import DecodedProxyCache

SHA = "a" * 64


def _array(height: int = 8, width: int = 8, dtype=np.float32) -> NDArray:
    ramp = np.arange(height * width * 3, dtype=np.float32).reshape(height, width, 3)
    if dtype is np.float32:
        return (ramp % 256.0) / np.float32(255.0)
    return (ramp % 256.0).astype(dtype)


def _stored_bytes(array: NDArray) -> int:
    """The cache stores one byte per channel, whatever the input dtype is."""
    return int(np.prod(array.shape))


def test_put_and_get_round_trip_is_exact() -> None:
    cache = DecodedProxyCache(1024 * 1024)
    image = LoadedImage(rgb=_array())
    key = cache.key_for(SHA, 1600)

    assert cache.put(key, image) is True
    loaded = cache.get(key)

    assert loaded is not None
    assert np.array_equal(loaded.rgb, image.rgb)
    assert loaded.rgb.dtype == np.float32


def test_key_separates_images_edges_and_proxy_version() -> None:
    cache = DecodedProxyCache(1024 * 1024)
    image = LoadedImage(rgb=_array())

    assert cache.key_for(SHA, 1600) == (SHA.lower(), PROXY_VERSION, 1600)
    cache.put(cache.key_for(SHA, 1600), image)

    assert cache.get(cache.key_for(SHA, 1536)) is None
    assert cache.get(cache.key_for("b" * 64, 1600)) is None
    assert cache.get((SHA.lower(), "loader/0", 1600)) is None


def test_zero_budget_disables_the_cache() -> None:
    cache = DecodedProxyCache(0)
    key = cache.key_for(SHA, 64)

    assert cache.enabled is False
    assert cache.put(key, LoadedImage(rgb=_array())) is False
    assert cache.get(key) is None
    assert cache.stats().entries == 0


def test_lru_evicts_the_oldest_entry_by_bytes() -> None:
    array = _array(16, 16)
    payload_bytes = _stored_bytes(array)
    cache = DecodedProxyCache(payload_bytes * 2 + 1)
    first = cache.key_for(SHA, 100)
    second = cache.key_for(SHA, 200)
    third = cache.key_for(SHA, 300)

    assert cache.put(first, LoadedImage(rgb=array)) is True
    assert cache.put(second, LoadedImage(rgb=array)) is True
    assert cache.get(first) is not None  # first becomes the newest entry
    assert cache.put(third, LoadedImage(rgb=array)) is True

    stats = cache.stats()
    assert stats.entries == 2
    assert stats.bytes_used == payload_bytes * 2
    assert cache.get(second) is None
    assert cache.get(first) is not None
    assert cache.get(third) is not None


def test_entry_larger_than_the_budget_is_not_cached() -> None:
    array = _array(16, 16)
    cache = DecodedProxyCache(_stored_bytes(array) - 1)

    assert cache.put(cache.key_for(SHA, 1600), LoadedImage(rgb=array)) is False
    assert cache.stats().entries == 0


def test_substituting_a_key_replaces_bytes_instead_of_growing() -> None:
    array = _array(16, 16)
    cache = DecodedProxyCache(_stored_bytes(array) + 8)
    key = cache.key_for(SHA, 1600)

    assert cache.put(key, LoadedImage(rgb=array)) is True
    assert cache.put(key, LoadedImage(rgb=array)) is True

    assert cache.stats().entries == 1
    assert cache.stats().bytes_used == _stored_bytes(array)


def test_arrays_that_are_not_eight_bit_representable_are_refused() -> None:
    cache = DecodedProxyCache(1024 * 1024)
    sixteen_bit_gray = np.array([[[0.0], [1.0 / 65535.0]]], dtype=np.float32)
    sixteen_bit_gray = np.dstack([sixteen_bit_gray] * 3).astype(np.float32)

    assert cache.put(cache.key_for(SHA, 1600), LoadedImage(rgb=sixteen_bit_gray)) is False
    assert cache.stats().entries == 0


def test_clear_forgets_every_entry() -> None:
    cache = DecodedProxyCache(1024 * 1024)
    key = cache.key_for(SHA, 1600)
    cache.put(key, LoadedImage(rgb=_array()))

    cache.clear()

    assert cache.get(key) is None
    assert cache.stats().entries == 0
    assert cache.stats().bytes_used == 0


def test_stats_count_hits_and_misses() -> None:
    cache = DecodedProxyCache(1024 * 1024)
    key = cache.key_for(SHA, 1600)

    cache.get(key)
    cache.put(key, LoadedImage(rgb=_array()))
    cache.get(key)
    cache.get(key)

    stats = cache.stats()
    assert stats.misses == 1
    assert stats.hits == 2


def test_concurrent_access_keeps_entries_consistent() -> None:
    cache = DecodedProxyCache(1024 * 1024)
    array = _array(16, 16)
    image = LoadedImage(rgb=array)
    errors: list[BaseException] = []

    def worker(edge: int) -> None:
        try:
            for _ in range(60):
                key = cache.key_for(SHA, edge)
                cache.put(key, image)
                cached = cache.get(key)
                if cached is not None and not np.array_equal(cached.rgb, array):
                    raise AssertionError("cached pixels changed")
        except BaseException as exc:  # pragma: no cover - only on failure
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(edge,)) for edge in (64, 128, 256, 512)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert cache.stats().entries <= 4
