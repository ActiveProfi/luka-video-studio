"""Маршрутизация по confidence для Timing Decision Agent."""

from src.config import Settings
from src.domain.enums import ConfidenceRouting


def route_confidence(
    confidence: float,
    critical_for_learning: bool,
    settings: Settings,
) -> ConfidenceRouting:
    if confidence < settings.confidence_senior_review and critical_for_learning:
        return ConfidenceRouting.SENIOR_REVIEW
    if confidence >= settings.confidence_auto_approve:
        return ConfidenceRouting.AUTO_APPROVE
    if confidence >= settings.confidence_standard_review:
        return ConfidenceRouting.STANDARD_REVIEW
    return ConfidenceRouting.REQUIRED_REVIEW
