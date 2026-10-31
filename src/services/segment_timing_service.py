"""Посимвольная привязка текста к тайм-блокам (без рассинхрона на этапе редактирования)."""

from __future__ import annotations

from typing import Any

# Совпадает с длиной STT-фрагмента для распознавания (удобство для агента).
DEFAULT_EDIT_BLOCK_SECONDS = 25.0


def _tokenize_words(text: str) -> list[str]:
    return [part for part in str(text or "").strip().split() if part]


def count_timing_steps(text: str) -> int:
    words = _tokenize_words(text)
    if not words:
        return 0
    chars = sum(len(word) for word in words)
    return chars + max(0, len(words) - 1)


def build_speech_timeline(text: str, start: float, end: float) -> list[dict[str, Any]]:
    """Один временной шаг на символ и один на паузу между словами."""
    words = _tokenize_words(text)
    if not words:
        return []

    total_steps = count_timing_steps(text)
    step_duration = (float(end) - float(start)) / total_steps
    cursor = float(start)
    entries: list[dict[str, Any]] = []

    for word_index, word in enumerate(words):
        for char in word:
            entries.append(
                {
                    "char": char,
                    "type": "char",
                    "start": round(cursor, 4),
                    "end": round(cursor + step_duration, 4),
                }
            )
            cursor += step_duration
        if word_index < len(words) - 1:
            entries.append(
                {
                    "char": " ",
                    "type": "gap",
                    "start": round(cursor, 4),
                    "end": round(cursor + step_duration, 4),
                }
            )
            cursor += step_duration

    return entries


def _entries_to_text(entries: list[dict[str, Any]]) -> str:
    return "".join(str(item.get("char", "")) for item in entries)


def split_text_into_time_blocks(
    text: str,
    duration: float,
    *,
    block_seconds: float = DEFAULT_EDIT_BLOCK_SECONDS,
) -> list[dict[str, Any]]:
    """Разбить весь текст на блоки: в каждый попадают только символы своего интервала."""
    cleaned = str(text or "").strip()
    if not cleaned or duration <= 0:
        return []

    timeline = build_speech_timeline(cleaned, 0.0, float(duration))
    blocks: list[dict[str, Any]] = []
    block_start = 0.0
    index = 0

    while block_start < float(duration) - 0.001:
        block_end = min(block_start + float(block_seconds), float(duration))
        chunk = [entry for entry in timeline if block_start <= entry["start"] < block_end]
        block_text = _entries_to_text(chunk).strip()
        blocks.append(
            {
                "segment_id": f"seg_{index + 1:03d}",
                "start": round(block_start, 3),
                "end": round(block_end, 3),
                "text": block_text,
                "original_text": block_text,
            }
        )
        block_start = block_end
        index += 1

    return blocks


def join_segments_text(segments: list[dict[str, Any]], field: str = "text") -> str:
    """Склеить текст всех блоков в одну строку для единого редактора."""
    parts = [str(item.get(field, "")).strip() for item in segments]
    return " ".join(part for part in parts if part)


def _block_weight(segment: dict[str, Any]) -> float:
    """Вес блока для раскладки текста: длительность, иначе число шагов исходника."""
    start = float(segment.get("start", 0.0) or 0.0)
    end = float(segment.get("end", 0.0) or 0.0)
    duration = max(0.0, end - start)
    if duration > 0.05:
        return duration
    original = str(segment.get("original_text") or segment.get("text") or "")
    return float(max(1, count_timing_steps(original)))


def redistribute_words_to_segments(
    full_text: str,
    source_segments: list[dict[str, Any]],
) -> list[str]:
    """
    Разложить единый текст по существующим блокам.
    Границы времени блоков не меняются. Слова не режутся.
    """
    words = _tokenize_words(full_text)
    if not source_segments:
        return [str(full_text or "").strip()] if str(full_text or "").strip() else []
    if not words:
        return [""] * len(source_segments)

    weights = [_block_weight(seg) for seg in source_segments]
    total_weight = sum(weights) or float(len(source_segments))
    total_words = len(words)

    # Сколько целых слов отдать каждому блоку пропорционально весу.
    raw_counts = [(w / total_weight) * total_words for w in weights]
    counts = [int(x) for x in raw_counts]
    # Распределить остаток по наибольшим дробным частям.
    remainder = total_words - sum(counts)
    order = sorted(
        range(len(raw_counts)),
        key=lambda i: (raw_counts[i] - counts[i], weights[i]),
        reverse=True,
    )
    for i in order:
        if remainder <= 0:
            break
        counts[i] += 1
        remainder -= 1

    # Последний блок забирает всё, что осталось (защита от округления).
    assigned = sum(counts[:-1]) if len(counts) > 1 else 0
    if counts:
        counts[-1] = max(0, total_words - assigned)

    parts: list[str] = []
    cursor = 0
    for count in counts:
        chunk = words[cursor : cursor + count]
        cursor += count
        parts.append(" ".join(chunk))
    # Если слова остались из-за сбоя счёта — дописать в последний блок.
    if cursor < total_words and parts:
        tail = " ".join(words[cursor:])
        parts[-1] = f"{parts[-1]} {tail}".strip() if parts[-1] else tail
    return parts


def segments_from_full_text(
    full_text: str,
    source_segments: list[dict[str, Any]],
    *,
    duration: float,
) -> list[dict[str, Any]]:
    """Разложить единый текст обратно на тайм-блоки для озвучки.

    - границы start/end блоков сохраняются из исходника;
    - слова не разбиваются между блоками;
    - original_text / text_before = текст до правки, text / text_after = после.
    """
    cleaned = str(full_text or "").strip()
    if not cleaned:
        raise ValueError("Текст урока не может быть пустым")
    if duration <= 0 and not source_segments:
        raise ValueError("Неизвестна длительность урока")
    if not source_segments:
        return split_text_into_time_blocks(cleaned, duration)

    text_parts = redistribute_words_to_segments(cleaned, source_segments)
    result: list[dict[str, Any]] = []
    for index, src in enumerate(source_segments):
        before = str(src.get("original_text") or src.get("text_before") or src.get("text") or "").strip()
        after = text_parts[index] if index < len(text_parts) else ""
        confidence = src.get("confidence")
        if confidence is None:
            confidence = 1.0
        result.append(
            {
                "segment_id": src.get("segment_id", f"seg_{index + 1:03d}"),
                "start": float(src["start"]),
                "end": float(src["end"]),
                "text": after,
                "text_after": after,
                "original_text": before,
                "text_before": before,
                "confidence": confidence,
                "edit_ids": list(src.get("edit_ids") or []),
            }
        )
    return result


def realign_transcript_segments(
    source_segments: list[dict[str, Any]],
    *,
    block_seconds: float = DEFAULT_EDIT_BLOCK_SECONDS,
) -> list[dict[str, Any]]:
    """Пересобрать блоки редактирования: текст строго по таймингу исходника."""
    if not source_segments:
        return []

    parts = [str(item.get("text", "")).strip() for item in source_segments]
    full_text = " ".join(part for part in parts if part)
    duration = max(float(item.get("end", 0.0)) for item in source_segments)
    return split_text_into_time_blocks(full_text, duration, block_seconds=block_seconds)


def merge_stt_segments_with_timing(
    source_segments: list[dict[str, Any]],
    *,
    block_seconds: float = DEFAULT_EDIT_BLOCK_SECONDS,
) -> list[dict[str, Any]]:
    """Блоки для ручного редактирования после STT."""
    aligned = realign_transcript_segments(source_segments, block_seconds=block_seconds)
    result: list[dict[str, Any]] = []
    for index, block in enumerate(aligned):
        src = source_segments[min(index, len(source_segments) - 1)]
        result.append(
            {
                **block,
                "confidence": src.get("confidence"),
                "edit_ids": [],
            }
        )
    return result


def realign_clean_segments_preserving_edits(
    segments: list[dict[str, Any]],
    *,
    duration: float | None = None,
    block_seconds: float = DEFAULT_EDIT_BLOCK_SECONDS,
) -> list[dict[str, Any]]:
    """Пересобрать блоки по таймингу, сохранив отредактированный и исходный текст целиком."""
    if not segments:
        return []

    edited_parts = [str(item.get("text", "")).strip() for item in segments]
    original_parts = [
        str(item.get("original_text") or item.get("text", "")).strip() for item in segments
    ]
    full_edited = " ".join(part for part in edited_parts if part)
    full_original = " ".join(part for part in original_parts if part)
    if not full_original and not full_edited:
        return segments

    resolved_duration = float(duration or max(float(item.get("end", 0.0)) for item in segments))
    edited_blocks = split_text_into_time_blocks(full_edited, resolved_duration, block_seconds=block_seconds)
    original_blocks = split_text_into_time_blocks(
        full_original or full_edited,
        resolved_duration,
        block_seconds=block_seconds,
    )

    result: list[dict[str, Any]] = []
    for index, edited in enumerate(edited_blocks):
        original = original_blocks[index] if index < len(original_blocks) else edited
        src = segments[min(index, len(segments) - 1)]
        confidence = src.get("confidence")
        if confidence is None:
            confidence = 1.0
        result.append(
            {
                "segment_id": edited["segment_id"],
                "start": edited["start"],
                "end": edited["end"],
                "text": edited["text"],
                "original_text": original["text"],
                "confidence": confidence,
                "edit_ids": list(src.get("edit_ids") or []),
            }
        )
    return result


def segments_need_timing_realign(
    segments: list[dict[str, Any]],
    *,
    duration: float | None = None,
) -> bool:
    """STT-куски часто дают разное число шагов в блоках одинаковой длины — нужна пересборка."""
    if len(segments) < 2:
        return False

    resolved_duration = float(duration or max(float(item.get("end", 0.0)) for item in segments))
    reference_parts = [
        str(item.get("original_text") or item.get("text", "")).strip() for item in segments
    ]
    full_reference = " ".join(part for part in reference_parts if part)
    total_steps = count_timing_steps(full_reference)
    if total_steps <= 0 or resolved_duration <= 0:
        return False

    budgets: list[int] = []
    slots: list[float] = []
    for seg in segments:
        slot = float(seg["end"]) - float(seg["start"])
        if slot <= 0:
            continue
        slots.append(slot)
        budgets.append(count_timing_steps(str(seg.get("original_text") or seg.get("text", ""))))

    if len(budgets) < 2:
        return False

    uniform_slots = [slot for slot in slots if abs(slot - slots[0]) < 0.05]
    if len(uniform_slots) < 2:
        return False

    expected = round(uniform_slots[0] * total_steps / resolved_duration)
    if expected <= 0:
        return False

    return any(abs(value - expected) > max(2, int(expected * 0.06)) for value in budgets)
