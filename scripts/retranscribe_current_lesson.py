"""Reprocess the explicitly authorized lesson, retaining previous text artifacts."""
import json
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.config import Settings
from src.agents.speech_recognition_agent import run_speech_recognition
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.automatic_script_service import generate_instruction_script

logging.basicConfig(level=logging.INFO)
logging.getLogger('httpx').setLevel(logging.WARNING)
cfg = Settings()
job_id = 'job_20261006_065154'
registry = ArtifactRegistry(cfg.job_output_dir(job_id))
state = registry.load_json('pipeline_state.json')
if state.get('status') == 'running':
    raise RuntimeError('Lesson is already running')
backup = registry.job_dir / ('before_retranscription_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
backup.mkdir()
for name in ('transcript.json', 'time_blocks.json', 'script_review_report.json',
             'subtitles.srt', 'subtitle_timing.json', 'pipeline_state.json'):
    source = registry.artifact_path(name)
    if source.exists():
        shutil.copy2(source, backup / name)
registry.save_json('pipeline_state.json', {**state, 'status': 'running', 'current_stage': 'subtitle_capture', 'error': None})
try:
    transcript = run_speech_recognition(registry, cfg, job_id, force=True)
    print('Transcription complete:', len(transcript['segments']), flush=True)
    report = generate_instruction_script(registry, cfg, job_id, refresh_generated=True)
    registry.save_json('pipeline_state.json', {**state, 'status': 'completed', 'current_stage': None, 'error': None})
    print(json.dumps({'status': report['status'], 'review_count': report['review_count'],
                      'edited_count': report.get('edited_count'), 'backup': str(backup)}, ensure_ascii=False))
except Exception as exc:
    registry.save_json('pipeline_state.json', {**state, 'status': 'failed', 'current_stage': None, 'error': type(exc).__name__})
    raise
