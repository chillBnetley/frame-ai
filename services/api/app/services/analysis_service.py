from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from app.core.config import Settings
from app.imaging.analyzer import ANALYZER_MAX_EDGE, ANALYZER_VERSION, analyze
from app.imaging.loader import load_proxy, proxy_cache_directory
from app.models.analysis import AnalysisFeatures
from app.services.image_service import ImageService


@dataclass(frozen=True)
class AnalysisResult:
    analysis_id: UUID
    features: AnalysisFeatures
    analyzer_version: str


def analysis_identifier(image_id: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"frame-ai:analysis:{image_id}:{ANALYZER_VERSION}")


class AnalysisService:
    def __init__(
        self,
        settings: Settings,
        images: ImageService,
        *,
        max_entries: int = 64,
    ) -> None:
        self.settings = settings
        self.images = images
        self.max_entries = max_entries
        self._lock = threading.Lock()
        self._cache: OrderedDict[tuple[str, str], AnalysisResult] = OrderedDict()

    def analyze(self, image_id: str) -> AnalysisResult:
        record, path = self.images.get_original(image_id)
        key = (record.id, ANALYZER_VERSION)
        cached = self._get(key)
        if cached is not None:
            return cached

        proxy = load_proxy(
            path,
            original_sha256=record.sha256,
            max_edge=ANALYZER_MAX_EDGE,
            cache_dir=proxy_cache_directory(self.settings.preview_dir),
            max_pixels=self.settings.max_image_pixels,
        )
        features = analyze(
            proxy,
            display_width=record.width,
            display_height=record.height,
            exif_orientation=record.exif_orientation,
        )
        result = AnalysisResult(
            analysis_id=analysis_identifier(record.id),
            features=features,
            analyzer_version=ANALYZER_VERSION,
        )
        self._put(key, result)
        return result

    def _get(self, key: tuple[str, str]) -> AnalysisResult | None:
        with self._lock:
            result = self._cache.get(key)
            if result is not None:
                self._cache.move_to_end(key)
            return result

    def _put(self, key: tuple[str, str], result: AnalysisResult) -> None:
        with self._lock:
            self._cache[key] = result
            self._cache.move_to_end(key)
            while len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)
