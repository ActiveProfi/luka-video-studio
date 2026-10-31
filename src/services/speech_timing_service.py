"""Оценка длительности речи для тайм-блоков ручного редактирования текста."""

from __future__ import annotations

# Запасной темп русской речи, если нет эталона в блоке (~13.5 символов/с)
DEFAULT_CHARS_PER_SECOND = 13.5


def segment_slot_seconds(start: float, end: float) -> float:
    return round(max(0.0, float(end) - float(start)), 3)


def estimate_speech_seconds(
    text: str,
    *,
    reference_text: str = "",
    reference_seconds: float = 0.0,
    chars_per_second: float | None = None,
) -> float:
    """Оценить длительность произнесения текста (до реального TTS)."""
    cleaned = str(text or "").strip()
    if not cleaned:
        return 0.0

    ref = str(reference_text or "").strip()
    ref_seconds = float(reference_seconds or 0)
    if ref and ref_seconds > 0:
        rate = ref_seconds / max(1, len(ref))
        return round(len(cleaned) * rate, 3)

    rate = float(chars_per_second or DEFAULT_CHARS_PER_SECOND)
    return round(len(cleaned) / rate, 3)


def build_segment_timing_info(
    start: float,
    end: float,
    text: str,
    *,
    original_text: str = "",
) -> dict[str, float | bool]:
    """Бюджет блока и превышение относительно исходного тайминга."""
    slot = segment_slot_seconds(start, end)
    original = str(original_text or "").strip()
    estimated = estimate_speech_seconds(
        text,
        reference_text=original or text,
        reference_seconds=slot if original else 0.0,
    )
    margin = round(slot - estimated, 1)
    exceeds = round(max(0.0, estimated - slot), 1)
    return {
        "slot_seconds": slot,
        "estimated_speech_seconds": estimated,
        "timing_margin_seconds": margin,
        "exceeds_by_seconds": exceeds,
        "timing_exceeded": exceeds > 0.05,
    }
