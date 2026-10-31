"""Speech Recognition Agent — Этап 1: STT."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from src.config import Settings
from src.domain.contracts import utc_now_iso
from src.domain.enums import ArtifactStatus, PipelineStage
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.providers.stt.base import STTResult
from src.providers.stt.runner import transcribe_with_fallback
from src.services.ffmpeg_service import extract_audio_ogg, get_media_duration_seconds

logger = logging.getLogger(__name__)


def run_speech_recognition(
    registry: ArtifactRegistry,
    settings: Settings,
    job_id: str,
    *,
    force: bool = False,
) -> dict:
    if registry.exists("transcript.json") and not force:
        logger.info("transcript.json уже существует, пропуск")
        return registry.load_json("transcript.json")

    manifest = registry.load_json("input_manifest.json")
    if registry.exists("lesson_options.json"):
        from src.services.lesson_options_service import load_options

        options = load_options(registry, settings)
        if options.content_profile == "general":
            settings = settings.model_copy(update={
                "stt_context": options.topic_context or options.title,
                "stt_keywords": options.terminology,
            })
        elif options.topic_context or options.terminology:
            settings = settings.model_copy(update={
                "stt_context": options.topic_context or settings.stt_context,
                "stt_keywords": options.terminology or settings.stt_keywords,
            })
    raw_video = Path(manifest["raw_video_path"])
    if not raw_video.exists():
        raise FileNotFoundError(f"Видео не найдено: {raw_video}")

    language = manifest.get("language", settings.default_language)
    audio_path = registry.job_dir / "raw_audio.ogg"

    logger.info("Этап 1: извлечение аудио из %s", raw_video.name)
    extract_audio_ogg(raw_video, audio_path)

    stt_result = asyncio.run(transcribe_with_fallback(audio_path, settings, language))

    try:
        total_duration = get_media_duration_seconds(raw_video)
    except Exception:
        total_duration = stt_result.duration_seconds

    _normalize_segment_times(stt_result, total_duration)

    confidences = [s.confidence for s in stt_result.segments if s.confidence is not None]
    confidence_summary = sum(confidences) / len(confidences) if confidences else None

    transcript = {
        "job_id": job_id,
        "stage": PipelineStage.TRANSCRIPTION.value,
        "version": "1.0.0",
        "created_at": utc_now_iso(),
        "source_artifacts": ["raw_video.mp4", "raw_audio.ogg"],
        "status": ArtifactStatus.COMPLETED.value,
        "confidence_summary": confidence_summary,
        "warnings": [],
        "errors": [],
        "language": stt_result.language,
        "duration_seconds": total_duration,
        "provider": stt_result.provider,
        "model": settings.openai_stt_model
        if stt_result.provider == "openai"
        else settings.whisper_model,
        "timing_source": "text_aligned_to_acoustic_segments"
        if (stt_result.provider == "openai" and settings.openai_stt_model != "whisper-1")
        else "recognizer",
        "segments": [
            {
                "segment_id": s.segment_id,
                "start": round(s.start, 3),
                "end": round(s.end, 3),
                "text": s.text,
                "confidence": s.confidence,
                "words": [
                    {
                        "word": w.word,
                        "start": round(w.start, 3),
                        "end": round(w.end, 3),
                        "confidence": w.confidence,
                    }
                    for w in s.words
                ],
            }
            for s in stt_result.segments
        ],
    }

    # Confidence is optional in the contract. Do not invent a score for models
    # that do not expose one, or serialize null where a number is expected.
    if confidence_summary is None:
        transcript.pop("confidence_summary", None)
    for segment in transcript["segments"]:
        if segment["confidence"] is None:
            segment.pop("confidence")
        for word in segment["words"]:
            if word["confidence"] is None:
                word.pop("confidence")
    registry.save_json("transcript.json", transcript, "transcript.schema.json")
    logger.info(
        "Этап 1 завершён: %s сегментов, провайдер=%s",
        len(stt_result.segments),
        stt_result.provider,
    )
    return transcript


def _normalize_segment_times(result: STTResult, total_duration: float) -> None:
    """Подправить end-таймкоды сегментов."""
    for i, seg in enumerate(result.segments):
        if i + 1 < len(result.segments):
            seg.end = result.segments[i + 1].start
        else:
            seg.end = min(seg.end, total_duration) if seg.end > 0 else total_duration
        if seg.end <= seg.start:
            seg.end = min(seg.start + 1.0, total_duration)
