"""Check configured providers using ONLY invented non-private sample text."""
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.config import Settings
from src.providers.llm.factory import build_llm_chain
from src.providers.llm.runner import complete_with_fallback
from src.services.automatic_script_service import PROMPT, parse_editor_response


async def main():
    settings = Settings()
    batch = [{'segment_id': f'seg_{i:03}', 'text': 'Ну, открываем учебный документ.'}
             for i in range(1, 21)]
    for provider in build_llm_chain(settings):
        try:
            raw = await provider.complete(PROMPT, json.dumps(batch, ensure_ascii=False))
            Path(f'output/editor_synthetic_{provider.name}.txt').write_text(raw, encoding='utf-8')
            parse_editor_response(raw, batch)
            print(provider.name, 'valid response', flush=True)
        except Exception as exc:
            message = str(exc)
            for secret in (settings.openai_api_key, settings.yandex_api_key,
                           settings.yandex_gpt_api_key, settings.yandex_folder_id,
                           settings.yandex_gpt_folder_id):
                if secret:
                    message = message.replace(secret, '[redacted]')
            print(provider.name, type(exc).__name__, message[:1000], flush=True)
    raw, provider = await complete_with_fallback(
        settings, PROMPT, json.dumps(batch, ensure_ascii=False),
        validate_response=lambda value: parse_editor_response(value, batch))
    print('Validated pipeline:', provider, 'segments:', len(parse_editor_response(raw, batch)), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
