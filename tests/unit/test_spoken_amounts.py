import pytest

from src.services.speech_script_auto import build_speech_text
from src.services.spoken_amounts import normalize_spoken_amounts
from src.services.text_cleanup_rules import clean_technical_noise


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("3,5 млн. рублей", "три с половиной миллиона рублей"),
        ("3, 5 миллиона рублей", "три с половиной миллиона рублей"),
        ("1.5 млн рублей", "один с половиной миллион рублей"),
        ("2,5 тыс. рублей", "две с половиной тысячи рублей"),
        ("19,3 млн рублей", "девятнадцать миллионов триста тысяч рублей"),
        ("22,8 миллиона рублей", "двадцать два миллиона восемьсот тысяч рублей"),
        ("0,5 млн рублей", "пятьсот тысяч рублей"),
        ("1,000001 млн рублей", "один миллион один рубль"),
        ("0 млн рублей", "ноль рублей"),
    ],
)
def test_amounts_preserve_scale_and_value(source, expected):
    assert normalize_spoken_amounts(source) == expected
    assert build_speech_text(source) == expected


def test_unrelated_numbers_and_precise_fraction_are_not_reinterpreted():
    for source in ("Ставки 3, 5 и 7 процентов", "Версия 3.5", "06.10.2026", "0,0000001 млн рублей"):
        assert normalize_spoken_amounts(source) == source


def test_grammar_in_both_script_and_speech():
    source = "Месяцом превышения будет июль, месяцом применения — август."
    assert "месяцом" not in build_speech_text(source).lower()
    cleaned, changes = clean_technical_noise(source)
    assert cleaned.startswith("Месяцем превышения")
    assert changes
