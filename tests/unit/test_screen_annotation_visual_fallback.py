import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from src.services.screen_annotation_service import locate_screen_annotations


def test_ocr_miss_uses_pixels_and_context_before_automatic_decision(tmp_path):
    ann = {"annotation_id": "plus", "label": "Нажимаем плюс", "speech_context": "В источниках добавим окно", "type": "arrow", "target_start": 1, "target_end": 2, "speech_cue": {"start": 1, "end": 2}, "timing_required": True}
    observations = [{"time": t, "visible": True, "bbox": {"x": .2, "y": .3, "width": .03, "height": .03}, "confidence": .99, "evidence": "Plus icon in Sources toolbar"} for t in (1.05, 1.5, 1.95)]
    client = MagicMock()
    client.chat.completions.create.return_value.choices[0].message.content = json.dumps({"observations": observations})
    registry = MagicMock(job_dir=tmp_path)
    settings = SimpleNamespace(openai_api_key="test", screen_analysis_model="test", screen_annotation_auto_confidence=.92)
    with patch("src.services.voice_word_timing.ensure_voice_word_timing", return_value={}), patch("src.services.voice_word_timing.bind_spoken_cues", return_value=[ann]), patch("src.services.voice_word_timing.save_annotation_timing_report"), patch("src.services.screen_annotation_service.OpenAI", return_value=client), patch("importlib.util.find_spec", return_value=True), patch("src.services.annotation_recovery.recover_annotations", return_value=[ann]), patch("src.services.grounded_screen_annotations.locate_grounded", return_value=[ann]), patch("src.services.screen_annotation_service.extract_frame", return_value=np.zeros((100, 100, 3), dtype=np.uint8)), patch("src.services.lesson_options_service.load_options", return_value=SimpleNamespace(automatic=True)):
        result = locate_screen_annotations(tmp_path / "source.mp4", [ann], registry, settings, [])
    assert result[0]["placement_confirmed"]
    content = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert sum(item["type"] == "image_url" for item in content) == 3
    assert "В источниках" in content[0]["text"]
