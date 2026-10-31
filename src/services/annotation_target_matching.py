"""Local, evidence-based recovery of small OCR labels and monetary targets."""

import hashlib
import json
import re
from decimal import Decimal
from difflib import SequenceMatcher

import cv2


def normalize_label(text):
    text = text.lower().replace("ё", "е").translate(str.maketrans("aceopxy", "асеорху"))
    text = text.replace("главная", "главное")
    for wrong, correct in (
        ("гпавное", "главное"),
        ("гявное", "главное"),
        ("напоги", "налоги"),
        ("ощеты", "отчеты"),
    ):
        text = text.replace(wrong, correct)
    return re.sub(r"[^а-яa-z0-9]", "", text)


def money_value(text):
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*миллион\w*(?:\s+(\d+)\s*(тысяч\w*)?)?", text.lower())
    if not match:
        return None
    value = Decimal(match[1].replace(",", ".")) * 1_000_000
    if match[2]:
        value += Decimal(match[2]) * 1000
    return value


def read_money(text):
    text = text.strip().replace("D", "0").replace("О", "0").replace("O", "0")
    if not re.fullmatch(r"[\d\s.,]+", text):
        return None
    # OCR sometimes drops the comma but keeps two isolated decimal digits.
    text = re.sub(r"(?<=\d)\s+(\d{2})$", r",\1", text)
    text = re.sub(r"\s+", "", text).replace(",", ".")
    try:
        return Decimal(text)
    except Exception:
        return None


def label_query(ann):
    if "поступление на расчетный счет" in ann["label"].lower():
        return "Поступление на расчетный счет"
    query = re.sub(r"^в\s+источниках\s+", "", ann["label"], flags=re.I)
    query = re.sub(r"^источники\s+", "", query, flags=re.I)
    query = re.sub(r"^(?:переходим\s+(?:во?\s+)?(?:вкладку|раздел)|выбираем|нажимаем|клавиша|кнопка|открываем)\s+", "", query, flags=re.I)
    query = re.sub(r"^(?:(?:пункт\s+меню|меню|пункт|закладка|вкладка|вкладку|кнопку|кнопка|раздел)\s+)+", "", query, flags=re.I)
    if re.match(r"^плюс\b", query, flags=re.I):
        query = "плюс"
    return query


def phrase_focus(ann, voice):
    """Approximate word location within the synthesized phrase, not a forced alignment."""
    if ann.get("speech_cue"):
        return float(ann["speech_cue"]["start"])
    context = str(
        voice.get("subtitle_text") or voice.get("text") or ann.get("speech_context") or ""
    )
    query = label_query(ann)
    words = list(re.finditer(r"\w+", context.lower()))
    needle = re.findall(r"\w+", query.lower())
    index = next(
        (
            i
            for i in range(len(words))
            if needle and normalize_label(words[i][0]) == normalize_label(needle[0])
        ),
        0,
    )
    fraction = index / max(1, len(words))
    start = float(voice.get("audio_start", ann["target_start"]))
    end = float(voice.get("audio_end", ann["target_end"]))
    return start + fraction * (end - start)


def zoom_boxes(frame, seed, query, cache_dir, numeric=False):
    from src.services.grounded_screen_annotations import _reader

    h, w = frame.shape[:2]
    b = seed["bbox"]
    x = max(0, int(b["x"] * w) - (80 if numeric else 15))
    y = max(0, int(b["y"] * h) - 5)
    right = min(w, int((b["x"] + b["width"]) * w) + (35 if numeric else max(90, len(query) * 6)))
    bottom = min(h, int((b["y"] + b["height"]) * h) + 5)
    crop = frame[y:bottom, x:right]
    key = hashlib.sha256(crop.tobytes() + str(numeric).encode()).hexdigest()
    cache_dir.mkdir(exist_ok=True, parents=True)
    path = cache_dir / (key + ".json")
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
    else:
        options = {"allowlist": "0123456789., "} if numeric else {}
        raw = []
        for polygon, text, confidence in _reader().readtext(
            cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC), **options
        ):
            xs, ys = [float(p[0]) / 3 for p in polygon], [float(p[1]) / 3 for p in polygon]
            raw.append(
                {
                    "text": text,
                    "confidence": float(confidence),
                    "rect": [min(xs), min(ys), max(xs), max(ys)],
                }
            )
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return [
        {
            "id": "zoom",
            "text": r["text"],
            "ocr_confidence": r["confidence"],
            "bbox": {
                "x": max(0, x + r["rect"][0] - 4) / w,
                "y": max(0, y + r["rect"][1] - 3) / h,
                "width": (r["rect"][2] - r["rect"][0] + 8) / w,
                "height": (r["rect"][3] - r["rect"][1] + 6) / h,
            },
        }
        for r in raw
        if r["confidence"] >= (0.65 if numeric else 0.40)
    ]


def candidates(frame, boxes, ann, cache_dir, force_zoom=False):
    from src.services.grounded_screen_annotations import disambiguate_amount

    query = label_query(ann)
    expected = money_value(query)
    context = str(ann.get("speech_context") or "")

    def matches(box):
        if expected is not None:
            return read_money(box["text"]) == expected
        text = normalize_label(box["text"])
        wanted = normalize_label(query)
        if query == "Поступление на расчетный счет":
            # A document row must also match a spoken month when one is given.
            months = [
                "январ",
                "феврал",
                "март",
                "апрел",
                "мае",
                "июн",
                "июл",
                "август",
                "сентябр",
                "октябр",
                "ноябр",
                "декабр",
            ]
            month = next((i + 1 for i, m in enumerate(months) if m in context.lower()), None)
            return SequenceMatcher(None, wanted, text[: len(wanted)]).ratio() >= 0.88 and (
                month is None or re.search(rf"\d{{2}}[.,]{month:02d}[.,]\d{{4}}", box["text"])
            )
        return SequenceMatcher(None, wanted, text).ratio() >= 0.90

    direct = [b for b in boxes if matches(b)]
    if not direct and query == "Поступление на расчетный счет":
        # A selection border can lower full-frame OCR confidence enough to
        # omit the selected row. Re-read colored row outlines at higher scale;
        # accept only the same document name AND the spoken month.
        h, w = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (18, 80, 150), (40, 255, 255))
        for contour in cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[0]:
            x, y, width, height = cv2.boundingRect(contour)
            if not (0.08 * w < width < 0.7 * w and 15 < height < 0.07 * h):
                continue
            seed = {"bbox": {"x": x / w, "y": y / h, "width": width / w, "height": height / h}}
            direct.extend(b for b in zoom_boxes(frame, seed, query, cache_dir) if matches(b))
        # These boxes already come from this exact frame.
        if direct:
            force_zoom = False
    if not direct or force_zoom:
        previous_direct = direct
        direct = []
        if expected is not None:
            seeds = [
                b
                for b in boxes
                if read_money(b["text"]) is not None and len(re.sub(r"\D", "", b["text"])) >= 5
            ]
        else:
            tokens = [normalize_label(t) for t in query.split() if len(t) >= 4]
            seeds = [
                b
                for b in boxes
                if any(
                    SequenceMatcher(None, t, normalize_label(word)).ratio() >= 0.75
                    for t in tokens
                    for word in b["text"].split()
                )
            ]
        if force_zoom and previous_direct:
            seeds = previous_direct
        for seed in seeds[:8]:
            refined = zoom_boxes(frame, seed, query, cache_dir, numeric=expected is not None)
            direct.extend(b for b in refined if matches(b))
    if expected is not None and "доход" in context.lower():
        direct = [
            corrected
            for b in direct
            if (corrected := disambiguate_amount(b, boxes + direct, context)) is not None
        ]
    unique = []
    for box in direct:
        if not any(
            abs(box["bbox"]["x"] - b["bbox"]["x"]) < 0.01
            and abs(box["bbox"]["y"] - b["bbox"]["y"]) < 0.01
            for b in unique
        ):
            unique.append(box)
    return unique


def outside_arrow(ann):
    """Point to the edge, keeping the arrow shaft off the label."""
    if ann.get("type") != "arrow" or not ann.get("placement_confirmed"):
        return ann
    track = []
    for evidence in ann["visual_evidence"]:
        box = evidence["anchor"]
        left = box["x"] + box["width"] < 0.85
        anchor = {
            "x": box["x"] + box["width"] + 0.006 if left else box["x"] - 0.006,
            "y": box["y"] + box["height"] / 2,
            "width": 0.0,
            "height": 0.0,
        }
        track.append({"time": evidence["time"], "anchor": anchor})
    return {
        **ann,
        "anchor": track[0]["anchor"],
        "anchor_track": track,
        "arrow_direction": "left" if left else "right",
        "arrow_length_ratio": 0.06,
    }


def track_recognized_box(reference_frame, frame, box, numeric=False, current_boxes=()):
    """Track a previously read label under a cursor; reject layout changes.

    Numeric targets keep the stricter glyph threshold: neighboring amounts
    cannot be accepted merely because their containers have the same color.
    """
    b = box["bbox"]
    if numeric:
        expected = read_money(box["text"])
        for current in current_boxes:
            cb = current["bbox"]
            cx, cy = cb["x"] + cb["width"] / 2, cb["y"] + cb["height"] / 2
            value = read_money(current["text"])
            if (
                b["x"] <= cx <= b["x"] + b["width"]
                and b["y"] <= cy <= b["y"] + b["height"]
                and current.get("ocr_confidence", 0) >= 0.8
                and value is not None
                and value != expected
            ):
                return False
    h, w = frame.shape[:2]
    x, y = int(b["x"] * w), int(b["y"] * h)
    right, bottom = int((b["x"] + b["width"]) * w), int((b["y"] + b["height"]) * h)
    old, new = reference_frame[y:bottom, x:right], frame[y:bottom, x:right]
    if not old.size or old.shape != new.shape or old.std() < 1:
        return False
    correlation = float(cv2.matchTemplate(new, old, cv2.TM_CCOEFF_NORMED)[0, 0])
    old_edges = cv2.Canny(cv2.cvtColor(old, cv2.COLOR_BGR2GRAY), 70, 150) > 0
    new_edges = cv2.Canny(cv2.cvtColor(new, cv2.COLOR_BGR2GRAY), 70, 150) > 0
    score = float(2 * (old_edges & new_edges).sum() / max(1, old_edges.sum() + new_edges.sum()))
    return correlation >= 0.7 and score >= (0.80 if numeric else 0.72)
