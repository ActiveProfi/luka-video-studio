"""Compare a bounded original-audio excerpt with context-aware STT."""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from openai import OpenAI
from src.config import Settings
from src.services.ffmpeg_service import _ffmpeg_bin

cfg = Settings()
job = cfg.job_output_dir('job_20261006_065154')
clip = job / 'stt_context_sample.wav'
subprocess.run([_ffmpeg_bin(cfg), '-y', '-ss', '18', '-i', str(job / 'raw_audio.ogg'),
                '-t', '20', '-ac', '1', '-ar', '16000', str(clip)],
               capture_output=True, check=True)
with OpenAI(api_key=cfg.openai_api_key) as client, clip.open('rb') as audio:
    result = client.audio.transcriptions.create(
        model=cfg.openai_stt_model, file=audio, response_format='json', prompt=cfg.stt_context,
        extra_body={'languages': ['ru'], 'keywords': cfg.stt_keywords.split(',')})
report = {'model': cfg.openai_stt_model, 'source_start': 18, 'source_end': 38,
          'text': result.text}
(job / 'stt_context_sample.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False))
