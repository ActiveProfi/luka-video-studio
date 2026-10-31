"""Pillow + Shapely: прозрачные PNG-оверлеи для MoviePy/ffmpeg."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw

try:
    from shapely.geometry import LineString
except ImportError:  # pragma: no cover
    LineString = None  # type: ignore[misc, assignment]

OverlayKind = Literal["highlight_rect", "arrow", "callout"]


def create_overlay_png(
    width: int,
    height: int,
    kind: OverlayKind,
    *,
    x_norm: float,
    y_norm: float,
    w_norm: float,
    h_norm: float,
    label: str = "",
) -> Image.Image:
    """
    Прозрачный PNG с одной аннотацией.
    Координаты 0..1 — как в annotation_suggestions.json.
    """
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    x1 = int(x_norm * width)
    y1 = int(y_norm * height)
    x2 = int((x_norm + w_norm) * width)
    y2 = int((y_norm + h_norm) * height)

    if kind == "highlight_rect":
        draw.rectangle((x1, y1, x2, y2), outline=(255, 210, 0, 230), width=4)
    elif kind == "arrow":
        tip = (x2, y2)
        tail = (max(0, x1 - int(width * 0.08)), y1 + (y2 - y1) // 2)
        _draw_arrow_pil(draw, tail, tip, color=(255, 40, 40, 240), width=4)
    elif kind == "callout" and label:
        pad = 6
        text_box = draw.textbbox((x1, y1), label)
        tw, th = text_box[2] - text_box[0], text_box[3] - text_box[1]
        draw.rounded_rectangle(
            (x1, y1, x1 + tw + pad * 2, y1 + th + pad * 2),
            radius=8,
            fill=(255, 255, 255, 210),
            outline=(60, 60, 60, 255),
            width=2,
        )
        draw.text((x1 + pad, y1 + pad), label, fill=(20, 20, 20, 255))

    return img


def save_overlay_png(path: Path | str, overlay: Image.Image) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    overlay.save(path, format="PNG")
    return path


def _draw_arrow_pil(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    color: tuple[int, int, int, int],
    width: int,
) -> None:
    draw.line([start, end], fill=color, width=width)
    if LineString is not None:
        line = LineString([start, end])
        if line.length > 0:
            tip = line.interpolate(line.length - 1)
            base = line.interpolate(max(0, line.length - 18))
            dx, dy = tip.x - base.x, tip.y - base.y
            import math

            angle = math.atan2(dy, dx)
            for sign in (-1, 1):
                wing = (
                    tip.x - 14 * math.cos(angle - sign * 0.45),
                    tip.y - 14 * math.sin(angle - sign * 0.45),
                )
                draw.line([(tip.x, tip.y), wing], fill=color, width=width)
