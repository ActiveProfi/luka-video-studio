"""Regression checks for the original-recording instruction conveyor."""

import hashlib
import json
import subprocess
from unittest.mock import AsyncMock, patch

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.config import Settings
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.automatic_script_service import (
    conservative_cleanup,
    generate_instruction_script,
    make_blocks,
    rewrite_risks,
)
from src.services.ffmpeg_service import _ffmpeg_bin
from src.services.lesson_options_service import (
    LessonOptions,
    load_options,
    voice_hash,
    voice_settings,
)
from src.services.screen_annotation_service import accept_observations, valid_box
from src.services.video_probe_service import probe_video


@pytest.fixture
def setup_job(tmp_path):
    registry = ArtifactRegistry(tmp_path / "job_auto")
    settings = Settings(output_dir=tmp_path, _env_file=None)
    registry.save_json("video_meta.json", {"duration_seconds": 6, "has_audio": True})
    registry.save_json("time_blocks.json", {"duration_seconds": 6, "blocks": [], "saved_at": None})
    registry.save_json("lesson_options.json", LessonOptions().model_dump())
    registry.artifact_path("raw_video.mp4").write_bytes(b"fixture")
    return registry, settings


@pytest.mark.parametrize(
    "before,after",
    [
        ("Не нажимаем «Удалить»", "Нажимаем «Удалить»"),
        ("Вводим 20 процентов НДС", "Вводим 22 процента НДС"),
        ("Открываем «Создать»", "Открываем «Удалить»"),
        ("Открываем документ в программе", "Закрываем документ в программе"),
        ("Выбираем НДС", "Выбираем налог"),
    ],
)
def test_semantic_guard(before, after):
    assert rewrite_risks(before, after)


def test_safe_cleanup():
    assert conservative_cleanup("Ну, открываем открываем документ") == "открываем документ"
    assert not rewrite_risks("Ну, открываем документ", "Открываем документ")
    assert "значит" in conservative_cleanup("Это значит, что документ без НДС")


def test_preserve_manual_draft(setup_job):
    registry, settings = setup_job
    registry.save_json("time_blocks.json", {"blocks": [{"subtitle": "Моя правка"}]})
    with patch("src.services.automatic_script_service.run_speech_recognition") as stt:
        generate_instruction_script(registry, settings, "job_auto")
        stt.assert_not_called()
    assert registry.load_json("time_blocks.json")["blocks"][0]["subtitle"] == "Моя правка"


def transcript(text="Открываем документ", confidence=0.95):
    return {
        "provider": "faster_whisper",
        "segments": [
            {
                "segment_id": "seg_001",
                "start": 0.2,
                "end": 5.5,
                "text": text,
                "confidence": confidence,
            }
        ],
    }


def test_safe_script_continues_automatically(setup_job):
    registry, settings = setup_job
    response = json.dumps(
        {
            "segments": [
                {"segment_id": "seg_001", "text": "Открываем документ", "needs_review": False}
            ]
        }
    )
    with (
        patch(
            "src.services.automatic_script_service.run_speech_recognition",
            return_value=transcript(),
        ),
        patch(
            "src.services.automatic_script_service.complete_with_fallback",
            new=AsyncMock(return_value=(response, "test")),
        ),
    ):
        result = generate_instruction_script(registry, settings, "job_auto")
    assert result["status"] == "completed"
    assert registry.load_json("time_blocks.json")["saved_at"]
    assert "Открываем документ" in registry.artifact_path("subtitles.srt").read_text(
        encoding="utf-8"
    )


def test_dangerous_rewrite_stops_for_review(setup_job):
    registry, settings = setup_job
    response = json.dumps(
        {
            "segments": [
                {"segment_id": "seg_001", "text": "Вводим 22 процента НДС", "needs_review": False}
            ]
        }
    )
    with (
        patch(
            "src.services.automatic_script_service.run_speech_recognition",
            return_value=transcript("Вводим 20 процентов НДС"),
        ),
        patch(
            "src.services.automatic_script_service.complete_with_fallback",
            new=AsyncMock(return_value=(response, "test")),
        ),
    ):
        result = generate_instruction_script(registry, settings, "job_auto")
    assert result["status"] == "needs_review"
    assert not registry.load_json("time_blocks.json")["saved_at"]
    assert "20" in registry.load_json("time_blocks.json")["blocks"][0]["subtitle"]


def test_llm_failure_keeps_narration(setup_job):
    registry, settings = setup_job
    with (
        patch(
            "src.services.automatic_script_service.run_speech_recognition",
            return_value=transcript(),
        ),
        patch(
            "src.services.automatic_script_service.complete_with_fallback",
            new=AsyncMock(side_effect=RuntimeError("offline")),
        ),
    ):
        with pytest.raises(RuntimeError, match="Технический сбой"):
            generate_instruction_script(registry, settings, "job_auto")
    result = registry.load_json("script_review_report.json")
    assert result["status"] == "technical_error"
    assert result["review_count"] == 0
    assert registry.load_json("time_blocks.json")["blocks"] == []


def test_no_audio_is_manual_review(setup_job):
    registry, settings = setup_job
    registry.save_json("video_meta.json", {"duration_seconds": 6, "has_audio": False})
    with patch("src.services.automatic_script_service.run_speech_recognition") as stt:
        assert (
            generate_instruction_script(registry, settings, "job_auto")["status"] == "needs_review"
        )
        stt.assert_not_called()


def test_subtitle_splitting_preserves_text_and_original_time():
    text = " ".join(["открываем", "документ"] * 25)
    blocks = make_blocks([{"segment_id": "s", "start": 2, "end": 12, "text": text}], 14)
    assert len(blocks) > 1
    assert " ".join(b["subtitle"] for b in blocks) == text
    assert blocks[0]["start"] == 2 and blocks[-1]["end"] == 12
    assert all(a["end"] == b["start"] for a, b in zip(blocks, blocks[1:]))


def test_voice_is_per_lesson_and_changes_hash(setup_job):
    registry, settings = setup_job
    old = voice_hash(registry, settings)
    options = LessonOptions(voice="filipp", speed=0.9)
    registry.save_json("lesson_options.json", options.model_dump())
    local = voice_settings(registry, settings)
    assert local.yandex_tts_voice == "filipp" and local.tts_fallback_order == "yandex"
    assert settings.yandex_tts_voice == "alena"
    assert old != voice_hash(registry, settings)
    registry.artifact_path("lesson_options.json").unlink()
    assert load_options(registry, settings).automatic is False


def observations():
    return [
        {
            "time": t,
            "visible": True,
            "bbox": {"x": 0.1, "y": 0.2, "width": 0.1, "height": 0.05},
            "confidence": 0.98,
            "evidence": "Кнопка Создать",
            "cursor": {"x": 0.15, "y": 0.225},
        }
        for t in [1.0, 2.0, 3.0]
    ]


def test_auto_anchor_has_visual_evidence_and_cursor():
    ann = {"type": "arrow", "target_start": 1, "target_end": 4}
    result = accept_observations(ann, observations(), [1, 2, 3], 0.92)
    assert result["placement_confirmed"] is True
    assert result["anchor"]["x"] == pytest.approx(0.15)
    assert result["target_end"] == 3
    assert len(result["anchor_track"]) == 3 and result["visual_evidence"][0]["cursor"]


def test_copied_prompt_example_is_not_visual_evidence():
    items = observations()
    for item in items:
        item["evidence"] = "точная надпись и положение"
    assert not accept_observations({"type": "arrow"}, items, [1, 2, 3], 0.92)["placement_confirmed"]


@pytest.mark.parametrize(
    "problem",
    ["missing", "low_confidence", "disappeared", "movement", "invalid_box", "no_evidence"],
)
def test_uncertain_object_is_not_placed(problem):
    items = observations()
    if problem == "missing":
        items.pop()
    elif problem == "low_confidence":
        items[1]["confidence"] = 0.7
    elif problem == "disappeared":
        items[1]["visible"] = False
    elif problem == "movement":
        items[1]["bbox"]["x"] = 0.6
    elif problem == "invalid_box":
        items[1]["bbox"]["width"] = 1.5
    elif problem == "no_evidence":
        items[1]["evidence"] = ""
    assert not accept_observations({"type": "arrow"}, items, [1, 2, 3], 0.92)["placement_confirmed"]


def test_nan_coordinates_rejected():
    assert valid_box({"x": float("nan"), "y": 0.2, "width": 0.1, "height": 0.1}) is None


def test_api_voice_change_invalidates_downstream(setup_job):
    from src.api.app import app

    registry, settings = setup_job
    for file in ["voiceover.wav", "final_lesson.mp4", "approved_annotations.json"]:
        registry.artifact_path(file).write_bytes(b"old")
    with patch("src.api.app.get_settings", return_value=settings):
        response = TestClient(app).put(
            "/jobs/job_auto/options", json=LessonOptions(voice="filipp").model_dump()
        )
        assert response.status_code == 200
        assert response.json()["voiceover_invalidated"]
    assert not registry.exists("final_lesson.mp4") and not registry.exists("voiceover.wav")


@pytest.mark.parametrize(
    "saved,expected",
    [
        (False, ["subtitle_capture"]),
        (True, ["subtitle_capture", "voiceover", "annotations", "export"]),
    ],
)
def test_automatic_chain_waits_for_script_review(setup_job, saved, expected):
    import importlib

    api = importlib.import_module("src.api.app")
    registry, settings = setup_job
    registry.save_json("pipeline_state.json", {"status": "completed"})
    calls = []

    def run(job_id, stage):
        calls.append(stage)
        if stage == "subtitle_capture" and saved:
            registry.save_json(
                "time_blocks.json", {"saved_at": "approved", "blocks": [{"subtitle": "Текст"}]}
            )
        if stage == "annotations":
            registry.save_json("annotation_suggestions.json", {"suggestions": []})
        if stage == "voiceover":
            registry.artifact_path("edited_video.mp4").write_bytes(b"generated")
        registry.save_json("pipeline_state.json", {"status": "completed"})

    with (
        patch.object(api, "get_settings", return_value=settings),
        patch.object(api, "run_single_ui_stage", side_effect=run),
        patch.object(api, "approve_annotation_review"),
    ):
        api._auto_chain_ui_stages("job_auto", "upload")
    assert calls == expected


def test_unresolved_annotation_blocks_automatic_export(setup_job):
    import importlib

    api = importlib.import_module("src.api.app")
    registry, settings = setup_job
    registry.save_json("pipeline_state.json", {"status": "completed"})
    registry.save_json(
        "annotation_suggestions.json", {"suggestions": [{"placement_confirmed": False}]}
    )
    with patch.object(api, "run_single_ui_stage") as run:
        api._finish_automatic_lesson(registry, settings, "job_auto")
        run.assert_not_called()


def test_real_media_assembly_preserves_original_and_replaces_sound(setup_job):
    from src.agents.lesson_assembly_agent import run_lesson_assembly
    from src.services.auto_voiceover_service import run_auto_voiceover
    from src.services.subtitle_capture_service import finalize_subtitles

    registry, settings = setup_job
    try:
        ffmpeg = _ffmpeg_bin(settings)
    except RuntimeError:
        pytest.skip("FFmpeg unavailable")
    raw = registry.artifact_path("raw_video.mp4")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x180:r=10:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-pix_fmt",
            "yuv420p",
            str(raw),
        ],
        capture_output=True,
        check=True,
    )
    original_hash = hashlib.sha256(raw.read_bytes()).hexdigest()
    registry.save_json("input_manifest.json", {"raw_video_path": str(raw)})
    registry.save_json(
        "time_blocks.json",
        {
            "duration_seconds": 2,
            "blocks": [
                {
                    "id": 1,
                    "start": 0.1,
                    "end": 0.9,
                    "subtitle": "Открываем документ",
                    "status": "edited",
                },
                {
                    "id": 2,
                    "start": 1.0,
                    "end": 1.9,
                    "subtitle": "Нажимаем Создать",
                    "status": "edited",
                },
            ],
            "saved_at": None,
        },
    )
    finalize_subtitles(registry, "job_auto", settings=settings)

    def synthesize(text, path, language, selected_settings):
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=880:duration=0.5",
                "-ar",
                "48000",
                "-ac",
                "1",
                str(path),
            ],
            capture_output=True,
            check=True,
        )
        return 0.5, "yandex"

    with (
        patch("src.services.auto_voiceover_service._synthesize", side_effect=synthesize),
        patch("src.services.generated_speech_audit.audit_and_repair_voiceover"),
    ):
        run_auto_voiceover(registry, settings, "job_auto")
    registry.save_json(
        "approved_annotations.json",
        {
            "annotations": [
                {
                    "annotation_id": "a",
                    "placement_confirmed": True,
                    "type": "arrow",
                    "anchor": {"x": 0.5, "y": 0.3, "width": 0, "height": 0},
                    "target_start": 0.1,
                    "target_end": 0.8,
                }
            ]
        },
    )
    report = run_lesson_assembly(registry, settings, "job_auto")
    assert probe_video(registry.artifact_path("annotation_preview.mp4"), settings)[
        "duration_seconds"
    ] == pytest.approx(2, abs=0.15)
    assert report["includes_subtitles"] and report["includes_annotations"]
    assert report["original_recording_used"] and report["original_audio_replaced"]
    assert probe_video(registry.artifact_path("edited_video.mp4"), settings)[
        "duration_seconds"
    ] == pytest.approx(2, abs=0.1)
    assert probe_video(registry.artifact_path("final_lesson.mp4"), settings)[
        "duration_seconds"
    ] == pytest.approx(12, abs=0.15)
    assert hashlib.sha256(raw.read_bytes()).hexdigest() == original_hash
    # Verify the resulting audio contains the new tone, not the original recording's tone.
    clean_audio = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(registry.artifact_path("edited_video.mp4")),
            "-ss",
            "0.2",
            "-t",
            "0.3",
            "-f",
            "f32le",
            "-ar",
            "48000",
            "-ac",
            "1",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    samples = np.frombuffer(clean_audio, dtype=np.float32)
    peak = np.fft.rfftfreq(len(samples), 1 / 48000)[np.argmax(abs(np.fft.rfft(samples)))]
    assert peak == pytest.approx(880, abs=10)
    for time in [0.5, 6.5, 10.0]:
        cap = cv2.VideoCapture(str(registry.artifact_path("final_lesson.mp4")))
        cap.set(cv2.CAP_PROP_POS_MSEC, time * 1000)
        ok, frame = cap.read()
        cap.release()
        assert ok
        cv2.imwrite(str(registry.artifact_path(f"verified_{time}.jpg")), frame)

    # Changing only presentation must reuse all semantic/audio artifacts.
    from src.services.subtitle_capture_service import save_layout

    protected = ["raw_video.mp4", "edited_video.mp4", "voiceover.wav",
                 "speech_script_auto.json", "approved_annotations.json", "subtitle_timing.json"]
    before = {name: hashlib.sha256(registry.artifact_path(name).read_bytes()).hexdigest()
              for name in protected}
    old_final = registry.artifact_path("final_lesson.mp4").read_bytes()
    save_layout(registry, "job_auto", {"font_color": "#00ff00", "font_size_px": 28})
    assert registry.artifact_path("final_lesson.mp4").read_bytes() == old_final
    with patch("src.services.auto_voiceover_service._synthesize", side_effect=AssertionError("TTS called")):
        run_lesson_assembly(registry, settings, "job_auto")
    assert registry.artifact_path("final_lesson.mp4").read_bytes() != old_final
    assert not registry.exists("render_pending.json")
    for name, digest in before.items():
        assert hashlib.sha256(registry.artifact_path(name).read_bytes()).hexdigest() == digest
