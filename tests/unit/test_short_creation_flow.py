from unittest.mock import Mock

import pytest

from src.api import shorts


@pytest.mark.parametrize("render", [False, True])
def test_new_platform_can_generate_then_render_without_touching_existing_clip(monkeypatch, render):
    parent = Mock()
    parent.exists.side_effect = lambda name: name == "final_lesson.mp4"
    settings = object()
    create = Mock(return_value=[{"id": "clip_new_shorts"}])
    build = Mock()
    monkeypatch.setattr(shorts, "parent_registry", lambda job: (parent, None))
    monkeypatch.setattr(shorts, "get_settings", lambda: settings)
    monkeypatch.setattr(shorts, "create_drafts", create)
    monkeypatch.setattr(shorts, "render_short", build)
    monkeypatch.setattr(shorts, "queue", lambda parent, tasks, action: action())
    payload = shorts.PlanRequest(target_platform="shorts", kind="promo", render=render)
    assert shorts.plan_shorts("job_test", payload, None) == {"ok": True}
    create.assert_called_once_with(parent, settings, payload.cta, "promo", "shorts")
    if render:
        build.assert_called_once_with(parent, settings, "clip_new_shorts", "shorts")
    else:
        build.assert_not_called()
