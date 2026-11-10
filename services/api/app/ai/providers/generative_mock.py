from __future__ import annotations

import hashlib
from io import BytesIO

import numpy as np
from PIL import Image, ImageOps

from app.ai.generative import (
    GeneratedImage,
    GenerativeCapabilities,
    GenerativeProviderError,
    GenerativeProviderJob,
    GenerativeRequest,
    GenerativeRequestSpec,
)
from app.ai.generative import (
    validate_spec as validate_capability_spec,
)
from app.imaging.output import encode_image
from app.models.generative import GenerativeTaskType

_MOCK_RETENTION = "Mock provider runs in-process and sends no pixels off this machine."


class MockGenerativeProvider:
    """Deterministic in-process generator used to exercise the task pipeline.

    The output is intentionally synthetic: a stable tint plus a small checker
    pattern, optionally confined to the mask. It is never presented as a real
    model result and its tasks are always recorded with ``is_mock=1``.
    """

    name = "mock"
    model = "generative-mock-1"
    is_mock = True
    prompt_version = "generative-mock/1"

    def capabilities(self) -> GenerativeCapabilities:
        return GenerativeCapabilities(
            supported_task_types=(GenerativeTaskType.LOCAL_EDIT,),
            supports_mask=True,
            supports_multiple_outputs=False,
            supports_async=False,
            supports_cancel=False,
            max_output_pixels=24_000_000,
            max_long_edge=8192,
            allowed_output_formats=("png",),
            declared_retention=_MOCK_RETENTION,
            notes=("模拟生成：仅用于验证任务、版本与存储链路，不代表真实模型效果。",),
        )

    def validate_spec(self, spec: GenerativeRequestSpec) -> None:
        validate_capability_spec(self.capabilities(), spec)

    def validate_request(self, request: GenerativeRequest) -> None:
        if not request.image.data:
            raise GenerativeProviderError(
                "generative_invalid_input",
                "The input image is empty.",
            )
        raw_candidates = request.params.get("candidates", 1)
        candidates = (
            raw_candidates
            if isinstance(raw_candidates, int) and not isinstance(raw_candidates, bool)
            else 1
        )
        self.validate_spec(
            GenerativeRequestSpec(
                task_type=request.task_type,
                instruction=request.instruction,
                has_mask=request.image.mask is not None,
                candidates=candidates,
                input_width=request.image.width,
                input_height=request.image.height,
            )
        )

    def submit(self, request: GenerativeRequest) -> GenerativeProviderJob:
        self.validate_request(request)
        result = self._render(request)
        return GenerativeProviderJob(
            provider_job_id=f"mock-{request.task_id}",
            status="succeeded",
            result=result,
        )

    def poll(self, job: GenerativeProviderJob) -> GenerativeProviderJob:
        return job

    def fetch(self, job: GenerativeProviderJob) -> GeneratedImage:
        if job.status != "succeeded" or job.result is None:
            raise GenerativeProviderError(
                job.error_code or "generative_provider_failed",
                job.error_message or "The mock generation did not produce a result.",
            )
        return job.result

    def cancel(self, job: GenerativeProviderJob) -> None:
        return None

    def check_connection(self, *, timeout: float | None = None) -> int:
        return 0

    def _render(self, request: GenerativeRequest) -> GeneratedImage:
        with Image.open(BytesIO(request.image.data)) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
        width, height = image.size
        source = np.asarray(image, dtype=np.float32)

        seed = hashlib.sha256(f"{request.task_id}|{request.instruction}".encode()).digest()
        tint = np.array(
            (
                40.0 + seed[0] % 80,
                40.0 + seed[1] % 80,
                40.0 + seed[2] % 80,
            ),
            dtype=np.float32,
        )
        generated = source * np.float32(0.85) + tint * np.float32(0.15)

        yy, xx = np.mgrid[0:height, 0:width]
        checker = (((xx // 16) + (yy // 16)) % 2).astype(np.float32)
        generated += ((checker - np.float32(0.5)) * np.float32(18.0))[..., None]

        if request.image.mask is not None:
            with Image.open(BytesIO(request.image.mask)) as opened_mask:
                mask = opened_mask.convert("L")
                if mask.size != (width, height):
                    mask = mask.resize((width, height), Image.Resampling.NEAREST)
                alpha = np.asarray(mask, dtype=np.float32) / np.float32(255.0)
            generated = source * (np.float32(1.0) - alpha[..., None]) + generated * alpha[..., None]

        pixels = np.clip(np.rint(generated), 0.0, 255.0).astype(np.uint8)
        data = encode_image(np.ascontiguousarray(pixels), image_format="png")
        return GeneratedImage(
            data=data,
            mime_type="image/png",
            width=width,
            height=height,
            provider_job_id=f"mock-{request.task_id}",
            metadata={"mock": True},
        )


__all__ = ["MockGenerativeProvider"]
