"""Базовые типы TTS-провайдеров."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TTSChunk:
    text: str
    output_path: Path
    language: str = "ru"


@dataclass
class TTSResult:
    output_path: Path
    provider: str
    duration_seconds: float


class TTSProvider(ABC):
    name: str

    @abstractmethod
    async def synthesize(self, chunk: TTSChunk) -> TTSResult:
        """Синтез речи в WAV-файл."""
