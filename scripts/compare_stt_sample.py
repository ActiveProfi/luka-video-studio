"""Compare OpenAI recognizers on the previously authorized 20-second excerpt."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from openai import OpenAI
from src.config import Settings

cfg = Settings()
job = cfg.job_output_dir('job_20261006_065154')
context = ('Учебная запись 1С о компании на УСН — упрощенной системе налогообложения. '
           'Тема: превышение лимита доходов на УСН и начало применения НДС. '
           'Разделы программы: Главное, Налоги и отчеты, Анализ учета по УСН. '
           'Передай именно произнесенную речь; не добавляй пояснения из подсказки.')
keywords = ['УСН', 'на УСН', 'по УСН', 'НДС', '1С', 'Налоги и отчеты', 'Анализ учета по УСН']
reports = []
with OpenAI(api_key=cfg.openai_api_key) as client:
    for model in ['gpt-transcribe', 'gpt-4o-transcribe']:
        kwargs = dict(model=model, response_format='json', prompt=context)
        if model == 'gpt-transcribe':
            kwargs['extra_body'] = {'languages': ['ru'], 'keywords': keywords}
        else:
            kwargs['language'] = 'ru'
        with (job / 'stt_context_sample.wav').open('rb') as audio:
            result = client.audio.transcriptions.create(file=audio, **kwargs)
        reports.append({'model': model, 'text': result.text})
        print(model, 'completed', flush=True)
(job / 'stt_sample_comparison.json').write_text(
    json.dumps({'context': context, 'results': reports}, ensure_ascii=False, indent=2), encoding='utf-8')
