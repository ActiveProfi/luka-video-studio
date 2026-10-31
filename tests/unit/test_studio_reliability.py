from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.config import Settings
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services import job_execution
from src.services.lesson_options_service import LessonOptions, load_options


def test_failed_atomic_replace_preserves_old_document(tmp_path, monkeypatch):
    registry = ArtifactRegistry(tmp_path)
    registry.save_json("state.json", {"version": 1})

    def fail(*args):
        raise OSError("disk error")

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError):
        registry.save_json("state.json", {"version": 2})
    assert registry.load_json("state.json") == {"version": 1}
    assert not list(tmp_path.glob(".saving-*"))


def test_concurrent_reads_never_observe_partial_json(tmp_path):
    registry = ArtifactRegistry(tmp_path)
    registry.save_json("state.json", {"value": "a" * 10000})

    def write():
        for i in range(20):
            registry.save_json("state.json", {"value": str(i) * 10000})

    with ThreadPoolExecutor() as pool:
        future = pool.submit(write)
        for _ in range(100):
            assert isinstance(registry.load_json("state.json")["value"], str)
        future.result()


def test_live_work_not_completed_from_intermediate_files(tmp_path):
    import src.api.app as api

    registry = ArtifactRegistry(tmp_path / "live_job")
    registry.save_json("annotation_suggestions.json", {"suggestions": []})
    state = {"status": "running", "current_stage": "annotations"}
    assert job_execution.reserve("live_job")
    try:
        assert not job_execution.reserve("live_job")
        assert api._reconcile_stale_running(registry, state) == state
        with pytest.raises(api.HTTPException) as error:
            api._ensure_pipeline_not_running(registry)
        assert error.value.status_code == 409
    finally:
        job_execution.release("live_job")


def test_restart_reports_interruption_and_preserves_output(tmp_path, monkeypatch):
    import src.api.app as api

    registry = ArtifactRegistry(tmp_path / "restart_job")
    registry.save_json(
        "pipeline_state.json",
        {"status": "running", "current_stage": "assembly", "stages_completed": ["voiceover"]},
    )
    registry.artifact_path("final_lesson.mp4").write_bytes(b"last-good")
    monkeypatch.setattr(api, "get_settings", lambda: Settings(output_dir=tmp_path))
    with TestClient(api.app):
        state = registry.load_json("pipeline_state.json")
        assert state["status"] == "failed" and "перезапуском" in state["error"]
        assert state["stages_completed"] == ["voiceover"]
        assert registry.artifact_path("final_lesson.mp4").read_bytes() == b"last-good"


def test_old_profile_preserved_new_projects_general(tmp_path):
    registry = ArtifactRegistry(tmp_path)
    registry.save_json("lesson_options.json", {"provider": "yandex", "voice": "alena"})
    assert load_options(registry, Settings()).content_profile == "accounting"
    registry.save_json(
        "lesson_options.json", LessonOptions(topic_context="Работа в Blender").model_dump()
    )
    assert load_options(registry, Settings()).content_profile == "general"


def test_new_topic_does_not_inherit_server_stt_context(tmp_path, monkeypatch):
    from src.agents import speech_recognition_agent as agent
    from src.providers.stt.base import STTResult

    registry = ArtifactRegistry(tmp_path)
    raw = registry.artifact_path("raw_video.mp4")
    raw.write_bytes(b"raw")
    registry.save_json("input_manifest.json", {"raw_video_path": str(raw)})
    registry.save_json(
        "lesson_options.json",
        LessonOptions(topic_context="Blender", terminology="Bevel, Extrude").model_dump(),
    )
    captured = []

    async def recognize(path, settings, language):
        captured.append(settings)
        return STTResult(language="ru", duration_seconds=1, segments=[], provider="openai")

    monkeypatch.setattr(agent, "transcribe_with_fallback", recognize)
    monkeypatch.setattr(agent, "extract_audio_ogg", lambda *a: None)
    monkeypatch.setattr(agent, "get_media_duration_seconds", lambda *a: 1)
    agent.run_speech_recognition(
        registry, Settings(stt_context="НДС, УСН", stt_keywords="1С"), "job"
    )
    assert captured[0].stt_context == "Blender" and captured[0].stt_keywords == "Bevel, Extrude"
