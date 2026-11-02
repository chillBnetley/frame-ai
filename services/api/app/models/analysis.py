from __future__ import annotations

from uuid import UUID

from pydantic import Field

from app.models.schemas import CamelModel


class SizeFeatures(CamelModel):
    width: int
    height: int
    orientation: int
    aspect_ratio: float


class LuminanceFeatures(CamelModel):
    mean: float
    std: float
    p1: float
    p5: float
    p50: float
    p95: float
    p99: float
    histogram32: list[float] = Field(min_length=32, max_length=32)


class ClippingFeatures(CamelModel):
    highlights_pct: float
    shadows_pct: float


class CastEstimate(CamelModel):
    temperature: float
    tint: float


class ColorFeatures(CamelModel):
    mean_rgb: list[float] = Field(min_length=3, max_length=3)
    cast_estimate: CastEstimate
    saturation_mean: float
    saturation_p95: float


class DetailFeatures(CamelModel):
    sharpness: float
    noise_estimate: float


class CompositionFeatures(CamelModel):
    horizon_tilt_deg: float | None
    edge_density_grid3x3: list[float] = Field(
        min_length=9,
        max_length=9,
        alias="edgeDensityGrid3x3",
    )
    brightness_centroid: list[float] = Field(min_length=2, max_length=2)


class SceneHints(CamelModel):
    is_low_light: bool
    is_high_key: bool
    is_low_key: bool
    is_monochrome: bool


class AnalysisFeatures(CamelModel):
    analyzer_version: str
    is_heuristic: bool
    size: SizeFeatures
    luminance: LuminanceFeatures
    clipping: ClippingFeatures
    color: ColorFeatures
    detail: DetailFeatures
    composition: CompositionFeatures
    scene_hints: SceneHints


class AnalyzeRequest(CamelModel):
    session_id: UUID | None = None


class AnalyzeResponse(CamelModel):
    analysis_id: UUID
    features: AnalysisFeatures
    analyzer_version: str
