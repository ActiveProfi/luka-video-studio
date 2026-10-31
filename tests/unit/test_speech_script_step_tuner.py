"""Тесты точной доводки Speech Script под бюджет шагов."""

from src.services.segment_timing_service import count_timing_steps
from src.services.speech_script_step_tuner import (
    fine_tune_to_exact_steps,
    is_timing_edit_faithful,
    timing_retry_hint_preserve_speech,
)


def test_fine_tune_preserves_abbreviation_spelling() -> None:
    text = "Открываем документ эн дэ эс в один эс и проводим."
    budget = count_timing_steps(text) + 5
    fitted = fine_tune_to_exact_steps(text, budget)
    assert count_timing_steps(fitted) == budget
    assert "эн дэ эс" in fitted
    assert "один эс" in fitted
    assert "НДС" not in fitted
    assert "1С" not in fitted
    assert is_timing_edit_faithful(text, fitted)


def test_fine_tune_shortens_without_collapsing_tts() -> None:
    text = (
        "Сейчас также открываем документ эн дэ эс в один эс и далее проводим операцию."
    )
    budget = count_timing_steps(text) - 8
    assert budget > 10
    fitted = fine_tune_to_exact_steps(text, budget)
    assert count_timing_steps(fitted) == budget
    assert "эн дэ эс" in fitted
    assert "один эс" in fitted


def test_rejects_invented_ending() -> None:
    draft = "Открываем документ эн дэ эс в один эс и проводим."
    invented = (
        draft
        + " Далее обязательно сохраните изменения и закройте программу полностью."
    )
    assert not is_timing_edit_faithful(draft, invented)


def test_timing_retry_hint_forbids_new_sentences() -> None:
    hint = timing_retry_hint_preserve_speech(100, 80)
    assert "новые предложения" in hint
    assert "финал" in hint
