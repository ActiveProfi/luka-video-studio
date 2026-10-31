from unittest.mock import Mock

from src.services import annotation_review_service as service


def test_missing_thumbnails_do_not_invalidate_new_automatic_approval(monkeypatch):
    docs = {
        service.SUGGESTIONS_FILE: {
            "suggestions": [{"placement_confirmed": True, "linked_segment_id": "one"}]
        },
        service.REVIEW_FILENAME: {"status": "pending", "blocks": []},
    }
    registry = Mock()
    registry.load_json.side_effect = lambda name: docs[name]
    registry.save_json.side_effect = lambda name, data, schema: docs.update({name: data})
    monkeypatch.setattr(service, "annotation_suggestions_ready", lambda _: True)
    monkeypatch.setattr(service, "confirmed_suggestions", lambda items: items)
    monkeypatch.setattr(service, "load_annotation_review", lambda *_: docs[service.REVIEW_FILENAME])
    prepared = False

    def prepare(*_):
        nonlocal prepared
        if not prepared:
            docs.pop(service.APPROVED_FILE, None)
            docs[service.REVIEW_FILENAME]["status"] = "pending"
            prepared = True

    def payload(*_):
        prepare()
        return docs[service.REVIEW_FILENAME]

    monkeypatch.setattr(service, "_ensure_preview_and_review", prepare)
    monkeypatch.setattr(service, "get_annotation_edit_payload", payload)
    result = service.approve_annotation_review(registry, "job", approved_by="automatic")
    assert result["status"] == "approved"
    assert docs[service.APPROVED_FILE]["auto_approved_count"] == 1


def test_subtitle_preview_reset_keeps_verified_annotations(tmp_path):
    from src.orchestrator.artifact_registry import ArtifactRegistry

    registry = ArtifactRegistry(tmp_path)
    registry.save_json(service.SUGGESTIONS_FILE, {"suggestions": []})
    registry.save_json(service.REVIEW_FILENAME, {"status": "approved"})
    registry.save_json(service.APPROVED_FILE, {"annotations": []})
    assert not registry.exists(service.PREVIEW_FILENAME)
    assert service.annotation_review_approved(registry, "job")


def test_reading_annotation_review_does_not_start_preview_render(tmp_path, monkeypatch):
    from src.orchestrator.artifact_registry import ArtifactRegistry
    registry = ArtifactRegistry(tmp_path)
    registry.save_json(service.SUGGESTIONS_FILE, {"suggestions": []})
    registry.save_json(service.REVIEW_FILENAME, {"status": "pending", "blocks": []})
    prepare = Mock(side_effect=AssertionError("GET must not render"))
    monkeypatch.setattr(service, "_ensure_preview_and_review", prepare)
    monkeypatch.setattr("src.services.subtitle_burn_service.ensure_subtitled_studio_video", lambda *a, **k: "edited_video.mp4")
    monkeypatch.setattr("src.services.subtitle_review_service.subtitles_edit_ready", lambda _: False)
    payload = service.get_annotation_edit_payload(registry, "job")
    assert payload["pending_count"] == 0
    prepare.assert_not_called()
