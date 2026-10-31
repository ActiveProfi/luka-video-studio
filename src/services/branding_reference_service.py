"""Local video references shared by draft and saved lesson options."""
import json
import math
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from src.services.ffmpeg_service import _ffmpeg_bin, _ffprobe_bin

MAX_BYTES = 100 * 1024 * 1024
EXTENSIONS = {'.mp4', '.mov', '.webm'}


def reference_directory(settings, reference_id):
    if not re.fullmatch(r'[0-9a-f]{32}', reference_id):
        raise ValueError('Неверный идентификатор референса')
    return settings.output_dir / '_branding_references' / reference_id


def load_reference(settings, reference_id):
    path = reference_directory(settings, reference_id) / 'metadata.json'
    if not path.exists():
        raise ValueError('Референс не найден. Загрузите файл повторно.')
    return json.loads(path.read_text(encoding='utf-8'))


def finish_reference(settings, reference_id, filename, suffix):
    directory = reference_directory(settings, reference_id)
    source = directory / ('source' + suffix)
    try:
        result = subprocess.run([_ffprobe_bin(settings), '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(source)], capture_output=True, check=True, timeout=30)
        info = json.loads(result.stdout)
        video = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic')), None)
        duration = float(info.get('format', {}).get('duration') or (video or {}).get('duration') or 0)
        if not video or not math.isfinite(duration) or not 0 < duration <= 60:
            raise ValueError('Нужен видеоролик длительностью до 60 секунд.')
        if int(video.get('width', 0)) * int(video.get('height', 0)) > 3840 * 2160:
            raise ValueError('Максимальное разрешение референса — 4K.')
        # A silent browser-compatible copy and representative frames stay local.
        subprocess.run([_ffmpeg_bin(settings), '-nostdin', '-v', 'error', '-i', str(source), '-map', '0:v:0', '-an', '-vf', 'scale=640:360:force_original_aspect_ratio=decrease:force_divisible_by=2', '-r', '24', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '27', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(directory / 'preview.mp4')], capture_output=True, check=True, timeout=120)
        from src.services.brand_design_service import logo_palette
        palettes = []
        for index, fraction in enumerate((.15, .5, .85)):
            frame = directory / f'frame_{index}.png'
            subprocess.run([_ffmpeg_bin(settings), '-nostdin', '-v', 'error', '-ss', str(duration * fraction), '-i', str(directory / 'preview.mp4'), '-frames:v', '1', str(frame)], capture_output=True, check=True, timeout=20)
            palettes.extend(logo_palette(frame))
        data = {'id': reference_id, 'name': filename[:160], 'duration': round(duration, 2), 'source': 'source' + suffix, 'palette': list(dict.fromkeys(palettes))[:9], 'url': f'/branding/references/{reference_id}/preview'}
        (directory / 'metadata.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        return data
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError, StopIteration) as exc:
        raise ValueError('Не удалось прочитать видео. Используйте исправный MP4, MOV или WebM.') from exc


async def upload_reference(file, settings):
    suffix = Path(file.filename or '').suffix.lower()
    if suffix not in EXTENSIONS:
        raise ValueError('Поддерживаются MP4, MOV и WebM.')
    reference_id = uuid.uuid4().hex
    directory = reference_directory(settings, reference_id)
    directory.mkdir(parents=True)
    try:
        size = 0
        with (directory / ('source' + suffix)).open('wb') as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError('Размер референса — до 100 МБ.')
                output.write(chunk)
        import asyncio
        return await asyncio.to_thread(finish_reference, settings, reference_id, Path(file.filename or 'Референс').name, suffix)
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    finally:
        await file.close()
