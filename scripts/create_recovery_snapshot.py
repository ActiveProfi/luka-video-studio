"""Local recovery archive; includes local .env, so never upload this archive."""
import hashlib
import json
from datetime import datetime
from pathlib import Path
import subprocess
import zipfile


def main():
    root = Path(__file__).resolve().parents[1]
    lesson = root / "output/job_20261006_065154"
    state = json.loads((lesson / "pipeline_state.json").read_text(encoding="utf-8"))
    if state.get("status") == "running":
        raise RuntimeError("Lesson processing is running; snapshot cancelled")
    folder = root / "backups" / ("recovery_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    folder.mkdir(parents=True, exist_ok=False)
    names = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=root
    ).decode("utf-8").split("\0")
    files = {root / name for name in names if name and (root / name).is_file()}
    for extra in [root / ".env", root / "review-ui/dist", lesson]:
        if extra.is_file():
            files.add(extra)
        elif extra.is_dir():
            files.update(p for p in extra.rglob("*") if p.is_file()
                         and not any(part.startswith("before_") for part in p.relative_to(extra).parts))
    manifest = {"created_at": datetime.now().isoformat(), "lesson": lesson.name,
                "git_base": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root).decode().strip(),
                "contains_local_secrets": True, "files": {}}
    archive = folder / "project_and_lesson.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        for path in sorted(files):
            name = path.relative_to(root).as_posix()
            data = path.read_bytes()
            manifest["files"][name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            z.writestr(name, data)
        z.writestr("RECOVERY_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(archive) as z:
        failure = z.testzip()
        if failure:
            raise RuntimeError(f"Archive integrity check failed: {failure}")
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / "RESTORE.txt").write_text(
        "Local backup. Contains .env credentials: do not publish this archive.\n"
        "Restore into a separate directory. The archive contains source, built UI and the current lesson.\n"
        "Install Python dependencies from pyproject.toml in a new virtual environment if needed.\n"
        "Run: python -m uvicorn src.api.app:app --host 127.0.0.1 --port 8000\n"
        "Do not overwrite a running project. Historical before_* lesson copies are excluded.\n",
        encoding="utf-8")
    print(json.dumps({"folder": str(folder), "files": len(files), "bytes": archive.stat().st_size,
                      "integrity": "passed"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
