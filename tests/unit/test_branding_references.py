import asyncio
import io
import json
import subprocess

import pytest
from starlette.datastructures import UploadFile

from src.config import get_settings
from src.services import branding_reference_service as refs
from src.services.ffmpeg_service import _ffmpeg_bin


def test_invalid_media_and_paths_are_rejected(tmp_path):
    settings = get_settings().model_copy(update={'output_dir': tmp_path})
    with pytest.raises(ValueError):
        refs.reference_directory(settings, '../other')
    with pytest.raises(ValueError):
        asyncio.run(refs.upload_reference(UploadFile(io.BytesIO(b'not a video'), filename='bad.mp4'), settings))
    assert list((tmp_path / '_branding_references').iterdir()) == []


def test_real_video_is_saved_previewed_and_used_by_design(tmp_path, monkeypatch):
    from src.services import lesson_options_service as options_service
    from src.services import brand_design_service as design_service
    from src.orchestrator.artifact_registry import ArtifactRegistry
    settings = get_settings().model_copy(update={'output_dir': tmp_path})
    source = tmp_path / 'test.mp4'
    subprocess.run([_ffmpeg_bin(settings), '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=purple:s=320x180:d=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)], check=True, timeout=30)
    with source.open('rb') as stream:
        result = asyncio.run(refs.upload_reference(UploadFile(stream, filename='example.mp4'), settings))
    assert result['duration'] == 1
    assert result['palette']
    assert (refs.reference_directory(settings, result['id']) / 'preview.mp4').exists()
    monkeypatch.setattr(options_service, 'get_settings', lambda: settings)
    options = options_service.LessonOptions(branding_reference_ids=[result['id']], branding_reference_notes='Use purple')
    registry = ArtifactRegistry(tmp_path / 'job_test')
    registry.save_json('lesson_options.json', options.model_dump())
    assert options_service.load_options(registry, settings).branding_reference_ids == [result['id']]
    calls = []
    async def complete(profile, prompt, payload, **kwargs):
        calls.append(json.loads(payload))
        return json.dumps({'title':'Test', 'background':'#112233', 'accent':'#aabbcc', 'layout':'center'}), 'test'
    monkeypatch.setattr(design_service, 'complete_with_fallback', complete)
    first = design_service.prepare_brand_design(registry, options, settings)
    assert calls[0]['reference_palettes'] == [result['palette']]
    assert calls[0]['branding_reference_notes'] == 'Use purple'
    changed = design_service.prepare_brand_design(registry, options.model_copy(update={'branding_reference_ids':[]}), settings)
    assert first['input_hash'] != changed['input_hash']
