"""Правила подготовки текста к AI-озвучке (промпты и справочники)."""

from __future__ import annotations

import re
from typing import Any

FILLER_PATTERNS = (
    r"\bэ[\-\s]?э\b",
    r"\bээ+\b",
    r"\bну+\b",
    r"\bвот\b",
    r"\bкак\s+бы\b",
    r"\bтипа\b",
    r"\bзначит\b",
    r"\bсобственно\b",
    r"\bв\s+общем\b",
)

TTS_VOICEOVER_RULES = """Правила текста для AI-озвучки (обязательно применяй):
1. Аббревиатуры — через пробел между буквами или слогами:
   НДС → «эн дэ эс», УСН → «у эс эн», 1С → «один эс», ООО → «о о о», ИП → «и пэ»
2. Числа и даты — словами, как их произнесёт диктор:
   2024 → «две тысячи двадцать четвёртый год» (если год) или «два ноль два четыре» (если код)
   20% → «двадцать процентов», 1 500 руб. → «полторы тысячи рублей»
3. Пунктуация: точки между предложениями, запятые в перечислениях и перед «что», «который», «чтобы»
4. Убрать слова-паразиты: «э-э», «ну», «вот», «как бы», «типа», лишние повторы
5. Исправить ошибки распознавания: подобрать слово по смыслу урока 1С, не оставлять бессмыслицу
6. Без emoji, без markdown, без скобок-пояснений для редактора
7. Текст должен звучать естественно вслух — короткие фразы, ясные формулировки"""


def strip_fillers(text: str) -> str:
    """Простая локальная очистка слов-паразитов перед отправкой в LLM."""
    cleaned = str(text or "")
    for pattern in FILLER_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def normalize_text_for_compare(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def texts_are_unchanged(before: str, after: str) -> bool:
    return normalize_text_for_compare(before) == normalize_text_for_compare(after)


def format_block_guide(segments: list[dict[str, Any]]) -> str:
    from src.services.segment_timing_service import count_timing_steps

    lines: list[str] = []
    for index, seg in enumerate(segments):
        original = str(seg.get("original_text") or seg.get("text", "")).strip()
        budget = max(1, count_timing_steps(original))
        start = float(seg.get("start", 0))
        end = float(seg.get("end", 0))
        lines.append(f"- Блок {index + 1}: {start:.1f}–{end:.1f} с, ~{budget} шагов")
    return "\n".join(lines) if lines else "—"
