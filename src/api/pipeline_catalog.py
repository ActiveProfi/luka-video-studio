"""Описание этапов pipeline для веб-интерфейса.

Архитектура v3: пользователь видит только пять этапов —
загрузка → субтитры → озвучка → аннотации → экспорт.
Всё остальное (распознавание речи, подготовка текста, Speech Script)
работает внутри как сервис и в UI_STAGES не входит: см. LEGACY_UI_STAGES.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UIStage:
    id: str
    order: int
    title: str
    description: str
    artifact_keys: tuple[str, ...]
    preview_type: str  # video | json | text | none | stub
    preview_key: str | None = None
    is_stub: bool = False


# --- Целевая последовательность (v3) ---
# 1 загрузка (+ авторазбиение) → 2 субтитры на видео → 3 озвучка
# → 4 аннотации → 5 экспорт

UI_STAGES: list[UIStage] = [
    UIStage(
        id="upload",
        order=0,
        title="Загрузка видео",
        description=(
            "Ролик принят. Длительность, кадры, разрешение и разбивка на тайм-блоки "
            "определяются автоматически."
        ),
        artifact_keys=("input_manifest.json", "raw_video.mp4", "video_meta.json", "time_blocks.json"),
        preview_type="video",
        preview_key="raw_video.mp4",
    ),
    UIStage(
        id="subtitle_capture",
        order=1,
        title="Сценарий и субтитры",
        description=(
            "Речь автора из исходной записи превращается в очищенный сценарий и субтитры. "
            "Проверьте только спорные фрагменты; сохранённые правки остаются источником озвучки."
        ),
        artifact_keys=("time_blocks.json", "subtitles.srt", "subtitle_timing.json"),
        preview_type="none",
        preview_key=None,
    ),
    UIStage(
        id="voiceover",
        order=2,
        title="Озвучка",
        description=(
            "Полностью автоматически: текст субтитров переводится во внутренний сценарий речи, "
            "каждый блок озвучивается и подгоняется по длительности."
        ),
        artifact_keys=("voiceover.wav", "voiceover_segments.json", "edited_video.mp4"),
        preview_type="video",
        preview_key="edited_video_with_subtitles.mp4",
    ),
    UIStage(
        id="annotations",
        order=3,
        title="Аннотации",
        description=(
            "Рамки и стрелки определяются по речи, кадрам исходной записи и видимому курсору. "
            "Выделения синхронизируются с готовой озвучкой автоматически. "
            "После обработки здесь появится готовый ролик для просмотра и скачивания."
        ),
        artifact_keys=(
            "annotation_suggestions.json",
            "annotation_review.json",
            "annotation_preview.mp4",
            "approved_annotations.json",
            "final_lesson.mp4",
            "assembly_report.json",
        ),
        preview_type="video",
        preview_key="final_lesson.mp4",
    ),
]


# Внутренние и старые этапы: в списке не показываются, код и раннеры сохранены
LEGACY_UI_STAGES: list[UIStage] = [
    UIStage(
        id="export",
        order=99,
        title="[внутренний] Экспорт",
        description="Объединён с шагом «Аннотации»: сборка идёт после подтверждения.",
        artifact_keys=("final_lesson.mp4", "assembly_report.json"),
        preview_type="video",
        preview_key="final_lesson.mp4",
    ),
    UIStage(
        id="stt",
        order=100,
        title="[внутренний] Распознавание речи",
        description="Не используется в v3. Код сохранён.",
        artifact_keys=("transcript.json",),
        preview_type="json",
        preview_key="transcript.json",
    ),
    UIStage(
        id="cleanup",
        order=101,
        title="[внутренний] Подготовка текста",
        description="Не используется в v3. Код сохранён.",
        artifact_keys=("clean_transcript.json", "edits_map.json", "cleanup_review.json"),
        preview_type="json",
        preview_key="clean_transcript.json",
    ),
    UIStage(
        id="subtitle_blocks",
        order=102,
        title="[внутренний] Блоки субтитров по транскрипции",
        description="Заменён экраном субтитров v3. Код сохранён.",
        artifact_keys=("subtitles.srt", "subtitle_timing.json", "subtitle_layout.json"),
        preview_type="video",
        preview_key="raw_video.mp4",
    ),
    UIStage(
        id="voiceover_script",
        order=103,
        title="[внутренний] Speech Script",
        description="В v3 строится автоматически и пользователю не показывается.",
        artifact_keys=("voiceover_script.json",),
        preview_type="json",
        preview_key="voiceover_script.json",
    ),
    UIStage(
        id="final_voiceover",
        order=104,
        title="[внутренний] Финальная озвучка v2",
        description="Заменена автоматической озвучкой v3. Код сохранён.",
        artifact_keys=("voiceover.wav", "voiceover_segments.json", "edited_video.mp4"),
        preview_type="video",
        preview_key="edited_video.mp4",
    ),
    UIStage(
        id="assembly",
        order=105,
        title="[внутренний] Сборка урока v2",
        description="В v3 сборка идёт сразу после подтверждения аннотаций. Код сохранён.",
        artifact_keys=("final_lesson.mp4", "assembly_report.json"),
        preview_type="video",
        preview_key="final_lesson.mp4",
    ),
    UIStage(
        id="tts",
        order=106,
        title="[legacy] AI-озвучка",
        description="Старый шаг озвучки до монтажа. Код сохранён.",
        artifact_keys=("voiceover.wav", "voiceover_segments.json"),
        preview_type="audio",
        preview_key="voiceover.wav",
    ),
    UIStage(
        id="edit",
        order=107,
        title="[legacy] Монтаж видео",
        description="Старый шаг склейки raw + voiceover. Код сохранён.",
        artifact_keys=("edited_video.mp4", "video_edit_report.json"),
        preview_type="video",
        preview_key="edited_video.mp4",
    ),
    UIStage(
        id="subtitles",
        order=108,
        title="[legacy] Субтитры",
        description="Старый шаг субтитров после монтажа + подшаг 6.1. Код сохранён.",
        artifact_keys=("subtitles.srt", "subtitle_timing.json", "subtitle_layout.json"),
        preview_type="video",
        preview_key="edited_video.mp4",
    ),
]


DECISION_LABELS: dict[str, str] = {
    "remove_audio_video": "Вырезать паузу",
    "trim_soft": "Сократить фрагмент",
    "speedup_video": "Ускорить видео",
    "keep_as_is": "Оставить как есть",
    "needs_human_review": "Требует проверки",
}
