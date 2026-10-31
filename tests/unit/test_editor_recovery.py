import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from src.config import Settings
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.providers.llm.runner import complete_with_fallback
from src.services.automatic_script_service import (
    parse_editor_response,
    resolve_context_reviews,
    retryable_script,
)


def test_invalid_answer_uses_next_provider():
    bad = AsyncMock()
    bad.name = "primary"
    bad.complete.return_value = "broken JSON"
    good = AsyncMock()
    good.name = "fallback"
    good.complete.return_value = '{"ok":true}'
    with patch("src.providers.llm.runner.build_llm_chain", return_value=[bad, good]):
        result, provider = asyncio.run(
            complete_with_fallback(
                Settings(_env_file=None), "system", "user", validate_response=json.loads
            )
        )
    assert provider == "fallback"
    assert json.loads(result)["ok"] is True
    assert bad.complete.await_count == 2


def test_duplicate_ids_rejected():
    item = {"segment_id": "s", "text": "Text", "needs_review": False}
    with pytest.raises(ValueError):
        parse_editor_response(json.dumps({"segments": [item, item]}), [item])


def test_array_response_keeps_all_segments():
    item = {"segment_id": "s", "text": "Text", "needs_review": False}
    assert parse_editor_response(json.dumps([item]), [item]) == {"s": item}
    with pytest.raises(ValueError, match="состав"):
        parse_editor_response(json.dumps([item]), [item, {**item, "segment_id": "s2"}])


def test_context_review_clears_only_model_ambiguity():
    items = [
        {
            "segment_id": "s",
            "text": "Открываем",
            "needs_review": True,
            "review_reason": "Обрыв фразы",
        },
        {
            "segment_id": "s2",
            "text": "документ",
            "needs_review": True,
            "review_reason": "Низкая уверенность распознавания",
        },
    ]
    answer = json.dumps(
        {"segments": [{"segment_id": "s", "text": "Открываем", "needs_review": False}]}
    )
    with patch(
        "src.services.automatic_script_service.complete_with_fallback",
        new=AsyncMock(return_value=(answer, "test")),
    ):
        resolve_context_reviews(Settings(_env_file=None), items, {"s"})
    assert not items[0]["needs_review"]
    assert items[1]["needs_review"]


def test_context_review_cannot_rewrite_text():
    items = [
        {
            "segment_id": "s",
            "text": "Не удаляем",
            "needs_review": True,
            "review_reason": "Неясная фраза",
        }
    ]
    answer = json.dumps(
        {"segments": [{"segment_id": "s", "text": "Удаляем", "needs_review": False}]}
    )
    with patch(
        "src.services.automatic_script_service.complete_with_fallback",
        new=AsyncMock(return_value=(answer, "test")),
    ):
        resolve_context_reviews(Settings(_env_file=None), items, {"s"})
    assert items[0]["needs_review"]
    assert items[0]["text"] == "Не удаляем"


def test_retry_does_not_overwrite_manual_changes(tmp_path):
    registry = ArtifactRegistry(tmp_path)
    registry.save_json(
        "script_review_report.json",
        {
            "status": "technical_error",
            "segments": [{"segment_id": "s", "start": 0, "end": 2, "text": "Original"}],
        },
    )
    doc = {
        "duration_seconds": 2,
        "blocks": [{"id": 1, "start": 0, "end": 2, "subtitle": "Original"}],
    }
    assert retryable_script(registry, doc)
    doc["blocks"][0]["subtitle"] = "My edit"
    assert not retryable_script(registry, doc)
    doc["blocks"][0]["subtitle"] = "Original"
    doc["saved_at"] = "2026-10-06"
    assert not retryable_script(registry, doc)
