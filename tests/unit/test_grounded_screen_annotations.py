import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.services.grounded_screen_annotations import (
    disambiguate_amount,
    locate_grounded,
    verify_local_hold,
)


def test_repeated_amount_is_grounded_to_income_not_net_income():
    label = {"text": "Доходы", "bbox": {"x": 0.25, "y": 0.2, "width": 0.05, "height": 0.02}}
    income = {
        "text": "19 300 000,00",
        "bbox": {"x": 0.25, "y": 0.23, "width": 0.05, "height": 0.02},
    }
    net = {"text": "19 300 000,00", "bbox": {"x": 0.25, "y": 0.4, "width": 0.05, "height": 0.02}}
    assert disambiguate_amount(net, [label, income, net], "Доходы за полугодие") == income
    assert disambiguate_amount(net, [net], "Доходы за полугодие") is None


def test_disappearing_text_never_gets_a_hold():
    frame = np.random.default_rng(4).integers(0, 255, (100, 100, 3), dtype=np.uint8)
    observation = {"time": 2, "bbox": {"x": 0.1, "y": 0.1, "width": 0.4, "height": 0.2}}
    with patch(
        "src.services.grounded_screen_annotations.extract_frame",
        side_effect=[frame] + [np.zeros_like(frame)] * 20,
    ):
        assert verify_local_hold("video", observation, 1, 4) == []


def test_stationary_text_gets_five_local_witnesses():
    frame = np.random.default_rng(4).integers(0, 255, (100, 100, 3), dtype=np.uint8)
    observation = {"time": 2, "bbox": {"x": 0.1, "y": 0.1, "width": 0.4, "height": 0.2}}
    with patch("src.services.grounded_screen_annotations.extract_frame", return_value=frame):
        witnesses = verify_local_hold("video", observation, 1, 4)
    assert len(witnesses) == 5
    assert witnesses[-1]["time"] - witnesses[0]["time"] == pytest.approx(1.2)


@pytest.mark.parametrize("box_id,confirmed", [(0, True), (99, False), (None, False)])
def test_only_existing_ocr_coordinates_can_be_used(tmp_path, box_id, confirmed):
    registry = MagicMock(job_dir=tmp_path)
    settings = SimpleNamespace(screen_analysis_model="test", screen_annotation_auto_confidence=0.92)
    client = MagicMock()

    def complete(**kwargs):
        frames = json.loads(kwargs["messages"][1]["content"])["frames"]
        content = json.dumps(
            {
                "observations": [
                    {
                        "time": f["time"],
                        "box_id": box_id,
                        "selected_text": "Создать",
                        "confidence": 0.99,
                        "evidence": "Кнопка Создать",
                    }
                    for f in frames
                ]
            }
        )
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    client.chat.completions.create.side_effect = complete
    boxes = [
        {"id": 0, "text": "Создать", "bbox": {"x": 0.1, "y": 0.2, "width": 0.1, "height": 0.04}}
    ]
    ann = {"label": "Создать", "type": "highlight_rect", "target_start": 1, "target_end": 5}
    with (
        patch("src.services.grounded_screen_annotations.extract_frame"),
        patch("src.services.grounded_screen_annotations.read_boxes", return_value=boxes),
        patch("src.services.grounded_screen_annotations.verify_local_hold", return_value=[]),
    ):
        result = locate_grounded("video", [ann], registry, settings, client)[0]
    assert result["placement_confirmed"] == confirmed
    if confirmed:
        assert result["anchor"] == boxes[0]["bbox"]
