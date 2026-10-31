"""Этап 3.2: исправление бухгалтерских терминов без LLM."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.config import Settings
from src.services.tts_preparation_types import TextChange


def _rules_path(settings: Settings) -> Path:
    return settings.assets_dir / "accounting_terms.json"


def load_accounting_term_rules(settings: Settings) -> list[dict[str, Any]]:
    path = _rules_path(settings)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("rules") or [])


def apply_accounting_term_rules(
    text: str,
    settings: Settings,
) -> tuple[str, list[TextChange]]:
    """Исправить только известные термины из словаря."""
    current = str(text or "")
    changes: list[TextChange] = []

    for rule in load_accounting_term_rules(settings):
        pattern = str(rule.get("pattern", "")).strip()
        replacement = str(rule.get("replacement", "")).strip()
        reason = str(rule.get("reason") or "Исправление бухгалтерского термина")
        if not pattern or not replacement:
            continue

        regex = re.compile(pattern, flags=re.IGNORECASE)

        def replace(match: re.Match[str]) -> str:
            before = match.group(0)
            if before == replacement:
                return before
            changes.append(
                TextChange(
                    before=before,
                    after=replacement,
                    stage="3.2 term_correction",
                    reason=reason,
                    metadata={"pattern": pattern},
                )
            )
            return replacement

        current = regex.sub(replace, current)

    return current, changes
