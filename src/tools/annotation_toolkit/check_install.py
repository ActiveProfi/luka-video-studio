"""Проверка установки: python -m src.tools.annotation_toolkit.check_install"""

from __future__ import annotations

from src.tools.annotation_toolkit.availability import annotation_stack_report


def main() -> None:
    print(annotation_stack_report(include_ocr=True))


if __name__ == "__main__":
    main()
