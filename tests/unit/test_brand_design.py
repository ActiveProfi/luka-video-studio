import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from src.config import Settings
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services import brand_design_service as service
from src.services.lesson_options_service import LessonOptions
from src.services.lesson_title_service import draw_card


def logo_bytes(color="red"):
    buffer = io.BytesIO()
    Image.new("RGBA", (200, 60), color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_logo_is_decoded_not_accepted_by_filename(tmp_path):
    r = ArtifactRegistry(tmp_path)
    with pytest.raises(ValueError):
        service.store_logo(r, b"<svg>invalid</svg>")
    service.store_logo(r, logo_bytes())
    with Image.open(r.artifact_path(service.LOGO_FILE)) as image:
        assert image.size == (200, 60) and image.mode == "RGBA"
    with pytest.raises(ValueError):
        service.store_logo(r, b"x" * (service.MAX_LOGO_BYTES + 1))
    assert Image.open(r.artifact_path(service.LOGO_FILE)).size == (200, 60)


def test_design_uses_context_preserves_title_and_logo_invalidates_cache(tmp_path, monkeypatch):
    r = ArtifactRegistry(tmp_path)
    r.save_json("speech_script_auto.json", {"items": [{"speech_text": "Проверим доходы на УСН"}]})
    options = LessonOptions(title="Моё точное название", company_description="Обучаем бухгалтеров")
    calls = []

    async def complete(settings, prompt, payload, *, validate_response):
        data = json.loads(payload)
        calls.append(data)
        assert data["company_description"] == options.company_description
        assert "доходы" in data["lesson_context"]
        raw = json.dumps(
            {
                "title": "Самовольная замена",
                "subtitle": "Работа в 1С",
                "background": "#102030",
                "accent": "#22bbcc",
                "layout": "left",
            }
        )
        validate_response(raw)
        return raw, "test"

    monkeypatch.setattr(service, "complete_with_fallback", complete)
    first = service.prepare_brand_design(r, options, Settings())
    assert first["design"]["title"] == options.title
    assert service.prepare_brand_design(r, options, Settings()) == first
    assert len(calls) == 1
    service.store_logo(r, logo_bytes())
    changed = service.prepare_brand_design(r, options, Settings())
    assert changed["logo_used"] and changed["input_hash"] != first["input_hash"]
    assert calls[-1]["logo_palette"] == ["#ff0000"]
    draw_card(
        tmp_path / "card.png",
        options.title,
        "Тест",
        1280,
        720,
        design=changed["design"],
        company_name="Компания",
        logo_path=r.artifact_path(service.LOGO_FILE),
    )
    image = Image.open(tmp_path / "card.png")
    assert image.size == (1280, 720)
    # The original red logo is actually composited into the card.
    assert sum(p == (255, 0, 0) for p in image.getdata()) > 1000


def test_logo_api_keeps_voice_and_annotations_and_rejects_invalid_file(tmp_path, monkeypatch):
    import src.api.app as api

    r = ArtifactRegistry(tmp_path / "brand_job")
    r.save_json("lesson_options.json", LessonOptions().model_dump())
    r.artifact_path("voiceover.wav").write_bytes(b"keep audio")
    r.save_json("approved_annotations.json", {"annotations": [{"id": "keep"}]})
    r.artifact_path("final_lesson.mp4").write_bytes(b"outdated export")
    monkeypatch.setattr(api, "get_settings", lambda: Settings(output_dir=tmp_path))
    client = TestClient(api.app)
    response = client.post(
        "/jobs/brand_job/logo", files={"logo": ("image.png", b"wrong", "image/png")}
    )
    assert response.status_code == 400
    assert r.exists("final_lesson.mp4")
    response = client.post(
        "/jobs/brand_job/logo", files={"logo": ("image.png", logo_bytes(), "image/png")}
    )
    assert response.status_code == 200 and response.json()["logo_url"]
    assert r.exists("final_lesson.mp4")
    assert r.exists("render_pending.json")
    assert r.artifact_path("voiceover.wav").read_bytes() == b"keep audio"
    assert r.load_json("approved_annotations.json")["annotations"] == [{"id": "keep"}]
    updated = client.put(
        "/jobs/brand_job/options",
        json=LessonOptions(company_name="Актив Профи", intro_seconds=8).model_dump(),
    )
    assert updated.status_code == 200
    assert client.get("/jobs/brand_job/options").json()["intro_seconds"] == 8
    assert client.delete("/jobs/brand_job/logo").status_code == 200
    assert client.get("/jobs/brand_job/options").json()["logo_url"] is None


def test_unavailable_ai_is_reported_as_template(tmp_path, monkeypatch):
    async def unavailable(*args, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(service, "complete_with_fallback", unavailable)
    result = service.prepare_brand_design(
        ArtifactRegistry(tmp_path), LessonOptions(title="Мой урок"), Settings()
    )
    assert result["method"] == "template" and result["warning"]
    assert result["design"]["title"] == "Мой урок"


def test_new_video_upload_saves_logo_and_company_context(tmp_path, monkeypatch):
    import src.api.app as api

    monkeypatch.setattr(api, "get_settings", lambda: Settings(output_dir=tmp_path))
    monkeypatch.setattr(api, "new_job_id", lambda: "new_brand_job")
    monkeypatch.setattr(api, "run_input_ingestion", lambda *args: None)
    monkeypatch.setattr(api, "_schedule_processing", lambda *args: None)
    monkeypatch.setattr(api, "_build_stages", lambda *args: [])
    options = LessonOptions(title="Новый урок", company_description="Обучение бухгалтеров")
    response = TestClient(api.app).post(
        "/jobs/upload",
        data={"options": options.model_dump_json()},
        files={
            "video": ("screen.mp4", b"video-input", "video/mp4"),
            "company_logo": ("logo.png", logo_bytes(), "image/png"),
        },
    )
    assert response.status_code == 200
    r = ArtifactRegistry(tmp_path / "new_brand_job")
    assert r.exists(service.LOGO_FILE)
    assert r.load_json("lesson_options.json")["company_description"] == options.company_description


def test_unchanged_subtitle_style_keeps_final_video(tmp_path, monkeypatch):
    from src.services import subtitle_capture_service as capture

    r = ArtifactRegistry(tmp_path)
    r.save_json(capture.SUBTITLE_LAYOUT, {"font_color": "#ffff00", "font_bold": True})
    r.artifact_path("final_lesson.mp4").write_bytes(b"keep final")
    monkeypatch.setattr(capture, "get_capture_payload", lambda *args: {"ok": True})
    capture.save_layout(r, "job", {"font_color": "#ffff00"})
    assert r.artifact_path("final_lesson.mp4").read_bytes() == b"keep final"
    capture.save_layout(r, "job", {"font_bold": False})
    assert r.artifact_path("final_lesson.mp4").read_bytes() == b"keep final"
    assert r.exists("render_pending.json")


@pytest.mark.parametrize("seconds", [0, 2, 16])
def test_intro_duration_rejects_unreadable_or_excessive_values(seconds):
    with pytest.raises(ValueError):
        LessonOptions(intro_seconds=seconds)
