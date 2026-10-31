import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.config import Settings
from src.domain.contracts import utc_now_iso
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.providers.stt.base import TranscriptSegment
from src.services.transcript_alignment import align_transcript
from src.services.automatic_script_service import generate_instruction_script
cfg = Settings()
job_id = 'job_20261006_065154'
registry = ArtifactRegistry(cfg.job_output_dir(job_id))
original = None
for path in sorted(registry.job_dir.glob('before_retranscription_*/transcript.json')):
    candidate = json.loads(path.read_text(encoding='utf-8'))
    if candidate['provider'] == 'faster_whisper':
        original = candidate
        break
assert original is not None
result = registry.load_json('stt_full_audio_result.json')
anchors = [TranscriptSegment(s['segment_id'], s['start'], s['end'], s['text']) for s in original['segments']]
aligned = align_transcript(result['text'], anchors)
assert ' '.join(s.text for s in aligned) == ' '.join(result['text'].split())
new = {**original, 'created_at': utc_now_iso(), 'provider': 'openai', 'model': result['model'],
       'timing_source': 'text_aligned_to_acoustic_segments',
       'segments': [{'segment_id': s.segment_id, 'start': s.start, 'end': s.end, 'text': s.text, 'words': []} for s in aligned]}
new.pop('confidence_summary', None)
registry.save_json('transcript.json', new, 'transcript.schema.json')
report = generate_instruction_script(registry, cfg, job_id, refresh_generated=True)
state = registry.load_json('pipeline_state.json')
registry.save_json('pipeline_state.json', {**state, 'status': 'completed', 'error': None, 'current_stage': None})
print(json.dumps({'status':report['status'], 'review_count':report['review_count'], 'edited_count':report.get('edited_count')},ensure_ascii=False))
