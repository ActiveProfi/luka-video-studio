"""CLI-запуск pipeline."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from src.agents.input_ingestion_agent import run_input_ingestion
from src.config import get_settings
from src.domain.enums import ArtifactStatus, PipelineStage
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.orchestrator.pipeline_state import PipelineState

logger = logging.getLogger(__name__)


def new_job_id() -> str:
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return f"job_{ts}"


def run_bootstrap_pipeline(
    raw_video: Path,
    reference_video: Path | None = None,
    job_id: str | None = None,
) -> PipelineState:
    settings = get_settings()
    job_id = job_id or new_job_id()
    job_dir = settings.job_output_dir(job_id)
    registry = ArtifactRegistry(job_dir)
    state = PipelineState(job_id=job_id, output_dir=str(job_dir))

    logging.basicConfig(level=settings.log_level)
    logger.info("Старт pipeline job_id=%s", job_id)

    state.mark_running(PipelineStage.INPUT)
    run_input_ingestion(registry, settings, job_id, raw_video, reference_video)
    state.mark_stage_done(PipelineStage.INPUT)

    registry.save_json("pipeline_state.json", state.to_dict())
    state.status = ArtifactStatus.COMPLETED
    logger.info("Этап 0 завершён. Артефакты: %s", registry.list_artifacts())
    return state


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pipeline видеоуроков 1С")
    parser.add_argument("--input", required=True, help="Путь к raw_video.mp4")
    parser.add_argument("--reference", help="Путь к reference_final.mp4 (образец)")
    parser.add_argument("--job-id", help="ID задачи (опционально)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    raw = Path(args.input)
    ref = Path(args.reference) if args.reference else None
    try:
        state = run_bootstrap_pipeline(raw, ref, args.job_id)
        print(f"OK job_id={state.job_id} output={state.output_dir}")
        return 0
    except FileNotFoundError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
