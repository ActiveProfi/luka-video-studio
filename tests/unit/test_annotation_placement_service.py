"""Тесты сохранения координат аннотаций пользователем."""

from src.services.annotation_placement_service import normalize_placement_payload


def test_normalize_arrow_placement():
    result = normalize_placement_payload(
        {"type": "arrow", "x": 0.5, "y": 0.3, "arrow_direction": "top"}
    )
    assert result["placement_confirmed"] is True
    assert result["anchor"]["x"] == 0.5
    assert result["arrow_direction"] == "top"


def test_normalize_frame_placement():
    result = normalize_placement_payload(
        {"type": "frame", "x": 0.1, "y": 0.2, "width": 0.3, "height": 0.1}
    )
    assert result["type"] == "highlight_rect"
    assert result["anchor"]["width"] == 0.3


def test_skip_placement():
    result = normalize_placement_payload({"type": "arrow", "skipped": True})
    assert result["skipped"] is True
    assert result["placement_confirmed"] is False
