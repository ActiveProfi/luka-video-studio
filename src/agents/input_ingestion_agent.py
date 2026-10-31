"""Input Ingestion Agent — регистрация входного видео."""

import shutil
from pathlib import Path

from src.config import Settings
from src.domain.contracts import InputManifest, utc_now_iso
from src.domain.enums import ArtifactStatus, PipelineStage
from src.orchestrator.artifact_registry import ArtifactRegistry


def run_input_ingestion(
    registry: ArtifactRegistry,
    settings: Settings,
    job_id: str,
    raw_video: Path,
    reference_video: Path | None = None,
) -> InputManifest:
    if not raw_video.exists():
        raise FileNotFoundError(f"Исходное видео не найдено: {raw_video}")

    job_raw = registry.job_dir / "raw_video.mp4"
    shutil.copy2(raw_video, job_raw)

    ref_path: str | None = None
    if reference_video and reference_video.exists():
        job_ref = registry.job_dir / "reference_final.mp4"
        shutil.copy2(reference_video, job_ref)
        ref_path = str(job_ref)
    elif settings.reference_video_path.exists():
        job_ref = registry.job_dir / "reference_final.mp4"
        shutil.copy2(settings.reference_video_path, job_ref)
        ref_path = str(job_ref)

    manifest = InputManifest(
        job_id=job_id,
        stage=PipelineStage.INPUT,
        created_at=utc_now_iso(),
        source_artifacts=[str(raw_video)],
        status=ArtifactStatus.COMPLETED,
        raw_video_path=str(job_raw),
        reference_video_path=ref_path,
        language=settings.default_language,
        metadata={
            "pipeline_version": settings.pipeline_version,
            "stt_provider": settings.stt_provider,
            "tts_provider": settings.tts_provider,
            "llm_provider": settings.llm_provider,
        },
    )
    registry.save_json("input_manifest.json", manifest.model_dump(mode="json"))
    return manifest
