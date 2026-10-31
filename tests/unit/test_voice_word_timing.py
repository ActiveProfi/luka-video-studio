from src.services.screen_annotation_service import accept_observations
from src.services.speech_script_auto import build_speech_text
from src.services.voice_word_timing import find_spoken_cue, speech_tokens


def test_contextual_control_label_matches_without_identical_action_phrase():
    words = [{"word": word, "start": i, "end": i + .5} for i, word in enumerate(["Выбираем", "здесь", "захват", "окна"])]
    assert find_spoken_cue({"label": "Выбираем захват окна"}, words)["start"] == 2
    words = [{"word": word, "start": i, "end": i + .5} for i, word in enumerate(["Вкладка", "Audio"])]
    assert find_spoken_cue({"label": "Переходим во вкладку Аудио"}, words)["start"] == 1
    words = [{"word": "расширенная", "start": 8, "end": 9}]
    assert find_spoken_cue({"label": "Переходим во вкладку расширенные"}, words)["start"] == 8
    words = [{"word": "плюс", "start": 12, "end": 12.5}]
    assert find_spoken_cue({"label": "Источники плюс"}, words)["start"] == 12


def test_measured_cue_replaces_model_window_ending_before_action():
    from src.services.voice_word_timing import bind_spoken_cues
    ann = {"label": "Вкладка Аудио", "linked_segment_id": "s", "target_start": 1, "target_end": 3}
    timing = {"segments": [{"segment_id": "s", "words": [{"word": "audio", "start": 8, "end": 9}]}]}
    bound = bind_spoken_cues([ann], timing)[0]
    assert bound["target_start"] == 8
    assert bound["target_end"] == 9.35


def test_1c_is_pronounced_as_a_name_in_current_speech_pipeline():
    for name in ("1С", "1C", "1с", "1c"):
        assert build_speech_text(f"В {name} мы смотрим") == "В один эс мы смотрим"
    assert build_speech_text("Код 11С") == "Код 11С"


def test_dictionary_and_word_boundary_reach_yandex_without_changing_subtitles():
    from src.config import Settings
    from src.services.tts_normalization_rules import prepare_provider_speech_text

    subtitle = "В 1C мы смотрим"
    prepared = prepare_provider_speech_text(subtitle, Settings(), "yandex")
    assert prepared == "В один эс sil<[100]> мы смотрим"
    assert prepare_provider_speech_text(prepared, Settings(), "yandex") == prepared
    assert subtitle == "В 1C мы смотрим"


def test_action_context_disambiguates_repeated_abbreviation():
    words = [
        {"word": w, "start": t, "end": t + 0.4}
        for t, w in enumerate(["Ставим", "клавишу", "nds", "будем", "применять", "nds"])
    ]
    assert find_spoken_cue({"label": "Клавиша НДС"}, words)["start"] == 1


def test_numbers_match_measured_words_without_spreading_time_over_sentence():
    words = [
        {"word": "Доходы", "start": 55, "end": 55.4},
        {"word": "составили", "start": 55.4, "end": 56},
        {"word": "22", "start": 58.2, "end": 58.9},
        {"word": "миллиона", "start": 58.9, "end": 59.3},
        {"word": "800", "start": 59.3, "end": 59.9},
        {"word": "тысяч", "start": 59.9, "end": 60.2},
    ]
    cue = find_spoken_cue({"label": "22 миллиона 800 тысяч"}, words)
    assert cue["start"] == 58.2
    assert cue["end"] == 60.2
    assert find_spoken_cue({"label": "22 миллиона 300 тысяч"}, words) is None


def test_ambiguous_repeated_label_is_not_assigned_first_occurrence():
    words = [{"word": "НДС", "start": 2, "end": 3}, {"word": "НДС", "start": 7, "end": 8}]
    assert find_spoken_cue({"label": "НДС"}, words) is None


def test_natural_half_amount_normalizes_for_matching():
    assert speech_tokens("3,5 миллиона рублей") == speech_tokens("три с половиной миллиона рублей")


def test_visual_evidence_cannot_override_spoken_start():
    ann = {"speech_cue": {"start": 60, "end": 61}, "timing_required": True}
    assert not accept_observations(ann, [], [59.4, 59.8, 60.2], 0.9)["placement_confirmed"]
    assert not accept_observations({"timing_required": True}, [], [], 0.9)["placement_confirmed"]


def test_recovery_only_searches_inside_spoken_interval(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from src.services import annotation_recovery as recovery
    from src.services import grounded_screen_annotations as grounded

    registry = Mock(job_dir=tmp_path)
    registry.load_json.return_value = {"segments": []}
    box = {"text": "Доходы", "bbox": {"x": 0.2, "y": 0.2, "width": 0.1, "height": 0.05}}
    monkeypatch.setattr(recovery, "extract_frame", lambda *_: None)
    monkeypatch.setattr(recovery, "candidates", lambda *_args, **_kwargs: [box])
    monkeypatch.setattr(grounded, "read_boxes", lambda *_: [box])

    def verify(video, observation, start, end):
        assert start >= 49.62
        assert end <= 51.35
        return [{**observation, "time": start + d} for d in (0.01, 0.2, 0.4, 0.6, 0.8)]

    monkeypatch.setattr(grounded, "verify_local_hold", verify)
    ann = {
        "label": "Доходы",
        "target_start": 45,
        "target_end": 54,
        "speech_cue": {"start": 49.62, "end": 51},
        "timing_required": True,
    }
    result = recovery.recover_annotations(
        "video", [ann], registry, SimpleNamespace(screen_annotation_auto_confidence=0.9)
    )[0]
    assert result["placement_confirmed"]
    assert result["target_start"] >= 49.62


def test_tracking_cannot_override_a_new_clearly_read_amount():
    import numpy as np

    from src.services.annotation_target_matching import track_recognized_box

    frame = np.random.default_rng(3).integers(0, 255, (100, 100, 3), dtype=np.uint8)
    box = {"text": "19 300 000,00", "bbox": {"x": 0.2, "y": 0.2, "width": 0.4, "height": 0.2}}
    changed = {**box, "text": "22 800 000,00", "ocr_confidence": 0.99}
    assert not track_recognized_box(frame, frame, box, numeric=True, current_boxes=[changed])
