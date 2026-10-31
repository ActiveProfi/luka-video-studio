from types import SimpleNamespace

import pytest

from src.config import Settings
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services import promo_speech_service as service


def test_alignment_preserves_measured_variable_pauses():
    phrases = ["Проверяем доходы.", "Выбираем ставку.", "Открываем урок."]
    words = [
        {"word": word, "start": start, "end": end}
        for word, start, end in [
            ("Проверяем", 0.1, 0.5),
            ("доходы", 0.5, 1),
            ("Выбираем", 1.3, 1.7),
            ("ставку", 1.7, 2),
            ("Открываем", 2.55, 3),
            ("урок", 3, 3.5),
        ]
    ]
    cues = service.align_sentences(phrases, phrases, words, 3.6)
    assert cues[0]["start"] == 0
    assert cues[1]["start"] - cues[0]["end"] == pytest.approx(0.3)
    assert cues[2]["start"] - cues[1]["end"] == pytest.approx(0.55)
    with pytest.raises(ValueError):
        service.align_sentences(phrases, phrases, words[:2], 3.6)


def test_alignment_accepts_original_spelling_of_pronunciation_hints():
    texts = ["Выберите Very Fast.", "OBS Studio готова."]
    spoken = ["Выберите Вери Фаст.", "ОБС Студио готова."]
    words = [{"word": word, "start": i, "end": i + .7} for i, word in enumerate("Выберите Very Fast OBS Studio готова".split())]
    cues = service.align_sentences(texts, spoken, words, 6)
    assert cues[1]["start"] == 3
    assert cues[1]["end"] == 5.7
    with pytest.raises(ValueError):
        service.align_sentences(texts, spoken, words[:2], 6)


def test_connected_synthesis_is_cached_even_after_alignment_failure(tmp_path, monkeypatch):
    from src.services import auto_voiceover_service, contextual_pronunciation

    calls = []

    def synthesize(text, path, *args):
        calls.append(text)
        path.write_bytes(b"test audio")
        return 4.0, "test"

    monkeypatch.setattr(auto_voiceover_service, "_synthesize", synthesize)
    monkeypatch.setattr(
        contextual_pronunciation,
        "prepare_contextual_speech",
        lambda blocks, *a: {str(b["id"]): b["subtitle"] for b in blocks},
    )
    monkeypatch.setattr(
        service, "measure_sentences", lambda *a: (_ for _ in ()).throw(ValueError("timing"))
    )
    registry = ArtifactRegistry(tmp_path)
    settings = Settings()
    draft = SimpleNamespace(narration=["Проверим доходы?", "Откройте урок"])
    with pytest.raises(ValueError, match="timing"):
        service.create_connected_speech(draft, registry, settings, settings)
    monkeypatch.setattr(
        service,
        "measure_sentences",
        lambda *a: [
            {"start": 0, "end": 1.5, "text": draft.narration[0]},
            {"start": 2, "end": 4, "text": draft.narration[1]},
        ],
    )
    duration, cues = service.create_connected_speech(draft, registry, settings, settings)
    assert calls == ["Проверим доходы? Откройте урок."]
    assert duration == 4 and cues[1]["start"] == 2
    assert registry.load_json("prosody-report.json")["artificial_gaps"] is False
