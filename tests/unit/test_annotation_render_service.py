"""Тесты OpenCV-рендера аннотаций."""

import shutil
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from src.services.annotation_render_service import _paint_frame, render_annotation_preview


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def test_locked_temporary_file_does_not_hide_render_error(tmp_path):
    source = tmp_path / "source.mp4"
    source.touch()
    with patch("src.services.annotation_render_service._render_video_opencv", side_effect=RuntimeError("encode failed")), patch("pathlib.Path.unlink", side_effect=PermissionError("file locked")):
        with pytest.raises(RuntimeError, match="encode failed"):
            render_annotation_preview(source, [{"type": "arrow"}], tmp_path / "out.mp4", refine_anchors=False)


def test_paint_frame_draws_outline_not_fullscreen():
    frame = np.full((100, 200, 3), 180, dtype=np.uint8)
    annotations = [
        {
            "type": "highlight_rect",
            "target_start": 0.0,
            "target_end": 1.0,
            "placement_confirmed": True,
            "anchor": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.2},
        }
    ]
    painted = _paint_frame(frame, annotations, 0.5, 200, 100)
    # Центр кадра не должен стать полностью жёлтым/красным (нет заливки drawbox)
    center = painted[50, 100]
    assert center[0] == 180 and center[1] == 180 and center[2] == 180
    # Угол рамки меняется
    corner = painted[20, 20]
    assert not np.array_equal(corner, center)


@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg не установлен")
def test_render_annotation_preview_writes_file(tmp_path):
    video_path = tmp_path / "lesson.mp4"
    output_path = tmp_path / "preview.mp4"

    writer = cv2.VideoWriter(
        str(video_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        10.0,
        (320, 240),
    )
    for _ in range(20):
        frame = np.full((240, 320, 3), 128, dtype=np.uint8)
        writer.write(frame)
    writer.release()

    annotations = [
        {
            "type": "arrow",
            "target_start": 0.2,
            "target_end": 1.0,
            "label": "Кнопка",
            "anchor": {"x": 0.4, "y": 0.4, "width": 0.1, "height": 0.08},
        }
    ]

    with patch(
        "src.services.annotation_render_service.refine_annotation_anchors",
        side_effect=lambda _v, items, **_: items,
    ):
        render_annotation_preview(
            video_path,
            annotations,
            output_path,
            refine_anchors=False,
        )

    assert output_path.exists()
    assert output_path.stat().st_size > 1000
