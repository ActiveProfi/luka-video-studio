import json

import pytest

from src.config import Settings
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services import contextual_pronunciation as service
from src.services.pronunciation_entities import extract_entities, validate_entity


@pytest.mark.parametrize(
    "source,spoken",
    [
        ("До 3,5 млн. рублей.", "трёх с половиной миллионов рублей"),
        ("Сумма 19 миллионов 300.", "девятнадцать миллионов триста тысяч"),
        ("Сумма 22 800 000 рублей.", "двадцать два миллиона восемьсот тысяч рублей"),
        ("На 31.07.2026 года.", "тридцать первое июля две тысячи двадцать шестого года"),
        ("С 2026 года.", "две тысячи двадцать шестого года"),
        ("В 1С.", "один эс"),
    ],
)
def test_contextual_forms_keep_values(source, spoken):
    targets = extract_entities({"id": 1, "subtitle": source}, [])
    assert len(targets) == 1
    validate_entity(targets[0], spoken)
    assert not targets[0]["expression"].endswith("рублей.")


@pytest.mark.parametrize(
    "source,spoken",
    [
        ("3,5 млн рублей", "три с половиной рубля"),
        ("31.07.2026", "тридцать первое июня две тысячи двадцать шестого года"),
        ("2026 года", "две тысячи двадцать седьмого года"),
        ("1С", "один смы"),
    ],
)
def test_reject_changed_meaning(source, spoken):
    with pytest.raises(ValueError):
        validate_entity(extract_entities({"id": 1, "subtitle": source}, [])[0], spoken)


def test_unknown_name_requires_second_check(tmp_path, monkeypatch):
    calls = []

    async def complete(settings, prompt, payload, *, validate_response):
        data = json.loads(payload)
        calls.append(data)
        if "targets" in data:
            raw = json.dumps(
                {"replacements": [{"id": data["targets"][0]["id"], "spoken": "фигма"}]}
            )
        else:
            raw = json.dumps({"checks": [{"id": data["terms"][0]["id"], "approved": False}]})
        validate_response(raw)
        return raw, "test"

    monkeypatch.setattr(service, "complete_with_fallback", complete)
    with pytest.raises(ValueError, match="проверку"):
        service.prepare_contextual_speech(
            [{"id": 1, "subtitle": "Открываем Figma"}], ArtifactRegistry(tmp_path), Settings()
        )
    assert len(calls) == 2
