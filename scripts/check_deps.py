"""Проверка установленных зависимостей проекта."""
from __future__ import annotations

import importlib
import shutil
import subprocess
import sys


def check(mod: str) -> str:
    try:
        importlib.import_module(mod)
        return "OK"
    except ImportError as exc:
        name = getattr(exc, "name", None) or str(exc)
        return f"НЕТ ({name})"


def ffmpeg_ok() -> str:
    try:
        r = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if r.returncode == 0:
            line = (r.stdout or r.stderr).splitlines()[0]
            return f"OK — {line[:60]}"
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return "НЕ НАЙДЕН в PATH"


def main() -> int:
    core = [
        "fastapi",
        "uvicorn",
        "pydantic",
        "pydantic_settings",
        "httpx",
        "tenacity",
        "dotenv",
        "jsonschema",
        "ffmpeg",
        "numpy",
        "cv2",
        "PIL",
        "openai",
        "multipart",
    ]
    groups: dict[str, list[str]] = {
        "annotations": ["moviepy", "imageio", "pysubs2", "skimage", "shapely"],
        "annotations-ocr (опционально)": ["pytesseract", "easyocr"],
        "audio": ["pydub", "librosa", "soundfile", "scipy"],
        "stt-local (резерв STT)": ["faster_whisper"],
        "tts-elevenlabs (резерв TTS)": ["elevenlabs"],
        "dev": ["pytest", "pytest_asyncio", "ruff", "mypy"],
    }

    print(f"=== Python {sys.version.split()[0]} ===\n")
    print("--- Основные (обязательные) ---")
    core_missing = []
    for mod in core:
        status = check(mod)
        print(f"  {mod:22} {status}")
        if status != "OK":
            core_missing.append(mod)

    for title, mods in groups.items():
        print(f"\n--- {title} ---")
        for mod in mods:
            print(f"  {mod:22} {check(mod)}")

    print("\n--- Системные утилиты ---")
    print(f"  {'ffmpeg':22} {ffmpeg_ok()}")
    for name, cmd in [("ffprobe", "ffprobe"), ("tesseract-ocr", "tesseract")]:
        path = shutil.which(cmd)
        print(f"  {name:22} {'OK — ' + path if path else 'НЕ НАЙДЕН в PATH'}")

    try:
        import src  # noqa: F401

        print("\n--- Пакет проекта ---")
        print("  lesson-pipeline-1c     OK")
    except Exception as exc:
        print(f"\n--- Пакет проекта ---\n  ОШИБКА: {exc}")

    print()
    if core_missing:
        print("ИТОГ: не хватает обязательных пакетов:", ", ".join(core_missing))
        return 1
    print("ИТОГ: все обязательные пакеты установлены.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
