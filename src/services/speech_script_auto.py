"""Speech Script — внутреннее представление текста для озвучки (этап 3, v3).

Пользователь его не видит и не редактирует.
Источник — субтитр: смысл нельзя обрезать и нельзя раздувать длинными расшифровками,
иначе озвучка перестаёт совпадать с тем, что человек написал на экране.
"""

from __future__ import annotations

import re

from src.services.spoken_amounts import correct_known_grammar, normalize_spoken_amounts

# Короткие произношения (не полные расшифровки — иначе речь не влезает в блок
# и авто-оптимизация начинает вырезать смысл).
ABBREVIATIONS: list[tuple[str, str]] = [
    (r"(?i)(?<!\w)1\s*[сc](?!\w)", "один эс"),
    (r"\bНДС\b", "эн дэ эс"),
    (r"\bНДФЛ\b", "эн дэ эф эл"),
    (r"\bУСН\b", "у эс эн"),
    (r"\bОСНО\b", "осно"),
    (r"\bЕНС\b", "е эн эс"),
    (r"\bЕНП\b", "е эн пэ"),
    (r"\bУПД\b", "у пэ дэ"),
    (r"\bЭДО\b", "э дэ о"),
    (r"\bККТ\b", "ка ка тэ"),
    (r"\bФНС\b", "эф эн эс"),
    (r"\bИП\b", "и пэ"),
    (r"\bООО\b", "о о о"),
    (r"\bЗУП\b", "зуп"),
    (r"\bУТ\b", "у тэ"),
]

# Символы и короткие сокращения
SYMBOLS: list[tuple[str, str]] = [
    (r"№\s*", "номер "),
    (r"%", " процентов"),
    (r"₽", " рублей"),
    (r"\bруб\.", "рублей"),
    (r"\bтыс\.", "тысяч"),
    (r"\bмлн\.?", "миллионов"),
    (r"\bг\.\s*", "года "),
    (r"\bкв\.\s*", "квартал "),
    (r"\bт\.\s*д\.", "так далее"),
    (r"\bт\.\s*п\.", "тому подобное"),
    (r"\bт\.\s*е\.", "то есть"),
    (r"→", " затем "),
    (r"—|–", " "),
]

# Только безопасные слова-связки (не режут смысл фразы)
FILLER_WORDS: tuple[str, ...] = (
    "давайте",
    "итак",
    "просто",
    "собственно",
    "обратите внимание",
    "как видите",
    "хорошо",
)

SHORTENINGS: list[tuple[str, str]] = [
    (r"необходимо\s+", "нужно "),
    (r"для\s+того\s+чтобы\s+", "чтобы "),
    (r"таким\s+образом,?\s*", ""),
    (r"нажимаем\s+на\s+кнопку\s+", "нажимаем "),
]


def _collapse_spaces(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    return text.strip()


def build_speech_text(subtitle: str) -> str:
    """Субтитр → текст для озвучки. Близко к написанному, без потери смысла."""
    text = normalize_spoken_amounts(correct_known_grammar(str(subtitle or "").strip()))
    if not text:
        return ""
    for pattern, replacement in ABBREVIATIONS:
        text = re.sub(pattern, replacement, text)
    for pattern, replacement in SYMBOLS:
        text = re.sub(pattern, replacement, text)
    # перенос строки в субтитре — не пауза в речи
    text = text.replace("\n", " ")
    return _collapse_spaces(text)


def shorten_speech_text(text: str, level: int = 1) -> str:
    """Мягко сократить текст, если озвучка не влезает в блок.

    Важно: нельзя отрезать половину предложения после запятой —
    пользователь писал субтитр целиком, озвучка должна его сохранить.
    """
    result = str(text or "").strip()
    if not result:
        return ""

    if level >= 1:
        for word in FILLER_WORDS:
            result = re.sub(rf"\b{re.escape(word)}\b,?\s*", "", result, flags=re.IGNORECASE)
    if level >= 2:
        for pattern, replacement in SHORTENINGS:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    # level 3 раньше резал «часть после запятой» — из‑за этого пропадало
    # «…с которого применяется НДС». Больше так не делаем.

    result = _collapse_spaces(result)
    if not result:
        return str(text or "").strip()
    return result[:1].upper() + result[1:]
