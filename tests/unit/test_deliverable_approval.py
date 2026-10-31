from pathlib import Path

from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services import deliverable_approval as approvals


def test_approval_preserves_previous_file_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(approvals, "PROJECT_ROOT", tmp_path)
    registry = ArtifactRegistry(tmp_path / "job")
    source = registry.artifact_path("shorts.mp4")
    source.write_bytes(b"first approved video")
    args = (registry, source, "approval.json", "finals", "clip_one")
    first = approvals.approve_output(*args)
    assert approvals.approve_output(*args) == first
    assert approvals.approval_status(registry, source, "approval.json")["approved"]
    source.write_bytes(b"a different new video")
    assert not approvals.approval_status(registry, source, "approval.json")["approved"]
    second = approvals.approve_output(*args)
    assert first["saved_file"] != second["saved_file"]
    assert Path(first["saved_file"]).read_bytes() == b"first approved video"
    assert Path(second["saved_file"]).read_bytes() == b"a different new video"
