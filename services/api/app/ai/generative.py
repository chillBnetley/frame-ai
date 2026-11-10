from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from app.models.generative import GenerativeTaskType

ProviderJobStatus = Literal["queued", "processing", "succeeded", "failed"]


class GenerativeProviderError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


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
    "ProviderJobStatus",
]
