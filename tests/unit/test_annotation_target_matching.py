from decimal import Decimal
from unittest.mock import patch

from src.services.annotation_target_matching import (
    candidates,
    money_value,
    outside_arrow,
    phrase_focus,
    read_money,
)


def test_amount_reading_preserves_scale_and_decimal_separators():
    assert money_value("3,5 миллиона рублей") == Decimal("3500000")
    assert money_value("22 миллиона 800 тысяч") == Decimal("22800000")
    assert read_money("3 500 000 00") == Decimal("3500000")
    assert read_money("500 000,00") == Decimal("500000")
    assert read_money("31.07.2026") is None


def test_missing_leading_digit_requires_a_new_ocr_observation(tmp_path):
    seed = {"text": "500 000,00", "bbox": {"x": 0.2, "y": 0.2, "width": 0.1, "height": 0.03}}
    ann = {"label": "3,5 миллиона рублей"}
    with patch("src.services.annotation_target_matching.zoom_boxes", return_value=[]):
        assert candidates(None, [seed], ann, tmp_path) == []
    full = {**seed, "text": "3 500 000 00"}
    with patch("src.services.annotation_target_matching.zoom_boxes", return_value=[full]):
        assert candidates(None, [seed], ann, tmp_path) == [full]


def test_confirmation_is_timed_after_checkbox_in_same_phrase():
    voice = {
        "audio_start": 10,
        "audio_end": 18,
        "subtitle_text": "Ставим НДС. Указываем месяц. Нажимаем ОК.",
    }
    nds = {"label": "Клавиша НДС", "target_start": 10, "target_end": 25}
    ok = {**nds, "label": "Нажимаем ОК"}
    assert phrase_focus(ok, voice) > phrase_focus(nds, voice) + 3


def test_arrow_does_not_cross_target_label():
    b = {"x": 0.3, "y": 0.2, "width": 0.1, "height": 0.03}
    ann = {
        "type": "arrow",
        "placement_confirmed": True,
        "visual_evidence": [{"time": 1, "anchor": b}, {"time": 2, "anchor": b}],
    }
    result = outside_arrow(ann)
    assert result["anchor"]["x"] > b["x"] + b["width"]
    assert result["arrow_direction"] == "left"

def test_menu_and_tab_prefixes_match_visible_labels(tmp_path):
    box={'text':'Формат','ocr_confidence':0.99,'bbox':{'x':0.13,'y':0.03,'width':0.04,'height':0.03}}
    for label in ['Меню "Формат"','Пункт меню «Формат»','Закладка «Формат»']:
        assert candidates(None,[box],{'label':label},tmp_path)==[box]
