from pathlib import Path
import wave
import pytest
from unittest.mock import patch

from src.config import Settings
from src.services.auto_voiceover_service import _fit_block_audio
from src.services.auto_voiceover_service import _fit_small_overrun
from src.services.speech_units import group_speech_units
from src.services.text_cleanup_rules import clean_technical_noise


def test_technical_cleanup_preserves_decimal_numbers():
    result, _ = clean_technical_noise("Доходы 19,3 млн. и 22.8 млн. на 06.10.2026 в 12:30")
    assert result == "Доходы 19,3 млн. и 22.8 млн. на 06.10.2026 в 12:30"


def test_numbers_are_spoken_with_their_sentence():
    items = [
        {"id": 1, "start": 45, "end": 49.5, "subtitle": "Доходы составили"},
        {"id": 2, "start": 49.5, "end": 51.4, "subtitle": "19,3 млн."},
        {"id": 3, "start": 51.4, "end": 54, "subtitle": "Превышения нет."},
    ]
    units = group_speech_units(items, "subtitle")
    assert len(units) == 2
    assert units[0]["subtitle"] == "Доходы составили 19,3 млн."
    assert units[0]["start"] == 45 and units[0]["end"] == 51.4
    assert units[0]["source_ids"] == [1, 2]
    assert units[1]["start"] == 51.4


def test_silence_gap_prevents_grouping():
    items = [
        {"start": 0, "end": 2, "text": "Открываем"},
        {"start": 4, "end": 6, "text": "документ"},
    ]
    assert len(group_speech_units(items)) == 2


def test_small_overrun_is_fitted_instead_of_rejected(tmp_path):
    with (
        patch("src.services.auto_voiceover_service._synthesize", return_value=(2.01, "test")),
        patch("src.services.auto_voiceover_service.change_wav_speed") as speed,
        patch("src.services.auto_voiceover_service.get_media_duration_seconds", return_value=1.98),
    ):
        fitted = _fit_block_audio(
            subtitle="Текст",
            speech_text="Текст",
            slot_seconds=2,
            tolerance=0,
            work_dir=Path(tmp_path),
            index=1,
            language="ru",
            settings=Settings(_env_file=None),
        )
    assert fitted["fits"]
    speed.assert_called_once()


@pytest.mark.parametrize("duration,allowed", [(16.124,16), (17.083,16.8), (13.295,12.989), (19.02,18.54), (10.107,9.38), (19.358,18.997)])
def test_real_audio_small_overrun_is_fitted(tmp_path, duration, allowed):
    import math
    import struct
    source = tmp_path / "speech.wav"
    with wave.open(str(source), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(b''.join(struct.pack('<h', int(2000*math.sin(i*2*math.pi*440/48000))) for i in range(round(duration*48000))))
    path, measured, speed = _fit_small_overrun(source, duration, allowed, 1.35, Settings())
    assert path != source
    assert allowed - .1 < measured <= allowed
    assert 1.35 < speed <= 1.5


def test_large_overrun_is_not_hidden(tmp_path):
    source = tmp_path / "speech.wav"
    assert _fit_small_overrun(source, 12, 10, 1.35, Settings(_env_file=None)) == (source, 12, 1.35)


def test_speech_cache_reuses_only_matching_voice_and_text(tmp_path, monkeypatch):
    from src.services import auto_voiceover_service as service
    from src.providers.tts.base import TTSResult
    calls = []
    async def synthesize(chunk, settings):
        calls.append(chunk.text)
        with wave.open(str(chunk.output_path), 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(48000)
            wav.writeframes(b'\x00\x20\x00\xe0' * 24000)
        return TTSResult(chunk.output_path, 'test', 1)
    monkeypatch.setattr(service, 'synthesize_with_fallback', synthesize)
    work = tmp_path / '_tts_auto'
    work.mkdir()
    settings = Settings()
    service._synthesize('Фраза', work / 'one.wav', 'ru', settings)
    service._synthesize('Фраза', work / 'two.wav', 'ru', settings)
    assert len(calls) == 1
    assert (work / 'one.wav').read_bytes() == (work / 'two.wav').read_bytes()
    service._synthesize('Фраза', work / 'three.wav', 'ru', settings.model_copy(update={'elevenlabs_voice_id':'another'}))
    service._synthesize('Другой текст', work / 'four.wav', 'ru', settings)
    assert len(calls) == 3


def test_pending_sync_report_is_not_described_as_completed(tmp_path):
    from src.api.app import _stage_description
    from src.orchestrator.artifact_registry import ArtifactRegistry
    registry = ArtifactRegistry(tmp_path)
    registry.save_json('automatic_sync_report.json', {'status': 'pending'})
    assert _stage_description(registry, 'voiceover', 'Озвучка') == 'Озвучка'
