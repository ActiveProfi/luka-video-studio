"""Заглушки новой последовательности пайплайна (v2).

Старый код этапов tts / edit / subtitles / final_voiceover_from_subtitles
НЕ удаляется — здесь только маркеры «этап пройден как stub», пока логика не подключена.
"""

from __future__ import annotations

import logging
from typing import Any

from src.domain.contracts import utc_now_iso
from src.domain.enums import ArtifactStatus
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.orchestrator.pipeline_state import PipelineState

logger = logging.getLogger(__name__)

STUB_FILES: dict[str, str] = {
    "subtitle_blocks": "subtitle_blocks_stub.json",
    "voiceover_script": "voiceover_script_stub.json",
    "final_voiceover": "final_voiceover_stub.json",
}

STUB_MESSAGES: dict[str, str] = {
    "subtitle_blocks": (
        "Заглушка шага «Разбивка на блоки / субтитры». "
        "Сюда будет подключён редактор как в бывшем шаге 6 "
        "(SubtitleLayoutEditor + subtitle_service), но до озвучки. "
        "Старый код не удалён."
    ),
    "voiceover_script": (
        "Заглушка шага «Текст для озвучки». "
        "Будет отдельный файл Speech Script параллельно субтитрам: "
        "два окна под видео (озвучка + субтитры) и раздельное утверждение. "
        "Текст субтитров останется прежним. Старый speech_script / cleanup сохранены."
    ),
    "final_voiceover": (
        "Заглушка шага «Финальная озвучка». "
        "Будет подключён существующий final_voiceover_from_subtitles "
        "и/или бывший TTS. Старый код tts / edit / 6.1 сохранён."
    ),
}

LEGACY_POINTERS: dict[str, list[str]] = {
    "subtitle_blocks": [
        "review-ui/src/SubtitleLayoutEditor.tsx",
        "src/services/subtitle_service.py",
        "src/services/subtitle_review_service.py",
        "src/agents/subtitle_alignment_agent.py",
    ],
    "voiceover_script": [
        "review-ui/src/App.tsx (CleanupTextEditor / speech_script)",
        "src/services/cleanup_review_service.py",
        "src/agents/tts_generation_agent.py",
    ],
    "final_voiceover": [
        "src/services/final_voiceover_from_subtitles.py",
        "src/agents/tts_generation_agent.py",
        "src/agents/video_edit_agent.py",
        "POST /jobs/{id}/subtitles/final-voiceover",
    ],
}


def stub_artifact_name(ui_stage_id: str) -> str | None:
    return STUB_FILES.get(ui_stage_id)


def stub_is_done(registry: ArtifactRegistry, ui_stage_id: str) -> bool:
    name = stub_artifact_name(ui_stage_id)
    if not name:
        return False
    return registry.exists(name)


def run_pipeline_v2_stub(job_id: str, ui_stage_id: str) -> PipelineState:
    """Отметить stub-этап выполненным (без реальной логики)."""
    from src.config import get_settings

    if ui_stage_id not in STUB_FILES:
        raise ValueError(f"Нет заглушки для этапа «{ui_stage_id}»")

    settings = get_settings()
    job_dir = settings.job_output_dir(job_id)
    registry = ArtifactRegistry(job_dir)
    state_data = registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
    completed = list(state_data.get("stages_completed") or [])

    state = PipelineState(
        job_id=job_id,
        output_dir=str(job_dir),
        status=ArtifactStatus.RUNNING,
        stages_completed=completed,
        current_stage=ui_stage_id,
    )
    registry.save_json("pipeline_state.json", state.to_dict())

    # Мягкий мост: минимальные placeholder-субтитры из transcript (старый редактор не трогаем)
    if ui_stage_id == "subtitle_blocks":
        _ensure_placeholder_subtitles(registry, job_id)
    if ui_stage_id == "final_voiceover":
        _ensure_placeholder_edited_video(registry)

    payload: dict[str, Any] = {
        "job_id": job_id,
        "stage": ui_stage_id,
        "stub": True,
        "ok": True,
        "created_at": utc_now_iso(),
        "message": STUB_MESSAGES[ui_stage_id],
        "legacy_code_paths": LEGACY_POINTERS.get(ui_stage_id, []),
        "note": "Реализация будет подключена без удаления старого кода.",
    }
    registry.save_json(STUB_FILES[ui_stage_id], payload)
    logger.info("Stub-этап %s отмечен для job %s", ui_stage_id, job_id)

    if ui_stage_id not in completed:
        completed.append(ui_stage_id)

    state = PipelineState(
        job_id=job_id,
        output_dir=str(job_dir),
        status=ArtifactStatus.COMPLETED,
        stages_completed=completed,
        current_stage=None,
        error=None,
    )
    registry.save_json("pipeline_state.json", state.to_dict())
    return state


def _ensure_placeholder_subtitles(registry: ArtifactRegistry, job_id: str) -> None:
    """Если субтитров ещё нет — создать минимальные из transcript (заглушка шага 4)."""
    if registry.exists("subtitle_timing.json") and registry.exists("subtitles.srt"):
        return
    if not registry.exists("transcript.json"):
        return
    transcript = registry.load_json("transcript.json")
    segments = list(transcript.get("segments") or [])
    cues: list[dict[str, Any]] = []
    for idx, seg in enumerate(segments, start=1):
        start = float(seg.get("start", 0) or 0)
        end = float(seg.get("end", start + 1) or (start + 1))
        text = str(seg.get("text") or "").strip()
        cues.append(
            {
                "cue_id": f"cue_{idx:04d}",
                "source_segment_id": str(seg.get("id") or seg.get("segment_id") or f"seg_{idx}"),
                "start": round(start, 3),
                "end": round(max(end, start + 0.3), 3),
                "text": text,
            }
        )
    total = max((c["end"] for c in cues), default=0.0)
    timing = {
        "job_id": job_id,
        "version": "stub-1.0",
        "stub": True,
        "created_at": utc_now_iso(),
        "total_duration_seconds": round(total, 3),
        "cue_count": len(cues),
        "cues": cues,
        "note": "Placeholder из transcript. Полный редактор шага 4 ещё не подключён.",
    }
    registry.save_json("subtitle_timing.json", timing)
    lines: list[str] = []
    for i, cue in enumerate(cues, start=1):
        lines.append(str(i))
        lines.append(_fmt_srt(cue["start"]) + " --> " + _fmt_srt(cue["end"]))
        lines.append(cue["text"] or " ")
        lines.append("")
    registry.artifact_path("subtitles.srt").write_text("\n".join(lines), encoding="utf-8")
    if not registry.exists("subtitle_layout.json"):
        registry.save_json(
            "subtitle_layout.json",
            {
                "job_id": job_id,
                "stub": True,
                "x": 0.06,
                "y": 0.82,
                "width": 0.88,
                "height": 0.12,
                "font_size_px": 12,
                "alignment": "center",
                "font_color": "#ffffff",
                "background_color": "#000000",
                "background_opacity": 0.72,
                "cue_layouts": {},
            },
        )


def _fmt_srt(sec: float) -> str:
    total_ms = int(round(max(0.0, sec) * 1000))
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ensure_placeholder_edited_video(registry: ArtifactRegistry) -> None:
    """Если edited_video нет — скопировать raw (заглушка, без реальной озвучки)."""
    import shutil

    if registry.exists("edited_video.mp4"):
        return
    if not registry.exists("raw_video.mp4"):
        return
    shutil.copy2(registry.artifact_path("raw_video.mp4"), registry.artifact_path("edited_video.mp4"))
