import json
import subprocess
from types import SimpleNamespace

import pytest

from src.config import Settings
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services import promo_motion_service as motion
from src.services.short_video_service import ShortDraft


def test_renderer_keeps_full_cause_but_does_not_expose_stack(tmp_path, monkeypatch):
    details = b"No frame found at position 10752\n" + b"at internal stack\n" * 200

    def run(*args, **kwargs):
        kwargs["stdout"].write(details)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(motion.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="Сценарий и озвучка сохранены") as error:
        motion.run_motion_renderer("node", tmp_path, tmp_path)
    assert (tmp_path / "motion-render.log").read_bytes() == details
    assert "internal stack" not in str(error.value)


def test_renderer_timeout_keeps_diagnostics(tmp_path, monkeypatch):
    def run(*args, **kwargs):
        kwargs["stdout"].write(b"render started")
        raise subprocess.TimeoutExpired(args[0], 900)

    monkeypatch.setattr(motion.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="время ожидания"):
        motion.run_motion_renderer("node", tmp_path, tmp_path)
    assert (tmp_path / "motion-render.log").read_bytes() == b"render started"


def setup(tmp_path):
    parent = ArtifactRegistry(tmp_path / "parent")
    child = ArtifactRegistry(tmp_path / "child")
    parent.save_json(
        "speech_script_auto.json",
        {
            "items": [
                {"start": i * 5, "end": (i + 1) * 5, "subtitle": f"Действие {i}"} for i in range(4)
            ]
        },
    )
    parent.save_json(
        "approved_annotations.json",
        {
            "annotations": [
                {
                    "annotation_id": "a",
                    "target_start": 6,
                    "target_end": 7,
                    "placement_confirmed": True,
                    "anchor": {"x": 0.5, "y": 0.5},
                    "label": "Объект",
                }
            ]
        },
    )
    draft = ShortDraft(
        kind="promo",
        title="Реклама",
        start=0,
        end=10,
        narration=["Открываем документ.", "Проверяем результат."],
    )
    return parent, child, draft


def test_valid_shots_cached_and_unrelated_highlight_omitted(tmp_path, monkeypatch):
    parent, child, draft = setup(tmp_path)
    calls = []

    async def complete(settings, system, payload, validate_response):
        calls.append(json.loads(payload))
        raw = json.dumps(
            {
                "shots": [
                    {
                        "unit": 0,
                        "label": "Неверная перефразировка",
                        "annotation": "a",
                        "reason": "Документ",
                    },
                    {
                        "unit": 1,
                        "label": "Проверяем результат.",
                        "annotation": "a",
                        "reason": "Результат",
                    },
                ]
            }
        )
        validate_response(raw)
        return raw, "test"

    monkeypatch.setattr(motion, "complete_with_fallback", complete)
    shots, _, _ = motion.plan_shots(parent, child, Settings(), draft)
    assert shots[0]["annotation"] is None
    assert shots[0]["label"] == draft.narration[0]
    assert shots[1]["annotation"] == "a"
    assert motion.plan_shots(parent, child, Settings(), draft)[0] == shots
    assert len(calls) == 1
    assert calls[0]["units"][1]["annotations"][0]["id"] == "a"


@pytest.mark.parametrize("units", [[99, 1], [1, 1]])
def test_unknown_shots_rejected_but_same_source_can_support_neighboring_phrases(tmp_path, monkeypatch, units):
    parent, child, draft = setup(tmp_path)

    async def complete(settings, system, payload, validate_response):
        raw = json.dumps(
            {
                "shots": [
                    {"unit": u, "label": draft.narration[i], "reason": "Test"}
                    for i, u in enumerate(units)
                ]
            }
        )
        validate_response(raw)
        return raw, "test"

    monkeypatch.setattr(motion, "complete_with_fallback", complete)
    if 99 in units:
        with pytest.raises(ValueError):
            motion.plan_shots(parent, child, Settings(), draft)
    else:
        shots, _, _ = motion.plan_shots(parent, child, Settings(), draft)
        assert [s["unit"] for s in shots] == [1, 1]
    assert child.exists("semantic-shots.json") == (99 not in units)
