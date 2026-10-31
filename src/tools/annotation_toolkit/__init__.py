"""
Инструменты для точных аннотаций на screencast (1С и др.).

Сейчас основной pipeline использует ffmpeg drawbox — этот пакет НЕ подключён к нему.
Установка (из корня проекта):

    .\\.venv\\Scripts\\pip install -e \".[annotations]\"

OCR (опционально, тяжелее):

    .\\.venv\\Scripts\\pip install -e \".[annotations-ocr]\"

Проверка, что установилось:

    python -m src.tools.annotation_toolkit.check_install
"""

from src.tools.annotation_toolkit.availability import annotation_stack_report, missing_packages

__all__ = ["annotation_stack_report", "missing_packages"]
