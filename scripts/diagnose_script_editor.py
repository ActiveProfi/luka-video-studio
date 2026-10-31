"""Diagnose the configured editor on an existing transcript; never print credentials."""
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.config import Settings
from src.providers.llm.runner import complete_with_fallback
from src.services.automatic_script_service import PROMPT

settings = Settings()
job = Path('output/job_20261006_065154')
segments = json.loads((job / 'transcript.json').read_text(encoding='utf-8'))['segments'][:20]
print('Configured order:', settings.llm_fallback_order, flush=True)
try:
    raw, provider = asyncio.run(complete_with_fallback(settings, PROMPT, json.dumps(
        [{'segment_id': s['segment_id'], 'text': s['text']} for s in segments], ensure_ascii=False)))
    (job / 'editor_diagnostic_response.txt').write_text(raw, encoding='utf-8')
    print('Provider:', provider, 'response characters:', len(raw), flush=True)
    parsed = json.loads(raw.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip())
    print('Root type:', type(parsed).__name__)
    items = parsed['segments']
    print('Items:', len(items), 'IDs match:', {s['segment_id'] for s in items} == {s['segment_id'] for s in segments})
except Exception as exc:
    message = str(exc)
    for secret in (settings.openai_api_key, settings.yandex_api_key, settings.yandex_gpt_api_key):
        if secret:
            message = message.replace(secret, '[redacted]')
    print(type(exc).__name__, message[:1500])
