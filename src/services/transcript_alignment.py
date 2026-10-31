"""Align revised recognition to acoustic segment anchors using matching words."""

import re
from difflib import SequenceMatcher

from src.providers.stt.base import TranscriptSegment


def align_transcript(text: str, anchors: list[TranscriptSegment]) -> list[TranscriptSegment]:
    words = text.split()
    old, owners = [], []
    for index, segment in enumerate(anchors):
        tokens = segment.text.split()
        old.extend(tokens)
        owners.extend([index] * len(tokens))
    if not old or not words:
        raise ValueError("Cannot align an empty transcript")
    def normalize(value):
        return re.sub(r"[^\w]", "", value.casefold())
    matcher = SequenceMatcher(
        None, list(map(normalize, old)), list(map(normalize, words)), autojunk=False
    )
    assigned = [[] for _ in anchors]
    for tag, a, b, c, d in matcher.get_opcodes():
        for offset, word in enumerate(words[c:d]):
            source_index = (
                a + offset if tag == "equal" else a + int(offset * (b - a) / max(1, d - c))
            )
            owner = owners[min(source_index, len(owners) - 1)]
            assigned[owner].append(word)
    return [
        TranscriptSegment(segment.segment_id, segment.start, segment.end, " ".join(tokens))
        for segment, tokens in zip(anchors, assigned)
        if tokens
    ]
