"""MoviePy: наложение PNG-оверлеев на видео по таймкоду (вместо drawbox)."""

from __future__ import annotations

from pathlib import Path

try:
    from moviepy import CompositeVideoClip, ImageClip, VideoFileClip
except ImportError as exc:  # pragma: no cover
    raise ImportError("Установите: pip install -e \".[annotations]\"") from exc


def overlay_png_on_video(
    video_path: Path | str,
    overlay_png: Path | str,
    output_path: Path | str,
    *,
    start_sec: float,
    end_sec: float,
) -> Path:
    """
    Наложить прозрачный PNG на участок видео [start_sec, end_sec].
    Подходит для превью одной аннотации перед финальной сборкой.
    """
    video_path = Path(video_path)
    overlay_png = Path(overlay_png)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    duration = max(0.1, end_sec - start_sec)
    with VideoFileClip(str(video_path)) as video:
        overlay = (
            ImageClip(str(overlay_png), transparent=True)
            .with_start(start_sec)
            .with_duration(duration)
            .with_position((0, 0))
        )
        final = CompositeVideoClip([video, overlay])
        final.write_videofile(
            str(output_path),
            codec="libx264",
            audio_codec="aac",
            preset="fast",
            logger=None,
        )
        final.close()
    return output_path
