"""Точная доводка Speech Script до бюджета шагов без новых предложений."""

from __future__ import annotations

import re

from src.services.segment_timing_service import count_timing_steps

# Можно удалить, если уже есть в тексте (вводные).
_SOFT_REMOVE_WORDS = frozenset(
    {
        "также",
        "сейчас",
        "далее",
        "затем",
        "пожалуйста",
        "просто",
        "именно",
        "сначала",
        "потом",
        "итак",
        "здесь",
        "вот",
    }
)

# Для набора длины — только короткие служебные слова, без новых фраз в конце.
_SOFT_INSERT_WORDS = ("и", "же", "то", "также")

# Слоги произношения TTS — нельзя удалять.
_TTS_SPELLED_TOKENS = frozenset(
    {
        "эн",
        "дэ",
        "эс",
        "эм",
        "пэ",
        "бэ",
        "вэ",
        "гэ",
        "жэ",
        "зэ",
        "ка",
        "эль",
        "эр",
        "тэ",
        "фэ",
        "ха",
        "цэ",
        "че",
        "ша",
        "ща",
        "один",
    }
)

_PUNCT_TRAIL = re.compile(r"([.,!?;:]+)$")
_SENTENCE_SPLIT = re.compile(r"[.!?]+")


def _core_word(token: str) -> str:
    return _PUNCT_TRAIL.sub("", token).casefold()


def _is_protected_token(token: str) -> bool:
    return _core_word(token) in _TTS_SPELLED_TOKENS


def _join_words(words: list[str]) -> str:
    return " ".join(words).strip()


def _content_words(text: str) -> set[str]:
    return {
        _core_word(part)
        for part in str(text or "").split()
        if len(_core_word(part)) > 3 and not _is_protected_token(part)
    }


def sentence_count(text: str) -> int:
    parts = [part.strip() for part in _SENTENCE_SPLIT.split(str(text or "")) if part.strip()]
    return len(parts)


def is_timing_edit_faithful(draft: str, candidate: str) -> bool:
    """Проверка: нет новых предложений и мало «чужих» слов относительно Speech Script."""
    draft = str(draft or "").strip()
    candidate = str(candidate or "").strip()
    if not draft or not candidate:
        return False
    if sentence_count(candidate) > sentence_count(draft):
        return False

    draft_words = _content_words(draft)
    cand_words = _content_words(candidate)
    if not draft_words:
        return True

    overlap = len(draft_words & cand_words) / len(draft_words)
    if overlap < 0.72:
        return False
    if cand_words:
        new_ratio = len(cand_words - draft_words) / len(cand_words)
        if new_ratio > 0.28:
            return False
    return True


def _remove_one_soft_word(words: list[str]) -> list[str] | None:
    for index in range(len(words) - 1, -1, -1):
        if _is_protected_token(words[index]):
            continue
        if _core_word(words[index]) in _SOFT_REMOVE_WORDS:
            return words[:index] + words[index + 1 :]
    return None


def _remove_one_trailing_punct(words: list[str]) -> list[str] | None:
    for index in range(len(words) - 1, -1, -1):
        if _is_protected_token(words[index]):
            continue
        match = _PUNCT_TRAIL.search(words[index])
        if not match:
            continue
        punct = match.group(1)
        stem = words[index][: -len(punct)]
        if not stem:
            continue
        next_token = stem + punct[1:]
        return words[:index] + [next_token] + words[index + 1 :]
    return None


def _trim_one_char_from_long_word(words: list[str]) -> list[str] | None:
    for index in range(len(words) - 1, -1, -1):
        if _is_protected_token(words[index]):
            continue
        match = _PUNCT_TRAIL.search(words[index])
        punct = match.group(1) if match else ""
        stem = words[index][: -len(punct)] if punct else words[index]
        if len(stem) < 7:
            continue
        trimmed = stem[:-1]
        return words[:index] + [trimmed + punct] + words[index + 1 :]
    return None


def _insert_soft_word(words: list[str], soft: str, round_index: int) -> list[str]:
    """Вставляем служебное слово по тексту, не разрывая «эн дэ эс» / «один эс»."""
    if not words:
        return [soft]
    if len(words) == 1:
        return [soft, words[0]]

    safe_positions: list[int] = []
    for index in range(1, len(words)):
        # Нельзя вставлять между слогами произношения аббревиатуры.
        if _is_protected_token(words[index - 1]) and _is_protected_token(words[index]):
            continue
        safe_positions.append(index)
    if not safe_positions:
        # В крайнем случае — только в самое начало (не в конец и не внутрь аббревиатур).
        return [soft] + words

    insert_at = safe_positions[(round_index * 3) % len(safe_positions)]
    return words[:insert_at] + [soft] + words[insert_at:]


def _add_one_trailing_punct(words: list[str]) -> list[str] | None:
    for index, token in enumerate(words):
        if _is_protected_token(token):
            continue
        if _PUNCT_TRAIL.search(token):
            continue
        if not _core_word(token):
            continue
        return words[:index] + [token + ","] + words[index + 1 :]
    return None


def _steps_delta_for_insert(soft: str) -> int:
    return len(soft) + 1


def fine_tune_to_exact_steps(text: str, budget_steps: int) -> str:
    """Подогнать ровно к budget_steps без новых предложений в конце."""
    budget = max(1, int(budget_steps))
    current = str(text or "").strip()
    if not current:
        raise ValueError("Пустой Speech Script — нечего подгонять")
    if count_timing_steps(current) == budget:
        return current

    insert_round = 0

    for _ in range(budget * 6 + 80):
        steps = count_timing_steps(current)
        if steps == budget:
            return current
        words = current.split()

        if steps > budget:
            nxt = _remove_one_soft_word(words)
            if nxt is None:
                nxt = _remove_one_trailing_punct(words)
            if nxt is None:
                nxt = _trim_one_char_from_long_word(words)
            if nxt is None:
                break
            current = _join_words(nxt)
            continue

        need = budget - steps
        chosen = None
        for offset in range(len(_SOFT_INSERT_WORDS)):
            soft = _SOFT_INSERT_WORDS[(insert_round + offset) % len(_SOFT_INSERT_WORDS)]
            if _steps_delta_for_insert(soft) <= need:
                chosen = soft
                break
        if chosen is not None:
            current = _join_words(_insert_soft_word(words, chosen, insert_round))
            insert_round += 1
            continue

        if need == 1:
            nxt = _add_one_trailing_punct(words)
            if nxt is None:
                current = _join_words(_insert_soft_word(words, "и", insert_round))
                insert_round += 1
            else:
                current = _join_words(nxt)
            continue

        current = _join_words(_insert_soft_word(words, "и", insert_round))
        insert_round += 1

    final_steps = count_timing_steps(current)
    if final_steps != budget:
        raise ValueError(
            f"Не удалось точно подогнать тайминг: получилось {final_steps} шагов, нужно ровно {budget}."
        )
    return current


def timing_retry_hint_preserve_speech(budget_steps: int, got_steps: int) -> str:
    delta = got_steps - budget_steps
    if delta > 0:
        return (
            f"Сократи примерно на {delta} шаг(ов) внутри УЖЕ существующих предложений. "
            "ЗАПРЕЩЕНО добавлять или убирать целые предложения. "
            "ЗАПРЕЩЕНО дописывать новый текст в конце. "
            "ЗАПРЕЩЕНО сворачивать «эн дэ эс» / «один эс» обратно в НДС/1С."
        )
    need = -delta
    return (
        f"Добавь примерно {need} шаг(ов) ТОЛЬКО внутри существующих предложений "
        "(чуть подробнее те же формулировки, союзы «и», «то есть»). "
        "ЗАПРЕЩЕНО писать новые предложения и новый финал, которого не было в Speech Script. "
        "Сохрани расшифровки аббревиатур для озвучки."
    )
