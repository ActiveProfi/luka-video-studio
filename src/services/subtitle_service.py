"""Формирование SRT и JSON-тайминга субтитров из voiceover_segments."""

from __future__ import annotations

import re
from typing import Any

MAX_LINE_CHARS = 42
MAX_LINES_PER_CUE = 2
MIN_CUE_SECONDS = 0.8

SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def format_srt_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(float(seconds) * 1000)))
    hours, rem_ms = divmod(total_ms, 3_600_000)
    minutes, rem_ms = divmod(rem_ms, 60_000)
    secs, ms = divmod(rem_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _wrap_line(text: str, max_chars: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join(current + [word])
        if len(candidate) <= max_chars:
            current.append(word)
        elif current:
            lines.append(" ".join(current))
            current = [word]
        else:
            lines.append(word[:max_chars])
            current = []
    if current:
        lines.append(" ".join(current))
    return lines


def wrap_subtitle_text(text: str, max_line_chars: int = MAX_LINE_CHARS, max_lines: int = MAX_LINES_PER_CUE) -> str:
    """Разбить текст субтитра на 1–2 строки."""
    normalized = " ".join(str(text).split())
    if not normalized:
        return ""
    lines = _wrap_line(normalized, max_line_chars)
    if len(lines) <= max_lines:
        return "\n".join(lines)
    merged = lines[: max_lines - 1]
    merged.append(" ".join(lines[max_lines - 1 :]))
    return "\n".join(merged[:max_lines])


def _split_text_chunks(text: str) -> list[str]:
    normalized = " ".join(str(text).split())
    if not normalized:
        return []
    parts = [p.strip() for p in SENTENCE_SPLIT.split(normalized) if p.strip()]
    if not parts:
        return [normalized]
    chunks: list[str] = []
    for part in parts:
        wrapped_lines = _wrap_line(part, MAX_LINE_CHARS)
        if len(wrapped_lines) <= MAX_LINES_PER_CUE:
            chunks.append(part)
            continue
        words = part.split()
        bucket: list[str] = []
        for word in words:
            candidate = " ".join(bucket + [word])
            wrapped = wrap_subtitle_text(candidate)
            line_count = len(wrapped.splitlines()) if wrapped else 0
            char_ok = all(len(line) <= MAX_LINE_CHARS for line in wrapped.splitlines())
            if line_count <= MAX_LINES_PER_CUE and char_ok:
                bucket.append(word)
            else:
                if bucket:
                    chunks.append(" ".join(bucket))
                bucket = [word]
        if bucket:
            chunks.append(" ".join(bucket))
    return chunks


def assign_global_cue_ids(cues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Пронумеровать cues по всему уроку: cue_0001, cue_0002, … без повторов."""
    return [{**cue, "cue_id": f"cue_{index:04d}"} for index, cue in enumerate(cues, start=1)]


def has_duplicate_cue_ids(cues: list[dict[str, Any]]) -> bool:
    ids = [str(c.get("cue_id", "")) for c in cues if c.get("cue_id")]
    return len(ids) != len(set(ids))


def fill_cue_timeline_gaps(
    cues: list[dict[str, Any]],
    total_duration: float,
    *,
    min_gap: float = 0.05,
) -> list[dict[str, Any]]:
    """
    Закрыть паузы пустыми блоками: от 0 до total_duration без дыр.
    Пустой text — место для ручного ввода на шаге 6.
    """
    duration = max(0.0, float(total_duration or 0.0))
    if duration <= 0 and cues:
        duration = max(float(c.get("end", 0) or 0) for c in cues)

    ordered = sorted(
        (
            {
                "cue_id": str(c.get("cue_id") or ""),
                "source_segment_id": str(c.get("source_segment_id") or ""),
                "start": round(max(0.0, float(c.get("start", 0))), 3),
                "end": round(max(0.0, float(c.get("end", 0))), 3),
                "text": str(c.get("text") or ""),
            }
            for c in cues
        ),
        key=lambda item: (item["start"], item["end"]),
    )

    filled: list[dict[str, Any]] = []
    cursor = 0.0
    for cue in ordered:
        start = cue["start"]
        end = max(start + 0.05, cue["end"])
        if start > cursor + min_gap:
            filled.append(
                {
                    "cue_id": "gap",
                    "source_segment_id": "",
                    "start": round(cursor, 3),
                    "end": round(start, 3),
                    "text": "",
                }
            )
        elif start > cursor:
            # Крошечный зазор — приклеить к текущему блоку слева, если он уже есть.
            if filled and not str(filled[-1].get("text") or "").strip():
                filled[-1]["end"] = round(start, 3)
            elif filled:
                filled[-1]["end"] = round(start, 3)
            cursor = start
        filled.append({**cue, "start": start, "end": end})
        cursor = max(cursor, end)

    if duration > cursor + min_gap:
        filled.append(
            {
                "cue_id": "gap",
                "source_segment_id": "",
                "start": round(cursor, 3),
                "end": round(duration, 3),
                "text": "",
            }
        )
    elif filled and duration > cursor:
        filled[-1]["end"] = round(duration, 3)

    return assign_global_cue_ids(filled)


def timeline_has_gaps(cues: list[dict[str, Any]], total_duration: float, *, min_gap: float = 0.05) -> bool:
    """Есть ли дыры во временной шкале субтитров."""
    if total_duration <= 0:
        return False
    ordered = sorted(cues, key=lambda c: float(c.get("start", 0)))
    cursor = 0.0
    for cue in ordered:
        start = float(cue.get("start", 0))
        end = float(cue.get("end", 0))
        if start > cursor + min_gap:
            return True
        cursor = max(cursor, end)
    return total_duration > cursor + min_gap


def segment_to_cues(
    text: str,
    start: float,
    end: float,
    *,
    source_segment_id: str = "",
    start_index: int = 1,
) -> list[dict[str, Any]]:
    """Разбить фрагмент озвучки на cues с пропорциональным таймингом."""
    start_f = float(start)
    end_f = float(end)
    duration = max(MIN_CUE_SECONDS, end_f - start_f)
    chunks = _split_text_chunks(text)
    if not chunks:
        return []

    weights = [max(1, len(chunk)) for chunk in chunks]
    total_weight = sum(weights)
    cues: list[dict[str, Any]] = []
    cursor = start_f

    for idx, (chunk, weight) in enumerate(zip(chunks, weights)):
        chunk_duration = duration * (weight / total_weight)
        if idx == len(chunks) - 1:
            cue_end = end_f
        else:
            cue_end = min(end_f, cursor + chunk_duration)
        if cue_end - cursor < MIN_CUE_SECONDS and idx < len(chunks) - 1:
            cue_end = min(end_f, cursor + MIN_CUE_SECONDS)
        cues.append(
            {
                "cue_id": f"cue_{start_index + idx:04d}",
                "source_segment_id": source_segment_id,
                "start": round(cursor, 3),
                "end": round(cue_end, 3),
                "text": wrap_subtitle_text(chunk),
            }
        )
        cursor = cue_end

    if cues:
        cues[-1]["end"] = round(end_f, 3)
    return cues


def build_srt_content(cues: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for idx, cue in enumerate(cues, start=1):
        text = str(cue.get("text", "")).strip()
        if not text:
            continue
        blocks.append(
            "\n".join(
                [
                    str(idx),
                    f"{format_srt_timestamp(cue['start'])} --> {format_srt_timestamp(cue['end'])}",
                    text,
                ]
            )
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def cues_from_voiceover_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cues: list[dict[str, Any]] = []
    next_index = 1
    for seg in segments:
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        start = seg.get("audio_start", seg.get("target_start", 0))
        end = seg.get("audio_end", seg.get("target_end", start))
        seg_cues = segment_to_cues(
            text,
            float(start),
            float(end),
            source_segment_id=str(seg.get("segment_id", "")),
            start_index=next_index,
        )
        next_index += len(seg_cues)
        cues.extend(seg_cues)
    return cues


SUBTITLE_LAYOUT = "subtitle_layout.json"


def default_subtitle_layout() -> dict[str, Any]:
    """Базовое положение блока субтитров (нормализованные координаты 0..1)."""
    return {
        "x": 0.06,
        "y": 0.82,
        "width": 0.88,
        "height": 0.12,
        "font_size_px": 12,
        "alignment": "center",
        "font_color": "#ffffff",
        "background_color": "#000000",
        "background_opacity": 0.72,
        "font_bold": False,
        "font_italic": False,
        "cue_layouts": {},
    }
