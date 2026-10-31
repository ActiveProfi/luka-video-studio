"""Connected advertising speech: one utterance, measured sentence boundaries."""

import hashlib
import json
import shutil
from difflib import SequenceMatcher

from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.voice_word_timing import speech_tokens

PROSODY_VERSION = 1


def align_sentences(texts, spoken, words, duration):
    # ASR often writes the original spelling (Very Fast), even when TTS was
    # given a pronunciation hint (Вери Фаст). Both represent the same script.
    try:
        return _align_sentence_tokens(texts, spoken, words, duration)
    except ValueError:
        if texts == spoken:
            raise
        return _align_sentence_tokens(texts, texts, words, duration)


def _align_sentence_tokens(texts, spoken, words, duration):
    if not texts or len(texts) != len(spoken):
        raise ValueError("Нет реплик для измерения озвучки")
    expected, spans = [], []
    for text in spoken:
        start = len(expected)
        expected.extend(speech_tokens(text))
        spans.append((start, len(expected)))
    measured = [(token, word) for word in words for token in speech_tokens(word["word"])]
    matching = SequenceMatcher(None, expected, [t for t, _ in measured], autojunk=False)
    positions = {}
    for block in matching.get_matching_blocks():
        for offset in range(block.size):
            positions[block.a + offset] = measured[block.b + offset][1]
    cues = []
    for text, (start, end) in zip(texts, spans):
        matches = [positions[i] for i in range(start, end) if i in positions]
        if not matches or len(matches) / max(1, end - start) < 0.65:
            raise ValueError("Не удалось надёжно измерить границы связной озвучки")
        left, right = max(0, matches[0]["start"]), min(duration, matches[-1]["end"])
        if right <= left or (cues and left < cues[-1]["end"]):
            raise ValueError("Нарушен порядок измеренных реплик")
        cues.append({"start": left, "end": right, "text": text})
    # No extra silence is inserted. These marks only steer video and captions.
    cues[0]["start"] = 0.0
    return cues


def measure_sentences(registry, settings, texts, spoken, duration):
    from src.services.voice_word_timing import ensure_voice_word_timing

    timing = ArtifactRegistry(registry.job_dir / "connected-speech-timing")
    shutil.copy2(registry.artifact_path("promo_voice.wav"), timing.artifact_path("voiceover.wav"))
    timing.save_json(
        "voiceover_segments.json",
        {
            "segments": [
                {"transcript_segment_id": "paragraph", "audio_start": 0, "audio_end": duration}
            ]
        },
    )
    doc = ensure_voice_word_timing(timing, settings)
    return align_sentences(texts, spoken, doc["segments"][0]["words"], duration)


def create_connected_speech(draft, registry, speech, settings):
    from src.services.auto_voiceover_service import _synthesize
    from src.services.contextual_pronunciation import prepare_contextual_speech
    from src.services.tts_normalization_rules import pronunciation_rules_hash

    blocks = [{"id": i + 1, "subtitle": text} for i, text in enumerate(draft.narration)]
    prepared = prepare_contextual_speech(blocks, registry, speech)
    spoken = [prepared[str(b["id"])].strip() for b in blocks]
    # Sentence punctuation supplies linguistic boundaries, without equal-length gaps.
    paragraph = " ".join(t if t.endswith((".", "!", "?", "…")) else t + "." for t in spoken)
    voice = {
        k: v
        for k, v in speech.model_dump().items()
        if k
        in {
            "tts_provider",
            "yandex_tts_voice",
            "yandex_tts_emotion",
            "yandex_tts_speed",
            "openai_tts_model",
            "openai_tts_voice",
            "openai_tts_speed",
            "elevenlabs_model",
            "elevenlabs_voice_id",
            "elevenlabs_speed",
            "edge_tts_voice",
            "edge_tts_speed",
        }
    }
    key = hashlib.sha256(
        json.dumps(
            [PROSODY_VERSION, paragraph, voice, pronunciation_rules_hash(speech)], sort_keys=True
        ).encode()
    ).hexdigest()
    audio = registry.artifact_path("promo_voice.wav")
    cached = (
        registry.load_json("connected_voice.json")
        if registry.exists("connected_voice.json")
        else {}
    )
    if cached.get("key") == key and audio.exists():
        duration, provider = cached["duration"], cached["provider"]
    else:
        duration, provider = _synthesize(paragraph, audio, settings.default_language, speech)
        registry.save_json(
            "connected_voice.json",
            {
                "key": key,
                "duration": duration,
                "provider": provider,
                "text": paragraph,
                "method": "single_paragraph",
                "inserted_pause_seconds": 0,
            },
        )
    if duration > 54:
        raise ValueError("Связная рекламная озвучка превышает 54 секунды")
    cues = measure_sentences(registry, settings, draft.narration, spoken, duration)
    registry.save_json(
        "prosody-report.json",
        {
            "method": "single_paragraph_with_local_word_alignment",
            "duration": duration,
            "sentence_gaps": [round(b["start"] - a["end"], 3) for a, b in zip(cues, cues[1:])],
            "artificial_gaps": False,
            "cues": cues,
        },
    )
    return duration, cues
