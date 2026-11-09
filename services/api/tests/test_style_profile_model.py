from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.models.photographer import StyleCategory, StyleEnvelope
from app.models.style_profile import StyleKind, StyleProfile


def _payload(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "fan_ho",
        "kind": "master",
        "version": "1.0",
        "name": "Fan Ho 灵感",
        "description": "强烈光影与几何构图的街头风格档案。",
        "philosophy": "以光为笔，在街头空间中寻找明暗交界的戏剧性瞬间。",
        "color": {
            "tendency": "克制色彩，以影调为核心",
            "relationships": "低饱和互补",
            "saturation": "整体偏低",
        },
        "light": {
            "contrast": "高对比",
            "shadows": "深而有力",
            "highlights": "集中受光区",
            "expression": "方向性硬光",
        },
        "composition": {
            "space": "层次分割",
            "geometry": "强几何",
            "negative_space": "暗部留白",
            "subject_relation": "主体置于光区",
        },
        "texture": {"grain": "细腻颗粒", "sharpness": "适中", "detail": "保留暗部层次"},
        "scene_fit": {
            "suitable": ["street", "architecture"],
            "suitable_notes": "有方向性光线与建筑结构的街头",
            "unsuitable_notes": "光线平坦、缺少空间层次",
        },
        "post_strategy": "通过曝光、对比、曲线与局部明暗塑造强化既有光影。",
        "capture_techniques": "无法凭空创造真实光源、人物姿态或拍摄瞬间。",
        "constraints": ["preserve_highlight_detail", "preserve_shadow_detail"],
        "preserve_notes": "不破坏人物身份与现场光线关系。",
        "sources": [
            {
                "title": "Fan Ho 作品集研究",
                "url": "https://example.com/fan-ho",
                "license": "研究参考，不复制原作",
            }
        ],
        "engine_style": "street",
        "default_strength": 0.6,
    }
    data.update(overrides)
    return data


def test_camel_case_json_round_trip() -> None:
    profile = StyleProfile.model_validate(_payload())
    dumped = profile.model_dump_json(by_alias=True)
    assert '"sceneFit"' in dumped
    assert '"postStrategy"' in dumped
    assert '"engineStyle"' in dumped
    assert '"defaultStrength"' in dumped
    assert StyleProfile.model_validate_json(dumped) == profile


def test_defaults() -> None:
    data = _payload()
    for key in ("version", "engine_style", "default_strength", "constraints"):
        data.pop(key)
    profile = StyleProfile.model_validate(data)
    assert profile.version == "1.0"
    assert profile.engine_style == "natural"
    assert profile.default_strength == 0.5
    assert profile.constraints == ()
    assert profile.enabled is True
    assert profile.envelope == StyleEnvelope()


def test_to_style_definition_master_maps_to_creative() -> None:
    profile = StyleProfile.model_validate(_payload())
    definition = profile.to_style_definition()
    assert definition.id == "fan_ho"
    assert definition.version == "1.0"
    assert definition.category is StyleCategory.CREATIVE
    assert definition.name == profile.name
    assert definition.description == profile.description
    assert definition.supported_scenes == profile.scene_fit.suitable
    assert definition.default_strength == 0.6
    assert definition.envelope == profile.envelope
    assert definition.constraints == profile.constraints
    assert definition.engine_style == "street"
    assert definition.enabled is True


def test_to_style_definition_genre_maps_to_scene() -> None:
    profile = StyleProfile.model_validate(_payload(kind="genre", id="bw_documentary"))
    assert profile.kind is StyleKind.GENRE
    assert profile.to_style_definition().category is StyleCategory.SCENE


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": "Bad-ID"},
        {"id": "x"},
        {"id": "1abc"},
        {"version": "1"},
        {"version": "v1.0"},
        {"version": "1.0.0"},
        {"kind": "author"},
        {"name": "   "},
        {"description": ""},
        {"philosophy": "x" * 501},
        {"color": {}},
        {"light": {"contrast": "高对比"}},
        {"scene_fit": {"suitable": [], "suitable_notes": "a", "unsuitable_notes": "b"}},
        {
            "scene_fit": {
                "suitable": ["street", "street"],
                "suitable_notes": "a",
                "unsuitable_notes": "b",
            }
        },
        {
            "scene_fit": {
                "suitable": ["unknown"],
                "suitable_notes": "a",
                "unsuitable_notes": "b",
            }
        },
        {"constraints": ["preserve_skin_tone", "preserve_skin_tone"]},
        {"constraints": ["not_a_constraint"]},
        {"default_strength": 1.5},
        {"default_strength": -0.1},
        {"sources": []},
        {"sources": [{"title": "x", "url": "ftp://example.com", "license": "y"}]},
        {"sources": [{"title": "x", "license": ""}]},
        {"preserve_notes": ""},
        {"engine_style": "monochrome"},
        {"unknownField": 1},
    ],
)
def test_invalid_profiles_are_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        StyleProfile.model_validate(_payload(**overrides))
