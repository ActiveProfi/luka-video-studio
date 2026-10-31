"""Базовые Pydantic-модели артефактов pipeline."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from src.domain.enums import ArtifactStatus, PipelineStage


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ArtifactEnvelope(BaseModel):
    """Общие поля для всех JSON-артефактов."""

    job_id: str
    stage: str
    version: str = "1.0.0"
    created_at: str = Field(default_factory=utc_now_iso)
    source_artifacts: list[str] = Field(default_factory=list)
    status: ArtifactStatus = ArtifactStatus.PENDING
    confidence_summary: float | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class InputManifest(ArtifactEnvelope):
    stage: str = PipelineStage.INPUT
    raw_video_path: str
    reference_video_path: str | None = None
    language: str = "ru"
    metadata: dict[str, Any] = Field(default_factory=dict)


class JobSummary(BaseModel):
    job_id: str
    status: ArtifactStatus
    output_dir: str
    stages_completed: list[str] = Field(default_factory=list)
    current_stage: str | None = None
