import json
import subprocess

import pytest

from src.config import Settings
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services import short_video_service as service
from src.services.ffmpeg_service import _ffmpeg_bin, _ffprobe_bin
from src.services.lesson_options_service import LessonOptions


@pytest.mark.parametrize(
    "raw",
    ['{"clips":[]}', '```\n{"clips":[]}\n```', '```JSON\n{"clips":[]}\n```', 'Ответ: {"clips":[]}'],
)
def test_provider_json_formats(raw):
    assert service.parse_json_response(raw) == {"clips": []}


def test_eleven_ad_phrases_are_merged_without_losing_words_or_cta():
    phrases = [f"Фраза {i}." for i in range(10)] + ["Полный разбор — в основном видео."]
    normalized = service.normalize_ad_narration(phrases)
    assert len(normalized) == 8
    assert " ".join(normalized) == " ".join(phrases)
    assert phrases[-1] in normalized[-1]
    assert len(phrases) == 11


def test_phrase_merging_does_not_bypass_total_word_limit():
    narration = service.normalize_ad_narration(["слово " * 10] * 11)
    with pytest.raises(ValueError, match="100 слов"):
        service.ShortDraft(kind="promo", title="Тест", start=0, end=20, narration=narration)


@pytest.mark.parametrize("platform", [None, "vk", "reels", "shorts"])
def test_separate_selection_advertising_and_fact_check(tmp_path, monkeypatch, platform):
    parent = ArtifactRegistry(tmp_path)
    parent.artifact_path("final_lesson.mp4").write_bytes(b"video")
    parent.save_json(
        "speech_script_auto.json",
        {
            "items": [
                {
                    "start": 0,
                    "end": 20,
                    "subtitle": "Открываем документ в 1С и проверяем сумму 500 рублей.",
                }
            ]
        },
    )
    calls = []
    responses = [
        {"clips": [{"title": "Документ в 1С", "start": 0, "end": 20}]},
        {
            "narration": [
                "Показываем проверку документа в 1С.",
                "Проверяем сумму 500 рублей.",
                "Посмотрите полный урок.",
            ]
        },
        {"supported": True, "reason": "Supported"},
    ]

    async def complete(settings, system, user, validate_response=None):
        calls.append(system)
        raw = json.dumps(responses[len(calls) - 1], ensure_ascii=False)
        validate_response(raw)
        return raw, "test"

    monkeypatch.setattr(service, "complete_with_fallback", complete)
    result = service.create_drafts(parent, Settings(), "Полный урок", "both", platform)
    assert len(calls) == 3 and {d["draft"]["kind"] for d in result} == {"excerpt", "promo"}
    assert all(d["draft"]["target_platform"] == platform for d in result)
    if platform:
        assert f"Профиль {platform}" in calls[0] and f"Профиль {platform}" in calls[1]
    assert parent.artifact_path("final_lesson.mp4").read_bytes() == b"video"


def test_shifted_annotations_keep_source_immutable():
    original = [
        {
            "placement_confirmed": True,
            "target_start": 5,
            "target_end": 8,
            "anchor_track": [{"time": 5, "anchor": {"x": 0.2}}],
        }
    ]
    shifted = service.shifted_annotations(original, 6, 12)
    assert shifted[0]["target_start"] == 0 and shifted[0]["target_end"] == 2
    assert shifted[0]["anchor_track"][0]["time"] == -1
    assert original[0]["anchor_track"][0]["time"] == 5


def test_platform_profile_cannot_be_relabelled(tmp_path):
    parent = ArtifactRegistry(tmp_path)
    child = ArtifactRegistry(tmp_path / "derivatives/clip_0123456789ab")
    child.save_json("project.json", {
        "source_signature": service.source_signature(parent),
        "draft": service.ShortDraft(kind="promo", target_platform="vk", title="Пример",
                                    start=0, end=20, narration=["Проверяем документ."]).model_dump(),
        "status": "draft", "exports": {},
    })
    with pytest.raises(ValueError, match="другой площадки"):
        service.render_short(parent, Settings(), "clip_0123456789ab", "reels")
    assert child.load_json("project.json")["status"] == "draft"


@pytest.mark.parametrize("start,end", [(5, 3), (0, 55), (-1, 10), (0, 1)])
def test_invalid_ranges_rejected(start, end):
    with pytest.raises(ValueError):
        service.ShortDraft(kind="excerpt", title="test", start=start, end=end)


def test_source_change_preserves_previous_short(tmp_path):
    parent = ArtifactRegistry(tmp_path)
    child = ArtifactRegistry(tmp_path / "derivatives/clip_0123456789ab")
    child.save_json("project.json", {"source_signature": "old"})
    child.artifact_path("shorts.mp4").write_bytes(b"old export")
    with pytest.raises(ValueError, match="изменён"):
        service.render_short(parent, Settings(), "clip_0123456789ab", "shorts")
    assert child.artifact_path("shorts.mp4").read_bytes() == b"old export"


def test_real_vertical_export_preserves_parent(tmp_path, monkeypatch):
    settings = Settings()
    try:
        ffmpeg = _ffmpeg_bin(settings)
    except RuntimeError:
        pytest.skip("FFmpeg not available")
    parent = ArtifactRegistry(tmp_path / "lesson")
    source = parent.artifact_path("edited_video.mp4")
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=640x360:r=30:d=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=3",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    parent.save_json(
        "subtitle_timing.json",
        {"cues": [{"start": 0, "end": 3, "text": "Полезный фрагмент урока"}]},
    )
    parent.save_json("approved_annotations.json", {"annotations": []})
    parent.save_json("lesson_options.json", LessonOptions(company_name="Компания").model_dump())
    before = service.source_signature(parent)
    child = ArtifactRegistry(parent.job_dir / "derivatives/clip_0123456789ab")
    draft = service.ShortDraft(kind="excerpt", title="Один понятный шаг", start=0, end=3)
    child.save_json(
        "project.json", {"source_signature": before, "draft": draft.model_dump(), "exports": {}}
    )
    result = service.render_short(parent, settings, "clip_0123456789ab", "shorts")
    assert result["status"] == "ready"
    output = result["exports"]["shorts"]
    assert (output["width"], output["height"]) == (1080, 1920)
    assert output["has_audio"] and output["duration_seconds"] == pytest.approx(3, abs=0.15)
    assert service.source_signature(parent) == before
    # A second platform reuses the finished master, without another render/TTS call.
    original_run = service._run
    monkeypatch.setattr(service, "_run", lambda *a, **k: pytest.fail("unexpected re-render"))
    copied = service.render_short(parent, settings, "clip_0123456789ab", "vk")
    assert copied["exports"]["vk"]["width"] == 1080
    monkeypatch.setattr(service, "_run", original_run)

    saved_doc = child.load_json("project.json")
    saved_doc.update(status="failed", error="TTS unavailable")
    child.save_json("project.json", saved_doc)
    with monkeypatch.context() as m:
        m.setattr(service, "_render", lambda *a: pytest.fail("Existing export was rebuilt"))
        restored = service.render_short(parent, settings, "clip_0123456789ab", "vk")
        assert restored["status"] == "ready" and restored["error"] is None

    # New advertising narration has its own audio, and heading edits reuse it.
    from src.services import auto_voiceover_service, contextual_pronunciation

    synthesis_calls = []

    def synthesize(text, path, language, cfg):
        synthesis_calls.append(text)
        subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=660:duration=1",
                "-ar",
                "48000",
                "-ac",
                "1",
                str(path),
            ],
            check=True,
            capture_output=True,
        )
        return 1.0, "test"

    monkeypatch.setattr(auto_voiceover_service, "_synthesize", synthesize)
    from src.services import promo_motion_service, promo_speech_service

    monkeypatch.setattr(
        promo_speech_service,
        "measure_sentences",
        lambda registry, settings, texts, spoken, duration: [
            {"start": 0, "end": duration, "text": texts[0]}
        ],
    )

    monkeypatch.setattr(
        promo_motion_service,
        "plan_shots",
        lambda *args: (
            [
                {
                    "unit": 0,
                    "label": "Посмотрите один понятный шаг.",
                    "reason": "Synthetic test motion",
                }
            ],
            [{"start": 0, "end": 3}],
            {},
        ),
    )
    monkeypatch.setattr(
        contextual_pronunciation,
        "prepare_contextual_speech",
        lambda blocks, *a: {str(b["id"]): b["subtitle"] for b in blocks},
    )
    promo = service.ShortDraft(
        kind="promo",
        title="Реклама урока",
        start=0,
        end=3,
        narration=["Посмотрите один понятный шаг."],
    )
    child.save_json(
        "project.json", {"source_signature": before, "draft": promo.model_dump(), "exports": {}}
    )
    service.render_short(parent, settings, "clip_0123456789ab", "reels")
    doc = child.load_json("project.json")
    assert doc["exports"]["reels"]["playback_speed"] == 1.2
    assert doc["exports"]["reels"]["duration_seconds"] == pytest.approx(1.0 / 1.2, abs=0.10)
    assert doc["exports"]["reels"]["preview_available"]
    stream = json.loads(
        subprocess.check_output(
            [
                _ffprobe_bin(settings),
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_streams",
                "-of",
                "json",
                str(child.artifact_path("preview.webm")),
            ]
        )
    )["streams"][0]
    assert stream["pix_fmt"] == "yuv420p" and stream["color_range"] == "tv"
    assert stream["color_space"] == "bt709"
    plan = child.load_json("motion-plan.json")
    assert plan["frames"] == round(1.0 / 1.2 * 30)
    assert plan["shots"][0]["text"] == promo.narration[0]

    # Preview contains moving screen pixels, not just an audio stream or poster.
    def frame(at):
        return subprocess.check_output(
            [
                ffmpeg,
                "-v",
                "error",
                "-ss",
                str(at),
                "-i",
                str(child.artifact_path("preview.webm")),
                "-frames:v",
                "1",
                "-vf",
                "crop=460:170:40:285,scale=32:16",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ]
        )

    assert frame(0.1) != frame(0.7)
    doc["draft"]["title"] = "Другой заголовок"
    doc["revision"] = doc.get("revision", 1) + 1
    child.save_json("project.json", doc)
    service.render_short(parent, settings, "clip_0123456789ab", "shorts")
    assert len(synthesis_calls) == 1
    assert service.source_signature(parent) == before
