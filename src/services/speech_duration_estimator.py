"""Этап 3.5: детерминированная оценка длительности речи."""

from __future__ import annotations

import re

from src.config import Settings
from src.services.segment_timing_service import count_timing_steps
from src.services.tts_preparation_types import TextChange

DEFAULT_THRESHOLD_MS = 500

PROVIDER_STEP_SECONDS = {
    "yandex": 0.075,
    "openai": 0.07,
    "elevenlabs": 0.072,
}


def estimate_speech_duration(text: str, tts_provider: str = "yandex") -> float:
    """Грубая, но стабильная оценка длительности произнесения текста."""
    cleaned = str(text or "").strip()
    if not cleaned:
        return 0.0

    provider = (tts_provider or "yandex").strip().lower()
    step_seconds = PROVIDER_STEP_SECONDS.get(provider, PROVIDER_STEP_SECONDS["yandex"])
    steps = count_timing_steps(cleaned)

    sentence_pauses = len(re.findall(r"[.!?]", cleaned)) * 0.18
    comma_pauses = len(re.findall(r"[,;:]", cleaned)) * 0.08
    return round((steps * step_seconds) + sentence_pauses + comma_pauses, 3)


def compare_duration(
    original_text: str,
    edited_text: str,
    *,
    tts_provider: str = "yandex",
    threshold_ms: int = DEFAULT_THRESHOLD_MS,
) -> dict[str, float | str | bool]:
    original = estimate_speech_duration(original_text, tts_provider)
    edited = estimate_speech_duration(edited_text, tts_provider)
    diff = round(edited - original, 3)
    within = abs(diff) <= threshold_ms / 1000
    return {
        "original_duration_seconds": original,
        "edited_duration_seconds": edited,
        "duration_diff_seconds": diff,
        "budget_status": "within_budget" if within else "needs_review",
        "within_budget": within,
    }


def is_within_budget(diff_seconds: float, threshold_ms: int = DEFAULT_THRESHOLD_MS) -> bool:
    return abs(float(diff_seconds)) <= threshold_ms / 1000


def attach_duration_report(
    changes: list[TextChange],
    settings: Settings,
    *,
    threshold_ms: int = DEFAULT_THRESHOLD_MS,
) -> list[TextChange]:
    for change in changes:
        report = compare_duration(
            change.before,
            change.after,
            tts_provider=settings.tts_provider,
            threshold_ms=threshold_ms,
        )
        change.original_duration_seconds = float(report["original_duration_seconds"])
        change.edited_duration_seconds = float(report["edited_duration_seconds"])
        change.duration_diff_seconds = float(report["duration_diff_seconds"])
        change.budget_status = str(report["budget_status"])
    return changes
