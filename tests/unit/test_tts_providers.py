from unittest.mock import AsyncMock

import httpx
import pytest

from src.config import Settings
from src.providers.tts.base import TTSChunk
from src.providers.tts import yandex, runner, elevenlabs
from src.providers.tts.factory import build_tts_chain
from src.services import lesson_options_service as options


@pytest.mark.parametrize("voice", ["fr-FR-RemyMultilingualNeural", "de-DE-FlorianMultilingualNeural"])
def test_selected_edge_voice_without_api_key(voice, tmp_path):
    from src.orchestrator.artifact_registry import ArtifactRegistry
    settings = Settings(_env_file=None)
    registry = ArtifactRegistry(tmp_path)
    registry.save_json(options.OPTIONS_FILE, {"provider": "edge", "voice": voice, "speed": 1.2})
    selected = options.voice_settings(registry, settings)
    chain = build_tts_chain(selected)
    assert [p.name for p in chain] == ["edge"]
    assert chain[0].settings.edge_tts_voice == voice
    assert chain[0].settings.edge_tts_speed == 1.2


def test_selected_elevenlabs_voice_and_tempo(tmp_path, monkeypatch):
    from src.orchestrator.artifact_registry import ArtifactRegistry
    settings = Settings(_env_file=None, elevenlabs_api_key="test", elevenlabs_voices={"chosen": "Выбранный"})
    monkeypatch.setattr(options, "get_settings", lambda: settings)
    registry = ArtifactRegistry(tmp_path)
    registry.save_json(options.OPTIONS_FILE, {"provider": "elevenlabs", "voice": "chosen", "speed": 1.2})
    selected = options.voice_settings(registry, settings)
    chain = build_tts_chain(selected)
    assert [p.name for p in chain] == ["elevenlabs"]
    assert chain[0].settings.elevenlabs_voice_id == "chosen"
    assert chain[0].settings.elevenlabs_speed == 1.2
    assert options.voice_catalog(settings)["elevenlabs"] == {"chosen": "Выбранный"}
    with pytest.raises(ValueError):
        options.LessonOptions(provider="elevenlabs", voice="unknown").validate_voice()


@pytest.mark.parametrize("status,expected_calls", [(500, 3), (401, 1)])
async def test_yandex_retries_only_temporary_errors(status, expected_calls, tmp_path, monkeypatch):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "internal"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(yandex.httpx, "AsyncClient", lambda **kwargs: client)
    monkeypatch.setattr(yandex.asyncio, "sleep", AsyncMock())
    provider = yandex.YandexTTSProvider("test", "folder", settings=Settings(_env_file=None))
    with pytest.raises(RuntimeError, match=f"ошибку {status}"):
        await provider.synthesize(TTSChunk("Проверка.", tmp_path / "voice.wav"))
    assert len(calls) == expected_calls
    assert not (tmp_path / "voice.wav").exists()


async def test_single_provider_error_does_not_claim_all_failed(tmp_path, monkeypatch):
    class Failed:
        name = "yandex"
        synthesize = AsyncMock(side_effect=RuntimeError("HTTP 500"))
    monkeypatch.setattr(runner, "build_tts_chain", lambda settings: [Failed()])
    with pytest.raises(RuntimeError, match="через yandex") as error:
        await runner.synthesize_with_fallback(TTSChunk("Проверка.", tmp_path / "voice.wav"), Settings(_env_file=None))
    assert "Все TTS" not in str(error.value)


async def test_elevenlabs_auth_error_preserves_existing_audio(tmp_path, monkeypatch):
    def respond(request):
        assert request.headers["xi-api-key"] == "test-key"
        assert request.url.path.endswith("/chosen")
        return httpx.Response(401, json={"detail": "private diagnostic"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(elevenlabs.httpx, "AsyncClient", lambda **kwargs: client)
    output = tmp_path / "voice.wav"
    output.write_bytes(b"previous audio")
    provider = elevenlabs.ElevenLabsTTSProvider(Settings(_env_file=None, elevenlabs_api_key="test-key", elevenlabs_voice_id="chosen"))
    with pytest.raises(RuntimeError, match="ошибка 401"):
        await provider.synthesize(TTSChunk("Проверка.", output))
    assert output.read_bytes() == b"previous audio"
