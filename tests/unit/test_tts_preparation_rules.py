"""Тесты детерминированных правил подготовки текста к TTS."""

from src.config import Settings
from src.services.accounting_terms_rules import apply_accounting_term_rules
from src.services.speech_duration_estimator import compare_duration, estimate_speech_duration
from src.services.text_cleanup_rules import clean_technical_noise
from src.services.tts_normalization_rules import apply_tts_normalization_rules


def test_clean_technical_noise_removes_fillers_only() -> None:
    text, changes = clean_technical_noise("эээ ну открываем   документ")
    assert text == "открываем документ"
    assert len(changes) >= 2


def test_accounting_terms_rules_from_assets() -> None:
    text, changes = apply_accounting_term_rules("открываем ндс и счет фактура", Settings())
    assert "НДС" in text
    assert "счёт-фактура" in text
    assert len(changes) == 2


def test_tts_normalization_uses_provider_rules() -> None:
    text, changes = apply_tts_normalization_rules("НДС в 1С № 5", Settings())
    assert "эн дэ эс" in text
    assert "один эс" in text
    assert "номер" in text
    assert len(changes) >= 3


def test_duration_estimator_reports_budget_status() -> None:
    short = estimate_speech_duration("НДС", "yandex")
    long = estimate_speech_duration("налог на добавленную стоимость", "yandex")
    assert long > short
    report = compare_duration("НДС", "эн дэ эс", tts_provider="yandex")
    assert report["budget_status"] == "within_budget"
