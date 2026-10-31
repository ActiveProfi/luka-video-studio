import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import Settings
from src.providers.stt.base import STTResult, TranscriptSegment
from src.providers.stt.factory import build_stt_chain
from src.providers.stt.openai_provider import (
    OpenAISTTProvider,
    merge_short_units,
    valid_transcription,
)


@pytest.mark.parametrize("empty_replies", [0, 1, 2])
def test_context_model_uses_audio_and_keeps_boundaries(tmp_path, empty_replies):
    cfg = Settings(_env_file=None, stt_context="Урок 1С", stt_keywords="УСН,НДС")
    source = tmp_path / "audio.ogg"
    source.write_bytes(b"fixture")
    anchors = STTResult(
        "ru",
        12,
        [
            TranscriptSegment("old1", 1, 5, "Ошибка распознавания."),
            TranscriptSegment("old2", 6, 10, "Новое СН."),
        ],
        "faster_whisper",
    )
    client = MagicMock()
    client.__enter__.return_value = client
    client.audio.transcriptions.create.side_effect = [
        SimpleNamespace(text="Компания на УСН."),
        *[SimpleNamespace(text="") for _ in range(empty_replies)],
        SimpleNamespace(text="НДС не применяется."),
    ]

    def extract(command, **kwargs):
        from pathlib import Path

        Path(command[-1]).write_bytes(b"audio fixture")

    with (
        patch("src.providers.stt.openai_provider.OpenAI", return_value=client),
        patch(
            "src.providers.stt.openai_provider.FasterWhisperSTTProvider.transcribe",
            new=AsyncMock(return_value=anchors),
        ),
        patch("src.providers.stt.openai_provider.subprocess.run", side_effect=extract),
    ):
        result = asyncio.run(
            OpenAISTTProvider(
                "test-key", "gpt-transcribe", settings=cfg
            )._chunked_contextual_transcribe(source, "ru")
        )
    assert [(s.start, s.end) for s in result.segments] == [(1, 5), (6, 10)]
    assert result.segments[0].text == "Компания на УСН."
    assert result.segments[0].words == []  # no fabricated word timestamps
    requests = client.audio.transcriptions.create.call_args_list
    assert requests[0].kwargs["extra_body"] == {"languages": ["ru"], "keywords": ["УСН", "НДС"]}
    assert "language" not in requests[0].kwargs
    assert "timestamp_granularities" not in requests[0].kwargs
    assert "Компания на УСН." not in requests[1].kwargs["prompt"]
    assert "Новое СН" not in requests[1].kwargs["prompt"]
    if empty_replies == 2:
        assert requests[-1].kwargs["model"] == "gpt-4o-transcribe"
        assert "extra_body" not in requests[-1].kwargs


def test_factory_passes_context():
    cfg = Settings(_env_file=None, stt_fallback_order="openai", stt_context="Программа 1С")
    provider = build_stt_chain(cfg)[0]
    assert provider.settings.stt_context == "Программа 1С"


def test_short_reply_gets_real_audio_context():
    units = [
        {"start": 84, "end": 85.5, "text": "Проверяем."},
        {"start": 85.5, "end": 90, "text": "В июле поступление."},
    ]
    assert [(s["start"], s["end"]) for s in merge_short_units(units)] == [(84, 90)]


def test_prompt_echo_is_not_a_transcription():
    prompt = "Учебная запись 1С о компании на УСН — упрощенной системе налогообложения."
    assert not valid_transcription(prompt, prompt, 1.5)
    assert not valid_transcription(prompt, prompt, 20)
    assert valid_transcription("Проверяем, компания находится на УСН.", prompt, 4)


def test_recognition_saves_model_without_confidence(tmp_path):
    from src.agents.speech_recognition_agent import run_speech_recognition
    from src.orchestrator.artifact_registry import ArtifactRegistry

    registry = ArtifactRegistry(tmp_path)
    raw = tmp_path / "raw.mp4"
    raw.write_bytes(b"fixture")
    registry.save_json("input_manifest.json", {"raw_video_path": str(raw)})
    result = STTResult("ru", 2, [TranscriptSegment("s", 0, 2, "На УСН")], "openai")
    with (
        patch("src.agents.speech_recognition_agent.extract_audio_ogg"),
        patch("src.agents.speech_recognition_agent.get_media_duration_seconds", return_value=2),
        patch(
            "src.agents.speech_recognition_agent.transcribe_with_fallback",
            new=AsyncMock(return_value=result),
        ),
    ):
        doc = run_speech_recognition(registry, Settings(_env_file=None), "test")
    assert "confidence_summary" not in doc
    assert "confidence" not in doc["segments"][0]
    assert registry.load_json("transcript.json")["segments"][0]["text"] == "На УСН"
