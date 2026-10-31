"""Этап 3.4: нормализация текста под конкретный TTS без LLM."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from src.config import Settings
from src.services.tts_preparation_types import TextChange


def pronunciation_rules_hash(settings: Settings) -> str:
    from src.services.contextual_pronunciation import PROMPT
    from src.services.pronunciation_entities import KNOWN_NAMES
    from src.services.speech_script_auto import ABBREVIATIONS, SYMBOLS

    payload = {
        "revision": 4,
        "context_prompt": PROMPT,
        "names": KNOWN_NAMES,
        "abbreviations": ABBREVIATIONS,
        "symbols": SYMBOLS,
        "rules": load_tts_rules(settings),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _rules_path(settings: Settings, provider: str | None = None) -> Path:
    resolved = (provider or settings.tts_provider or "yandex").strip().lower()
    return settings.assets_dir / f"tts_rules_{resolved}.json"


def load_tts_rules(settings: Settings, provider: str | None = None) -> list[dict[str, Any]]:
    path = _rules_path(settings, provider)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("rules") or [])


def apply_tts_normalization_rules(
    text: str,
    settings: Settings,
    *,
    provider: str | None = None,
) -> tuple[str, list[TextChange]]:
    """Подготовить известные символы и аббревиатуры к произношению TTS."""
    current = str(text or "")
    changes: list[TextChange] = []
    resolved_provider = (provider or settings.tts_provider or "yandex").strip().lower()

    for rule in load_tts_rules(settings, resolved_provider):
        pattern = str(rule.get("pattern", "")).strip()
        replacement = str(rule.get("replacement", "")).strip()
        reason = str(rule.get("reason") or "Подготовка к озвучке")
        if not pattern or not replacement:
            continue

        regex = re.compile(pattern)

        def replace(match: re.Match[str]) -> str:
            before = match.group(0)
            if before == replacement:
                return before
            changes.append(
                TextChange(
                    before=before,
                    after=replacement,
                    stage="3.4 tts_normalization",
                    reason=reason,
                    metadata={"provider": resolved_provider, "pattern": pattern},
                )
            )
            return replacement

        current = regex.sub(replace, current)

    current = re.sub(r"\s{2,}", " ", current).strip()
    return current, changes


def prepare_provider_speech_text(text: str, settings: Settings, provider: str) -> str:
    """Apply the pronunciation dictionary at the synthesis boundary on every path."""
    spoken, _ = apply_tts_normalization_rules(text, settings, provider=provider)
    if provider == "yandex":
        spoken = re.sub(r"(?i)\bодин эс\s+(?!sil<)(?=[а-яёa-z])", "один эс sil<[100]> ", spoken)
    return spoken
