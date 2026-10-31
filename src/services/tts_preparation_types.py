"""Общие типы для подготовки текста к озвучке."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TextChange:
    before: str
    after: str
    stage: str
    reason: str
    original_duration_seconds: float = 0.0
    edited_duration_seconds: float = 0.0
    duration_diff_seconds: float = 0.0
    budget_status: str = "not_checked"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "before": self.before,
            "after": self.after,
            "stage": self.stage,
            "reason": self.reason,
            "original_duration_seconds": round(self.original_duration_seconds, 3),
            "edited_duration_seconds": round(self.edited_duration_seconds, 3),
            "duration_diff_seconds": round(self.duration_diff_seconds, 3),
            "budget_status": self.budget_status,
            "metadata": self.metadata,
        }
