"""Этап 3.1: техническая очистка текста без LLM."""

from __future__ import annotations

import re

from src.services.spoken_amounts import correct_known_grammar
from src.services.tts_preparation_types import TextChange

FILLER_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bэ[\-э\s]*э+\b", "речевой мусор"),
    (r"\bа[\-а\s]*а+\b", "речевой мусор"),
    (r"\bм[\-м\s]*м+\b", "речевой мусор"),
    (r"\bну\s+вот\b", "слово-паразит"),
    (r"\bну\b", "слово-паразит"),
    (r"\bкак\s+бы\b", "слово-паразит"),
    (r"\bсобственно\b", "слово-паразит"),
    (r"\bзначит\b", "слово-паразит"),
)


def _is_safe_context(text: str, start: int, end: int) -> bool:
    """Не удалять мусор, если он зажат внутри слова."""
    before = text[start - 1] if start > 0 else " "
    after = text[end] if end < len(text) else " "
    return not before.isalnum() and not after.isalnum()


def _normalize_spacing(text: str) -> str:
    cleaned = re.sub(r"[ \t]{2,}", " ", text)
    cleaned = re.sub(r"\s+([,.!?;:])", r"\1", cleaned)
    # Decimal separators, dates and times are part of the number, not word punctuation.
    cleaned = re.sub(
        r"([,.!?;:])(?=\S)",
        lambda m: (
            m.group(0)
            if (m.start() > 0 and cleaned[m.start() - 1].isdigit() and cleaned[m.end()].isdigit())
            else m.group(0) + " "
        ),
        cleaned,
    )
    return cleaned.strip()


def clean_technical_noise(text: str) -> tuple[str, list[TextChange]]:
    """Удалить только очевидный технический мусор, не переписывая предложения."""
    current = str(text or "")
    changes: list[TextChange] = []

    for pattern, reason in FILLER_PATTERNS:
        regex = re.compile(pattern, flags=re.IGNORECASE)

        def replace(match: re.Match[str]) -> str:
            if not _is_safe_context(current, match.start(), match.end()):
                return match.group(0)
            fragment = match.group(0)
            changes.append(
                TextChange(
                    before=fragment,
                    after="",
                    stage="3.1 technical_clean",
                    reason=reason,
                )
            )
            return " "

        current = regex.sub(replace, current)

    corrected = correct_known_grammar(current)
    if corrected != current:
        changes.append(
            TextChange(
                before=current,
                after=corrected,
                stage="3.1 technical_clean",
                reason="Исправление ошибочной падежной формы",
            )
        )
        current = corrected
    spaced = _normalize_spacing(current)
    if spaced != current.strip():
        changes.append(
            TextChange(
                before=current.strip(),
                after=spaced,
                stage="3.1 technical_clean",
                reason="Нормализация пробелов и пунктуационных отступов",
            )
        )

    return spaced, changes
