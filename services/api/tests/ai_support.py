from __future__ import annotations

import json
from typing import Any

from app.ai.contracts import (
    AnalysisOptions,
    EvidenceRef,
    IssueCandidate,
    IssueType,
    MeasurementSummary,
    Severity,
)


def measurement_summary(**overrides: Any) -> MeasurementSummary:
    data: dict[str, Any] = {
        "feature_set_version": "test-features/1",
        "width": 1024,
        "height": 768,
        "aspect_ratio": 4 / 3,
        "luminance_mean": 0.45,
        "luminance_std": 0.18,
        "luminance_p1": 0.05,
        "luminance_p5": 0.12,
        "luminance_p50": 0.44,
        "luminance_p95": 0.9,
        "luminance_p99": 0.98,
        "histogram32": (0.0,) * 14 + (0.5, 0.5) + (0.0,) * 16,
        "highlights_pct": 1.5,
        "shadows_pct": 2.5,
        "mean_rgb_linear": (0.17, 0.18, 0.2),
        "cast_temperature": 0.02,
        "cast_tint": -0.01,
        "saturation_mean": 0.35,
        "saturation_p95": 0.62,
        "color_richness": 0.2,
        "sharpness": 0.3,
        "noise_estimate": 0.12,
        "horizon_tilt_deg": None,
        "brightness_centroid_x": 0.51,
        "brightness_centroid_y": 0.48,
        "edge_density_grid_3x3": (0.1,) * 9,
        "dominant_colors": ("#AABBCC", "#112233"),
    }
    data.update(overrides)
    return MeasurementSummary(**data)


def analysis_options(**overrides: Any) -> AnalysisOptions:
    data: dict[str, Any] = {}
    data.update(overrides)
    return AnalysisOptions(**data)


def vision_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "scene": {
            "primary": "portrait",
            "secondary": ["indoor"],
            "confidence": 0.72,
        },
        "subjects": [
            {
                "type": "person",
                "role": "primary",
                "confidence": 0.8,
                "bbox": {"x": 0.2, "y": 0.1, "width": 0.4, "height": 0.7},
            }
        ],
        "lighting": {
            "direction": "side",
            "type": "natural",
            "contrast": "moderate",
            "confidence": 0.6,
        },
        "color": {
            "temperature": "warm",
            "saturation": "moderate",
            "dominantColors": ["#C58B6A"],
            "confidence": 0.55,
        },
        "composition": {
            "balance": "moderate",
            "subjectPosition": "center",
            "negativeSpace": "moderate",
            "confidence": 0.5,
        },
        "limitations": ["室内光线判断存在不确定性。"],
    }
    payload.update(overrides)
    return payload


def issue_candidate(**overrides: Any) -> IssueCandidate:
    data: dict[str, Any] = {
        "id": "c1",
        "type": IssueType.UNDEREXPOSURE,
        "severity": Severity.HIGH,
        "confidence": 0.8,
        "evidence": "中位亮度 0.12，低于阈值 0.18。",
        "region_ids": ("r1",),
        "evidence_refs": (EvidenceRef(source="measurement", key="luminanceP50", value="0.12"),),
    }
    data.update(overrides)
    return IssueCandidate(**data)


def decision_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "technicalQuality": {
            "exposure": "slightly_underexposed",
            "sharpness": "good",
            "noise": "low",
            "confidence": 0.6,
        },
        "issues": [
            {
                "candidateId": "c1",
                "severity": "high",
                "confidence": 0.75,
                "evidence": "中位亮度 0.12，低于阈值 0.18。",
                "regionIds": ["r1"],
            }
        ],
        "recommendations": [
            {
                "category": "exposure",
                "priority": "high",
                "description": "提高曝光补偿，并检查暗部细节。",
                "targetRegions": ["r1"],
            }
        ],
        "limitations": ["仅依据给定测量与候选问题。"],
    }
    payload.update(overrides)
    return payload


def chat_response(content: str, *, usage: dict[str, Any] | None = None) -> dict[str, Any]:
    response: dict[str, Any] = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    if usage is not None:
        response["usage"] = usage
    return response


def json_response(payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return chat_response(json.dumps(payload, ensure_ascii=False), **kwargs)
