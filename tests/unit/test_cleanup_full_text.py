"""Тесты единого редактора текста: full_text, save, payload."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.cleanup_review_service import (
    get_cleanup_edit_payload,
    improve_full_text_with_ai,
    save_speech_script_edits,
    save_full_text_cleanup_edits,
)
from src.services.segment_timing_service import join_segments_text


def _seed_multi_block_job(job_dir: Path) -> ArtifactRegistry:
    registry = ArtifactRegistry(job_dir)
    segments = [
        {
            "segment_id": "seg_001",
            "start": 0.0,
            "end": 25.0,
            "text": "Первый блок текста для урока",
            "original_text": "Первый блок текста из распознавания",
            "confidence": 1.0,
        },
        {
            "segment_id": "seg_002",
            "start": 25.0,
            "end": 50.0,
            "text": "Второй блок текста для урока",
            "original_text": "Второй блок текста из распознавания",
            "confidence": 1.0,
        },
    ]
    registry.save_json(
        "clean_transcript.json",
        {
            "job_id": "job_full",
            "stage": "speech_cleanup",
            "version": "1.0.0",
            "created_at": "2026-01-01T00:00:00Z",
            "source_artifacts": ["transcript.json"],
            "status": "completed",
            "language": "ru",
            "duration_seconds": 50.0,
            "timing_aligned": True,
            "segments": segments,
        },
    )
    registry.save_json("edits_map.json", {"job_id": "job_full", "edits": []})
    registry.save_json(
        "cleanup_review.json",
        {
            "job_id": "job_full",
            "stage": "speech_cleanup_review",
            "version": "1.0.0",
            "created_at": "2026-01-01T00:00:00Z",
            "status": "pending",
            "approved_at": None,
            "approved_by": None,
            "manual_edits_count": 0,
            "last_saved_at": None,
        },
    )
    return registry


def test_get_cleanup_edit_includes_full_text(tmp_path: Path) -> None:
    registry = _seed_multi_block_job(tmp_path / "job_full")
    payload = get_cleanup_edit_payload(registry, "job_full")
    expected = join_segments_text(registry.load_json("clean_transcript.json")["segments"], "text")
    assert payload["full_text"] == expected
    assert payload["duration_seconds"] == 50.0
    assert payload["total_budget_steps"] > 0
    assert len(payload["block_markers"]) == 2


def test_save_full_text_splits_into_blocks(tmp_path: Path) -> None:
    registry = _seed_multi_block_job(tmp_path / "job_full2")
    new_text = "Новый единый текст урока для проверки сохранения и автоматической нарезки"
    save_full_text_cleanup_edits(registry, "job_full", new_text)
    clean = registry.load_json("clean_transcript.json")
    joined = join_segments_text(clean["segments"], "text")
    assert joined == new_text
    assert len(clean["segments"]) == 2
    payload = get_cleanup_edit_payload(registry, "job_full")
    assert payload["full_text"] == new_text


def test_improve_full_text_saves_tts_preparation_report(tmp_path: Path) -> None:
    registry = _seed_multi_block_job(tmp_path / "job_full3")
    result_doc = {
        "job_id": "job_full",
        "stage": "tts_preparation",
        "version": "1.0.0",
        "created_at": "2026-01-01T00:00:00Z",
        "status": "ok",
        "text": "Новый текст",
        "full_text": "Новый текст",
        "changes": [
            {
                "before": "ндс",
                "after": "НДС",
                "stage": "3.2 term_correction",
                "reason": "термин",
                "original_duration_seconds": 0.2,
                "edited_duration_seconds": 0.2,
                "duration_diff_seconds": 0,
                "budget_status": "within_budget",
                "metadata": {},
            }
        ],
        "duration_report": [],
        "audit_result": {"approved": True, "notes": "ok"},
        "notes": "",
        "provider": "mock",
        "phases": [],
        "issues_found": 1,
        "changes_applied": ["термин"],
        "budget_matched": True,
        "budget_exceeded": False,
    }

    with patch(
        "src.services.cleanup_review_service.run_tts_preparation_pipeline_async",
        new=AsyncMock(return_value=result_doc),
    ):
        response = improve_full_text_with_ai(registry, "job_full", full_text="Старый текст")

    assert response["full_text"] == "Новый текст"
    assert response["changes"][0]["after"] == "НДС"
    assert registry.exists("tts_preparation_report.json")
    assert registry.exists("speech_script.json")
    script = registry.load_json("speech_script.json")
    assert script["text"] == "Новый текст"
    clean = registry.load_json("clean_transcript.json")
    assert "Новый текст" not in clean["segments"][0]["text"]


def test_save_speech_script_does_not_change_clean_transcript(tmp_path: Path) -> None:
    registry = _seed_multi_block_job(tmp_path / "job_full4")
    before = registry.load_json("clean_transcript.json")["segments"][0]["text"]
    save_speech_script_edits(registry, "job_full", "Сценарий озвучки эн дэ эс")
    script = registry.load_json("speech_script.json")
    after = registry.load_json("clean_transcript.json")["segments"][0]["text"]

    assert script["text"] == "Сценарий озвучки эн дэ эс"
    assert script["text_after"] == "Сценарий озвучки эн дэ эс"
    assert script["text_before"]
    assert after == before


def test_speech_script_keeps_block_bounds_and_does_not_split_words(tmp_path: Path) -> None:
    registry = _seed_multi_block_job(tmp_path / "job_full5")
    text_after = (
        "Первый улучшенный блок текста для озвучки без обрыва "
        "Второй улучшенный блок текста для озвучки тоже целый"
    )
    save_speech_script_edits(registry, "job_full", text_after)
    script = registry.load_json("speech_script.json")
    segs = script["segments"]
    assert len(segs) == 2
    assert segs[0]["start"] == 0.0
    assert segs[0]["end"] == 25.0
    assert segs[1]["start"] == 25.0
    assert segs[1]["end"] == 50.0
    assert segs[0]["text_before"]
    assert segs[0]["text_after"] == segs[0]["text"]
    assert segs[1]["text_after"] == segs[1]["text"]
    # слова не разрезаны: каждый блок состоит из целых слов
    for seg in segs:
        words = seg["text"].split()
        assert " ".join(words) == seg["text"]
    joined = " ".join(seg["text"] for seg in segs if seg["text"]).strip()
    assert joined == text_after


def test_save_full_text_after_speech_script_updates_script_only(tmp_path: Path) -> None:
    registry = _seed_multi_block_job(tmp_path / "job_full6")
    save_speech_script_edits(registry, "job_full", "Сначала сценарий")
    before_clean = registry.load_json("clean_transcript.json")["segments"][0]["text"]
    save_full_text_cleanup_edits(registry, "job_full", "Потом сценарий обновлён")
    script = registry.load_json("speech_script.json")
    after_clean = registry.load_json("clean_transcript.json")["segments"][0]["text"]
    assert script["text_after"] == "Потом сценарий обновлён"
    assert after_clean == before_clean
