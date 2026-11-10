from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.ai.base import StyleAuthoringRequest
from app.ai.prompts import build_style_authoring_messages
from app.ai.providers.mock import MockPlannerProvider
from app.models.personal_style import (
    PersonalStyleSource,
    build_default_personal_profile,
)
from app.models.style_authoring import StyleAuthoringDraft


def _draft_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "测试风格",
        "description": "低饱和的街头风格。",
        "color": {"tendency": "偏冷", "relationships": "自然", "saturation": "低饱和"},
        "light": {
            "contrast": "中等反差",
            "shadows": "保留暗部",
            "highlights": "高光柔和",
            "expression": "柔和漫射光",
        },
        "composition": {
            "space": "负空间适中",
            "geometry": "平衡构图",
            "negativeSpace": "适中",
            "subjectRelation": "主体与环境保护关系",
        },
        "texture": {"grain": "颗粒克制", "sharpness": "清晰度自然", "detail": "细节自然"},
        "suitableScenes": ["street"],
        "unsuitableNotes": "未覆盖场景需要重新适配。",
        "targets": {"saturation": -12},
        "protected": ["preserve_skin_tone"],
        "avoid": ["oversaturated"],
        "summary": "低饱和的街头风格。",
        "confidence": 0.6,
    }
    payload.update(overrides)
    return payload


def test_draft_rejects_unknown_or_unbounded_parameters() -> None:
    with pytest.raises(ValidationError):
        StyleAuthoringDraft.model_validate(_draft_payload(targets={"curve": 1}))
    with pytest.raises(ValidationError):
        StyleAuthoringDraft.model_validate(_draft_payload(targets={"saturation": 200}))
    with pytest.raises(ValidationError):
        StyleAuthoringDraft.model_validate(_draft_payload(targets={"saturation": "x"}))
    assert StyleAuthoringDraft.model_validate(_draft_payload()).targets == {"saturation": -12}


def test_mock_authoring_detects_preferences_and_avoidance() -> None:
    draft = MockPlannerProvider().author_style(
        StyleAuthoringRequest(
            name="克制的城市",
            description="低饱和、偏冷的环境色，保留暗部层次，人物肤色自然。",
            avoid_text="不要过饱和，不要压黑，高光不要溢出",
        )
    )

    assert draft.suitable_scenes == ("portrait",)
    assert draft.targets["saturation"] == -12
    assert draft.targets["temperature"] == -8
    assert {
        "preserve_skin_tone",
        "preserve_highlight_detail",
        "preserve_shadow_detail",
    } <= {item.value for item in draft.protected}
    assert {item.value for item in draft.avoid} == {
        "oversaturated",
        "crushed_blacks",
        "clipped_highlights",
    }
    assert draft.rationale
    assert draft.summary
    assert any("模拟" in item for item in draft.limitations)


def test_mock_refinement_applies_only_requested_changes() -> None:
    base = build_default_personal_profile(
        style_id="personal_abcdef123456",
        name="基础风格",
        description="低饱和的街拍风格。",
        source=PersonalStyleSource.CUSTOM,
        targets={"saturation": -12, "temperature": -8},
    )
    refined = MockPlannerProvider().author_style(
        StyleAuthoringRequest(
            name=base.name,
            description=base.description,
            base_profile=base,
            instruction="保留更多高光，暗部不要太黑，肤色不要偏冷。",
        )
    )

    assert refined.name == base.name
    assert refined.targets["saturation"] == -12
    assert refined.targets["highlights"] < 0
    assert refined.targets["shadows"] > 0
    assert refined.targets["temperature"] > -8
    assert {
        "preserve_highlight_detail",
        "preserve_shadow_detail",
        "preserve_skin_tone",
    } <= {item.value for item in refined.protected}
    assert refined.light.highlights == "保留更多高光细节"


def test_authoring_prompt_contains_the_allowlist_and_untrusted_data_rule() -> None:
    messages = build_style_authoring_messages(
        StyleAuthoringRequest(name="测试", description="低饱和")
    )
    system = messages[0]["content"]
    assert "targets" in system
    assert "saturation" in system
    assert "untrusted" in system
    assert "Never output curves" in system
