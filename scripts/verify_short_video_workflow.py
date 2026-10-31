"""Create real short-video examples and verify that the parent lesson is untouched."""

import argparse
import hashlib
import json

from src.config import get_settings
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.short_video_service import create_drafts, render_short


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("job")
    args = parser.parse_args()
    settings = get_settings()
    parent = ArtifactRegistry(settings.job_output_dir(args.job))
    files = [p for p in parent.job_dir.iterdir() if p.is_file()]
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    settings = settings.model_copy(
        update={
            "llm_provider": settings.cleanup_improve_llm_provider,
            "llm_fallback_order": settings.cleanup_improve_llm_fallback_order,
            "openai_llm_model": settings.cleanup_improve_openai_llm_model,
        }
    )
    print("Creating excerpt and advertising drafts", flush=True)
    drafts = create_drafts(parent, settings, "Полный разбор — в основном видео", "both")
    reports = []
    for kind in ("excerpt", "promo"):
        draft = next(d for d in drafts if d["draft"]["kind"] == kind)
        for platform in ("shorts", "reels", "vk"):
            print(f"Rendering {kind}: {draft['id']} / {platform}", flush=True)
            report = render_short(parent, settings, draft["id"], platform)
        reports.append(report)
    changed = [
        p.name for p in files if hashlib.sha256(p.read_bytes()).hexdigest() != before[p.name]
    ]
    if changed:
        raise RuntimeError(f"Parent artifacts changed: {changed}")
    result = {"status": "passed", "parent_artifacts_unchanged": len(files), "shorts": reports}
    report_path = parent.job_dir / "derivatives/verification.json"
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps({"status": "passed", "report": str(report_path)}, ensure_ascii=False), flush=True
    )


if __name__ == "__main__":
    main()
