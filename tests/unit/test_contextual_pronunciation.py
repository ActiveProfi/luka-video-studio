import json

import pytest

from src.config import Settings
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services import contextual_pronunciation as service


def test_choice_and_governed_case_are_resolved_in_full_context(tmp_path, monkeypatch):
    blocks = [
        {"id": 1, "subtitle": "Сначала проверим, какой режим применяется."},
        {"id": 2, "subtitle": "Нам нужно выбрать ставку 5, 7 или 22% НДС."},
        {"id": 3, "subtitle": "Затем считаем по ставке 7%."},
    ]
    calls = []

    async def complete(settings, prompt, payload, *, validate_response):
        data = json.loads(payload)
        assert len(data["context"]) == 3
        assert data["context"][0]["text"] == blocks[0]["subtitle"]
        calls.append(data)
        raw = json.dumps(
            {
                "replacements": [
                    {
                        "id": "2:0",
                        "spoken": "пять, семь или двадцать два процента",
                        "reason": "Выбор варианта",
                    },
                    {
                        "id": "3:0",
                        "spoken": "семи процентов",
                        "reason": "Управление: по ставке чего",
                    },
                ]
            }
        )
        validate_response(raw)
        return raw, "test"

    monkeypatch.setattr(service, "complete_with_fallback", complete)
    registry = ArtifactRegistry(tmp_path)
    result = service.prepare_contextual_speech(blocks, registry, Settings())
    assert result["2"] == "Нам нужно выбрать ставку пять, семь или двадцать два процента эн дэ эс."
    assert result["3"] == "Затем считаем по ставке семи процентов."
    assert blocks[1]["subtitle"] == "Нам нужно выбрать ставку 5, 7 или 22% НДС."
    assert service.prepare_contextual_speech(blocks, registry, Settings()) == result
    assert len(calls) == 1
    blocks[0]["subtitle"] = "Теперь обсуждаем иной режим."
    # A changed neighboring sentence must invalidate cached decisions.
    service.prepare_contextual_speech(blocks, registry, Settings())
    assert len(calls) == 2


@pytest.mark.parametrize(
    "spoken",
    [
        "пять, семь или двадцать процентов",
        "семь, пять или двадцать два процента",
        "пять, семь или двадцать два миллиона процентов",
        "пять, семь или двадцать два",
        "не пять, семь или двадцать два процента",
    ],
)
def test_editor_cannot_change_values_order_units_or_negation(spoken):
    targets = [{"id": "1:0", "values": [5, 7, 22]}]
    with pytest.raises(ValueError):
        service.validate_replacements(
            json.dumps({"replacements": [{"id": "1:0", "spoken": spoken}]}), targets
        )


def test_valid_inflected_reading_preserves_same_values():
    assert service.spoken_values("пяти, семи или двадцати двух процентов") == [5, 7, 22]
    assert service.spoken_values("одиннадцати процентов") == [11]


def test_explicit_choice_requires_alternative_connector():
    target = {"id": "1:0", "values": [5, 7, 22], "context_role": "choice"}
    raw = json.dumps(
        {"replacements": [{"id": "1:0", "spoken": "пять, семь и двадцать два процента"}]}
    )
    with pytest.raises(ValueError, match="Выбор"):
        service.validate_replacements(raw, [target])


def test_no_model_call_for_text_without_target_expressions(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No contextual percentage work required")

    monkeypatch.setattr(service, "complete_with_fallback", forbidden)
    result = service.prepare_contextual_speech(
        [{"id": 1, "subtitle": "В 1С смотрим отчёт."}], ArtifactRegistry(tmp_path), Settings()
    )
    assert result["1"] == "В один эс смотрим отчёт."
