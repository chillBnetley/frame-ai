from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.models.schemas import CamelModel


class GenerativeTaskType(StrEnum):
    OUTPAINT = "outpaint"
    INPAINT = "inpaint"
    REMOVE = "remove"
    LOCAL_EDIT = "local_edit"


class GenerativeTaskStatus(StrEnum):
    CREATED = "created"
    VALIDATING = "validating"
    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class GenerativeTaskStage(StrEnum):
    QUEUED = "queued"
    PREPARING_INPUT = "preparing_input"
    SUBMITTING = "submitting"
    GENERATING = "generating"
    VALIDATING = "validating"
    SAVING = "saving"
    COMPLETED = "completed"
    FAILED = "failed"


class GenerativeResultStatus(StrEnum):
    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DISCARDED = "discarded"


class GenerativeMaskKind(StrEnum):
    BRUSH = "brush"
    RECT = "rect"
    ELLIPSE = "ellipse"
    SEMANTIC = "semantic"
    AI_PROPOSAL = "ai_proposal"


class GenerativeMaskSource(StrEnum):
    USER = "user"
    SEMANTIC = "semantic"
    AI = "ai"


class GenerativeParams(CamelModel):
    """Execution parameters shared by the current task types.

    Batch 1 only exposes candidates=1 through the mock provider. Task-specific
    canvas and mask parameters join this model in their own batches, after the
    Provider capability that supports them is declared.
    """

    candidates: int = Field(default=1, ge=1, le=2)


class GenerativeTaskRequest(CamelModel):
    session_id: UUID
    task_type: GenerativeTaskType = GenerativeTaskType.LOCAL_EDIT
    instruction: str = Field(default="", max_length=2000)
    params: GenerativeParams = Field(default_factory=GenerativeParams)
    mask_id: UUID | None = None
    # Required only when the selected provider sends pixels off this machine.
    consent: bool = False


class GenerativePlan(CamelModel):
    """Structured task plan; never carries low-level image parameters."""

    task_type: GenerativeTaskType
    instruction: str
    target: Literal["full-image", "mask"] = "full-image"
    mask_id: UUID | None = None
    preserve: list[str] = Field(default_factory=list)
    candidates: int = 1
    needs_clarification: bool = False
    notes: list[str] = Field(default_factory=list)


class GenerativeErrorInfo(CamelModel):
    code: str
    message: str


class GenerativeTaskCreated(CamelModel):
    task_id: UUID
    status: GenerativeTaskStatus
    stage: GenerativeTaskStage
    deduplicated: bool
    is_mock: bool
    provider: str
    model: str
    expires_at: datetime


class GenerativeResultView(CamelModel):
    result_id: UUID
    result_index: int
    status: GenerativeResultStatus
    width: int
    height: int
    image_url: str
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime
    decided_at: datetime | None = None


class GenerativeTaskStatusResponse(CamelModel):
    task_id: UUID
    task_type: GenerativeTaskType
    status: GenerativeTaskStatus
    stage: GenerativeTaskStage
    instruction: str
    is_mock: bool
    provider: str
    model: str
    error: GenerativeErrorInfo | None = None
    results: list[GenerativeResultView] = Field(default_factory=list)
    attempts: int = 0
    max_attempts: int = 2
    cancel_requested: bool = False
    base_revision_id: UUID | None = None
    base_generated_asset_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    expires_at: datetime


class GenerativeTaskListResponse(CamelModel):
    items: list[GenerativeTaskStatusResponse]


class GenerativeCapabilitiesResponse(CamelModel):
    provider: str
    model: str
    is_mock: bool
    supported_task_types: list[GenerativeTaskType]
    supports_mask: bool
    supports_multiple_outputs: bool
    max_output_pixels: int
    max_long_edge: int
    allowed_output_formats: list[str]
    declared_retention: str
    notes: list[str] = Field(default_factory=list)


class GenerativeTaskRecord(CamelModel):
    id: str
    owner_id: str
    image_id: str
    session_id: str
    base_revision_id: str | None = None
    base_generated_asset_id: str | None = None
    task_type: GenerativeTaskType
    instruction: str
    plan_json: str
    params_json: str
    mask_id: str | None = None
    provider: str
    model: str
    prompt_version: str
    provider_job_id: str | None = None
    is_mock: bool
    status: GenerativeTaskStatus
    stage: GenerativeTaskStage
    attempts: int = 0
    max_attempts: int = 2
    cancel_requested: bool = False
    consent_at: datetime | None = None
    provider_retention: str = ""
    error_code: str | None = None
    error_message: str | None = None
    dedupe_key: str
    idempotency_key: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    expires_at: datetime


class GenerativeResultRecord(CamelModel):
    id: str
    task_id: str
    result_index: int
    storage_key: str
    sha256: str
    width: int
    height: int
    bytes: int
    mime_type: str
    status: GenerativeResultStatus
    validation_json: str
    revision_id: str | None = None
    created_at: datetime
    decided_at: datetime | None = None


class GenerativeMaskRecord(CamelModel):
    id: str
    owner_id: str
    image_id: str
    base_generated_asset_id: str | None = None
    kind: GenerativeMaskKind
    source: GenerativeMaskSource
    coordinate_space: Literal["base-normalized"] = "base-normalized"
    width: int
    height: int
    storage_key: str
    sha256: str
    feather: float = 0.0
    inverted: bool = False
    strokes_json: str = "[]"
    created_at: datetime
    deleted_at: datetime | None = None


class GeneratedAssetRecord(CamelModel):
    id: str
    image_id: str
    task_id: str | None = None
    result_id: str | None = None
    kind: Literal["generative"] = "generative"
    storage_key: str
    sha256: str
    width: int
    height: int
    bytes: int
    mime_type: str
    created_at: datetime
    deleted_at: datetime | None = None


__all__ = [
    "GeneratedAssetRecord",
    "GenerativeCapabilitiesResponse",
    "GenerativeErrorInfo",
    "GenerativeMaskKind",
    "GenerativeMaskRecord",
    "GenerativeMaskSource",
    "GenerativeParams",
    "GenerativePlan",
    "GenerativeResultRecord",
    "GenerativeResultStatus",
    "GenerativeResultView",
    "GenerativeTaskCreated",
    "GenerativeTaskListResponse",
    "GenerativeTaskRecord",
    "GenerativeTaskRequest",
    "GenerativeTaskStage",
    "GenerativeTaskStatus",
    "GenerativeTaskStatusResponse",
    "GenerativeTaskType",
]
