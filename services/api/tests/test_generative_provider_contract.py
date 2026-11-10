from __future__ import annotations

from io import BytesIO

import numpy as np
import pytest
from PIL import Image

from app.ai.generative import (
    GenerativeCapabilities,
    GenerativeImageInput,
    GenerativeProviderError,
    GenerativeRequest,
    GenerativeRequestSpec,
    validate_spec,
)
from app.ai.providers.generative_mock import MockGenerativeProvider
from app.models.generative import GenerativeTaskType
from tests.conftest import make_image


def _spec(
    *,
    task_type: GenerativeTaskType = GenerativeTaskType.LOCAL_EDIT,
    candidates: int = 1,
    has_mask: bool = False,
    width: int = 64,
    height: int = 48,
) -> GenerativeRequestSpec:
    return GenerativeRequestSpec(
        task_type=task_type,
        instruction="test",
        has_mask=has_mask,
        candidates=candidates,
        input_width=width,
        input_height=height,
    )


def test_mock_capabilities_are_explicit():
    capabilities = MockGenerativeProvider().capabilities()
    assert capabilities.supported_task_types == (GenerativeTaskType.LOCAL_EDIT,)
    assert capabilities.supports_mask is True
    assert capabilities.supports_multiple_outputs is False
    assert capabilities.supports_async is False
    assert capabilities.supports_cancel is False
    assert capabilities.allowed_output_formats == ("png",)
    assert "Mock" in capabilities.declared_retention
    assert capabilities.notes


def test_validate_spec_rejects_unsupported_capabilities():
    provider = MockGenerativeProvider()
    with pytest.raises(GenerativeProviderError) as excinfo:
        provider.validate_spec(_spec(task_type=GenerativeTaskType.OUTPAINT))
    assert excinfo.value.code == "generative_capability_unsupported"
    assert excinfo.value.details["taskType"] == "outpaint"

    with pytest.raises(GenerativeProviderError) as candidates:
        provider.validate_spec(_spec(candidates=2))
    assert candidates.value.code == "generative_capability_unsupported"

    with pytest.raises(GenerativeProviderError) as pixels:
        provider.validate_spec(_spec(width=6000, height=5000))
    assert pixels.value.code == "generative_input_too_large"

    with pytest.raises(GenerativeProviderError) as long_edge:
        provider.validate_spec(_spec(width=9000, height=1))
    assert long_edge.value.code == "generative_input_too_large"


def test_validate_spec_rejects_mask_when_unsupported():
    capabilities = GenerativeCapabilities(
        supported_task_types=(GenerativeTaskType.LOCAL_EDIT,),
        supports_mask=False,
        supports_multiple_outputs=False,
        supports_async=False,
        supports_cancel=False,
        max_output_pixels=1_000_000,
        max_long_edge=4096,
        allowed_output_formats=("png",),
        declared_retention="test",
    )
    with pytest.raises(GenerativeProviderError) as excinfo:
        validate_spec(capabilities, _spec(has_mask=True))
    assert excinfo.value.code == "generative_capability_unsupported"


def test_validate_request_rejects_empty_input():
    provider = MockGenerativeProvider()
    request = GenerativeRequest(
        task_id="task-1",
        task_type=GenerativeTaskType.LOCAL_EDIT,
        instruction="test",
        image=GenerativeImageInput(
            data=b"",
            mime_type="image/png",
            width=64,
            height=48,
        ),
    )
    with pytest.raises(GenerativeProviderError) as excinfo:
        provider.validate_request(request)
    assert excinfo.value.code == "generative_invalid_input"


def test_mock_lifecycle_and_output_shape():
    provider = MockGenerativeProvider()
    image = make_image(size=(64, 48))
    request = GenerativeRequest(
        task_id="task-1",
        task_type=GenerativeTaskType.LOCAL_EDIT,
        instruction="warm the scene",
        image=GenerativeImageInput(
            data=image,
            mime_type="image/png",
            width=64,
            height=48,
        ),
        params={"candidates": 1},
    )
    job = provider.submit(request)
    assert job.status == "succeeded"
    assert job.provider_job_id == "mock-task-1"
    assert provider.poll(job) is job
    result = provider.fetch(job)
    assert result.width == 64
    assert result.height == 48
    assert result.mime_type == "image/png"
    with Image.open(BytesIO(result.data)) as decoded:
        assert decoded.size == (64, 48)
        assert decoded.format == "PNG"
    assert provider.check_connection() == 0
    provider.cancel(job)


def test_mock_honours_the_mask():
    provider = MockGenerativeProvider()
    image = make_image(size=(64, 48))
    mask = np.zeros((48, 64), dtype=np.uint8)
    mask[:, 32:] = 255
    mask_buffer = BytesIO()
    Image.fromarray(mask, mode="L").save(mask_buffer, format="PNG")
    request = GenerativeRequest(
        task_id="task-mask",
        task_type=GenerativeTaskType.LOCAL_EDIT,
        instruction="edit the right half",
        image=GenerativeImageInput(
            data=image,
            mime_type="image/png",
            width=64,
            height=48,
            mask=mask_buffer.getvalue(),
            mask_mime_type="image/png",
        ),
        params={"candidates": 1},
    )

    result = provider.fetch(provider.submit(request))
    result_pixels = np.asarray(Image.open(BytesIO(result.data)).convert("RGB"))
    source_pixels = np.asarray(Image.open(BytesIO(image)).convert("RGB"))
    assert np.array_equal(result_pixels[:, :32], source_pixels[:, :32])
    assert not np.array_equal(result_pixels[:, 32:], source_pixels[:, 32:])
