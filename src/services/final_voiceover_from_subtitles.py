"""Шаг 6 (v2): финальная AI-озвучка.

Текст — из voiceover_script.json (шаг 5, поле voiceover_text).
Тайминг блоков — из subtitle_timing.json (шаг 4).
"""

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
from src.services.ffmpeg_service import get_media_duration_seconds, mux_video_with_voiceover
from src.services.media_paths import resolve_edited_video_path, resolve_raw_video_path
from src.services.speech_timing_service import segment_slot_seconds
from src.services.voiceover_assembly_service import VoiceoverPart, assemble_voiceover

logger = logging.getLogger(__name__)

VOICEOVER_WAV = "voiceover.wav"
VOICEOVER_SEGMENTS = "voiceover_segments.json"
SUBTITLE_TIMING = "subtitle_timing.json"
EDITED_VIDEO = "edited_video.mp4"
REPORT_NAME = "video_edit_report.json"


def subtitle_cues_text_hash(cues: list[dict[str, Any]]) -> str:
    payload = "\n".join(
        f"{c.get('cue_id')}|{c.get('start')}|{c.get('end')}|{str(c.get('text') or '').strip()}"
        for c in cues
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def voiceover_script_text_hash(registry: ArtifactRegistry) -> str | None:
    """Хеш текста озвучки шага 5 — по нему видно, нужна ли переозвучка."""
    if not registry.exists("voiceover_script.json"):
        return None
    doc = registry.load_json("voiceover_script.json")
    payload = "\n".join(
        f"{b.get('cue_id')}|{b.get('start')}|{b.get('end')}|{str(b.get('voiceover_text') or '').strip()}"
        for b in (doc.get("blocks") or [])
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def final_voiceover_matches_script(registry: ArtifactRegistry) -> bool:
    """True, если текущая озвучка сделана по актуальному тексту шага 5."""
    if not registry.exists(VOICEOVER_SEGMENTS):
        return False
    segs = registry.load_json(VOICEOVER_SEGMENTS)
    current = voiceover_script_text_hash(registry)
    if current is None:
        return False
    return str(segs.get("voiceover_script_hash") or "") == current


def run_final_voiceover_from_subtitles(
    registry: ArtifactRegistry,
    settings: Settings,
    job_id: str,
    *,
    force: bool = True,
) -> dict[str, Any]:
    """Озвучить текст шага 5 в таймингах блоков шага 4."""
    if not registry.exists(SUBTITLE_TIMING):
        raise FileNotFoundError("Нужен subtitle_timing.json — сначала выполните шаг 4")
    if not registry.exists("edited_video.mp4") and not registry.exists("raw_video.mp4"):
        raise FileNotFoundError("Нужно видео (edited_video или raw_video)")

    timing = registry.load_json(SUBTITLE_TIMING)
    cues = list(timing.get("cues") or [])
    if not cues:
        raise ValueError("В субтитрах нет блоков — нечего озвучивать")

    # Строго: текст озвучки только из шага 5 (voiceover_text), не из субтитров
    text_source = "subtitle_timing"
    tts_cues = list(cues)
    if not registry.exists("voiceover_script.json"):
        raise FileNotFoundError(
            "Нужен voiceover_script.json — сначала выполните шаг 5 и сохраните текст озвучки"
        )
    vs = registry.load_json("voiceover_script.json")
    by_id = {str(b.get("cue_id")): b for b in (vs.get("blocks") or [])}
    if not by_id:
        raise ValueError("В шаге 5 нет блоков текста озвучки")
    merged: list[dict[str, Any]] = []
    for cue in cues:
        cid = str(cue.get("cue_id") or "")
        block = by_id.get(cid) or {}
        vo_text = str(block.get("voiceover_text") or "").strip()
        if not vo_text:
            # пустой voiceover_text — пропускаем (не подставляем текст субтитров)
            continue
        merged.append({**cue, "text": vo_text})
    tts_cues = merged
    text_source = "voiceover_script"

    spoken = [c for c in tts_cues if str(c.get("text") or "").strip()]
    if not spoken:
        raise ValueError("Все блоки для озвучки пустые — заполните текст озвучки на шаге 5")

    text_hash = subtitle_cues_text_hash(tts_cues)
    if (
        not force
        and registry.exists(VOICEOVER_WAV)
        and registry.exists(VOICEOVER_SEGMENTS)
    ):
        existing = registry.load_json(VOICEOVER_SEGMENTS)
        if (
            existing.get("source") == "subtitles_final"
            and existing.get("subtitle_text_hash") == text_hash
        ):
            logger.info("Финальная озвучка уже совпадает с текущими субтитрами, пропуск")
            return {
                "ok": True,
                "skipped": True,
                "message": "Озвучка уже соответствует текущим субтитрам.",
                "voiceover_segments": existing,
            }

    language = str(timing.get("language") or settings.default_language)
    total_duration = float(timing.get("total_duration_seconds") or 0)
    try:
        video_for_duration = resolve_edited_video_path(registry)
        total_duration = max(
            total_duration,
            float(get_media_duration_seconds(video_for_duration, settings) or 0),
        )
    except Exception:
        if registry.exists("raw_video.mp4"):
            total_duration = max(
                total_duration,
                float(get_media_duration_seconds(resolve_raw_video_path(registry), settings) or 0),
            )
    if total_duration <= 0:
        total_duration = max(float(c.get("end", 0) or 0) for c in cues)

    registry.artifact_path(VOICEOVER_WAV).unlink(missing_ok=True)
    # Сохраняем hash сценария шага 3/4, чтобы шаг TTS не «откатывался» в интерфейсе
    previous_cleanup_hash = None
    if registry.exists(VOICEOVER_SEGMENTS):
        previous = registry.load_json(VOICEOVER_SEGMENTS)
        if previous.get("source") != "subtitles_final":
            previous_cleanup_hash = previous.get("cleanup_text_hash")
    registry.artifact_path(VOICEOVER_SEGMENTS).unlink(missing_ok=True)
    shutil.rmtree(registry.job_dir / "_tts_chunks_final", ignore_errors=True)
    shutil.rmtree(registry.job_dir / "_tts_build", ignore_errors=True)

    work_dir = registry.job_dir / "_tts_chunks_final"
    work_dir.mkdir(parents=True, exist_ok=True)

    voiceover_parts: list[VoiceoverPart] = []
    segment_records: list[dict[str, Any]] = []
    warnings: list[str] = []
    provider_name = settings.tts_provider

    for idx, cue in enumerate(spoken, start=1):
        text = str(cue.get("text") or "").strip()
        start = float(cue.get("start", 0))
        end = float(cue.get("end", start))
        slot_seconds = segment_slot_seconds(start, end)
        if slot_seconds < 0.15:
            warnings.append(f"Блок {cue.get('cue_id')} пропущен — слишком короткий")
            continue

        chunk_path = work_dir / f"final_tts_{idx:03d}.wav"
        try:
            result = asyncio.run(
                synthesize_with_fallback(
                    TTSChunk(text=text, output_path=chunk_path, language=language),
                    settings,
                )
            )
            provider_name = result.provider
        except Exception as exc:
            logger.exception("TTS 6.1 ошибка блока %s", cue.get("cue_id"))
            raise RuntimeError(f"Ошибка озвучки блока {cue.get('cue_id')}: {exc}") from exc

        audio_duration = float(result.duration_seconds)
        if audio_duration > slot_seconds + 0.8:
            warnings.append(
                f"Блок {cue.get('cue_id')}: озвучка {audio_duration:.1f} с длиннее слота "
                f"{slot_seconds:.1f} с"
            )

        voiceover_parts.append(
            VoiceoverPart(
                wav_path=chunk_path,
                target_start=start,
                audio_duration=audio_duration,
            )
        )
        segment_records.append(
            {
                "segment_id": f"final_tts_{idx:03d}",
                "transcript_segment_id": str(cue.get("cue_id") or f"cue_{idx:03d}"),
                "cue_id": str(cue.get("cue_id") or ""),
                "text": text,
                "target_start": round(start, 3),
                "target_end": round(end, 3),
                "target_slot_seconds": round(slot_seconds, 3),
                "audio_start": round(start, 3),
                "audio_end": round(start + audio_duration, 3),
                "audio_duration_seconds": round(audio_duration, 3),
                "provider": result.provider,
            }
        )

    if not voiceover_parts:
        raise ValueError("Не удалось озвучить ни одного блока из текста озвучки (шаг 5)")

    output_path = registry.artifact_path(VOICEOVER_WAV)
    assembled_duration = assemble_voiceover(
        voiceover_parts,
        output_path,
        total_duration,
        settings,
    )
    if not output_path.exists():
        raise RuntimeError("Финальная озвучка не создала voiceover.wav")

    doc = {
        "job_id": job_id,
        "stage": PipelineStage.TTS.value,
        "version": "1.2.0",
        "created_at": utc_now_iso(),
        "source_artifacts": ["voiceover_script.json", SUBTITLE_TIMING, "raw_video.mp4"],
        "status": ArtifactStatus.COMPLETED.value,
        "provider": provider_name,
        "language": language,
        "timeline_mode": "subtitle_blocks",
        # source=voiceover_script — UI считает шаг 6 выполненным по новому пути
        "source": "voiceover_script",
        "text_source": text_source,
        "voiceover_script_hash": voiceover_script_text_hash(registry),
        "subtitle_text_hash": text_hash,
        # Hash сценария шага 3 — чтобы UI не откатывал шаг TTS после озвучки
        "cleanup_text_hash": previous_cleanup_hash or text_hash,
        "total_duration_seconds": round(assembled_duration, 3),
        "confidence_summary": 0.9 if not warnings else 0.75,
        "warnings": warnings,
        "errors": [],
        "segments": segment_records,
    }
    registry.save_json(VOICEOVER_SEGMENTS, doc, "voiceover_segments.schema.json")

    # Обновить видео с новой озвучкой.
    source_video = resolve_raw_video_path(registry)
    edited_path = registry.artifact_path(EDITED_VIDEO)
    mux_video_with_voiceover(source_video, output_path, edited_path, settings)
    if registry.exists(REPORT_NAME):
        report = registry.load_json(REPORT_NAME)
        report["final_voiceover_from_subtitles_at"] = utc_now_iso()
        report["text_source"] = text_source
        report["warnings"] = list(report.get("warnings") or []) + [
            "Видео обновлено финальной озвучкой по тексту шага 5 (voiceover_text)."
        ]
        registry.save_json(REPORT_NAME, report)

    # Старое превью аннотаций устарело; прожиг субтитров пересоберём на новом edited_video
    registry.artifact_path("annotation_preview.mp4").unlink(missing_ok=True)
    registry.artifact_path("edited_video_with_subtitles.mp4").unlink(missing_ok=True)
    registry.artifact_path("_subtitle_burn.ass").unlink(missing_ok=True)
    try:
        from src.services.subtitle_burn_service import ensure_subtitled_studio_video

        ensure_subtitled_studio_video(registry, settings, force=True)
    except Exception:
        logger.exception("Не удалось вернуть субтитры на превью после финальной озвучки")

    logger.info(
        "Шаг 6 готов (текст из шага 5): voiceover.wav %.1f с, блоков %s",
        assembled_duration,
        len(segment_records),
    )
    return {
        "ok": True,
        "skipped": False,
        "message": (
            f"Финальная озвучка готова: {len(segment_records)} блоков "
            "из текста озвучки шага 5. Видео обновлено."
        ),
        "segment_count": len(segment_records),
        "total_duration_seconds": round(assembled_duration, 3),
        "warnings": warnings,
        "text_source": text_source,
        "voiceover_segments": doc,
    }
