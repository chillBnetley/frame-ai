from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import TypeAlias

import numpy as np
from numpy.typing import NDArray

from app.imaging.loader import PROXY_VERSION, LoadedImage

ProxyKey: TypeAlias = tuple[str, str, int]


@dataclass(frozen=True)
class ProxyCacheStats:
    hits: int
    misses: int
    entries: int
    bytes_used: int


def _to_uint8_if_exact(rgb: NDArray[np.float32]) -> NDArray[np.uint8] | None:
    """Return the 8-bit form, or None when the array is not 8-bit representable."""
    scaled = rgb * np.float32(255.0)
    quantised: NDArray[np.uint8] = np.rint(scaled).astype(np.uint8)
    if not np.array_equal(scaled, quantised.astype(np.float32)):
        return None
    return np.ascontiguousarray(quantised)


class DecodedProxyCache:
    """Bounded in-process cache of decoded render proxies.

    Entries hold uint8 pixels, so an image that is not 8-bit representable (a
    16-bit gray source on the loader's float path) is re-decoded instead of
    silently losing precision.
    """

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max(0, max_bytes)
        self._entries: OrderedDict[ProxyKey, NDArray[np.uint8]] = OrderedDict()
        self._bytes_used = 0
        self._hits = 0
        self._misses = 0
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.max_bytes > 0

    def key_for(self, original_sha256: str, edge: int) -> ProxyKey:
        return (original_sha256.lower(), PROXY_VERSION, edge)

    def get(self, key: ProxyKey) -> LoadedImage | None:
        with self._lock:
            stored = self._entries.get(key)
            if stored is None:
                self._misses += 1
                return None
            self._entries.move_to_end(key)
            self._hits += 1
        return LoadedImage(rgb=stored.astype(np.float32) / np.float32(255.0))

    def put(self, key: ProxyKey, image: LoadedImage) -> bool:
        if not self.enabled:
            return False
        stored = _to_uint8_if_exact(image.rgb)
        if stored is None or stored.nbytes > self.max_bytes:
            return False
        with self._lock:
            replaced = self._entries.pop(key, None)
            if replaced is not None:
                self._bytes_used -= replaced.nbytes
            self._entries[key] = stored
            self._bytes_used += stored.nbytes
            while self._bytes_used > self.max_bytes and len(self._entries) > 1:
                _, evicted = self._entries.popitem(last=False)
                self._bytes_used -= evicted.nbytes
        return True

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._bytes_used = 0

    def stats(self) -> ProxyCacheStats:
        with self._lock:
            return ProxyCacheStats(
                hits=self._hits,
                misses=self._misses,
                entries=len(self._entries),
                bytes_used=self._bytes_used,
            )
