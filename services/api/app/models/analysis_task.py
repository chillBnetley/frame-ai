from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.ai.contracts import AnalysisOptions
from app.models.analysis_report import AnalysisReport


class TaskStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskStage(StrEnum):
    QUEUED = "queued"
    PREPROCESSING = "preprocessing"
    VISION = "vision"
    FEATURES = "features"
    DIAGNOSIS = "diagnosis"
    COMPLETED = "completed"
    FAILED = "failed"


class _TaskModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


class AnalysisTaskCreateRequest(_TaskModel):
    image_id: UUID
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)
    force: bool = False


class AnalysisTaskCreated(_TaskModel):
    analysis_id: UUID
    status: TaskStatus
    stage: TaskStage
    deduplicated: bool


class AnalysisErrorInfo(_TaskModel):
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=500)


class AnalysisTaskStatusResponse(_TaskModel):
    analysis_id: UUID
    status: TaskStatus
    stage: TaskStage
    is_mock: bool
    result_available: bool
    error: AnalysisErrorInfo | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: AnalysisReport | None = None


class AnalysisTaskRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    image_id: str
    image_sha256: str
    options: AnalysisOptions
    config_key: str
    dedupe_key: str
    status: TaskStatus
    stage: TaskStage
    attempts: int = Field(default=0, ge=0)
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in {TaskStatus.COMPLETED, TaskStatus.FAILED}


class AnalysisResultRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    task_id: str
    schema_version: str
    is_mock: bool
    report_json: str
    created_at: datetime


__all__ = [
    "AnalysisErrorInfo",
    "AnalysisResultRecord",
    "AnalysisTaskCreateRequest",
    "AnalysisTaskCreated",
    "AnalysisTaskRecord",
    "AnalysisTaskStatusResponse",
    "TaskStage",
    "TaskStatus",
]
