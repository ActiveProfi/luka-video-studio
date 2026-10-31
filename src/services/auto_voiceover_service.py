"""Этап 3 архитектуры v3: озвучка запускается автоматически по субтитрам.

Пользователь не видит ни Speech Script, ни отдельных настроек:
субтитр → Speech Script → TTS → проверка длительности → авто-оптимизация.
Уведомление приходит только если автоматика не смогла уложиться в блок.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
import subprocess
from typing import Any

from src.config import Settings, get_settings
from src.domain.contracts import utc_now_iso
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.providers.tts.base import TTSChunk
from src.providers.tts.runner import synthesize_with_fallback
from src.services.ffmpeg_service import (
    _ffmpeg_bin,
    change_wav_speed,
    get_media_duration_seconds,
    mux_video_with_voiceover,
)
from src.services.media_paths import resolve_raw_video_path
from src.services.speech_script_auto import shorten_speech_text
from src.services.speech_timing_service import segment_slot_seconds
from src.services.speech_units import group_speech_units
from src.services.subtitle_capture_service import cue_id_for_block, subtitles_text_hash
from src.services.timeblock_service import TIME_BLOCKS_FILE, subtitles_saved
from src.services.tts_normalization_rules import pronunciation_rules_hash
from src.services.voiceover_assembly_service import VoiceoverPart, assemble_voiceover

logger = logging.getLogger(__name__)

VOICEOVER_WAV = "voiceover.wav"
VOICEOVER_SEGMENTS = "voiceover_segments.json"
SPEECH_SCRIPT_FILE = "speech_script_auto.json"
EDITED_VIDEO = "edited_video.mp4"

# Предел ускорения речи: выше звучит неестественно
MAX_SPEEDUP = 1.35


def _fit_small_overrun(path, duration, allowed, speed_applied, settings):
    """Correct a small residual overrun without clipping speech or shifting video."""
    over = duration - allowed
    # TTS duration varies between takes. Bound the correction by both absolute
    # time and relative change, rather than the three overruns from one recording.
    if not (0 < over <= min(1.0, allowed * 0.10)):
        return path, duration, speed_applied
    factor = duration / max(0.1, allowed - 0.025)
    if speed_applied * factor > 1.5:
        return path, duration, speed_applied
    corrected = path.with_name(path.stem + "_fit.wav")
    change_wav_speed(path, corrected, factor, settings)
    measured = float(get_media_duration_seconds(corrected, settings))
    if 0 < measured <= allowed:
        return corrected, measured, speed_applied * factor
    return path, duration, speed_applied


def auto_voiceover_ready(registry: ArtifactRegistry) -> bool:
    return (
        registry.exists(VOICEOVER_WAV)
        and registry.exists(VOICEOVER_SEGMENTS)
        and registry.exists(EDITED_VIDEO)
        and registry.load_json(VOICEOVER_SEGMENTS).get("status") not in ("checking", "failed")
    )


def auto_voiceover_matches_subtitles(registry: ArtifactRegistry) -> bool:
    """True, если озвучка сделана по актуальному тексту субтитров."""
    if not registry.exists(VOICEOVER_SEGMENTS):
        return False
    doc = registry.load_json(VOICEOVER_SEGMENTS)
    current = subtitles_text_hash(registry)
    if current is None:
        return False
    from src.services.lesson_options_service import voice_hash, voice_settings

    selected = voice_hash(registry, get_settings())
    rules_hash = pronunciation_rules_hash(voice_settings(registry, get_settings()))
    if doc.get("pronunciation_rules_hash") != rules_hash:
        return False
    return str(doc.get("subtitles_hash") or "") == current and (
        doc.get("voice_settings_hash") == selected
        or (not registry.exists("lesson_options.json") and not doc.get("voice_settings_hash"))
    )


def _synthesize(text: str, path, language: str, settings: Settings) -> tuple[float, str]:
    # Reuse only audio with the exact same text, voice, tempo and pronunciation rules.
    config = {k: v for k, v in settings.model_dump(mode="json").items()
              if k.startswith(("tts_", "yandex_tts_", "openai_tts_", "elevenlabs_", "edge_tts_"))
              and "key" not in k}
    signature = hashlib.sha256(json.dumps([text, language, config, pronunciation_rules_hash(settings)], sort_keys=True).encode()).hexdigest()
    cache = path.parent.parent / "_tts_cache"
    cache.mkdir(parents=True, exist_ok=True)
    cached_wav, cached_meta = cache / f"{signature}.wav", cache / f"{signature}.json"
    if cached_wav.exists() and cached_meta.exists():
        duration = float(get_media_duration_seconds(cached_wav, settings))
        if duration > 0:
            shutil.copyfile(cached_wav, path)
            return duration, json.loads(cached_meta.read_text(encoding="utf-8"))["provider"]
    result = asyncio.run(
        synthesize_with_fallback(
            TTSChunk(text=text, output_path=path, language=language),
            settings,
        )
    )
    # TTS providers return different sample rates/channels. Silence and every chunk
    # must have identical PCM format before concat, otherwise timing gets corrupted.
    normalized = path.with_name(path.stem + "_pcm.wav")
    # Remove only padding at the two ends, never pauses inside the phrase.
    edge_trim = "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.04"
    subprocess.run(
        [
            _ffmpeg_bin(settings),
            "-y",
            "-i",
            str(path),
            "-af",
            f"{edge_trim},areverse,{edge_trim},areverse",
            "-ar",
            "48000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(normalized),
        ],
        capture_output=True,
        check=True,
    )
    normalized.replace(path)
    duration = float(get_media_duration_seconds(path, settings))
    if duration > 0:
        shutil.copyfile(path, cached_wav)
        cached_meta.write_text(json.dumps({"provider": str(result.provider)}), encoding="utf-8")
    return duration, str(result.provider)


def _fit_block_audio(
    *,
    subtitle: str,
    speech_text: str,
    slot_seconds: float,
    tolerance: float,
    work_dir,
    index: int,
    language: str,
    settings: Settings,
) -> dict[str, Any]:
    """Озвучить блок и уложить в длительность, не выкидывая смысл субтитра.

    Порядок: исходный текст → ускорение речи → только мягкое сокращение связок.
    Жёсткая обрезка предложения запрещена: пользователь писал субтитр целиком.
    """
    allowed = slot_seconds + tolerance
    chunk_path = work_dir / f"block_{index:03d}.wav"
    duration, provider = _synthesize(speech_text, chunk_path, language, settings)
    used_text = speech_text
    optimization = "none"
    speed_applied = 1.0

    # Сначала ускорение — текст субтитра сохраняется
    if duration > allowed and allowed > 0.2:
        speed = min(MAX_SPEEDUP, duration / max(0.1, allowed - 0.025))
        if speed > 1.0:
            fast_path = work_dir / f"block_{index:03d}_fast.wav"
            try:
                change_wav_speed(chunk_path, fast_path, speed, settings)
                new_duration = float(get_media_duration_seconds(fast_path, settings) or 0.0)
                if 0 < new_duration < duration:
                    duration = new_duration
                    chunk_path = fast_path
                    speed_applied = round(speed, 3)
                    optimization = "speed"
            except Exception:
                logger.exception("Не удалось ускорить озвучку блока %s", index)

    previous_path = chunk_path
    chunk_path, duration, speed_applied = _fit_small_overrun(
        chunk_path, duration, allowed, speed_applied, settings
    )
    if chunk_path != previous_path:
        optimization = "speed+fine_fit"

    # Мягкое сокращение только если ускорения не хватило (без отрезания смысла)
    level = 1
    while duration > allowed and level <= 2:
        candidate = shorten_speech_text(used_text, level=level)
        if candidate and candidate != used_text:
            candidate_path = work_dir / f"block_{index:03d}_opt{level}.wav"
            try:
                cand_duration, cand_provider = _synthesize(
                    candidate, candidate_path, language, settings
                )
            except Exception:
                logger.exception("Не удалось озвучить сокращённый вариант блока %s", index)
                break
            if cand_duration < duration:
                duration = cand_duration
                provider = cand_provider
                used_text = candidate
                chunk_path = candidate_path
                optimization = (
                    f"speed+shortened_l{level}" if speed_applied > 1.01 else f"shortened_l{level}"
                )
                if duration > allowed and allowed > 0.2:
                    speed = min(MAX_SPEEDUP, duration / max(0.1, allowed - 0.025))
                    if speed > 1.0:
                        fast_path = work_dir / f"block_{index:03d}_opt{level}_fast.wav"
                        try:
                            change_wav_speed(chunk_path, fast_path, speed, settings)
                            new_duration = float(
                                get_media_duration_seconds(fast_path, settings) or 0.0
                            )
                            if 0 < new_duration < duration:
                                duration = new_duration
                                chunk_path = fast_path
                                speed_applied = round(speed, 3)
                                optimization = f"{optimization}+speed"
                        except Exception:
                            logger.exception("Не удалось ускорить сокращённый блок %s", index)
        level += 1

    previous_path = chunk_path
    chunk_path, duration, speed_applied = _fit_small_overrun(
        chunk_path, duration, allowed, speed_applied, settings
    )
    if chunk_path != previous_path:
        optimization += "+fine_fit"

    return {
        "wav_path": chunk_path,
        "audio_duration": duration,
        "speech_text": used_text,
        "subtitle": subtitle,
        "provider": provider,
        "optimization": optimization,
        "speed_applied": speed_applied,
        "fits": duration <= allowed + 0.001,
    }


def run_auto_voiceover(
    registry: ArtifactRegistry,
    settings: Settings | None,
    job_id: str,
) -> dict[str, Any]:
    """Полный автоматический проход: Speech Script + TTS + подгонка длительности."""
    settings = settings or get_settings()
    from src.services.lesson_options_service import voice_hash, voice_settings

    selected_voice_hash = voice_hash(registry, settings)
    settings = voice_settings(registry, settings)
    if not subtitles_saved(registry):
        raise ValueError("Сначала напишите субтитры и нажмите «Сохранить»")

    registry.save_json("voiceover_timing_report.json", {
        "job_id": job_id, "status": "running", "created_at": utc_now_iso(),
        "warnings": [], "segments": [],
    })
    registry.save_json("automatic_sync_report.json", {
        "job_id": job_id, "status": "pending", "created_at": utc_now_iso(),
        "mode": "original_timeline",
    })

    doc = registry.load_json(TIME_BLOCKS_FILE)
    blocks = [b for b in doc.get("blocks") or [] if str(b.get("subtitle") or "").strip()]
    blocks = group_speech_units(blocks, "subtitle")
    if not blocks:
        raise ValueError("Нет блоков с текстом — озвучивать нечего")

    from src.services.contextual_pronunciation import prepare_contextual_speech

    speech_texts = prepare_contextual_speech(blocks, registry, settings)

    language = settings.default_language
    tolerance = float(settings.voiceover_slot_tolerance_seconds)
    total_duration = float(doc.get("duration_seconds") or 0.0)
    if total_duration <= 0:
        total_duration = max(float(b.get("end") or 0.0) for b in doc.get("blocks") or [])

    registry.artifact_path(VOICEOVER_WAV).unlink(missing_ok=True)
    registry.artifact_path(VOICEOVER_SEGMENTS).unlink(missing_ok=True)
    shutil.rmtree(registry.job_dir / "_tts_auto", ignore_errors=True)
    shutil.rmtree(registry.job_dir / "_tts_build", ignore_errors=True)
    work_dir = registry.job_dir / "_tts_auto"
    work_dir.mkdir(parents=True, exist_ok=True)

    parts: list[VoiceoverPart] = []
    segments: list[dict[str, Any]] = []
    script_items: list[dict[str, Any]] = []
    warnings: list[str] = []
    provider_name = settings.tts_provider

    for index, block in enumerate(blocks, start=1):
        subtitle = str(block.get("subtitle") or "").strip()
        start = float(block.get("start") or 0.0)
        end = float(block.get("end") or start)
        slot = segment_slot_seconds(start, end)
        effective_tolerance = min(
            tolerance,
            max(
                0.0,
                (float(blocks[index]["start"]) if index < len(blocks) else total_duration) - end,
            ),
        )
        speech_text = speech_texts[str(block["id"])]
        if not speech_text:
            continue
        if slot < 0.3:
            warnings.append(f"Блок {block.get('id')} слишком короткий — пропущен")
            continue

        try:
            fitted = _fit_block_audio(
                subtitle=subtitle,
                speech_text=speech_text,
                slot_seconds=slot,
                tolerance=effective_tolerance,
                work_dir=work_dir,
                index=index,
                language=language,
                settings=settings,
            )
        except Exception as exc:
            logger.exception("Озвучка блока %s не удалась", block.get("id"))
            registry.save_json("voiceover_timing_report.json", {
                "job_id": job_id, "status": "failed", "warnings": [],
                "segments": segments, "error": str(exc),
            })
            raise RuntimeError(f"Ошибка озвучки блока {block.get('id')}: {exc}") from exc

        provider_name = fitted["provider"] or provider_name
        if not fitted["fits"]:
            over = max(0.0, fitted["audio_duration"] - (slot + effective_tolerance))
            warnings.append(
                f"Блок {block.get('id')} ({start:.1f}–{end:.1f} с): озвучка длиннее блока "
                f"на {over:.2f} с после автоматической подгонки."
            )

        parts.append(
            VoiceoverPart(
                wav_path=fitted["wav_path"],
                target_start=start,
                audio_duration=fitted["audio_duration"],
            )
        )
        segments.append(
            {
                "segment_id": f"auto_tts_{index:03d}",
                "transcript_segment_id": f"block_{block.get('id')}",
                "cue_id": cue_id_for_block(block.get("id")),
                "block_id": block.get("id"),
                "source_block_ids": block.get("source_ids", [block.get("id")]),
                "text": fitted["speech_text"],
                "subtitle_text": subtitle,
                "target_start": round(start, 3),
                "target_end": round(end, 3),
                "target_slot_seconds": round(slot, 3),
                "allowed_audio_seconds": round(slot + effective_tolerance, 3),
                "audio_start": round(start, 3),
                "audio_end": round(start + fitted["audio_duration"], 3),
                "audio_duration_seconds": round(fitted["audio_duration"], 3),
                "provider": fitted["provider"],
                "optimization": fitted["optimization"],
                "speed_applied": fitted["speed_applied"],
                "fits_slot": bool(fitted["fits"]),
            }
        )
        script_items.append(
            {
                "block_id": block.get("id"),
                "start": round(start, 3),
                "end": round(end, 3),
                "subtitle": subtitle,
                "speech_text": fitted["speech_text"],
                "optimization": fitted["optimization"],
                "speed_applied": fitted["speed_applied"],
            }
        )

    if not parts:
        raise ValueError("Не удалось озвучить ни один блок")

    registry.save_json(
        "voiceover_timing_report.json",
        {
            "job_id": job_id,
            "warnings": warnings,
            "segments": segments,
            "status": "needs_review" if warnings else "completed",
        },
    )
    if warnings:
        raise ValueError("Озвучка требует проверки тайминга. " + " ".join(warnings[:3]))

    output_path = registry.artifact_path(VOICEOVER_WAV)
    assembled = assemble_voiceover(parts, output_path, total_duration, settings)
    if not output_path.exists():
        raise RuntimeError("Озвучка не создала voiceover.wav")
    if abs(assembled - total_duration) > 0.05:
        raise RuntimeError("Длительность собранной аудиодорожки не совпала с исходным видео")
    from src.services.sync_service import build_sync_blocks

    sync_blocks = build_sync_blocks(segments)
    registry.save_json(
        "automatic_sync_report.json",
        {
            "job_id": job_id,
            "status": "completed",
            "mode": "original_timeline",
            "video_duration_seconds": total_duration,
            "audio_duration_seconds": assembled,
            "duration_delta_seconds": round(assembled - total_duration, 4),
            "overlap_count": 0,
            "blocks": sync_blocks,
        },
    )

    subtitles_hash = subtitles_text_hash(registry)
    registry.save_json(
        SPEECH_SCRIPT_FILE,
        {
            "job_id": job_id,
            "stage": "speech_script_auto",
            "version": "1.0.0",
            "created_at": utc_now_iso(),
            "note": "Внутреннее представление текста. Пользователю не показывается.",
            "subtitles_hash": subtitles_hash,
            "items": script_items,
        },
    )

    segments_doc = {
        "job_id": job_id,
        "stage": "tts",
        "version": "3.0.0",
        "created_at": utc_now_iso(),
        "source_artifacts": [TIME_BLOCKS_FILE, SPEECH_SCRIPT_FILE],
        "status": "completed",
        "provider": provider_name,
        "language": language,
        "total_duration_seconds": round(assembled, 3),
        "source": "user_subtitles",
        "text_source": "user_subtitles",
        "subtitles_hash": subtitles_hash,
        "voice_settings_hash": selected_voice_hash,
        "pronunciation_rules_hash": pronunciation_rules_hash(settings),
        "confidence_summary": 0.9 if not warnings else 0.7,
        "warnings": warnings,
        "errors": [],
        "segments": segments,
    }
    registry.save_json(VOICEOVER_SEGMENTS, segments_doc, "voiceover_segments.schema.json")

    from src.services.generated_speech_audit import audit_and_repair_voiceover

    segments_doc["status"] = "checking"
    registry.save_json(VOICEOVER_SEGMENTS, segments_doc)
    try:
        audit_and_repair_voiceover(registry, settings, _fit_block_audio)
    except Exception:
        segments_doc = registry.load_json(VOICEOVER_SEGMENTS)
        segments_doc["status"] = "failed"
        registry.save_json(VOICEOVER_SEGMENTS, segments_doc)
        raise
    segments_doc = registry.load_json(VOICEOVER_SEGMENTS)

    source_video = resolve_raw_video_path(registry)
    mux_video_with_voiceover(
        source_video,
        output_path,
        registry.artifact_path(EDITED_VIDEO),
        settings,
    )

    # Видео заменилось: превью с прожигом и превью аннотаций пересобираем
    registry.artifact_path("annotation_preview.mp4").unlink(missing_ok=True)
    registry.artifact_path("edited_video_with_subtitles.mp4").unlink(missing_ok=True)
    registry.artifact_path("_subtitle_burn.ass").unlink(missing_ok=True)
    try:
        from src.services.subtitle_burn_service import ensure_subtitled_studio_video

        ensure_subtitled_studio_video(registry, settings, force=True)
    except Exception:
        logger.exception("Не удалось собрать превью с субтитрами после озвучки")

    segments_doc["status"] = "completed"
    registry.save_json(VOICEOVER_SEGMENTS, segments_doc)

    logger.info(
        "Озвучка готова: блоков %s, длительность %.1f с, предупреждений %s",
        len(segments),
        assembled,
        len(warnings),
    )
    return {
        "ok": True,
        "message": (
            f"Озвучка готова: {len(segments)} блоков."
            + (f" Требует внимания: {len(warnings)}." if warnings else "")
        ),
        "segment_count": len(segments),
        "total_duration_seconds": round(assembled, 3),
        "warnings": warnings,
        "voiceover_segments": segments_doc,
    }


def downstream_is_stale(registry: ArtifactRegistry) -> bool:
    """v3: аннотации и экспорт устарели, если озвучка не по текущим субтитрам."""
    if not registry.exists(TIME_BLOCKS_FILE):
        return False
    return not (auto_voiceover_ready(registry) and auto_voiceover_matches_subtitles(registry))


def voiceover_summary(registry: ArtifactRegistry) -> dict[str, Any]:
    """Короткая сводка для интерфейса (без Speech Script)."""
    if not registry.exists(VOICEOVER_SEGMENTS):
        return {"ready": False}
    doc = registry.load_json(VOICEOVER_SEGMENTS)
    segments = doc.get("segments") or []
    problem = [s for s in segments if not s.get("fits_slot", True)]
    return {
        "ready": True,
        "segment_count": len(segments),
        "optimized_count": sum(
            1 for s in segments if str(s.get("optimization") or "none") != "none"
        ),
        "problem_blocks": [s.get("block_id") for s in problem],
        "warnings": list(doc.get("warnings") or []),
        "up_to_date": auto_voiceover_matches_subtitles(registry),
        "total_duration_seconds": doc.get("total_duration_seconds"),
    }


def voiceover_text_hash(registry: ArtifactRegistry) -> str | None:
    if not registry.exists(SPEECH_SCRIPT_FILE):
        return None
    doc = registry.load_json(SPEECH_SCRIPT_FILE)
    payload = "\n".join(
        f"{i.get('block_id')}|{i.get('speech_text')}" for i in doc.get("items") or []
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
