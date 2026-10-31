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
wav = job / 'stt_full_audio.wav'
subprocess.run([_ffmpeg_bin(cfg),'-y','-i',str(job/'raw_audio.ogg'),'-ac','1','-ar','16000',str(wav)],capture_output=True,check=True)
with OpenAI(api_key=cfg.openai_api_key) as client, wav.open('rb') as audio:
    r = client.audio.transcriptions.create(model='gpt-4o-transcribe',file=audio,language='ru',
        response_format='json',prompt='Урок по программе 1С. Компания на УСН, применение НДС. Главное, Налоги и отчеты, Анализ учета по УСН.')
(job/'stt_full_audio_result.json').write_text(json.dumps({'model':'gpt-4o-transcribe','text':r.text},ensure_ascii=False),encoding='utf-8')
print('Full audio result saved')
