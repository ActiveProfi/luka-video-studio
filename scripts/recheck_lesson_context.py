"""Recheck model-only ambiguity in a saved, untouched generated script."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.config import Settings
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.automatic_script_service import make_blocks, resolve_context_reviews
from src.services.subtitle_capture_service import finalize_subtitles

settings = Settings()
job_id = 'job_20261006_065154'
registry = ArtifactRegistry(settings.job_output_dir(job_id))
report = registry.load_json('script_review_report.json')
doc = registry.load_json('time_blocks.json')
expected = make_blocks(report['segments'], doc['duration_seconds'])
keys = ('id', 'start', 'end', 'subtitle')
assert not doc.get('saved_at'), 'Saved user text must not be overwritten'
assert [[b.get(k) for k in keys] for b in doc['blocks']] == [
    [b.get(k) for k in keys] for b in expected], 'User edits must not be overwritten'
eligible = {s['segment_id'] for s in report['segments']
            if s.get('needs_review') and s.get('review_reason') == 'неясное место'}
resolve_context_reviews(settings, report['segments'], eligible)
report['review_count'] = sum(bool(s.get('needs_review')) for s in report['segments'])
report['status'] = 'needs_review' if report['review_count'] else 'completed'
doc['blocks'] = make_blocks(report['segments'], doc['duration_seconds'])
registry.save_json('time_blocks.json', doc)
registry.save_json('script_review_report.json', report)
if not report['review_count']:
    finalize_subtitles(registry, job_id, settings=settings, approved_by='automatic')
print('Context review complete; remaining:', report['review_count'])
