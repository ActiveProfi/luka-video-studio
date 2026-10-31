"""Прожиг субтитров в edited_video → файл для студии аннотаций (шаг 7)."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any

import pysubs2

from src.config import Settings, get_settings
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.ffmpeg_service import burn_ass_onto_video, get_media_duration_seconds
from src.services.media_paths import resolve_edited_video_path
from src.services.subtitle_service import SUBTITLE_LAYOUT, default_subtitle_layout

logger = logging.getLogger(__name__)

SUBTITLED_VIDEO = "edited_video_with_subtitles.mp4"
BURN_ASS = "_subtitle_burn.ass"
SUBTITLE_TIMING = "subtitle_timing.json"
SUBTITLES_SRT = "subtitles.srt"


def _ffprobe_bin(settings: Settings) -> str:
    from src.services.ffmpeg_service import _ffprobe_bin as ffprobe_bin

    return ffprobe_bin(settings)


def get_video_size(path: Path, settings: Settings | None = None) -> tuple[int, int]:
    s = settings or get_settings()
    cmd = [
        _ffprobe_bin(s),
        "-v",
        "quiet",
        "-select_streams",
        "v:0",
        "-print_format",
        "json",
        "-show_streams",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    stream = (data.get("streams") or [{}])[0]
    w = int(stream.get("width") or 1280)
    h = int(stream.get("height") or 720)
    return max(16, w), max(16, h)


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    raw = (color or "#ffffff").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        return 255, 255, 255
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def _ass_color(rgb: tuple[int, int, int], opacity: float = 1.0) -> pysubs2.Color:
    alpha = int(round((1.0 - max(0.0, min(1.0, opacity))) * 255))
    return pysubs2.Color(rgb[0], rgb[1], rgb[2], alpha)


def _cue_box(cue: dict[str, Any], layout: dict[str, Any]) -> dict[str, float]:
    cue_layouts = layout.get("cue_layouts") or {}
    cue_id = str(cue.get("cue_id") or "")
    source_id = str(cue.get("source_segment_id") or "")
    override = None
    if cue_id and isinstance(cue_layouts.get(cue_id), dict):
        override = cue_layouts[cue_id]
    elif source_id and isinstance(cue_layouts.get(source_id), dict):
        override = cue_layouts[source_id]
    box = {
        "x": float(layout.get("x", 0.06)),
        "y": float(layout.get("y", 0.82)),
        "width": float(layout.get("width", 0.88)),
        "height": float(layout.get("height", 0.12)),
    }
    if isinstance(override, dict):
        for key in ("x", "y", "width", "height"):
            if override.get(key) is not None:
                box[key] = float(override[key])
    return box


def _escape_ass_text(text: str) -> str:
    cleaned = re.sub(r"[\r\n]+", r"\\N", str(text or "").strip())
    return cleaned.replace("{", "(").replace("}", ")")


def _ass_override_color(rgb: tuple[int, int, int], opacity: float = 1.0) -> tuple[str, str]:
    """Цвет и альфа для тегов ASS (&HBBGGRR&, &HAA&). alpha 00 = непрозрачный."""
    r, g, b = rgb
    alpha = int(round((1.0 - max(0.0, min(1.0, opacity))) * 255))
    return f"&H{b:02X}{g:02X}{r:02X}&", f"&H{alpha:02X}&"


def write_layout_ass(
    ass_path: Path,
    cues: list[dict[str, Any]],
    layout: dict[str, Any],
    *,
    play_res_x: int,
    play_res_y: int,
) -> Path:
    """Пишет ASS: рамка ровно как в редакторе (x/y/width/height + цвета), текст по центру."""
    font_size = int(layout.get("font_size_px") or 12)
    scaled_font = max(16, int(round(font_size * (play_res_y / 480.0))))
    fg = _hex_to_rgb(str(layout.get("font_color") or "#ffffff"))
    bg = _hex_to_rgb(str(layout.get("background_color") or "#000000"))
    bg_opacity = float(
        layout.get("background_opacity") if layout.get("background_opacity") is not None else 0.72
    )
    bold = -1 if layout.get("font_bold") else 0
    italic = -1 if layout.get("font_italic") else 0
    bg_c, bg_a = _ass_override_color(bg, bg_opacity)
    fg_c, _fg_a = _ass_override_color(fg, 1.0)

    subs = pysubs2.SSAFile()
    subs.info["PlayResX"] = str(play_res_x)
    subs.info["PlayResY"] = str(play_res_y)
    subs.info["WrapStyle"] = "0"
    # Стиль без «родной» ASS-плашки: рамку рисуем сами по размеру из layout
    subs.styles["Default"] = pysubs2.SSAStyle(
        fontname="Arial",
        fontsize=scaled_font,
        primarycolor=_ass_color(fg, 1.0),
        secondarycolor=_ass_color(fg, 1.0),
        outlinecolor=_ass_color((0, 0, 0), 1.0),
        backcolor=_ass_color(bg, bg_opacity),
        bold=bold,
        italic=italic,
        borderstyle=1,
        outline=0,
        shadow=0,
        alignment=5,
        marginl=0,
        marginr=0,
        marginv=0,
    )

    for cue in cues:
        start = max(0.0, float(cue.get("start", 0)))
        end = max(start + 0.05, float(cue.get("end", start + 1)))
        text = _escape_ass_text(str(cue.get("text") or ""))
        if not text:
            continue
        box = _cue_box(cue, layout)
        x0 = int(round(box["x"] * play_res_x))
        y0 = int(round(box["y"] * play_res_y))
        bw = max(8, int(round(box["width"] * play_res_x)))
        bh = max(8, int(round(box["height"] * play_res_y)))
        cx = x0 + bw // 2
        cy = y0 + bh // 2
        # Подгоняем кегль под высоту рамки, чтобы не вылезал за белый фон
        fit_font = max(12, min(scaled_font, int(bh * 0.42)))
        t0 = int(round(start * 1000))
        t1 = int(round(end * 1000))
        # Векторный прямоугольник = та же рамка, что пользователь тянул в шаге 2
        box_text = (
            f"{{\\an7\\pos({x0},{y0})\\p1\\bord0\\shad0\\1c{bg_c}\\1a{bg_a}"
            f"\\2c{bg_c}\\2a{bg_a}\\3c{bg_c}\\3a{bg_a}\\4c{bg_c}\\4a{bg_a}}}"
            f"m 0 0 l {bw} 0 l {bw} {bh} l 0 {bh}{{\\p0}}"
        )
        subs.append(pysubs2.SSAEvent(start=t0, end=t1, text=box_text))
        text_line = (
            f"{{\\an5\\pos({cx},{cy})\\fs{fit_font}\\bord0\\shad0\\1c{fg_c}}}"
            f"{text}"
        )
        subs.append(pysubs2.SSAEvent(start=t0, end=t1, text=text_line))

    ass_path.parent.mkdir(parents=True, exist_ok=True)
    subs.save(str(ass_path))
    return ass_path


def burn_subtitles_into_video(
    registry: ArtifactRegistry,
    settings: Settings | None = None,
) -> Path:
    """Создаёт edited_video_with_subtitles.mp4 по layout + cues."""
    s = settings or get_settings()
    if not registry.exists(SUBTITLE_TIMING) and not registry.exists(SUBTITLES_SRT):
        raise FileNotFoundError("Нет субтитров для прожига")

    source = resolve_edited_video_path(registry)
    output = registry.job_dir / SUBTITLED_VIDEO
    ass_path = registry.job_dir / BURN_ASS

    layout_raw = registry.load_json(SUBTITLE_LAYOUT) if registry.exists(SUBTITLE_LAYOUT) else None
    layout = {**default_subtitle_layout(), **(layout_raw if isinstance(layout_raw, dict) else {})}

    if registry.exists(SUBTITLE_TIMING):
        cues = list(registry.load_json(SUBTITLE_TIMING).get("cues") or [])
    else:
        cues = []

    width, height = get_video_size(source, s)
    write_layout_ass(ass_path, cues, layout, play_res_x=width, play_res_y=height)
    burn_ass_onto_video(source, ass_path, output, s)
    get_media_duration_seconds(output, s)
    return output


def _source_mtime(registry: ArtifactRegistry) -> float:
    times: list[float] = []
    for name in (SUBTITLE_TIMING, SUBTITLES_SRT, SUBTITLE_LAYOUT, "edited_video.mp4"):
        path = registry.artifact_path(name)
        if path.exists():
            times.append(path.stat().st_mtime)
    return max(times) if times else 0.0


def ensure_subtitled_studio_video(
    registry: ArtifactRegistry,
    settings: Settings | None = None,
    *,
    force: bool = False,
) -> str:
    """Гарантирует файл для студии шага 7. Возвращает имя артефакта."""
    if not registry.exists("edited_video.mp4"):
        return "edited_video.mp4"
    if not registry.exists(SUBTITLE_TIMING) and not registry.exists(SUBTITLES_SRT):
        return "edited_video.mp4"

    out = registry.artifact_path(SUBTITLED_VIDEO)
    need = force or (not out.exists())
    if out.exists() and not need:
        need = out.stat().st_mtime < _source_mtime(registry)

    if need:
        try:
            burn_subtitles_into_video(registry, settings)
        except Exception as exc:
            logger.warning("Прожиг субтитров не удался (%s), студия без прожига", exc)
            return "edited_video.mp4"

    return SUBTITLED_VIDEO if out.exists() else "edited_video.mp4"
