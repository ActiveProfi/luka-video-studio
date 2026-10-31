"""Rebuild changed speech units and measure final audio without retranscribing the source."""
import shutil
from datetime import datetime

from scipy.io import wavfile

from src.config import get_settings
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.auto_voiceover_service import _fit_block_audio
from src.services.ffmpeg_service import mux_video_with_voiceover
from src.services.lesson_options_service import voice_settings
from src.services.speech_script_auto import build_speech_text
from src.services.subtitle_burn_service import ensure_subtitled_studio_video
from src.services.voice_word_timing import ensure_voice_word_timing, find_spoken_cue
from src.services.voiceover_assembly_service import VoiceoverPart, assemble_voiceover

settings = get_settings()
r = ArtifactRegistry(settings.job_output_dir("job_20261006_065154"))
settings = voice_settings(r, settings)
backup = r.job_dir / ("before_word_sync_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
backup.mkdir()
for name in ("voiceover.wav", "voiceover_segments.json", "speech_script_auto.json", "edited_video.mp4",
             "edited_video_with_subtitles.mp4", "annotation_preview.mp4", "annotation_suggestions.json",
             "annotation_review.json", "approved_annotations.json", "screen_analysis_report.json"):
    if r.exists(name):
        shutil.copy2(r.artifact_path(name), backup / name)
voice = r.load_json("voiceover_segments.json")
script = r.load_json("speech_script_auto.json")
rate, samples = wavfile.read(r.artifact_path("voiceover.wav"))
work = r.job_dir / "_tts_pronunciation_fix"
work.mkdir(exist_ok=True)
parts = []
for index, segment in enumerate(voice["segments"], 1):
    new_text = build_speech_text(segment["subtitle_text"])
    if new_text != segment["text"] and "один эс" in new_text:
        fitted = _fit_block_audio(subtitle=segment["subtitle_text"], speech_text=new_text,
            slot_seconds=segment["target_slot_seconds"], tolerance=0, work_dir=work,
            index=index, language="ru", settings=settings)
        if not fitted["fits"]:
            raise RuntimeError("Corrected pronunciation does not fit its source slot")
        path = fitted["wav_path"]
        duration = fitted["audio_duration"]
        segment.update(text=fitted["speech_text"], audio_end=round(segment["audio_start"] + duration, 3),
            audio_duration_seconds=round(duration, 3), optimization=fitted["optimization"],
            speed_applied=fitted["speed_applied"])
        for item in script["items"]:
            if item["block_id"] == segment["block_id"]:
                item.update(speech_text=segment["text"], optimization=fitted["optimization"],
                            speed_applied=fitted["speed_applied"])
        print("Corrected:", segment["text"], flush=True)
    else:
        path = work / f"preserved_{index:03d}.wav"
        clip = samples[round(segment["audio_start"] * rate):round(segment["audio_end"] * rate)]
        wavfile.write(path, rate, clip)
        duration = len(clip) / rate
    parts.append(VoiceoverPart(path, segment["audio_start"], duration))
assemble_voiceover(parts, r.artifact_path("voiceover.wav"), voice["total_duration_seconds"], settings)
r.save_json("voiceover_segments.json", voice)
r.save_json("speech_script_auto.json", script)
mux_video_with_voiceover(r.artifact_path("raw_video.mp4"), r.artifact_path("voiceover.wav"),
                         r.artifact_path("edited_video.mp4"), settings)
ensure_subtitled_studio_video(r, settings, force=True)
timing = ensure_voice_word_timing(r, settings)
by_id = {s["segment_id"]: s["words"] for s in timing["segments"]}
for ann in r.load_json("annotation_suggestions.json")["suggestions"]:
    print(ann["annotation_id"], ann["label"], find_spoken_cue(ann, by_id.get(ann["linked_segment_id"], [])), flush=True)
