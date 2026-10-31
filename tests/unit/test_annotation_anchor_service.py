"""Тесты OCR-привязки аннотаций."""

from unittest.mock import patch

import numpy as np
import pytest

from src.services.annotation_anchor_service import _label_queries, refine_annotation_anchors


def test_label_queries_extracts_menu_and_nds():
    queries = _label_queries('Меню «Налоги и отчёты» по НДС')
    assert "Меню «Налоги и отчёты» по НДС" in queries
    assert "Налоги и отчёты" in queries
    assert any("ндс" in q.lower() for q in queries)


def test_refine_uses_ocr_hit(tmp_path):
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"fake")

    ann = {
        "annotation_id": "ann_001",
        "type": "highlight_rect",
        "target_start": 1.0,
        "target_end": 3.0,
        "label": "Отчёты",
        "anchor": {"x": 0.5, "y": 0.5, "width": 0.2, "height": 0.1},
    }

    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)

    def fake_ocr(frame_bgr, query):
        return [
            {
                "text": "Отчёты",
                "x": 120,
                "y": 80,
                "width": 180,
                "height": 32,
                "confidence": 0.93,
                "engine": "test",
            }
        ]

    with patch("src.services.annotation_anchor_service.video_size", return_value=(1920, 1080)):
        with patch("src.services.annotation_anchor_service.extract_frame", return_value=frame):
            with patch("src.services.annotation_anchor_service._pick_ocr_engine", return_value=fake_ocr):
                refined = refine_annotation_anchors(video, [ann])

    assert refined[0]["anchor_source"] == "ocr"
    assert refined[0]["anchor"]["x"] < 0.2
    assert refined[0]["ocr_text"] == "Отчёты"
