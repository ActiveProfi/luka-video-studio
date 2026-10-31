"""Keep an immutable copy of each explicitly approved output."""
import hashlib
import shutil
from pathlib import Path

from src.domain.contracts import utc_now_iso
from src.orchestrator.artifact_registry import ArtifactRegistry

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def fingerprint(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def approval_status(registry, source, name):
    if not source.exists() or not registry.exists(name):
        return {"approved": False}
    record = registry.load_json(name)
    stat = source.stat()
    return {"approved": record.get("source_size") == stat.st_size and record.get("source_mtime_ns") == stat.st_mtime_ns, "record": record}


def approve_output(registry, source, name, category, identity):
    if not source.exists():
        raise ValueError("Сначала соберите видео")
    if approval_status(registry, source, name)["approved"]:
        return registry.load_json(name)
    digest = fingerprint(source)
    destination = PROJECT_ROOT / category / identity / digest
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / source.name
    if not target.exists() or fingerprint(target) != digest:
        temporary = destination / (source.name + ".tmp")
        shutil.copy2(source, temporary)
        if fingerprint(temporary) != digest:
            raise ValueError("Не удалось проверить сохранённую копию")
        temporary.replace(target)
    stat = source.stat()
    record = {"status": "approved", "approved_at": utc_now_iso(), "sha256": digest,
              "source_size": stat.st_size, "source_mtime_ns": stat.st_mtime_ns,
              "saved_file": str(target)}
    ArtifactRegistry(destination).save_json("approval.json", record)
    registry.save_json(name, record)
    return record
