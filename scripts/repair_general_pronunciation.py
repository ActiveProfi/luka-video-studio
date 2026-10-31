"""Repair only speech units changed by contextual pronunciation; preserve video frames."""

import shutil
from datetime import datetime

from scipy.io import wavfile

from src.config import get_settings
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.auto_voiceover_service import _fit_block_audio
from src.services.contextual_pronunciation import prepare_contextual_speech
from src.services.ffmpeg_service import mux_video_with_voiceover
from src.services.lesson_options_service import voice_settings
from src.services.sync_service import build_sync_blocks
from src.services.tts_normalization_rules import pronunciation_rules_hash
from src.services.generated_speech_audit import audit_and_repair_voiceover

r = ArtifactRegistry(get_settings().job_output_dir("job_20261006_065154"))
settings = voice_settings(r, get_settings())
backup = r.job_dir / ("before_general_pronunciation_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
backup.mkdir()
for name in {p.name for p in r.job_dir.glob("*.json")} | set(
    (
        "voiceover.wav",
        "voiceover_segments.json",
        "speech_script_auto.json",
        "edited_video.mp4",
        "edited_video_with_subtitles.mp4",
        "annotation_preview.mp4",
        "voiceover_word_timing.json",
    )
):
    shutil.copy2(r.artifact_path(name), backup / name)
voice = r.load_json("voiceover_segments.json")
script = r.load_json("speech_script_auto.json")
blocks = [{"id": s["block_id"], "subtitle": s["subtitle_text"]} for s in voice["segments"]]
prepared = prepare_contextual_speech(blocks, r, settings)
target_ids = {t["block_id"] for t in r.load_json("contextual_pronunciation.json")["targets"]}
rate, samples = wavfile.read(r.artifact_path("voiceover.wav"))
work = r.job_dir / "_tts_general_pronunciation"
work.mkdir(exist_ok=True)
for index, s in enumerate(voice["segments"], 1):
    if str(s["block_id"]) not in target_ids or prepared[str(s["block_id"])] == s["text"]:
        continue
    fitted = _fit_block_audio(
        subtitle=s["subtitle_text"],
        speech_text=prepared[str(s["block_id"])],
        slot_seconds=s["target_slot_seconds"],
        tolerance=s["allowed_audio_seconds"] - s["target_slot_seconds"],
        work_dir=work,
        index=index,
        language="ru",
        settings=settings,
    )
    assert fitted["fits"], "Corrected speech does not fit its slot"
    chunk_rate, chunk = wavfile.read(fitted["wav_path"])
    assert chunk_rate == rate and chunk.dtype == samples.dtype
    start = round(s["audio_start"] * rate)
    boundary = round(
        (
            voice["segments"][index]["audio_start"]
            if index < len(voice["segments"])
            else voice["total_duration_seconds"]
        )
        * rate
    )
    assert start + len(chunk) <= boundary
    samples[start:boundary] = 0
    samples[start : start + len(chunk)] = chunk
    s.update(
        text=fitted["speech_text"],
        audio_end=round(s["audio_start"] + len(chunk) / rate, 3),
        audio_duration_seconds=round(len(chunk) / rate, 3),
        speed_applied=fitted["speed_applied"],
        optimization=fitted["optimization"],
    )
    for item in script["items"]:
        if item["block_id"] == s["block_id"]:
            item.update(
                speech_text=s["text"],
                speed_applied=s["speed_applied"],
                optimization=s["optimization"],
            )
    print(s["text"], flush=True)
temp = work / "voiceover.wav"
wavfile.write(temp, rate, samples)
temp.replace(r.artifact_path("voiceover.wav"))
voice["pronunciation_rules_hash"] = pronunciation_rules_hash(settings)
r.save_json("voiceover_segments.json", voice)
r.save_json("speech_script_auto.json", script)
sync = r.load_json("automatic_sync_report.json")
sync["blocks"] = build_sync_blocks(voice["segments"])
r.save_json("automatic_sync_report.json", sync)
timing = r.load_json("voiceover_timing_report.json")
timing["segments"] = voice["segments"]
r.save_json("voiceover_timing_report.json", timing)
report = audit_and_repair_voiceover(r, settings, _fit_block_audio)
print("Audio audit:", report["status"], report["checks"], flush=True)
for name in ("edited_video.mp4", "edited_video_with_subtitles.mp4"):
    temp = work / name
    mux_video_with_voiceover(
        r.artifact_path(name), r.artifact_path("voiceover.wav"), temp, settings
    )
    temp.replace(r.artifact_path(name))
print("Rebuild annotations from measured speech before delivering preview", flush=True)
