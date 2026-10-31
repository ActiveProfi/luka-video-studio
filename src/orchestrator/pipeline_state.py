"""Состояние job в pipeline."""

from dataclasses import dataclass, field

from src.domain.enums import ArtifactStatus, PipelineStage


@dataclass
class PipelineState:
    job_id: str
    output_dir: str
    status: ArtifactStatus = ArtifactStatus.PENDING
    stages_completed: list[str] = field(default_factory=list)
    current_stage: str | None = None
    error: str | None = None

    def mark_stage_done(self, stage: PipelineStage | str) -> None:
        stage_name = stage.value if isinstance(stage, PipelineStage) else stage
        if stage_name not in self.stages_completed:
            self.stages_completed.append(stage_name)
        self.current_stage = None

    def mark_running(self, stage: PipelineStage | str) -> None:
        self.status = ArtifactStatus.RUNNING
        self.current_stage = stage.value if isinstance(stage, PipelineStage) else stage

    def mark_failed(self, message: str) -> None:
        self.status = ArtifactStatus.FAILED
        self.error = message

    def mark_needs_review(self) -> None:
        self.status = ArtifactStatus.NEEDS_REVIEW

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "output_dir": self.output_dir,
            "status": self.status.value,
            "stages_completed": self.stages_completed,
            "current_stage": self.current_stage,
            "error": self.error,
        }
