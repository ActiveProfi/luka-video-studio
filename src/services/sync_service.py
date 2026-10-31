"""Анализ рассинхрона озвучки и смонтированного видео."""

from __future__ import annotations

from typing import Any


def build_sync_blocks(voiceover_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Блоки для ручной проверки синхронизации — по фрагментам озвучки."""
    blocks: list[dict[str, Any]] = []

    for idx, seg in enumerate(voiceover_segments, start=1):
        target_start = float(seg.get("target_start", 0))
        target_end = float(seg.get("target_end", target_start))
        slot = float(seg.get("target_slot_seconds", max(0.0, target_end - target_start)))
        audio_start = float(seg.get("audio_start", target_start))
        audio_end = float(seg.get("audio_end", audio_start))
        audio_duration = float(seg.get("audio_duration_seconds", max(0.0, audio_end - audio_start)))

        slot_gap = round(slot - audio_duration, 3)
        recommended = _recommended_offset(slot_gap, slot, audio_duration)

        blocks.append(
            {
                "block_id": str(seg.get("transcript_segment_id") or seg.get("segment_id") or f"block_{idx}"),
                "block_index": idx,
                "segment_id": str(seg.get("segment_id", "")),
                "transcript_segment_id": str(seg.get("transcript_segment_id", "")),
                "target_start": round(target_start, 3),
                "target_end": round(target_end, 3),
                "target_slot_seconds": round(slot, 3),
                "audio_start": round(audio_start, 3),
                "audio_end": round(audio_end, 3),
                "audio_duration_seconds": round(audio_duration, 3),
                "slot_gap_seconds": slot_gap,
                "recommended_offset_seconds": recommended,
                "offset_adjustment_seconds": recommended,
                "text": str(seg.get("text", "")).strip(),
                "sync_note": _sync_note(slot_gap, audio_duration, slot),
                "user_comment": "",
            }
        )
    return blocks


def global_audio_offset(blocks: list[dict[str, Any]]) -> float:
    """Суммарный сдвиг аудиодорожки для превью/сборки."""
    if not blocks:
        return 0.0
    values = [float(b.get("offset_adjustment_seconds", 0)) for b in blocks]
    return round(sum(values) / len(values), 3)


def _recommended_offset(slot_gap: float, slot: float, audio_duration: float) -> float:
    """Если озвучка короче слота — чуть задержать старт; если длиннее — сдвинуть раньше."""
    if slot <= 0:
        return 0.0
    if slot_gap > 1.0:
        return round(min(2.0, slot_gap * 0.25), 3)
    if slot_gap < -1.0:
        return round(max(-2.0, slot_gap * 0.25), 3)
    if audio_duration > slot + 0.5:
        return round(max(-1.5, (slot - audio_duration) * 0.15), 3)
    return 0.0


def _sync_note(slot_gap: float, audio_duration: float, slot: float) -> str:
    if abs(slot_gap) <= 0.5:
        return "Слот и длительность озвучки близки — проверьте совпадение действий на экране."
    if slot_gap > 0.5:
        return (
            f"Озвучка короче слота на {slot_gap:.1f} с — речь может опережать или отставать от картинки."
        )
    return (
        f"Озвучка длиннее слота на {abs(slot_gap):.1f} с — фраза может не уложиться в действие на экране."
    )
