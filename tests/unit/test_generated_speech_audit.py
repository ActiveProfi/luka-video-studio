import json

import numpy as np
import pytest
from scipy.io import wavfile

from src.config import Settings
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services import generated_speech_audit as service


def test_empty_recognition_cannot_pass_and_audio_change_invalidates_cache(tmp_path, monkeypatch):
    r = ArtifactRegistry(tmp_path)
    r.save_json(
        "voiceover_segments.json",
        {"segments": [{"transcript_segment_id": "a", "text": "семь процентов"}]},
    )
    timing = {"audio_sha256": "first", "segments": [{"segment_id": "a", "words": []}]}
    monkeypatch.setattr(service, "ensure_voice_word_timing", lambda *args: timing)
    calls = []

    async def complete(settings, prompt, payload, *, validate_response):
        calls.append(payload)
        raw = (
            "```json\n"
            + json.dumps({"checks": [{"id": "a", "status": "passed", "reason": "okay"}]})
            + "\n```"
        )
        validate_response(raw)
        return raw, "test"

    monkeypatch.setattr(service, "complete_with_fallback", complete)
    assert service.inspect_generated_speech(r, Settings())["status"] == "retry"
    service.inspect_generated_speech(r, Settings())
    assert len(calls) == 1
    timing["audio_sha256"] = "second"
    timing["segments"][0]["words"] = [{"word": "7 процентов"}]
    assert service.inspect_generated_speech(r, Settings())["status"] == "passed"
    assert len(calls) == 2


def test_uncertainty_does_not_trigger_resynthesis(tmp_path, monkeypatch):
    monkeypatch.setattr(
        service,
        "inspect_generated_speech",
        lambda *args: {"status": "uncertain", "checks": [{"id": "a", "status": "uncertain"}]},
    )

    def forbidden(**kwargs):
        raise AssertionError("Do not rewrite audio just for ASR normalization")

    assert (
        service.audit_and_repair_voiceover(ArtifactRegistry(tmp_path), Settings(), forbidden)[
            "status"
        ]
        == "uncertain"
    )


@pytest.mark.parametrize("final_status", ["passed", "retry"])
def test_retry_is_bounded_and_preserves_neighbor_audio(tmp_path, monkeypatch, final_status):
    r = ArtifactRegistry(tmp_path)
    wavfile.write(r.artifact_path("voiceover.wav"), 1000, np.full(3000, 11, dtype=np.int16))
    segment = {
        "transcript_segment_id": "a",
        "block_id": 1,
        "text": "семь процентов",
        "subtitle_text": "7%",
        "target_slot_seconds": 1,
        "allowed_audio_seconds": 1,
        "audio_start": 0,
        "audio_end": 1,
        "audio_duration_seconds": 1,
        "optimization": "none",
        "speed_applied": 1,
    }
    other = {
        **segment,
        "transcript_segment_id": "b",
        "block_id": 2,
        "audio_start": 1,
        "audio_end": 2,
    }
    r.save_json(
        "voiceover_segments.json", {"segments": [segment, other], "total_duration_seconds": 3}
    )
    r.save_json("speech_script_auto.json", {"items": [{"block_id": 1}, {"block_id": 2}]})
    r.save_json("automatic_sync_report.json", {})
    r.save_json("voiceover_timing_report.json", {})
    reports = iter(
        [
            {"status": "retry", "checks": [{"id": "a", "status": "retry"}]},
            {"status": final_status, "checks": [{"id": "a", "status": final_status}]},
        ]
    )
    monkeypatch.setattr(service, "inspect_generated_speech", lambda *args: next(reports))
    calls = []

    def fit(**kwargs):
        calls.append(kwargs)
        path = kwargs["work_dir"] / "retry.wav"
        wavfile.write(path, 1000, np.full(500, 22, dtype=np.int16))
        return {
            "fits": True,
            "wav_path": path,
            "speech_text": kwargs["speech_text"],
            "optimization": "none",
            "speed_applied": 1,
        }

    if final_status == "retry":
        with pytest.raises(RuntimeError, match="проверку"):
            service.audit_and_repair_voiceover(r, Settings(), fit)
    else:
        assert service.audit_and_repair_voiceover(r, Settings(), fit)["retried_segments"] == ["a"]
    assert len(calls) == 1
    _, samples = wavfile.read(r.artifact_path("voiceover.wav"))
    assert np.all(samples[:500] == 22)
    assert np.all(samples[500:1000] == 0)
    assert np.all(samples[1000:] == 11)
    assert r.load_json("voiceover_segments.json")["segments"][0]["audio_end"] == 0.5

def test_focused_review_rejects_invented_missing_word(tmp_path, monkeypatch):
    r = ArtifactRegistry(tmp_path)
    r.save_json('voiceover_segments.json', {'segments': [{'transcript_segment_id': 'a', 'text': 'Сохранились, программа может не найти файл.'}]})
    timing = {'audio_sha256':'audio','segments':[{'segment_id':'a','words':[{'word':'Сохранились, программа может не найти файл.'}]}]}
    monkeypatch.setattr(service, 'ensure_voice_word_timing', lambda *args: timing)
    calls=[]
    async def complete(settings, prompt, payload, *, validate_response):
        calls.append(json.loads(payload))
        status='retry' if len(calls)==1 else 'passed'
        raw=json.dumps({'checks':[{'id':'a','status':status,'reason':'Пропущено сохранились' if status=='retry' else 'Все слова присутствуют'}]})
        validate_response(raw)
        return raw,'test'
    monkeypatch.setattr(service,'complete_with_fallback',complete)
    result=service.inspect_generated_speech(r,Settings())
    assert result['status']=='passed'
    assert len(calls)==2
    assert result['focused_reviews'][0]['initial']['status']=='retry'
    service.inspect_generated_speech(r,Settings())
    assert len(calls)==2

def test_automatic_resume_retries_failed_voice_even_when_text_matches(monkeypatch):
    from unittest.mock import Mock
    from src.api import app as api
    from src.services import auto_voiceover_service, timeblock_service
    parent=Mock()
    parent.exists.return_value=True
    selected=[]
    monkeypatch.setattr(api,'save_lesson_options',lambda *args: None)
    monkeypatch.setattr(api,'_registry',lambda job: parent)
    monkeypatch.setattr(timeblock_service,'subtitles_saved',lambda registry: True)
    monkeypatch.setattr(auto_voiceover_service,'auto_voiceover_ready',lambda registry: False)
    monkeypatch.setattr(auto_voiceover_service,'auto_voiceover_matches_subtitles',lambda registry: True)
    monkeypatch.setattr(api,'_schedule_ui_stage',lambda job,stage,tasks: selected.append(stage) or True)
    assert api.start_automatic_lesson('test_job',None,{})['ok']
    assert selected==['voiceover']
