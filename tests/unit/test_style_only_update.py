from fastapi.testclient import TestClient
import pytest

from src.config import Settings
from src.orchestrator.artifact_registry import ArtifactRegistry


def test_layout_api_schedules_only_export_and_preserves_assets(tmp_path, monkeypatch):
    import src.api.app as api
    from src.services import auto_voiceover_service as voice
    from src.services import subtitle_capture_service as capture

    r = ArtifactRegistry(tmp_path / "style_job")
    r.save_json("subtitle_layout.json", {"font_color": "#ffffff"})
    assets = {"voiceover.wav": b"audio", "final_lesson.mp4": b"old final",
              "approved_annotations.json": b'{"annotations": []}',
              "speech_script_auto.json": b'{"items": []}'}
    for name, content in assets.items():
        r.artifact_path(name).write_bytes(content)
    monkeypatch.setattr(api, "get_settings", lambda: Settings(output_dir=tmp_path))
    monkeypatch.setattr(capture, "get_capture_payload", lambda *a: {})
    monkeypatch.setattr(voice, "auto_voiceover_ready", lambda *a: True)
    monkeypatch.setattr(voice, "auto_voiceover_matches_subtitles", lambda *a: True)
    monkeypatch.setattr(api, "_build_stages", lambda *a: [])
    scheduled = []
    monkeypatch.setattr(api, "_schedule_ui_stage", lambda job, stage, tasks: scheduled.append(stage) or True)
    client = TestClient(api.app)
    result = client.put("/jobs/style_job/capture/layout", json={"font_color": "#ffff00"})
    assert result.status_code == 200, result.text
    assert scheduled == ["export"]
    assert r.load_json("subtitle_layout.json")["font_color"] == "#ffff00"
    for name, content in assets.items():
        assert r.artifact_path(name).read_bytes() == content
    # A running export with the old final still present must remain busy.
    r.save_json("pipeline_state.json", {"status": "running", "current_stage": "assembly"})
    result = client.put("/jobs/style_job/capture/layout", json={"font_color": "#ff0000"})
    assert result.status_code == 409
    assert scheduled == ["export"]
    assert r.load_json("subtitle_layout.json")["font_color"] == "#ffff00"


def test_failed_render_keeps_previous_final(tmp_path, monkeypatch):
    from src.agents import lesson_assembly_agent as assembly

    r = ArtifactRegistry(tmp_path)
    r.save_json("approved_annotations.json", {"annotations": []})
    r.artifact_path("subtitles.srt").write_text("subtitles")
    r.artifact_path("voiceover.wav").write_bytes(b"audio")
    r.artifact_path("final_lesson.mp4").write_bytes(b"last good video")
    r.save_json("assembly_report.json", {"status": "completed"})
    def fail(*args):
        raise RuntimeError("ffmpeg failed")
    monkeypatch.setattr(assembly, "burn_subtitles_into_video", fail)
    with pytest.raises(RuntimeError, match="субтитры"):
        assembly.run_lesson_assembly(r, Settings(), "job")
    assert r.artifact_path("final_lesson.mp4").read_bytes() == b"last good video"
    assert r.load_json("assembly_report.json") == {"status": "completed"}


def test_unchanged_text_save_does_not_rewrite_timing(tmp_path, monkeypatch):
    from src.services import subtitle_capture_service as capture

    r = ArtifactRegistry(tmp_path)
    for name in ("subtitles.srt", "subtitle_timing.json"):
        r.artifact_path(name).write_bytes(b"unaltered")
    monkeypatch.setattr(capture, "load_time_blocks", lambda *a: {
        "saved_at": "saved", "blocks": [{"id": 1, "subtitle": "Текст"}]})
    monkeypatch.setattr(capture, "get_capture_payload", lambda *a: {"saved_at": "saved"})
    capture.finalize_subtitles(r, "job", [{"id": 1, "subtitle": "Текст"}], Settings())
    assert r.artifact_path("subtitle_timing.json").read_bytes() == b"unaltered"
