"""API for independent short-video drafts and exports."""

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from src.config import get_settings
from src.domain.contracts import utc_now_iso
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services import job_execution
from src.services.short_video_service import (
    PLATFORMS,
    ShortDraft,
    create_drafts,
    list_shorts,
    render_short,
    short_registry,
)

router = APIRouter(prefix="/jobs/{job_id}/shorts")


@router.api_route("/lesson-approval", methods=["GET", "POST"])
def lesson_approval(job_id: str, request: Request):
    from src.services.deliverable_approval import approval_status, approve_output
    parent, ensure_idle = parent_registry(job_id)
    source = parent.artifact_path("final_lesson.mp4")
    if request.method == "GET":
        return approval_status(parent, source, "lesson_approval.json")
    ensure_idle(parent)
    if parent.exists("render_pending.json"):
        raise HTTPException(409, "Сначала завершите сборку урока с текущими правками")
    try:
        return approve_output(parent, source, "lesson_approval.json", "Итоговые видео инструкции", job_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/guide")
def format_guide(job_id: str):
    path = Path(__file__).resolve().parents[2] / "docs" / "Сравнение VK Клипов, Reels и Shorts.html"
    return FileResponse(path, media_type="text/html")


def parent_registry(job_id):
    from src.api.app import _ensure_pipeline_not_running, _registry

    return _registry(job_id), _ensure_pipeline_not_running


def state_registry(parent):
    return ArtifactRegistry(parent.job_dir / "derivatives")


class PlanRequest(BaseModel):
    target_platform: Literal["shorts", "reels", "vk", "all"] | None = None
    kind: Literal["both", "excerpt", "promo"] = "both"
    render: bool = False
    cta: str = Field(default="Полный разбор — в основном видео", min_length=1, max_length=150)


class RenderRequest(BaseModel):
    platform: Literal["shorts", "reels", "vk"] = "shorts"


@router.get("/{short_id}/approve")
def short_approval_status(job_id: str, short_id: str, platform: Literal["shorts", "reels", "vk"]):
    from src.services.deliverable_approval import approval_status
    parent, _ = parent_registry(job_id)
    registry = short_registry(parent, short_id)
    result = approval_status(registry, registry.artifact_path(f"{platform}.mp4"), f"approval_{platform}.json")
    doc = registry.load_json("project.json")
    legacy = doc.get("approval", {})
    output = doc.get("exports", {}).get(platform, {})
    if (legacy.get("status") == "approved" and legacy.get("platform") == platform
            and legacy.get("export_created_at") == output.get("created_at")
            and legacy.get("revision", 1) == doc.get("revision", 1)):
        result["approved"] = True
    if output.get("revision", 1) != doc.get("revision", 1):
        result["approved"] = False
    return result


@router.post("/{short_id}/approve")
def approve_short(job_id: str, short_id: str, payload: RenderRequest):
    from src.services.deliverable_approval import approve_output
    parent, ensure_idle = parent_registry(job_id)
    ensure_idle(parent)
    registry = short_registry(parent, short_id)
    doc = registry.load_json("project.json")
    output = doc.get("exports", {}).get(payload.platform)
    if not output or output.get("revision", 1) != doc.get("revision", 1):
        raise HTTPException(409, "Сначала соберите ролик с текущими правками")
    try:
        return approve_output(registry, registry.artifact_path(f"{payload.platform}.mp4"),
                              f"approval_{payload.platform}.json", "Итоговые рекламные ролики",
                              f"{job_id}_{short_id}_{payload.platform}")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


def background_work(parent, action):
    state = state_registry(parent)
    try:
        action()
        state.save_json("state.json", {"status": "completed", "updated_at": utc_now_iso()})
    except Exception as exc:
        message = str(exc)
        settings = get_settings()
        for secret in (
            settings.openai_api_key,
            settings.yandex_api_key,
            settings.yandex_gpt_api_key,
        ):
            if secret:
                message = message.replace(secret, "[redacted]")
        state.save_json(
            "state.json", {"status": "failed", "error": message[:1000], "updated_at": utc_now_iso()}
        )
    finally:
        job_execution.release(parent.job_dir.name)


def queue(parent, tasks, action):
    from src.api.app import _ensure_pipeline_not_running

    _ensure_pipeline_not_running(parent)
    if not job_execution.reserve(parent.job_dir.name):
        raise HTTPException(409, "Проект уже обрабатывается")
    try:
        state_registry(parent).save_json(
            "state.json", {"status": "running", "updated_at": utc_now_iso()}
        )
        tasks.add_task(background_work, parent, action)
    except Exception:
        job_execution.release(parent.job_dir.name)
        raise


@router.get("")
def get_shorts(job_id: str):
    parent, _ = parent_registry(job_id)
    state = state_registry(parent)
    doc = state.load_json("state.json") if state.exists("state.json") else {"status": "idle"}
    if doc["status"] == "running" and not job_execution.is_active(job_id):
        doc = {
            "status": "failed",
            "error": "Создание коротких видео прервано перезапуском. Сохранённые файлы доступны; повторите нужное действие.",
        }
        state.save_json("state.json", doc)
    return {"items": list_shorts(parent), "state": doc, "platforms": PLATFORMS}


@router.post("/plan")
def plan_shorts(job_id: str, payload: PlanRequest, tasks: BackgroundTasks):
    parent, _ = parent_registry(job_id)
    if not parent.exists("final_lesson.mp4") or parent.exists("render_pending.json"):
        raise HTTPException(409, "Сначала завершите сборку основного видео")

    def create():
        targets = list(PLATFORMS) if payload.target_platform == "all" else [payload.target_platform]
        for target in targets:
            settings = get_settings()
            drafts = create_drafts(parent, settings, payload.cta, payload.kind, target)
            if payload.render:
                for draft in drafts:
                    render_short(parent, settings, draft["id"], target or "shorts")

    queue(parent, tasks, create)
    return {"ok": True}


@router.put("/{short_id}")
def edit_short(job_id: str, short_id: str, payload: ShortDraft):
    parent, ensure_idle = parent_registry(job_id)
    ensure_idle(parent)
    try:
        registry = short_registry(parent, short_id)
        doc = registry.load_json("project.json")
        if payload.model_dump() != doc["draft"]:
            doc.update(
                draft=payload.model_dump(), status="draft", revision=doc.get("revision", 1) + 1
            )
            registry.save_json("project.json", doc)
        return doc
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{short_id}/render")
def export_short(job_id: str, short_id: str, payload: RenderRequest, tasks: BackgroundTasks):
    parent, _ = parent_registry(job_id)
    try:
        short_registry(parent, short_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(404, str(exc)) from exc
    queue(parent, tasks, lambda: render_short(parent, get_settings(), short_id, payload.platform))
    return {"ok": True}


@router.get("/{short_id}/{platform}.mp4")
def get_video(job_id: str, short_id: str, platform: str, download: bool = False):
    parent, _ = parent_registry(job_id)
    if platform not in PLATFORMS:
        raise HTTPException(404, "Неизвестная площадка")
    try:
        registry = short_registry(parent, short_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(404, str(exc)) from exc
    path = registry.artifact_path(f"{platform}.mp4")
    if not path.exists():
        raise HTTPException(404, "Видео ещё не собрано")
    return FileResponse(
        path, media_type="video/mp4", filename=f"{short_id}_{platform}.mp4" if download else None
    )


@router.get("/{short_id}/preview/{asset}")
def get_preview(job_id: str, short_id: str, asset: str):
    if asset not in {"preview.webm", "poster.jpg"}:
        raise HTTPException(404, "Предпросмотр не найден")
    parent, _ = parent_registry(job_id)
    try:
        registry = short_registry(parent, short_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(404, str(exc)) from exc
    path = registry.artifact_path(asset)
    if not path.exists():
        raise HTTPException(404, "Предпросмотр ещё не собран")
    return FileResponse(path, media_type="video/webm" if asset.endswith("webm") else "image/jpeg")
