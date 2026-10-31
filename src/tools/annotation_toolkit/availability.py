"""Проверка установленных библиотек для аннотаций."""

from __future__ import annotations

from importlib import import_module
from typing import Any

# (pip-имя, import-имя, зачем нужно)
ANNOTATION_PACKAGES: list[tuple[str, str, str]] = [
    ("opencv-python-headless", "cv2", "Кадры, стрелки/рамки, поиск элементов на экране"),
    ("Pillow", "PIL", "PNG-оверлеи со стрелками и подписями"),
    ("moviepy", "moviepy", "Наложение PNG/GIF на видео по таймкоду"),
    ("imageio", "imageio", "Чтение/запись кадров"),
    ("pysubs2", "pysubs2", "ASS/SRT с точными координатами (libass через ffmpeg)"),
    ("scikit-image", "skimage", "Template matching — найти кнопку/иконку на кадре"),
    ("shapely", "shapely", "Геометрия стрелок и зон выделения"),
    ("numpy", "numpy", "Массивы кадров (уже в базовых зависимостях)"),
]

OCR_PACKAGES: list[tuple[str, str, str]] = [
    ("pytesseract", "pytesseract", "OCR текста интерфейса (нужен Tesseract-OCR в системе)"),
    ("easyocr", "easyocr", "OCR без отдельного бинарника (тяжёлый, но точнее на скринах)"),
]


def _try_import(module_name: str) -> tuple[bool, str | None]:
    try:
        import_module(module_name)
        return True, None
    except Exception as exc:  # noqa: BLE001 — диагностика окружения
        return False, str(exc)


def package_status(packages: list[tuple[str, str, str]] | None = None) -> list[dict[str, Any]]:
    packages = packages or ANNOTATION_PACKAGES
    rows: list[dict[str, Any]] = []
    for pip_name, import_name, purpose in packages:
        ok, err = _try_import(import_name)
        rows.append(
            {
                "pip": pip_name,
                "import": import_name,
                "purpose": purpose,
                "installed": ok,
                "error": err,
            }
        )
    return rows


def missing_packages(include_ocr: bool = False) -> list[str]:
    rows = package_status(ANNOTATION_PACKAGES + (OCR_PACKAGES if include_ocr else []))
    return [row["pip"] for row in rows if not row["installed"]]


def annotation_stack_report(include_ocr: bool = False) -> str:
    lines = ["Стек библиотек для аннотаций:", ""]
    for row in package_status(ANNOTATION_PACKAGES + (OCR_PACKAGES if include_ocr else [])):
        mark = "OK" if row["installed"] else "—"
        lines.append(f"[{mark}] {row['pip']} ({row['import']}) — {row['purpose']}")
        if row["error"]:
            lines.append(f"      ошибка: {row['error']}")
    missing = missing_packages(include_ocr=include_ocr)
    if missing:
        lines.append("")
        lines.append("Установить: pip install -e \".[annotations]\"")
        if include_ocr:
            lines.append("OCR: pip install -e \".[annotations-ocr]\"")
    return "\n".join(lines)
