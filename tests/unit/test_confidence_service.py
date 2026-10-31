import pytest

from src.config import Settings
from src.domain.enums import ConfidenceRouting
from src.services.confidence_service import route_confidence


def test_auto_approve_high_confidence():
    s = Settings(confidence_auto_approve=0.92, confidence_standard_review=0.75, confidence_senior_review=0.60)
    assert route_confidence(0.95, False, s) == ConfidenceRouting.AUTO_APPROVE


def test_senior_review_critical_low_confidence():
    s = Settings(confidence_auto_approve=0.92, confidence_standard_review=0.75, confidence_senior_review=0.60)
    assert route_confidence(0.55, True, s) == ConfidenceRouting.SENIOR_REVIEW


def test_required_review():
    s = Settings(confidence_auto_approve=0.92, confidence_standard_review=0.75, confidence_senior_review=0.60)
    assert route_confidence(0.70, False, s) == ConfidenceRouting.REQUIRED_REVIEW
