from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.ai.errors import ProviderConfigurationError
from app.ai.factory import (
    build_decision_provider,
    build_provider_bundle,
    build_vision_provider,
)
from app.ai.providers.mock import MockDecisionProvider, MockVisionProvider
from app.ai.providers.openai_compatible import (
    OpenAICompatibleDecisionProvider,
    OpenAICompatibleVisionProvider,
)
from app.core.config import Settings
from tests.ai_support import analysis_options, measurement_summary


def make_settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "vision_provider": "mock",
        "decision_provider": "mock",
        "vision_api_key": "",
        "vision_model": "",
        "vision_api_base_url": "",
        "decision_api_key": "",
        "decision_model": "",
        "decision_api_base_url": "",
        **overrides,
    }
    return Settings(**values)


def test_defaults_build_mock_providers_and_mark_the_bundle():
    settings = make_settings()

    bundle = build_provider_bundle(settings)

    assert isinstance(bundle.vision, MockVisionProvider)
    assert isinstance(bundle.decision, MockDecisionProvider)
    assert bundle.is_mock is True
    assert bundle.mock_reasons == ("vision_provider=mock", "decision_provider=mock")
    assert bundle.vision.model == "mock-vision"
    assert bundle.decision.model == "mock-decision"


def test_mock_scenario_flows_from_settings_and_unknown_falls_back():
    from app.ai.base import ModelImage, VisionRequest

    request = VisionRequest(
        image=ModelImage(data=b"x", mime_type="image/jpeg", width=8, height=8),
        options=analysis_options(),
        measurements=measurement_summary(),
    )

    portrait = build_vision_provider(make_settings(mock_scenario="portrait"))
    assert portrait.analyze(request).scene.primary == "portrait"

    unknown = build_vision_provider(make_settings(mock_scenario="nope"))
    assert unknown.analyze(request).scene.primary == "other"


@pytest.mark.parametrize(
    ("field", "env_name"),
    [
        ("vision_api_key", "FRAME_VISION_API_KEY"),
        ("vision_model", "FRAME_VISION_MODEL"),
        ("vision_api_base_url", "FRAME_VISION_API_BASE_URL"),
    ],
)
def test_openai_vision_requires_each_setting(field, env_name):
    values = {
        "vision_provider": "openai",
        "vision_api_key": "sk-test",
        "vision_model": "model",
        "vision_api_base_url": "https://example.test/v1",
        field: "",
    }

    with pytest.raises(ProviderConfigurationError) as error:
        build_vision_provider(make_settings(**values))

    assert env_name in str(error.value)
    assert "sk-test" not in str(error.value)


def test_openai_vision_lists_every_missing_setting_in_order():
    with pytest.raises(ProviderConfigurationError) as error:
        build_vision_provider(make_settings(vision_provider="openai"))

    message = str(error.value)
    assert message.index("FRAME_VISION_API_KEY") < message.index("FRAME_VISION_MODEL")
    assert message.index("FRAME_VISION_MODEL") < message.index("FRAME_VISION_API_BASE_URL")


@pytest.mark.parametrize(
    ("field", "env_name"),
    [
        ("decision_api_key", "FRAME_DECISION_API_KEY"),
        ("decision_model", "FRAME_DECISION_MODEL"),
        ("decision_api_base_url", "FRAME_DECISION_API_BASE_URL"),
    ],
)
def test_openai_decision_requires_each_setting(field, env_name):
    values = {
        "decision_provider": "openai",
        "decision_api_key": "sk-test",
        "decision_model": "model",
        "decision_api_base_url": "https://example.test/v1",
        field: "",
    }

    with pytest.raises(ProviderConfigurationError) as error:
        build_decision_provider(make_settings(**values))

    assert env_name in str(error.value)
    assert "sk-test" not in str(error.value)


def test_openai_providers_are_built_when_complete():
    settings = make_settings(
        vision_provider="openai",
        vision_api_key="sk-vision-secret",
        vision_model="vision-model",
        vision_api_base_url="https://vision.test/v1/",
        decision_provider="openai",
        decision_api_key="sk-decision-secret",
        decision_model="decision-model",
        decision_api_base_url="https://decision.test/v1",
    )

    bundle = build_provider_bundle(settings)

    assert isinstance(bundle.vision, OpenAICompatibleVisionProvider)
    assert isinstance(bundle.decision, OpenAICompatibleDecisionProvider)
    assert bundle.is_mock is False
    assert bundle.mock_reasons == ()
    assert bundle.vision.model == "vision-model"
    assert bundle.decision.model == "decision-model"
    assert "sk-vision-secret" not in repr(bundle.vision)
    assert "sk-decision-secret" not in repr(bundle.decision)


def test_mixed_bundle_reports_only_the_mock_reason():
    settings = make_settings(
        vision_provider="openai",
        vision_api_key="sk-vision-secret",
        vision_model="vision-model",
        vision_api_base_url="https://vision.test/v1",
        decision_provider="mock",
    )

    bundle = build_provider_bundle(settings)

    assert bundle.is_mock is True
    assert bundle.mock_reasons == ("decision_provider=mock",)


def test_settings_mask_secrets_in_repr_and_dump():
    settings = make_settings(vision_api_key="sk-secret")

    assert "sk-secret" not in repr(settings)
    assert "sk-secret" not in str(settings.model_dump())


@pytest.mark.parametrize(
    "overrides",
    [
        {"vision_provider": "bogus"},
        {"decision_provider": "bogus"},
        {"vision_api_base_url": "ftp://example.test"},
        {"vision_timeout": 0},
        {"vision_max_retries": -1},
        {"vision_repair_attempts": 4},
        {"decision_timeout": 601},
        {"decision_max_retries": 11},
        {"analysis_max_edge": 511},
        {"analysis_max_edge": 2049},
    ],
)
def test_invalid_provider_settings_are_rejected(overrides):
    with pytest.raises(ValidationError):
        make_settings(**overrides)


def test_analysis_max_edge_accepts_the_documented_range():
    assert make_settings(analysis_max_edge=512).analysis_max_edge == 512
    assert make_settings(analysis_max_edge=2048).analysis_max_edge == 2048
