from src.providers.stt.base import TranscriptSegment
from src.services.transcript_alignment import align_transcript


def test_context_corrections_keep_all_words_and_local_anchor_times():
    anchors = [
        TranscriptSegment("a", 1, 5, "Компания находится новое СН."),
        TranscriptSegment("b", 6, 10, "НДС не применяется."),
    ]
    text = "Компания находится на УСН. НДС не применяется."
    result = align_transcript(text, anchors)
    assert " ".join(s.text for s in result) == text
    assert [(s.start, s.end) for s in result] == [(1, 5), (6, 10)]
    assert result[0].text == "Компания находится на УСН."
    assert result[1].text == "НДС не применяется."


def test_alignment_keeps_inserted_numbers_without_fabricated_word_timestamps():
    anchors = [
        TranscriptSegment("a", 1, 5, "Доходы 19,3 млн."),
        TranscriptSegment("b", 6, 10, "Проверяем отчет."),
    ]
    text = "Доходы 19 миллионов 300 тысяч. Проверяем отчет."
    result = align_transcript(text, anchors)
    assert " ".join(s.text for s in result) == text
    assert all(not s.words and s.confidence is None for s in result)
