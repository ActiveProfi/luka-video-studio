"""pysubs2 / ASS: векторные подписи и рамки через libass (ffmpeg subtitles filter)."""

from __future__ import annotations

from pathlib import Path

import pysubs2


def write_ass_highlight_events(
    path: Path | str,
    events: list[dict],
    *,
    play_res_x: int = 1920,
    play_res_y: int = 1080,
) -> Path:
    """
    Создать .ass с событиями Draw (через override-теги).
    events: [{start_ms, end_ms, x, y, w, h, text, style}]
    """
    path = Path(path)
    subs = pysubs2.SSAFile()
    subs.info["PlayResX"] = str(play_res_x)
    subs.info["PlayResY"] = str(play_res_y)
    subs.styles["Default"] = pysubs2.SSAStyle(
        fontname="Arial",
        fontsize=28,
        primarycolor=pysubs2.Color(255, 255, 255),
        outlinecolor=pysubs2.Color(0, 0, 0),
        backcolor=pysubs2.Color(0, 0, 0, 128),
        outline=2,
        shadow=0,
        marginl=20,
        marginr=20,
        marginv=20,
    )

    for ev in events:
        start = int(ev["start_ms"])
        end = int(ev["end_ms"])
        x = int(ev.get("x", 100))
        y = int(ev.get("y", 100))
        text = str(ev.get("text", ""))
        line = pysubs2.SSAEvent(start=start, end=end, text=f"{{\\pos({x},{y})}}{text}")
        subs.append(line)

    path.parent.mkdir(parents=True, exist_ok=True)
    subs.save(str(path))
    return path
