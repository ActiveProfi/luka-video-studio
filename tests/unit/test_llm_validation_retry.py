import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.providers.llm import runner


def test_retry_receives_validation_feedback(monkeypatch):
    provider = SimpleNamespace(name="test", complete=AsyncMock(side_effect=["wrong", "valid"]))
    monkeypatch.setattr(runner, "build_llm_chain", lambda _: [provider])
    def validate(text):
        if text != "valid":
            raise ValueError("maximum eight phrases")
    assert asyncio.run(runner.complete_with_fallback(None, "system", "source", validate_response=validate)) == ("valid", "test")
    assert "maximum eight phrases" in provider.complete.call_args_list[1].args[1]


def test_invalid_response_is_not_reported_as_provider_outage(monkeypatch):
    provider = SimpleNamespace(name="test", complete=AsyncMock(return_value="wrong"))
    monkeypatch.setattr(runner, "build_llm_chain", lambda _: [provider])
    def validate(_):
        raise ValueError("bad format")
    with pytest.raises(RuntimeError, match="ИИ ответил"):
        asyncio.run(runner.complete_with_fallback(None, "system", "source", validate_response=validate))
