"""Преобразование source-таймкодов в target по timeline_map."""

from __future__ import annotations


def map_source_time_to_target(time: float, timeline_segments: list[dict]) -> float:
    """Перевести секунду исходного видео в секунду смонтированного."""
    if not timeline_segments:
        return max(0.0, time)

    ordered = sorted(timeline_segments, key=lambda s: float(s.get("source_start", 0)))
    if time <= float(ordered[0]["source_start"]):
        return float(ordered[0]["target_start"])

    for seg in ordered:
        source_start = float(seg["source_start"])
        source_end = float(seg["source_end"])
        target_start = float(seg["target_start"])
        target_end = float(seg["target_end"])
        transform = seg.get("transform", "keep")

        if time < source_start:
            continue
        if time > source_end:
            continue

        if transform == "removed":
            return target_start

        source_len = max(0.001, source_end - source_start)
        target_len = max(0.0, target_end - target_start)
        ratio = (time - source_start) / source_len
        return target_start + ratio * target_len

    return float(ordered[-1]["target_end"])


def map_source_interval_to_target(
    source_start: float,
    source_end: float,
    timeline_segments: list[dict],
) -> tuple[float, float, float]:
    """Вернуть (target_start, target_end, slot_seconds) для интервала исходника."""
    target_start = map_source_time_to_target(source_start, timeline_segments)
    target_end = map_source_time_to_target(source_end, timeline_segments)
    if target_end < target_start:
        target_end = target_start
    return round(target_start, 3), round(target_end, 3), round(max(0.0, target_end - target_start), 3)
