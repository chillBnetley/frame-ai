from __future__ import annotations

import json
from typing import Any

from app.ai.base import DecisionRequest
from app.ai.contracts import AnalysisOptions, MeasurementSummary

VISION_PROMPT_VERSION = "stage3-vision/2"
DECISION_PROMPT_VERSION = "stage3-decision/1"

_VISION_SYSTEM = """\
You are FRAME AI's photograph interpretation engine. Inspect the attached image and
return a grounded description of what is visibly present.

Return ONLY one JSON object with exactly these keys and no extra keys:
{
  "scene": {
    "primary": "portrait|landscape|street|architecture|night|indoor|food|nature|other",
    "secondary": ["same enum values"],
    "confidence": 0.0
  },
  "subjects": [
    {
      "type": "person|building|sky|road|plant|animal|food|vehicle|other",
      "role": "primary|secondary",
      "confidence": 0.0,
      "bbox": {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}
    }
  ],
  "lighting": {
    "direction": "front|side|back|side_back|diffuse|overcast|artificial|mixed|unknown",
    "type": "natural|artificial|mixed|unknown",
    "contrast": "low|moderate|high|unknown",
    "confidence": 0.0
  },
  "color": {
    "temperature": "warm|neutral|cool|unknown",
    "saturation": "low|moderate|high|unknown",
    "harmony": "harmonious|moderate|clashing|unknown",
    "dominantColors": ["#RRGGBB"],
    "confidence": 0.0
  },
  "composition": {
    "balance": "balanced|moderate|unbalanced|unknown",
    "subjectPosition": "left|right|center|top|bottom|unknown",
    "negativeSpace": "low|moderate|high|unknown",
    "occlusion": "none|minor|significant|unknown",
    "confidence": 0.0
  },
  "limitations": ["short statement in Simplified Chinese"]
}

Rules:
- Every confidence is a number from 0.0 to 1.0.
- Bounding boxes are normalized to the displayed image: x/y/width/height in 0..1,
  x+width <= 1, y+height <= 1, and width/height > 0.
- Include only subjects that are actually visible. Use "other" only when needed.
- If lighting, color, or composition cannot be judged reliably, use "unknown".
- "harmony" describes whether the dominant colors work together; use "unknown"
  when the palette is too limited or ambiguous.
- "occlusion" describes whether the primary subject is blocked by another object;
  use "none" only when the subject is clearly unobstructed.
- Do not invent details, text, locations, identities, or camera settings.
- "secondary" must not repeat the primary scene.
- Dominant colors must be 1-5 uppercase #RRGGBB values.
- Limitations must state uncertainty in Simplified Chinese; never mention JSON.
- Return JSON only: no markdown, no code fences, no commentary.
"""

_DECISION_SYSTEM = """\
You are FRAME AI's photography diagnosis assistant. You receive:
1. deterministic image measurements,
2. a vision model's semantic description,
3. a closed list of candidate issues produced by rule checks.

Return ONLY one JSON object with exactly these keys and no extra keys:
{
  "technicalQuality": {
    "exposure": "underexposed|slightly_underexposed|balanced|slightly_overexposed|overexposed|unknown",
    "sharpness": "poor|soft|good|unknown",
    "noise": "low|moderate|high|unknown",
    "confidence": 0.0
  },
  "issues": [
    {
      "candidateId": "candidate id copied from the input",
      "severity": "low|medium|high",
      "confidence": 0.0,
      "evidence": "short evidence in Simplified Chinese, citing the supplied numbers or vision fields",
      "regionIds": ["region ids from the input"]
    }
  ],
  "recommendations": [
    {
      "category": "exposure|color|composition|sharpness|lighting",
      "priority": "low|medium|high",
      "description": "specific, actionable recommendation in Simplified Chinese",
      "targetRegions": ["region ids from the input"]
    }
  ],
  "limitations": ["short statement in Simplified Chinese"]
}

Rules:
- Select issues ONLY from the supplied candidate list. Never invent a new issue.
- Copy candidateId exactly; do not modify it.
- Use only region IDs present in the supplied candidates or subjects.
- Every issue must cite concrete evidence. If evidence is insufficient, omit it.
- Recommendations must name the problem or region and a concrete direction.
  Do not write generic phrases such as "make it more transparent".
- Never claim a fact that is not supported by the supplied measurements or vision fields.
- If uncertain, use "unknown" and add a limitation.
- Return JSON only: no markdown, no code fences, no commentary.
"""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def build_vision_messages(
    image_data_url: str,
    options: AnalysisOptions,
    measurements: MeasurementSummary,
) -> list[dict[str, Any]]:
    user_text = (
        "Analyze the attached photograph according to the enabled options.\n"
        f"Enabled options: {_json(options.model_dump(mode='json', by_alias=True))}\n"
        f"Measured features (do not treat as semantic truth): "
        f"{_json(measurements.model_dump(mode='json', by_alias=True))}\n"
        "Return the required JSON object only."
    )
    return [
        {"role": "system", "content": _VISION_SYSTEM},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        },
    ]


def build_decision_messages(request: DecisionRequest) -> list[dict[str, Any]]:
    candidates = [
        candidate.model_dump(mode="json", by_alias=True) for candidate in request.candidates
    ]
    user_text = (
        f"Enabled options: {_json(request.options.model_dump(mode='json', by_alias=True))}\n"
        f"Measurements: {_json(request.measurements.model_dump(mode='json', by_alias=True))}\n"
        f"Vision description: {_json(request.vision.model_dump(mode='json', by_alias=True))}\n"
        f"Issue candidates: {_json(candidates)}\n"
        "Return the required JSON object only."
    )
    return [
        {"role": "system", "content": _DECISION_SYSTEM},
        {"role": "user", "content": user_text},
    ]


def build_repair_messages(
    messages: list[dict[str, Any]],
    invalid_content: str,
    problem: str,
) -> list[dict[str, Any]]:
    previous = invalid_content.strip()[:4000] or "(empty response)"
    return [
        *messages,
        {"role": "assistant", "content": previous},
        {
            "role": "user",
            "content": (
                f"Your previous response was rejected: {problem}. "
                "Return only a valid JSON object that exactly matches the required schema."
            ),
        },
    ]


__all__ = [
    "DECISION_PROMPT_VERSION",
    "VISION_PROMPT_VERSION",
    "build_decision_messages",
    "build_repair_messages",
    "build_vision_messages",
]
