"""Регистрация и валидация артефактов pipeline."""

import json
import os
import tempfile
from threading import RLock
from pathlib import Path
from typing import Any

import jsonschema

_json_io_lock = RLock()


class ArtifactRegistry:
    def __init__(self, job_dir: Path, schemas_dir: Path | None = None) -> None:
        self.job_dir = job_dir
        self.job_dir.mkdir(parents=True, exist_ok=True)
        root = Path(__file__).resolve().parents[1]
        self.schemas_dir = schemas_dir or (root / "schemas")

    def artifact_path(self, name: str) -> Path:
        return self.job_dir / name

    def save_json(self, name: str, data: dict[str, Any], schema_name: str | None = None) -> Path:
        if schema_name:
            self.validate(data, schema_name)
        path = self.artifact_path(name)
        # Readers see either the complete previous document or the complete new one.
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=".saving-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            with _json_io_lock:
                temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return path

    def load_json(self, name: str) -> dict[str, Any]:
        path = self.artifact_path(name)
        if not path.exists():
            raise FileNotFoundError(f"Артефакт не найден: {path}")
        with _json_io_lock:
            return json.loads(path.read_text(encoding="utf-8"))

    def exists(self, name: str) -> bool:
        return self.artifact_path(name).exists()

    def validate(self, data: dict[str, Any], schema_name: str) -> None:
        schema_path = self.schemas_dir / schema_name
        if not schema_path.exists():
            return
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(instance=data, schema=schema)

    def list_artifacts(self) -> list[str]:
        return sorted(p.name for p in self.job_dir.iterdir() if p.is_file())
