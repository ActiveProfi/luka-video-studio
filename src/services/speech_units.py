"""Sentence-sized speech units on the original recording's time axis."""

import re


def group_speech_units(items: list[dict], text_key: str = "text") -> list[dict]:
    result: list[dict] = []
    for item in items:
        text = str(item.get(text_key) or "").strip()
        if not text:
            continue
        previous = result[-1] if result else None
        join = (
            previous is not None
            and not re.search(r"[.!?][»\"]?$", previous[text_key])
            and 0 <= float(item["start"]) - float(previous["end"]) <= 0.6
            and float(item["end"]) - float(previous["start"]) <= 20
        )
        source_id = item.get("segment_id", item.get("id"))
        if join:
            previous[text_key] += " " + text
            previous["end"] = item["end"]
            previous["source_ids"].append(source_id)
            if "words" in previous:
                previous["words"] = previous["words"] + item.get("words", [])
            if item.get("confidence") is not None:
                previous["confidence"] = min(previous.get("confidence") or 1, item["confidence"])
        else:
            result.append({**item, text_key: text, "source_ids": [source_id]})
    return result
