"""Exact monetary amounts for speech; never discard the scale or round values."""

import re
from decimal import Decimal


def _form(number: int, forms: tuple[str, str, str]) -> str:
    if 11 <= number % 100 <= 14:
        return forms[2]
    return forms[0] if number % 10 == 1 else forms[1] if 2 <= number % 10 <= 4 else forms[2]


def _words(number: int, feminine: bool = False) -> str:
    ones = (
        "ноль",
        "одна" if feminine else "один",
        "две" if feminine else "два",
        "три",
        "четыре",
        "пять",
        "шесть",
        "семь",
        "восемь",
        "девять",
    )
    teens = (
        "десять",
        "одиннадцать",
        "двенадцать",
        "тринадцать",
        "четырнадцать",
        "пятнадцать",
        "шестнадцать",
        "семнадцать",
        "восемнадцать",
        "девятнадцать",
    )
    tens = (
        "",
        "",
        "двадцать",
        "тридцать",
        "сорок",
        "пятьдесят",
        "шестьдесят",
        "семьдесят",
        "восемьдесят",
        "девяносто",
    )
    hundreds = (
        "",
        "сто",
        "двести",
        "триста",
        "четыреста",
        "пятьсот",
        "шестьсот",
        "семьсот",
        "восемьсот",
        "девятьсот",
    )
    parts = [hundreds[number // 100]]
    rest = number % 100
    if 10 <= rest < 20:
        parts.append(teens[rest - 10])
    else:
        parts.append(tens[rest // 10])
        if rest % 10:
            parts.append(ones[rest % 10])
    return " ".join(p for p in parts if p) or "ноль"


SCALES = (
    (1_000_000_000, ("миллиард", "миллиарда", "миллиардов")),
    (1_000_000, ("миллион", "миллиона", "миллионов")),
    (1_000, ("тысяча", "тысячи", "тысяч")),
    (1, ("рубль", "рубля", "рублей")),
)


def normalize_spoken_amounts(text: str) -> str:
    # A decimal separator is accepted only inside an explicit monetary amount.
    pattern = (
        r"(?<![\w.,])(?P<n>\d{1,3}(?:[.,]\s*\d+)?)\s*"
        r"(?P<u>млрд\.?|миллиард(?:а|ов)?|млн\.?|миллион(?:а|ов)?|тыс\.?|тысяч(?:а|и)?)"
        r"\s*(?:рублей|рубля|рубль|руб\.?|₽)(?!\w)"
    )

    def replace(match: re.Match[str]) -> str:
        value = Decimal(re.sub(r"\s", "", match["n"]).replace(",", "."))
        unit = match["u"].lower()
        scale = (
            1_000_000_000
            if unit.startswith(("млрд", "миллиард"))
            else 1_000_000
            if unit.startswith(("млн", "миллион"))
            else 1_000
        )
        whole = int(value)
        forms = next(forms for size, forms in SCALES if size == scale)
        if whole and value - whole == Decimal("0.5"):
            return f"{_words(whole, scale == 1000)} с половиной {_form(whole, forms)} рублей"
        rubles = value * scale
        if rubles != rubles.to_integral_value():
            return match[0]  # No rounding away kopecks.
        remaining = int(rubles)
        parts = []
        for size, names in SCALES:
            count, remaining = divmod(remaining, size)
            if count:
                parts.append(f"{_words(count, size == 1000)} {_form(count, names)}")
        if not parts:
            return "ноль рублей"
        if int(rubles) % 1000 == 0:
            parts.append("рублей")
        return " ".join(parts)

    return re.sub(pattern, replace, text, flags=re.IGNORECASE)


def correct_known_grammar(text: str) -> str:
    return re.sub(
        r"\bмесяцом\b",
        lambda m: "Месяцем" if m[0][0].isupper() else "месяцем",
        text,
        flags=re.IGNORECASE,
    )
