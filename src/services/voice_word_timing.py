"""Measure word times on the final synthesized audio, after trimming and speed changes."""

import hashlib
import json
import re

from src.services.speech_script_auto import build_speech_text
from src.services.spoken_amounts import SCALES, _form, _words


def speech_tokens(text):
    for alias, spelling in ((r"\bnds\b", "НДС"), (r"\b(?:ok|окей)\b", "ОК"), (r"\baudio\b", "аудио"), (r"\bvideo\b", "видео")):
        text = re.sub(alias, spelling, text, flags=re.I)
    text = build_speech_text(text).lower().replace("ё", "е")
    text = text.replace("главную", "главное").replace("главная", "главное")
    text = text.replace("клавишу", "клавиша").replace("кнопку", "кнопка")
    text = re.sub(r"\bрасширенн(?:ая|ые|ую|ый)\b", "расширенные", text)
    text = re.sub(r"(?<=\d)\s+(?=\d{3}(?:\D|$))", "", text)

    def number(match):
        n = int(match[0])
        if n >= 10**12:
            return match[0]
        parts = []
        for size, forms in SCALES:
            count, n = divmod(n, size)
            if count:
                parts.append(_words(count, size == 1000))
                if size > 1:
                    parts.append(_form(count, forms))
        return " ".join(parts) or "ноль"

    text = re.sub(r"\d+", number, text)
    return re.findall(r"[а-яa-z]+", text)


def ensure_voice_word_timing(registry, settings):
    """Cached local ASR measurements; never fabricate timestamps by word count."""
    import numpy as np
    from faster_whisper import WhisperModel
    from scipy.io import wavfile

    audio = registry.artifact_path("voiceover.wav")
    digest = hashlib.sha256(audio.read_bytes()).hexdigest()
    path = registry.artifact_path("voiceover_word_timing.json")
    voice = registry.load_json("voiceover_segments.json")
    signature = hashlib.sha256(json.dumps(voice["segments"], sort_keys=True).encode()).hexdigest()
    if path.exists():
        saved = registry.load_json(path.name)
        if saved.get("audio_sha256") == digest and saved.get("segments_sha256") == signature:
            return saved
    rate, samples = wavfile.read(audio)
    if samples.dtype.kind in "iu":
        samples = samples.astype(np.float32) / max(
            abs(np.iinfo(samples.dtype).min), np.iinfo(samples.dtype).max
        )
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    from math import gcd

    from scipy.signal import resample_poly

    divisor = gcd(rate, 16000)
    samples = resample_poly(samples, 16000 // divisor, rate // divisor).astype(np.float32)
    model = WhisperModel(
        settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )
    result = {
        "audio_sha256": digest,
        "segments_sha256": signature,
        "method": "faster_whisper_final_audio",
        "segments": [],
    }
    cache = registry.job_dir / "_voice_word_cache"
    cache.mkdir(exist_ok=True)
    for segment in voice["segments"]:
        start, end = segment["audio_start"], segment["audio_end"]
        clip = samples[round(start * 16000) : round(end * 16000)]
        key = hashlib.sha256(clip.tobytes() + settings.whisper_model.encode()).hexdigest()
        cached = cache / (key + ".json")
        if cached.exists():
            words = json.loads(cached.read_text(encoding="utf-8"))
        else:
            recognized, _ = model.transcribe(
                clip,
                language="ru",
                word_timestamps=True,
                vad_filter=False,
                condition_on_previous_text=False,
                beam_size=5,
            )
            words = [
                {
                    "word": w.word.strip(),
                    "start": w.start,
                    "end": w.end,
                    "confidence": w.probability,
                }
                for phrase in recognized
                for w in (phrase.words or [])
            ]
            cached.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
        result["segments"].append(
            {
                "segment_id": segment["transcript_segment_id"],
                "words": [
                    {
                        **w,
                        "start": round(start + w["start"], 3),
                        "end": round(min(end, start + w["end"]), 3),
                    }
                    for w in words
                ],
            }
        )
        registry.save_json("voiceover_word_timing_progress.json", result)
    registry.save_json(path.name, result)
    return result


def find_spoken_cue(ann, words):
    """Find a unique spoken label in this phrase. Ambiguous matches stay unresolved."""
    from src.services.annotation_target_matching import label_query

    query = label_query(ann)
    # Keep the action verb/control noun to disambiguate repeated mentions,
    # e.g. "ставим ... НДС" versus "будем применять НДС" in the same phrase.
    variants = [speech_tokens(ann["label"]), speech_tokens(query)]
    if re.search(r"\d[,.]\d.*миллион", query):
        variants.append(speech_tokens(query + " рублей")[:-1])
    flattened = [(token, word) for word in words for token in speech_tokens(word["word"])]
    tokens = [token for token, _ in flattened]
    matches = []
    for needle in variants:
        if needle and needle[-1] in ("рублей", "рубля", "рубль"):
            needle = needle[:-1]
        for i in range(len(tokens) - len(needle) + 1):
            if needle and tokens[i : i + len(needle)] == needle:
                selected = [w for _, w in flattened[i : i + len(needle)]]
                confidence = [w.get("confidence", 1) for w in selected]
                if min(confidence) >= 0.35 and sum(confidence) / len(confidence) >= 0.65:
                    matches.append((selected[0]["start"], selected[-1]["end"]))
        if matches:
            break
    matches = sorted(set(matches))
    if len(matches) != 1:
        return None
    return {"start": matches[0][0], "end": matches[0][1], "method": "measured_final_audio"}


def bind_spoken_cues(suggestions, timing):
    by_id = {s["segment_id"]: s["words"] for s in timing["segments"]}
    result = []
    for ann in suggestions:
        cue = find_spoken_cue(ann, by_id.get(ann.get("linked_segment_id"), []))
        bound = {**ann, "speech_cue": cue, "timing_required": True}
        if cue:
            # The measured voice is authoritative. A model's coarse suggested
            # end may precede the actual spoken action inside a long block.
            bound["target_start"] = cue["start"]
            bound["target_end"] = max(cue["start"] + 1.0, cue["end"] + .35)
        result.append(bound)
    return result


def save_annotation_timing_report(registry, items):
    rows = []
    for ann in items:
        if ann.get("skipped"):
            continue
        cue = ann.get("speech_cue")
        placed = bool(ann.get("placement_confirmed"))
        delay = round(ann["target_start"] - cue["start"], 3) if cue and placed else None
        rows.append(
            {
                "annotation_id": ann["annotation_id"],
                "label": ann["label"],
                "spoken_start": cue["start"] if cue else None,
                "annotation_start": ann["target_start"] if placed else None,
                "delay_seconds": delay,
                "status": "unresolved"
                if delay is None
                else "early"
                if delay < -0.001
                else "late"
                if delay > 0.35
                else "aligned",
            }
        )
    report = {
        "method": "measured_final_audio",
        "items": rows,
        "aligned_count": sum(row["status"] == "aligned" for row in rows),
        "early_count": sum(row["status"] == "early" for row in rows),
        "late_count": sum(row["status"] == "late" for row in rows),
        "unresolved_count": sum(row["status"] == "unresolved" for row in rows),
    }
    registry.save_json("annotation_timing_report.json", report)
    return report
