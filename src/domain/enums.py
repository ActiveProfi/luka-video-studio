"""Перечисления домена pipeline."""

from enum import StrEnum


class ArtifactStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class PipelineStage(StrEnum):
    INPUT = "input_ingestion"
    TRANSCRIPTION = "transcription"
    SPEECH_CLEANUP = "speech_cleanup"
    TIMING_PAUSE_CANDIDATES = "timing_pause_candidates"
    TIMING_VISUAL_ACTIVITY = "timing_visual_activity"
    TIMING_SEMANTIC_ACTION = "timing_semantic_action"
    TIMING_POLICY = "timing_policy"
    TIMING_REVIEW_BUNDLE = "timing_review_bundle"
    TIMING_REVIEW_RESOLUTION = "timing_review_resolution"
    TIMELINE_MAP = "timeline_map"
    VIDEO_EDIT = "video_edit"
    TTS = "tts"
    SUBTITLES = "subtitles"
    VOICE_VIDEO_SYNC = "voice_video_sync"
    ASSEMBLY = "assembly"
    ANNOTATIONS = "annotations"
    QA = "qa"


class TimingDecisionType(StrEnum):
    REMOVE_AUDIO_VIDEO = "remove_audio_video"
    TRIM_SOFT = "trim_soft"
    SPEEDUP_VIDEO = "speedup_video"
    KEEP_AS_IS = "keep_as_is"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


class ConfidenceRouting(StrEnum):
    AUTO_APPROVE = "auto_approve"
    STANDARD_REVIEW = "standard_review"
    REQUIRED_REVIEW = "required_review"
    SENIOR_REVIEW = "senior_review"


class ProviderName(StrEnum):
    YANDEX = "yandex"
    OPENAI = "openai"
    ELEVENLABS = "elevenlabs"
    FASTER_WHISPER = "faster_whisper"
