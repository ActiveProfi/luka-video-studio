"""TTS Generation Agent — озвучка по тайм-блокам исходного видео (паузы не вырезаются)."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import shutil
from typing import Any

from src.config import Settings
from src.domain.contracts import utc_now_iso
from src.domain.enums import ArtifactStatus, PipelineStage
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.providers.tts.base import TTSChunk
from src.providers.tts.runner import synthesize_with_fallback
from src.services.ffmpeg_service import get_media_duration_seconds
from src.services.media_paths import resolve_raw_video_path
from src.services.speech_timing_service import segment_slot_seconds
from src.services.voiceover_assembly_service import VoiceoverPart, assemble_voiceover

logger = logging.getLogger(__name__)

VOICEOVER_WAV = "voiceover.wav"
VOICEOVER_SEGMENTS = "voiceover_segments.json"
SPEECH_SCRIPT_FILE = "speech_script.json"


def run_tts_generation(
    registry: ArtifactRegistry,
    settings: Settings,
    job_id: str,
) -> dict[str, Any]:
    if not registry.exists("clean_transcript.json"):
        raise FileNotFoundError("Нужен clean_transcript.json — сначала подготовьте и подтвердите текст")

    clean = registry.load_json("clean_transcript.json")
    tts_source = load_tts_source_document(registry)
    transcript_segments = tts_source.get("segments", [])
    cleanup_text_hash = cleanup_text_hash_for_segments(transcript_segments)
    has_voiceover_wav = registry.exists(VOICEOVER_WAV)
    has_voiceover_segments = registry.exists(VOICEOVER_SEGMENTS)
    if has_voiceover_wav and has_voiceover_segments:
        existing = registry.load_json(VOICEOVER_SEGMENTS)
        if existing.get("cleanup_text_hash") == cleanup_text_hash:
            logger.info("voiceover уже существует для актуального текста, пропуск")
            return existing
        logger.info("Текст изменился — старая озвучка удаляется и генерируется заново")
        registry.artifact_path(VOICEOVER_WAV).unlink(missing_ok=True)
        registry.artifact_path(VOICEOVER_SEGMENTS).unlink(missing_ok=True)
        shutil.rmtree(registry.job_dir / "_tts_chunks", ignore_errors=True)
        shutil.rmtree(registry.job_dir / "_tts_build", ignore_errors=True)
    elif has_voiceover_wav or has_voiceover_segments:
        logger.warning("Найден частичный результат TTS — удаляем и генерируем озвучку заново")
        registry.artifact_path(VOICEOVER_WAV).unlink(missing_ok=True)
        registry.artifact_path(VOICEOVER_SEGMENTS).unlink(missing_ok=True)
        shutil.rmtree(registry.job_dir / "_tts_chunks", ignore_errors=True)
        shutil.rmtree(registry.job_dir / "_tts_build", ignore_errors=True)

    language = clean.get("language", settings.default_language)

    source_video = resolve_raw_video_path(registry)
    total_duration = get_media_duration_seconds(source_video, settings)
    if total_duration <= 0 and registry.exists("transcript.json"):
        total_duration = float(registry.load_json("transcript.json").get("duration_seconds", 0))

    warnings: list[str] = []
    work_dir = registry.job_dir / "_tts_chunks"
    work_dir.mkdir(parents=True, exist_ok=True)

    voiceover_parts: list[VoiceoverPart] = []
    segment_records: list[dict[str, Any]] = []
    provider_name = settings.tts_provider

    for idx, seg in enumerate(transcript_segments, start=1):
        text = str(seg.get("text", "")).strip()
        if not text:
            continue

        source_start = float(seg["start"])
        source_end = float(seg["end"])
        slot_seconds = segment_slot_seconds(source_start, source_end)
        if slot_seconds < 0.15:
            warnings.append(f"Сегмент {seg.get('segment_id')} пропущен — блок слишком короткий")
            continue

        chunk_path = work_dir / f"tts_{idx:03d}.wav"
        try:
            result = asyncio.run(
                synthesize_with_fallback(
                    TTSChunk(text=text, output_path=chunk_path, language=language),
                    settings,
                )
            )
            provider_name = result.provider
        except Exception as exc:
            logger.exception("TTS ошибка сегмента %s", seg.get("segment_id"))
            raise RuntimeError(f"Ошибка озвучки сегмента {seg.get('segment_id')}: {exc}") from exc

        audio_duration = float(result.duration_seconds)
        if audio_duration > slot_seconds + 0.8:
            warnings.append(
                f"Сегмент {seg.get('segment_id')}: озвучка {audio_duration:.1f} с длиннее блока "
                f"{slot_seconds:.1f} с — проверьте текст на шаге 3"
            )

        voiceover_parts.append(
            VoiceoverPart(
                wav_path=chunk_path,
                target_start=source_start,
                audio_duration=audio_duration,
            )
        )
        segment_records.append(
            {
                "segment_id": f"tts_{idx:03d}",
                "transcript_segment_id": seg.get("segment_id", f"seg_{idx:03d}"),
                "text": text,
                "target_start": round(source_start, 3),
                "target_end": round(source_end, 3),
                "target_slot_seconds": slot_seconds,
                "audio_start": round(source_start, 3),
                "audio_end": round(source_start + audio_duration, 3),
                "audio_duration_seconds": round(audio_duration, 3),
                "provider": result.provider,
            }
        )
        logger.info(
            "TTS %s/%s: блок %.1f с, audio %.1f с",
            idx,
            len(transcript_segments),
            slot_seconds,
            audio_duration,
        )

    if not voiceover_parts:
        raise ValueError("Не удалось сгенерировать ни одного фрагмента озвучки")

    output_path = registry.artifact_path(VOICEOVER_WAV)
    assembled_duration = assemble_voiceover(
        voiceover_parts,
        output_path,
        total_duration or sum(p.audio_duration for p in voiceover_parts),
        settings,
    )
    if not output_path.exists():
        raise RuntimeError("TTS завершился без ошибки, но voiceover.wav не был создан")

    doc = {
        "job_id": job_id,
        "stage": PipelineStage.TTS.value,
        "version": "1.0.0",
        "created_at": utc_now_iso(),
        "source_artifacts": [tts_source.get("artifact_name", "clean_transcript.json"), str(source_video.name)],
        "status": ArtifactStatus.COMPLETED.value,
        "provider": provider_name,
        "language": language,
        "timeline_mode": "source_preserve_pauses",
        "cleanup_text_hash": cleanup_text_hash,
        "speech_script_used": tts_source.get("artifact_name") == SPEECH_SCRIPT_FILE,
        "total_duration_seconds": round(assembled_duration, 3),
        "confidence_summary": 0.9 if not warnings else 0.75,
        "warnings": warnings,
        "errors": [],
        "segments": segment_records,
    }
    registry.save_json(VOICEOVER_SEGMENTS, doc, "voiceover_segments.schema.json")
    logger.info("Озвучка готова: voiceover.wav %.1f с, сегментов %s", assembled_duration, len(segment_records))
    return doc


def cleanup_text_hash_for_segments(segments: list[dict[str, Any]]) -> str:
    payload = "\n".join(
        f"{seg.get('segment_id')}|{seg.get('start')}|{seg.get('end')}|{str(seg.get('text', '')).strip()}"
        for seg in segments
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_tts_source_document(registry: ArtifactRegistry) -> dict[str, Any]:
    """Источник текста для TTS: Speech Script (text_after) при наличии, иначе clean_transcript."""
    if registry.exists(SPEECH_SCRIPT_FILE):
        script = registry.load_json(SPEECH_SCRIPT_FILE)
        segments = list(script.get("segments") or [])
        # Гарантируем, что в озвучку уходит text_after, а не старый text_before.
        normalized: list[dict[str, Any]] = []
        for seg in segments:
            after = str(seg.get("text_after") or seg.get("text") or "").strip()
            if not after:
                continue
            normalized.append({**seg, "text": after})
        if normalized:
            return {**script, "segments": normalized, "artifact_name": SPEECH_SCRIPT_FILE}
        full_after = str(script.get("text_after") or script.get("text") or "").strip()
        if full_after and registry.exists("clean_transcript.json"):
            clean = registry.load_json("clean_transcript.json")
            from src.services.segment_timing_service import segments_from_full_text

            rebuilt = segments_from_full_text(
                full_after,
                list(clean.get("segments") or []),
                duration=float(clean.get("duration_seconds") or 0.0),
            )
            if rebuilt:
                return {
                    **script,
                    "segments": rebuilt,
                    "text": full_after,
                    "artifact_name": SPEECH_SCRIPT_FILE,
                }
    clean = registry.load_json("clean_transcript.json")
    return {**clean, "artifact_name": "clean_transcript.json"}


def current_tts_text_hash(registry: ArtifactRegistry) -> str:
    source = load_tts_source_document(registry)
    return cleanup_text_hash_for_segments(source.get("segments", []))
