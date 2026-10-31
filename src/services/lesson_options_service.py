"""Per-lesson options; never mutate the shared provider configuration."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from src.config import Settings, get_settings
from src.orchestrator.artifact_registry import ArtifactRegistry

OPTIONS_FILE = "lesson_options.json"
VOICES = {
    "edge": {
        "fr-FR-RemyMultilingualNeural": "Реми — мужской",
        "de-DE-FlorianMultilingualNeural": "Флориан — мужской",
    },
    "yandex": {
        "alena": "Алёна",
        "filipp": "Филипп",
        "ermil": "Ермил",
        "jane": "Джейн",
        "omazh": "Омаж",
        "zahar": "Захар",
    },
    "openai": {
        "alloy": "Alloy",
        "echo": "Echo",
        "fable": "Fable",
        "onyx": "Onyx",
        "nova": "Nova",
        "shimmer": "Shimmer",
    },
}


def voice_catalog(settings: Settings | None = None) -> dict[str, dict[str, str]]:
    settings = settings or get_settings()
    voices = dict(settings.elevenlabs_voices)
    if settings.elevenlabs_voice_id and settings.elevenlabs_voice_id not in voices:
        voices[settings.elevenlabs_voice_id] = "Основной голос ElevenLabs"
    return {**VOICES, "elevenlabs": voices}


class LessonOptions(BaseModel):
    provider: Literal["yandex", "openai", "elevenlabs", "edge"] = "yandex"
    voice: str = "alena"
    speed: float = Field(default=1.0, ge=0.8, le=1.2)
    automatic: bool = True
    title: str = Field(default="Видеоинструкция", max_length=160)
    company_name: str = Field(default="", max_length=100)
    company_description: str = Field(default="", max_length=1200)
    topic_context: str = Field(default="", max_length=2000)
    terminology: str = Field(default="", max_length=1500)
    content_profile: Literal["general", "accounting"] = "general"
    intro_seconds: float = Field(default=6, ge=4, le=15)
    outro_seconds: float = Field(default=4, ge=3, le=10)
    intro: bool = True
    outro: bool = True
    branding_reference_ids: list[str] = Field(default_factory=list, max_length=3)
    branding_reference_notes: str = Field(default="", max_length=1500)

    @field_validator("branding_reference_ids")
    @classmethod
    def valid_references(cls, values):
        from src.services.branding_reference_service import load_reference
        for reference_id in values:
            load_reference(get_settings(), reference_id)
        return list(dict.fromkeys(values))

    @field_validator("title", "company_name", "company_description", "topic_context", "terminology")
    @classmethod
    def clean_brand_text(cls, value: str) -> str:
        return " ".join(value.split())

    def validate_voice(self) -> None:
        if self.voice not in voice_catalog()[self.provider]:
            raise ValueError("Выберите голос из списка выбранного сервиса")


def load_options(registry: ArtifactRegistry, settings: Settings) -> LessonOptions:
    if registry.exists(OPTIONS_FILE):
        data = registry.load_json(OPTIONS_FILE)
        data.setdefault("content_profile", "accounting")
        options = LessonOptions.model_validate(data)
    else:
        provider = settings.tts_provider if settings.tts_provider in VOICES else "yandex"
        voice = settings.edge_tts_voice if provider == "edge" else settings.openai_tts_voice if provider == "openai" else settings.yandex_tts_voice
        # Existing lessons retain their manual review flow and no title cards.
        options = LessonOptions(
            provider=provider, voice=voice, automatic=False, intro=False, outro=False,
            content_profile="accounting",
        )
    options.validate_voice()
    return options


def voice_settings(registry: ArtifactRegistry, settings: Settings) -> Settings:
    options = load_options(registry, settings)
    return settings.model_copy(
        update={
            "tts_provider": options.provider,
            "tts_fallback_order": options.provider,  # Do not change the selected voice on failure.
            "yandex_tts_voice": options.voice
            if options.provider == "yandex"
            else settings.yandex_tts_voice,
            "openai_tts_voice": options.voice
            if options.provider == "openai"
            else settings.openai_tts_voice,
            "yandex_tts_speed": options.speed,
            "openai_tts_speed": options.speed,
            "elevenlabs_voice_id": options.voice if options.provider == "elevenlabs" else settings.elevenlabs_voice_id,
            "elevenlabs_speed": options.speed,
            "edge_tts_voice": options.voice if options.provider == "edge" else settings.edge_tts_voice,
            "edge_tts_speed": options.speed,
        }
    )


def voice_hash(registry: ArtifactRegistry, settings: Settings) -> str:
    options = load_options(registry, settings)
    value = {k: getattr(options, k) for k in ("provider", "voice", "speed")}
    value["model"] = "edge-multilingual" if options.provider == "edge" else settings.elevenlabs_model if options.provider == "elevenlabs" else settings.openai_tts_model if options.provider == "openai" else "speechkit-v1"
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
