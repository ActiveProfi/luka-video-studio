"""Extract protected speech spans and independently verify their numeric meaning."""

import re
from datetime import date
from decimal import Decimal

MONTHS = (
    "январ",
    "феврал",
    "март",
    "апрел",
    "ма",
    "июн",
    "июл",
    "август",
    "сентябр",
    "октябр",
    "ноябр",
    "декабр",
)
N = r"\d{1,3}(?:[ \u00a0]\d{3})+|\d+(?:[.,]\d+)?"
RUBLE = r"(?:руб\.|руб(?!\w)|рубл(?:ей|я|ь|ях|ями|ю|е)(?!\w)|₽)"
AMOUNT = re.compile(
    rf"(?<![\w.,])(?:{N})\s*(?:миллиард\w*|млрд\.?|миллион\w*|млн\.?|тысяч\w*|тыс\.?)(?:\s+\d+(?:\s+тысяч\w*)?)?(?:\s*{RUBLE})?|(?<![\w.,])(?:{N})\s*{RUBLE}",
    re.I,
)
DATE = re.compile(r"(?<!\d)(\d{1,2})[./](\d{1,2})[./](\d{4})(?!\d)(?:\s+года|\s+г\.)?")
NAMED_DATE = re.compile(
    r"\b(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(\d{4})(?:\s+года|\s+г\.)?",
    re.I,
)
YEAR = re.compile(r"\b(?:19|20)\d{2}\s*(?:года|году|годом|год|г\.)(?!\w)", re.I)
TERM = re.compile(r"(?<!\w)(?:1[СCсc]|[А-ЯЁ]{2,8}|[A-Za-z][A-Za-z0-9+.-]{1,30})(?!\w)")
KNOWN_NAMES = {
    "1с": ["один эс"],
    "1c": ["один эс"],
    "excel": ["эксель"],
    "python": ["пайтон"],
    "word": ["ворд"],
    "windows": ["виндоус"],
    "google": ["гугл"],
    "microsoft": ["майкрософт"],
    "ок": ["окей", "о кей", "ок"],
}


def numeral(text):
    from src.services.contextual_pronunciation import number_lexicon

    lexicon = number_lexicon()
    for n, forms in {
        200: "двести двухсот двумстам двумястами двухстах",
        300: "триста трехсот тремстам тремястами трехстах",
        400: "четыреста четырехсот четыремстам четырьмястами четырехстах",
        500: "пятьсот пятисот пятистам пятьюстами пятистах",
        600: "шестьсот шестисот шестистам шестьюстами шестистах",
        700: "семьсот семисот семистам семьюстами семистах",
        800: "восемьсот восьмисот восьмистам восемьюстами восьмистах",
        900: "девятьсот девятисот девятистам девятьюстами девятистах",
    }.items():
        lexicon.update({w: n for w in forms.split()})
    ordinals = {
        "перв": 1,
        "втор": 2,
        "треть": 3,
        "четверт": 4,
        "пят": 5,
        "шест": 6,
        "седьм": 7,
        "восьм": 8,
        "девят": 9,
        "десят": 10,
        "одиннадцат": 11,
        "двенадцат": 12,
        "тринадцат": 13,
        "четырнадцат": 14,
        "пятнадцат": 15,
        "шестнадцат": 16,
        "семнадцат": 17,
        "восемнадцат": 18,
        "девятнадцат": 19,
        "двадцат": 20,
        "тридцат": 30,
        "сороков": 40,
        "пятидесят": 50,
        "шестидесят": 60,
        "семидесят": 70,
        "восьмидесят": 80,
        "девяност": 90,
        "сот": 100,
    }
    text = text.lower().replace("ё", "е").replace("+", "")
    text = re.sub(r"\bс половиной\b", " half ", text)
    words = re.findall(r"\w+", text)
    total, group, last_scale = Decimal(0), Decimal(0), Decimal("1e15")
    last_class = 1000
    for word in words:
        if word == "half":
            group += Decimal(".5")
            continue
        scale = next(
            (
                s
                for stem, s in [("тысяч", 1000), ("миллион", 1000000), ("миллиард", 1000000000)]
                if word.startswith(stem)
            ),
            None,
        )
        if scale:
            if scale >= last_scale:
                raise ValueError("Неверный порядок разрядов")
            total += (group or 1) * scale
            group, last_class, last_scale = Decimal(0), 1000, scale
            continue
        value = lexicon.get(word)
        if value is None:
            value = next(
                (
                    n
                    for stem, n in ordinals.items()
                    if re.fullmatch(
                        stem + r"(?:ый|ой|ий|ое|ее|ого|его|ому|ему|ым|им|ом|ем|ая|яя|ую)", word
                    )
                ),
                None,
            )
        if value is None:
            raise ValueError("Неизвестное слово в числительном: " + word)
        cls = 100 if value >= 100 else 10 if value >= 10 else 1
        if cls >= last_class:
            raise ValueError("Неверное составное числительное")
        group += value
        last_class = cls
    if not words:
        raise ValueError("Пустое числительное")
    return total + group


def source_amount(text):
    clean = re.sub(r"(?<=\d)[ \u00a0](?=\d{3}(?:\D|$))", "", text.lower())
    values = re.findall(r"\d+(?:[.,]\d+)?", clean)
    value = Decimal(values[0].replace(",", "."))
    scale = (
        1000000000
        if re.search(r"миллиард|млрд", clean)
        else 1000000
        if re.search(r"миллион|млн", clean)
        else 1000
        if re.search(r"тысяч|тыс", clean)
        else 1
    )
    value *= scale
    if len(values) > 1:
        value += Decimal(values[1]) * (1000 if scale >= 1000000 else 1)
    return value


def spoken_amount(text, rubles):
    if rubles and not re.search(r"\bрубл", text, re.I):
        raise ValueError("Потеряна валюта")
    parts = re.split(r"\bрубл\w*\b", text.lower())
    amount = numeral(parts[0])
    if len(parts) > 1 and parts[1].strip(" .,"):
        tail = parts[1].strip(" .,")
        if not re.search(r"\bкопе", tail):
            raise ValueError("Лишние слова после суммы")
        amount += numeral(re.sub(r"\bкопе\w*\b", "", tail)) / 100
    return amount


def extract_entities(block, occupied):
    from src.services.speech_script_auto import ABBREVIATIONS

    text = block["subtitle"]
    results = []

    def add(match, kind, **fields):
        if any(match.start() < end and match.end() > start for start, end in occupied):
            return
        occupied.append((match.start(), match.end()))
        results.append(
            {
                "id": f"{block['id']}:{kind}:{match.start()}",
                "block_id": str(block["id"]),
                "kind": kind,
                "expression": match[0],
                "start": match.start(),
                "end": match.end(),
                **fields,
            }
        )

    for m in DATE.finditer(text):
        day, month, year = map(int, m.groups())
        date(year, month, day)
        add(m, "date", day=day, month=month, year=year)
    for m in NAMED_DATE.finditer(text):
        day, year = int(m[1]), int(m[3])
        month = next(i + 1 for i, s in enumerate(MONTHS) if m[2].lower().startswith(s))
        date(year, month, day)
        add(m, "date", day=day, month=month, year=year)
    for m in YEAR.finditer(text):
        add(m, "year", value=int(re.search(r"\d+", m[0])[0]))
    for m in AMOUNT.finditer(text):
        add(
            m,
            "amount",
            value=str(source_amount(m[0])),
            rubles=bool(re.search(r"руб|₽", m[0], re.I)),
        )
    for m in TERM.finditer(text):
        allowed = KNOWN_NAMES.get(m[0].casefold(), [])
        for pattern, reading in ABBREVIATIONS:
            if re.fullmatch(pattern, m[0]):
                allowed = [reading]
                break
        add(m, "term", allowed=allowed)
    return results


def validate_entity(target, spoken):
    if not isinstance(spoken, str) or not spoken.strip() or len(spoken) > 300:
        raise ValueError("Пустое или слишком длинное произношение")
    if re.search(r"\d|[<>\[\]]", spoken):
        raise ValueError("Нужны слова без цифровой записи и управляющей разметки")
    kind = target["kind"]
    if kind == "amount":
        if spoken_amount(spoken, target["rubles"]) != Decimal(target["value"]):
            raise ValueError("Изменена сумма или разрядность")
    elif kind == "year":
        if (
            not re.search(r"\bгод", spoken)
            or numeral(re.sub(r"\bгод\w*\b", "", spoken)) != target["value"]
        ):
            raise ValueError("Изменён год")
    elif kind == "date":
        words = spoken.lower().split()
        matches = [
            (i, n + 1)
            for i, w in enumerate(words)
            for n, stem in enumerate(MONTHS)
            if w.startswith(stem)
        ]
        if len(matches) != 1:
            raise ValueError("Неоднозначный месяц")
        i, month = matches[0]
        year_words = re.sub(r"\bгод\w*\b", "", " ".join(words[i + 1 :]))
        if (numeral(" ".join(words[:i])), month, numeral(year_words)) != (
            target["day"],
            target["month"],
            target["year"],
        ):
            raise ValueError("Изменена дата")
    elif kind == "term":

        def normalized(s):
            return re.sub(r"[^а-яa-z]", "", s.lower().replace("ё", "е"))

        if target["allowed"] and normalized(spoken) not in {
            normalized(s) for s in target["allowed"]
        }:
            raise ValueError("Изменено проверенное произношение термина")
        if not target["allowed"] and (
            len(spoken.split()) > 8 or not re.fullmatch(r"[А-Яа-яЁё +.-]+", spoken)
        ):
            raise ValueError("Недопустимая транскрипция названия")
