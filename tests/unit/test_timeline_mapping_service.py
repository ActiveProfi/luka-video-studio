"""Тесты преобразования timeline."""

from src.services.timeline_mapping_service import map_source_interval_to_target, map_source_time_to_target

TIMELINE = [
    {
        "segment_index": 0,
        "source_start": 0.0,
        "source_end": 10.0,
        "target_start": 0.0,
        "target_end": 10.0,
        "transform": "keep",
    },
    {
        "segment_index": 1,
        "source_start": 10.0,
        "source_end": 12.0,
        "target_start": 10.0,
        "target_end": 10.0,
        "transform": "removed",
    },
    {
        "segment_index": 2,
        "source_start": 12.0,
        "source_end": 20.0,
        "target_start": 10.0,
        "target_end": 18.0,
        "transform": "keep",
    },
]


def test_map_source_time_skips_removed():
    assert map_source_time_to_target(11.0, TIMELINE) == 10.0
    assert map_source_time_to_target(15.0, TIMELINE) == 13.0


def test_map_source_interval():
    start, end, slot = map_source_interval_to_target(0.0, 10.0, TIMELINE)
    assert start == 0.0
    assert end == 10.0
    assert slot == 10.0

    start, end, slot = map_source_interval_to_target(8.0, 15.0, TIMELINE)
    assert start == 8.0
    assert end == 13.0
    assert slot == 5.0
