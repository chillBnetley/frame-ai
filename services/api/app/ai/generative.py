from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from app.models.generative import GenerativeTaskType

ProviderJobStatus = Literal["queued", "processing", "succeeded", "failed"]


class GenerativeProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}


@dataclass(frozen=True, slots=True)
class GenerativeCapabilities:
    supported_task_types: tuple[GenerativeTaskType, ...]
    supports_mask: bool
    supports_multiple_outputs: bool
    supports_async: bool
    supports_cancel: bool
    max_output_pixels: int
    max_long_edge: int
    allowed_output_formats: tuple[str, ...]
    declared_retention: str
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GenerativeRequestSpec:
    """What the service knows before it prepares pixels."""

    task_type: GenerativeTaskType
    instruction: str
    has_mask: bool
    candidates: int
    input_width: int
    input_height: int
    target_width: int | None = None
    target_height: int | None = None

    @property
    def input_pixels(self) -> int:
        return self.input_width * self.input_height

    @property
    def output_width(self) -> int:
        return self.target_width if self.target_width is not None else self.input_width

    @property
    def output_height(self) -> int:
        return self.target_height if self.target_height is not None else self.input_height

    @property
    def output_pixels(self) -> int:
        return self.output_width * self.output_height

    @property
    def output_long_edge(self) -> int:
        return max(self.output_width, self.output_height)


def validate_spec(
    capabilities: GenerativeCapabilities,
    spec: GenerativeRequestSpec,
) -> None:
    """Validate a task against the provider's declared capabilities."""
    if spec.task_type not in capabilities.supported_task_types:
        raise GenerativeProviderError(
            "generative_capability_unsupported",
            "The selected provider does not support this task type.",
            details={
                "taskType": spec.task_type.value,
                "supported": [item.value for item in capabilities.supported_task_types],
            },
        )
    if spec.candidates < 1 or (spec.candidates > 1 and not capabilities.supports_multiple_outputs):
        raise GenerativeProviderError(
            "generative_capability_unsupported",
            "The selected provider does not support this candidate count.",
            details={"candidates": spec.candidates},
        )
    if spec.has_mask and not capabilities.supports_mask:
        raise GenerativeProviderError(
            "generative_capability_unsupported",
            "The selected provider does not support masks.",
        )
    if spec.input_width <= 0 or spec.input_height <= 0:
        raise GenerativeProviderError(
            "generative_invalid_input",
            "The input image has invalid dimensions.",
        )
    if spec.output_width <= 0 or spec.output_height <= 0:
        raise GenerativeProviderError(
            "generative_invalid_input",
            "The target canvas has invalid dimensions.",
        )
    if spec.output_pixels > capabilities.max_output_pixels:
        raise GenerativeProviderError(
            "generative_input_too_large",
            "The image or target canvas is larger than the provider accepts.",
            details={
                "pixels": spec.output_pixels,
                "maxPixels": capabilities.max_output_pixels,
            },
        )
    if spec.output_long_edge > capabilities.max_long_edge:
        raise GenerativeProviderError(
            "generative_input_too_large",
            "The image or target canvas is longer than the provider accepts.",
            details={
                "longEdge": spec.output_long_edge,
                "maxLongEdge": capabilities.max_long_edge,
            },
        )


@dataclass(frozen=True, slots=True)
class GenerativeImageInput:
    data: bytes
    mime_type: str
    width: int
    height: int
    mask: bytes | None = None
    mask_mime_type: str | None = None


@dataclass(frozen=True, slots=True)
class GenerativeRequest:
    task_id: str
    task_type: GenerativeTaskType
    instruction: str
    image: GenerativeImageInput
    params: dict[str, object] = field(default_factory=dict)
    prompt_version: str = "generative/1"


@dataclass(frozen=True, slots=True)
class GeneratedImage:
    data: bytes
    mime_type: str
    width: int
    height: int
    provider_job_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GenerativeProviderJob:
    provider_job_id: str | None
    status: ProviderJobStatus
    result: GeneratedImage | None = None
    error_code: str | None = None
    error_message: str | None = None


class GenerativeProvider(Protocol):
    name: str
    model: str
    is_mock: bool
    prompt_version: str

    def capabilities(self) -> GenerativeCapabilities: ...

    def validate_spec(self, spec: GenerativeRequestSpec) -> None: ...

    def validate_request(self, request: GenerativeRequest) -> None: ...

    def submit(self, request: GenerativeRequest) -> GenerativeProviderJob: ...

    def poll(self, job: GenerativeProviderJob) -> GenerativeProviderJob: ...

    def fetch(self, job: GenerativeProviderJob) -> GeneratedImage: ...

    def cancel(self, job: GenerativeProviderJob) -> None: ...

    def check_connection(self, *, timeout: float | None = None) -> int: ...


__all__ = [
    "GeneratedImage",
    "GenerativeCapabilities",
    "GenerativeImageInput",
    "GenerativeProvider",
    "GenerativeProviderError",
    "GenerativeProviderJob",
    "GenerativeRequest",
    "GenerativeRequestSpec",
    "ProviderJobStatus",
    "validate_spec",
]
