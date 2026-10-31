import json
import sys
import subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from openai import OpenAI
from src.config import Settings
from src.services.ffmpeg_service import _ffmpeg_bin
cfg = Settings()
job = cfg.job_output_dir('job_20261006_065154')
clip = job / 'stt_problem_interval.wav'
subprocess.run([_ffmpeg_bin(cfg), '-y', '-ss', '69.4', '-i', str(job/'raw_audio.ogg'),
                '-t', '21.1', '-ac', '1', '-ar', '16000', str(clip)],capture_output=True,check=True)
with OpenAI(api_key=cfg.openai_api_key) as client, clip.open('rb') as audio:
    r = client.audio.transcriptions.create(model='gpt-4o-transcribe',file=audio,language='ru',
            response_format='json',prompt='УСН, НДС, 1С. Доходы, превышение лимита.')
(job/'stt_problem_interval.json').write_text(json.dumps({'text':r.text},ensure_ascii=False),encoding='utf-8')
print('Saved interval result')
