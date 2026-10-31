"""Add short title/end cards around the processed ORIGINAL recording."""

from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.config import Settings
from src.services.ffmpeg_service import _ffmpeg_bin
from src.services.lesson_options_service import LessonOptions
from src.services.video_probe_service import probe_video


def _font(size: int):
    for name in ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    raise RuntimeError("Не найден шрифт с поддержкой русского языка для заставки")


def draw_card(
    path: Path,
    title: str,
    subtitle: str,
    width: int,
    height: int,
    *,
    design=None,
    company_name="",
    logo_path=None,
) -> None:
    design = design or {"background": "#101c2e", "accent": "#58c9dc", "layout": "center"}
    image = Image.new("RGB", (width, height), design["background"])
    draw = ImageDraw.Draw(image)
    accent = design["accent"]
    draw.rectangle((0, 0, width, max(4, int(height * 0.008))), fill=accent)
    draw.line(
        (width * 0.08, height * 0.9, width * 0.92, height * 0.9),
        fill=accent,
        width=max(2, int(height * 0.003)),
    )

    def text_box(text, box, size, color="white", center=False):
        x, y, w, h = box
        for font_size in range(max(12, int(size)), 7, -1):
            font = _font(font_size)
            lines, line = [], ""
            for word in text.split():
                candidate = (line + " " + word).strip()
                if draw.textlength(candidate, font=font) <= w:
                    line = candidate
                else:
                    if line:
                        lines.append(line)
                    line = word
            if line:
                lines.append(line)
            if len(lines) * font_size * 1.3 <= h and all(
                draw.textlength(s, font=font) <= w for s in lines
            ):
                break
        step = font_size * 1.3
        for i, line in enumerate(lines):
            draw.text(
                (x + w / 2 if center else x, y + i * step),
                line,
                font=font,
                fill=color,
                anchor="mt" if center else "lt",
            )

    has_logo = logo_path is not None and logo_path.exists()
    left = design["layout"] == "left" and has_logo
    if has_logo:
        box = (
            (width * 0.08, height * 0.25, width * 0.24, height * 0.4)
            if left
            else (width * 0.36, height * 0.12, width * 0.28, height * 0.23)
        )
        x, y, w, h = map(int, box)
        draw.rounded_rectangle(
            (x, y, x + w, y + h), radius=max(8, int(height * 0.02)), fill="white"
        )
        with Image.open(logo_path) as original:
            logo = original.convert("RGBA")
            logo.thumbnail((max(1, int(w * 0.88)), max(1, int(h * 0.8))), Image.Resampling.LANCZOS)
            image.paste(logo, (x + (w - logo.width) // 2, y + (h - logo.height) // 2), logo)
    text_box(
        company_name,
        (width * 0.08, height * 0.055, width * 0.84, height * 0.055),
        height * 0.025,
        color="#d7e2ee",
    )
    if left:
        text_box(title, (width * 0.39, height * 0.26, width * 0.53, height * 0.4), height * 0.067)
        text_box(
            subtitle,
            (width * 0.39, height * 0.71, width * 0.53, height * 0.13),
            height * 0.027,
            color="#d7e2ee",
        )
    else:
        text_box(
            title,
            (width * 0.09, height * (0.43 if has_logo else 0.31), width * 0.82, height * 0.31),
            height * 0.07,
            center=True,
        )
        text_box(
            subtitle,
            (width * 0.12, height * 0.77, width * 0.76, height * 0.10),
            height * 0.027,
            color="#d7e2ee",
            center=True,
        )
    image.save(path)


def render_title_previews(registry, options, settings, dimensions=None):
    from src.services.brand_design_service import LOGO_FILE, prepare_brand_design

    report = prepare_brand_design(registry, options, settings)
    width, height = dimensions or (1280, 720)
    design = report["design"]
    common = {
        "design": design,
        "company_name": options.company_name,
        "logo_path": registry.artifact_path(LOGO_FILE),
    }
    draw_card(
        registry.artifact_path("brand_intro.png"),
        design["title"],
        design["subtitle"],
        width,
        height,
        **common,
    )
    draw_card(
        registry.artifact_path("brand_outro.png"),
        "Спасибо за внимание",
        design["title"],
        width,
        height,
        **common,
    )
    return report


def add_title_cards(source: Path, output: Path, options: LessonOptions, settings: Settings) -> dict:
    if not options.intro and not options.outro:
        return {"intro_seconds": 0, "outro_seconds": 0}
    meta = probe_video(source, settings)
    width, height = meta["width"], meta["height"]
    fps = meta["fps"] or 25
    work = source.parent / "_title_cards"
    work.mkdir(exist_ok=True)
    from src.orchestrator.artifact_registry import ArtifactRegistry

    registry = ArtifactRegistry(source.parent)
    design_report = render_title_previews(registry, options, settings, (width, height))
    # Long names need enough time to read even when the user selects a short duration.
    intro_seconds = min(
        15, max(options.intro_seconds, len(design_report["design"]["title"]) / 14 + 1.5)
    )
    outro_seconds = options.outro_seconds
    inputs, filters, names = [], [], []
    index = 0
    if options.intro:
        card = registry.artifact_path("brand_intro.png")
        inputs += ["-loop", "1", "-framerate", str(fps), "-t", str(intro_seconds), "-i", str(card)]
        filters.append(
            f"[{index}:v]format=yuv420p,setsar=1,fade=t=in:st=0:d=0.4,"
            f"fade=t=out:st={intro_seconds - 0.4}:d=0.4,setpts=PTS-STARTPTS[v{index}]"
        )
        filters.append(
            f"anullsrc=r=48000:cl=stereo,atrim=duration={intro_seconds},asetpts=PTS-STARTPTS[a{index}]"
        )
        names.append(f"[v{index}][a{index}]")
        index += 1
    inputs += ["-i", str(source)]
    filters.append(f"[{index}:v]fps={fps},format=yuv420p,setsar=1,setpts=PTS-STARTPTS[v{index}]")
    filters.append(
        f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS[a{index}]"
    )
    names.append(f"[v{index}][a{index}]")
    index += 1
    if options.outro:
        card = registry.artifact_path("brand_outro.png")
        inputs += ["-loop", "1", "-framerate", str(fps), "-t", str(outro_seconds), "-i", str(card)]
        filters.append(
            f"[{index}:v]format=yuv420p,setsar=1,fade=t=in:st=0:d=0.4,"
            f"fade=t=out:st={outro_seconds - 0.4}:d=0.4,setpts=PTS-STARTPTS[v{index}]"
        )
        filters.append(
            f"anullsrc=r=48000:cl=stereo,atrim=duration={outro_seconds},asetpts=PTS-STARTPTS[a{index}]"
        )
        names.append(f"[v{index}][a{index}]")
    filters.append("".join(names) + f"concat=n={len(names)}:v=1:a=1[v][a]")
    cmd = [
        _ffmpeg_bin(settings),
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-crf",
        "20",
        "-preset",
        "fast",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(
            "Не удалось добавить заставки: "
            + result.stderr.decode("utf-8", errors="replace")[-1500:]
        )
    return {
        "intro_seconds": intro_seconds if options.intro else 0,
        "outro_seconds": outro_seconds if options.outro else 0,
        "design_method": design_report["method"],
        "title": design_report["design"]["title"],
        "logo_used": design_report["logo_used"],
        "warning": design_report["warning"],
    }
