"""Настройки приложения из .env."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    log_level: str = "INFO"
    output_dir: Path = Path("./output")
    fixtures_dir: Path = Path("./fixtures")
    assets_dir: Path = Path("./assets")
    pipeline_version: str = "1.0.0"
    default_language: str = "ru"

    confidence_auto_approve: float = 0.92
    confidence_standard_review: float = 0.75
    confidence_senior_review: float = 0.60

    stt_provider: str = "yandex"
    stt_fallback_order: str = "yandex,openai,faster_whisper"
    tts_provider: str = "yandex"
    tts_fallback_order: str = "yandex,openai,elevenlabs"
    llm_provider: str = "yandex"
    llm_fallback_order: str = "yandex,openai"

    yandex_api_key: str = ""
    yandex_folder_id: str = ""
    yandex_stt_model: str = "general"
    yandex_tts_voice: str = "alena"
    yandex_tts_emotion: str = "neutral"
    yandex_tts_speed: float = 1.0

    yandex_gpt_api_key: str = ""
    yandex_gpt_folder_id: str = ""
    yandex_gpt_model: str = "yandexgpt-lite"

    openai_api_key: str = ""
    openai_stt_model: str = "gpt-transcribe"
    stt_context: str = ""
    stt_keywords: str = ""
    openai_tts_model: str = "tts-1-hd"
    openai_tts_voice: str = "nova"
    openai_tts_speed: float = 1.0
    openai_llm_model: str = "gpt-4o-mini"

    # Отдельный LLM-профиль только для кнопки «Улучшить ИИ» в редакторе текста.
    cleanup_improve_llm_provider: str = "openai"
    cleanup_improve_llm_fallback_order: str = "openai,yandex"
    cleanup_improve_openai_llm_model: str = "gpt-4o"

    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    elevenlabs_voices: dict[str, str] = Field(default_factory=dict)
    elevenlabs_model: str = "eleven_multilingual_v2"
    elevenlabs_speed: float = 1.0
    edge_tts_voice: str = "fr-FR-RemyMultilingualNeural"
    edge_tts_speed: float = 1.0

    whisper_model: str = "medium"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    ffmpeg_path: str = ""
    ffprobe_path: str = ""
    # auto | tesseract | easyocr | off
    annotation_ocr_engine: str = "auto"
    reference_video_path: Path = Path("./fixtures/reference_final.mp4")
    domain_glossary_path: Path = Path("./assets/glossary_1c.txt")

    # Автоматическое разбиение ролика на тайм-блоки (этап 1 архитектуры v3)
    block_min_seconds: float = 2.5
    block_max_seconds: float = 12.0
    block_target_seconds: float = 7.0
    block_silence_noise_db: int = -32
    block_silence_min_seconds: float = 0.45
    block_scene_threshold: float = 0.35
    # Допустимый запас озвучки относительно длительности блока
    voiceover_slot_tolerance_seconds: float = 0.6
    screen_analysis_model: str = "gpt-4o"
    screen_annotation_auto_confidence: float = 0.92

    review_mode: str = "ui"
    review_ui_url: str = "http://127.0.0.1:5173"
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    @property
    def stt_fallbacks(self) -> list[str]:
        return [p.strip() for p in self.stt_fallback_order.split(",") if p.strip()]

    @property
    def tts_fallbacks(self) -> list[str]:
        return [p.strip() for p in self.tts_fallback_order.split(",") if p.strip()]

    @property
    def llm_fallbacks(self) -> list[str]:
        return [p.strip() for p in self.llm_fallback_order.split(",") if p.strip()]

    def job_output_dir(self, job_id: str) -> Path:
        path = self.output_dir / job_id
        path.mkdir(parents=True, exist_ok=True)
        return path


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
