"""Inspect the delivered movie, measured timing and current application readiness."""

import json
import shutil
import subprocess

import cv2
from PIL import Image, ImageDraw

from src.config import get_settings
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.auto_voiceover_service import (
    auto_voiceover_matches_subtitles,
    auto_voiceover_ready,
)
from src.services.ffmpeg_service import _ffprobe_bin

settings = get_settings()
r = ArtifactRegistry(settings.job_output_dir("job_20261006_065154"))
source = r.artifact_path("annotation_preview.mp4")
streams = json.loads(
    subprocess.check_output(
        [_ffprobe_bin(settings), "-v", "error", "-show_streams", "-of", "json", str(source)]
    )
)["streams"]
video = next(s for s in streams if s["codec_type"] == "video")
audio = next(s for s in streams if s["codec_type"] == "audio")
assert abs(float(video["duration"]) - float(audio["duration"])) < 0.1
timing = r.load_json("annotation_timing_report.json")
assert timing["aligned_count"] == 12 and not any(
    timing[k] for k in ["early_count", "late_count", "unresolved_count"]
)
assert r.load_json("generated_speech_audit.json")["status"] == "passed"
assert auto_voiceover_ready(r) and auto_voiceover_matches_subtitles(r)
voice = r.load_json("voiceover_segments.json")
for i, s in enumerate(voice["segments"]):
    assert s["audio_duration_seconds"] <= s["allowed_audio_seconds"] + 0.03
    if i + 1 < len(voice["segments"]):
        assert s["audio_end"] <= voice["segments"][i + 1]["audio_start"] + 0.001
capture = cv2.VideoCapture(str(source))
times = [49.3, 49.8, 59.5, 60.1, 115.4, 122.25]
sheet = Image.new("RGB", (1000, 840), "white")
draw = ImageDraw.Draw(sheet)
for index, seconds in enumerate(times):
    capture.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000)
    ok, frame = capture.read()
    assert ok
    pic = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    pic.thumbnail((500, 260))
    x, y = (index % 2) * 500, (index // 2) * 280
    sheet.paste(pic, (x, y + 20))
    draw.text((x + 5, y + 3), f"{seconds:.2f} s", fill="black")
capture.release()
sheet.save(r.artifact_path("pronunciation_final_frames.jpg"))
shutil.copy2(source, r.artifact_path("instruction_pronunciation_checked.mp4"))
result = {
    "speech_blocks_checked": len(voice["segments"]),
    "annotations_aligned": 12,
    "video_seconds": video["duration"],
    "audio_seconds": audio["duration"],
    "voice_current": True,
    "slot_overlap": False,
}
r.save_json("pronunciation_final_verification.json", result)
print(result)
