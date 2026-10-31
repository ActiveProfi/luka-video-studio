"""Обёртка над ffmpeg/ffprobe."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

from src.config import Settings, get_settings

logger = logging.getLogger(__name__)


def _ffmpeg_bin(settings: Settings | None = None) -> str:
    s = settings or get_settings()
    if s.ffmpeg_path:
        return s.ffmpeg_path
    path = shutil.which("ffmpeg")
    if not path:
        raise RuntimeError("FFmpeg не найден. Установите FFmpeg и добавьте в PATH.")
    return path


def _ffprobe_bin(settings: Settings | None = None) -> str:
    s = settings or get_settings()
    if s.ffprobe_path:
        return s.ffprobe_path
    path = shutil.which("ffprobe")
    if not path:
        raise RuntimeError("ffprobe не найден. Установите FFmpeg и добавьте в PATH.")
    return path


def get_media_duration_seconds(path: Path, settings: Settings | None = None) -> float:
    cmd = [
        _ffprobe_bin(settings),
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def extract_audio_ogg(
    video_path: Path,
    output_path: Path,
    sample_rate: int = 16000,
    settings: Settings | None = None,
) -> Path:
    """Извлечь моно-аудио OggOpus для Yandex STT."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _ffmpeg_bin(settings),
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ar",
        str(sample_rate),
        "-ac",
        "1",
        "-c:a",
        "libopus",
        "-application",
        "voip",
        str(output_path),
    ]
    logger.info("Извлечение аудио: %s", video_path.name)
    subprocess.run(cmd, capture_output=True, check=True)
    return output_path


def split_audio_segments(
    audio_path: Path,
    output_dir: Path,
    segment_seconds: int = 25,
    settings: Settings | None = None,
) -> list[tuple[Path, float]]:
    """Разбить аудио на фрагменты. Возвращает (путь, смещение в секундах)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    pattern = output_dir / "chunk_%04d.ogg"
    cmd = [
        _ffmpeg_bin(settings),
        "-y",
        "-i",
        str(audio_path),
        "-f",
        "segment",
        "-segment_time",
        str(segment_seconds),
        "-reset_timestamps",
        "1",
        "-c",
        "copy",
        str(pattern),
    ]
    subprocess.run(cmd, capture_output=True, check=True)

    chunks = sorted(output_dir.glob("chunk_*.ogg"))
    if not chunks:
        raise RuntimeError("Не удалось разбить аудио на фрагменты")

    return [(p, i * segment_seconds) for i, p in enumerate(chunks)]


def lpcm_bytes_to_wav(
    lpcm_bytes: bytes,
    output_path: Path,
    sample_rate: int = 48000,
    settings: Settings | None = None,
) -> Path:
    """Конвертировать LPCM (s16le mono) в WAV."""
    import tempfile

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as tmp:
        tmp.write(lpcm_bytes)
        raw_path = Path(tmp.name)
    try:
        cmd = [
            _ffmpeg_bin(settings),
            "-y",
            "-f",
            "s16le",
            "-ar",
            str(sample_rate),
            "-ac",
            "1",
            "-i",
            str(raw_path),
            str(output_path),
        ]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    finally:
        raw_path.unlink(missing_ok=True)
    return output_path


def generate_silence_wav(
    duration_seconds: float,
    output_path: Path,
    sample_rate: int = 48000,
    settings: Settings | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _ffmpeg_bin(settings),
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r={sample_rate}:cl=mono",
        "-t",
        f"{max(0.01, duration_seconds):.3f}",
        str(output_path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return output_path


def concat_wav_files(
    wav_paths: list[Path],
    output_path: Path,
    settings: Settings | None = None,
) -> Path:
    """Склеить WAV-файлы в один (через concat demuxer)."""
    if not wav_paths:
        raise ValueError("Нет WAV-файлов для склейки")
    if len(wav_paths) == 1:
        import shutil

        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(wav_paths[0], output_path)
        return output_path

    import tempfile

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tmp:
        for path in wav_paths:
            escaped = str(path.resolve()).replace("'", "'\\''")
            tmp.write(f"file '{escaped}'\n")
        list_path = Path(tmp.name)
    try:
        cmd = [
            _ffmpeg_bin(settings),
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c",
            "copy",
            str(output_path),
        ]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    finally:
        list_path.unlink(missing_ok=True)
    return output_path


def pad_wav_to_duration(
    input_path: Path,
    output_path: Path,
    target_duration: float,
    settings: Settings | None = None,
) -> Path:
    """Добавить тишину в конец, если файл короче целевой длительности."""
    current = get_media_duration_seconds(input_path, settings)
    if current >= target_duration - 0.05:
        import shutil

        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input_path, output_path)
        return output_path

    gap = target_duration - current
    silence_path = output_path.parent / "_pad_silence.wav"
    generate_silence_wav(gap, silence_path, settings=settings)
    concat_wav_files([input_path, silence_path], output_path, settings=settings)
    silence_path.unlink(missing_ok=True)
    return output_path


def _build_atempo_chain(speed_factor: float) -> str:
    """atempo поддерживает 0.5–2.0, для больших значений — цепочка."""
    if speed_factor <= 0:
        raise ValueError("speed_factor должен быть > 0")
    filters: list[str] = []
    remaining = speed_factor
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.6f}")
    return ",".join(filters)


def change_wav_speed(
    input_path: Path,
    output_path: Path,
    speed_factor: float,
    settings: Settings | None = None,
) -> Path:
    """Ускорить/замедлить озвучку без изменения тона (для подгонки в тайм-блок)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _ffmpeg_bin(settings),
        "-y",
        "-i",
        str(input_path),
        "-filter:a",
        _build_atempo_chain(speed_factor),
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return output_path


def _probe_has_audio(video_path: Path, settings: Settings | None = None) -> bool:
    cmd = [
        _ffprobe_bin(settings),
        "-v",
        "quiet",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "csv=p=0",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return "audio" in result.stdout


def render_timeline_video(
    source_video: Path,
    timeline_segments: list[dict],
    output_path: Path,
    settings: Settings | None = None,
) -> float:
    """Смонтировать видео по timeline_map (keep / trim_soft / speedup, без removed)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    has_audio = _probe_has_audio(source_video, settings)

    parts = [seg for seg in sorted(timeline_segments, key=lambda s: s.get("segment_index", 0))]
    active = [seg for seg in parts if seg.get("transform") != "removed"]
    if not active:
        raise ValueError("timeline_map не содержит сегментов для монтажа")

    if len(active) == 1 and active[0].get("transform") == "keep":
        seg = active[0]
        start = float(seg["source_start"])
        end = float(seg["source_end"])
        cmd = [
            _ffmpeg_bin(settings),
            "-y",
            "-ss",
            f"{start:.3f}",
            "-to",
            f"{end:.3f}",
            "-i",
            str(source_video),
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "20",
        ]
        if has_audio:
            cmd.extend(["-c:a", "aac", "-b:a", "128k"])
        else:
            cmd.append("-an")
        cmd.append(str(output_path))
        logger.info("Монтаж видео (один фрагмент): %s", output_path.name)
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return get_media_duration_seconds(output_path, settings)

    filter_parts: list[str] = []
    concat_inputs: list[str] = []
    for idx, seg in enumerate(active):
        start = float(seg["source_start"])
        end = float(seg["source_end"])
        transform = seg.get("transform", "keep")
        trim_removed = float(seg.get("trim_removed_seconds") or 0)
        if transform == "trim_soft" and trim_removed > 0:
            end = max(start + 0.05, end - trim_removed)

        v_label = f"v{idx}"
        a_label = f"a{idx}"
        v_chain = f"trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS"
        if transform == "speedup_video":
            speed = float(seg.get("speed_factor") or 2.0)
            v_chain += f",setpts=PTS/{speed:.6f}"

        filter_parts.append(f"[0:v]{v_chain}[{v_label}]")
        if has_audio:
            a_chain = f"atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS"
            if transform == "speedup_video":
                speed = float(seg.get("speed_factor") or 2.0)
                a_chain += f",{_build_atempo_chain(speed)}"
            filter_parts.append(f"[0:a]{a_chain}[{a_label}]")
            concat_inputs.extend([f"[{v_label}]", f"[{a_label}]"])
        else:
            concat_inputs.append(f"[{v_label}]")

    if has_audio:
        filter_parts.append(
            f"{''.join(concat_inputs)}concat=n={len(active)}:v=1:a=1[outv][outa]"
        )
        maps = ["-map", "[outv]", "-map", "[outa]"]
        audio_codec = ["-c:a", "aac", "-b:a", "128k"]
    else:
        filter_parts.append(f"{''.join(concat_inputs)}concat=n={len(active)}:v=1:a=0[outv]")
        maps = ["-map", "[outv]"]
        audio_codec = ["-an"]

    filter_complex = ";".join(filter_parts)
    cmd = [
        _ffmpeg_bin(settings),
        "-y",
        "-i",
        str(source_video),
        "-filter_complex",
        filter_complex,
        *maps,
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "20",
        *audio_codec,
        str(output_path),
    ]
    logger.info("Монтаж видео (%s фрагментов): %s", len(active), output_path.name)
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        tail = (result.stderr or "")[-2000:]
        raise RuntimeError(f"ffmpeg montage failed: {tail}")
    return get_media_duration_seconds(output_path, settings)


def burn_ass_onto_video(
    video_path: Path,
    ass_path: Path,
    output_path: Path,
    settings: Settings | None = None,
) -> float:
    """Прожечь ASS-субтитры в видео (libass)."""
    s = settings or get_settings()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    resolved = ass_path.resolve().as_posix().replace("\\", "/")
    filter_path = resolved.replace(":", "\\:").replace("'", "\\'")
    cmd = [
        _ffmpeg_bin(s),
        "-y",
        "-i",
        str(video_path),
        "-vf",
        f"ass='{filter_path}'",
        "-c:a",
        "copy",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        str(output_path),
    ]
    logger.info("Прожиг ASS → %s", output_path.name)
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        tail = (result.stderr or "")[-2000:]
        raise RuntimeError(f"ffmpeg ass burn failed: {tail}")
    return get_media_duration_seconds(output_path, s)


def mux_video_with_voiceover(
    video_path: Path,
    voiceover_path: Path,
    output_path: Path,
    settings: Settings | None = None,
) -> float:
    """Подставить AI-озвучку к исходному видео без изменения картинки (паузы сохраняются)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    video_duration = get_media_duration_seconds(video_path, settings)
    cmd = [
        _ffmpeg_bin(settings),
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(voiceover_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        str(output_path),
    ]
    logger.info("Монтаж: исходное видео + AI-озвучка → %s", output_path.name)
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        tail = (result.stderr or "")[-2000:]
        raise RuntimeError(f"ffmpeg mux failed: {tail}")
    out_duration = get_media_duration_seconds(output_path, settings)
    if abs(out_duration - video_duration) > 2.0:
        logger.warning(
            "Длительность после mux %.1f с, исходник %.1f с",
            out_duration,
            video_duration,
        )
    return out_duration

