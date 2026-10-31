"""Save approved exports and separate local working archives without changing jobs."""

import argparse
import hashlib
import json
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job")
    parser.add_argument("clip")
    args = parser.parse_args()
    if not re.fullmatch(r"job_[\w-]+", args.job) or not re.fullmatch(r"clip_[a-f0-9]+", args.clip):
        parser.error("Invalid job or clip identifier")
    root = Path(__file__).resolve().parents[1]
    job = root / "output" / args.job
    clip = job / "derivatives" / args.clip
    doc = json.loads((clip / "project.json").read_text(encoding="utf-8"))
    if doc.get("status") != "ready":
        raise RuntimeError("Advertising export is not ready")
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    lesson_dir = root / "Итоговые видео инструкции" / f"{args.job}_{stamp}"
    ad_dir = root / "Итоговые рекламные ролики" / f"{args.clip}_{stamp}"
    options = json.loads((job / "lesson_options.json").read_text(encoding="utf-8"))
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " — ", options.get("title") or args.job)
    title = title.strip(" .")[:120] or args.job
    sources = [(job / "final_lesson.mp4", lesson_dir / f"{title}.mp4")]
    names = {"shorts": "YouTube Shorts", "reels": "Reels", "vk": "VK Клипы"}
    for platform, name in names.items():
        filename = doc["exports"][platform]["filename"]
        if Path(filename).name != filename:
            raise ValueError("Invalid export filename")
        sources.append((clip / filename, ad_dir / f"{name}.mp4"))
    # Also preserve the exact browser preview the user approved.
    sources.append((clip / "preview.webm", ad_dir / "Утверждённый предпросмотр.webm"))
    if not all(src.is_file() for src, _ in sources):
        raise FileNotFoundError("An approved export is missing")
    records = []
    for src, dest in sources:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        sha = digest(src)
        if digest(dest) != sha:
            raise RuntimeError(f"Copy verification failed: {dest}")
        records.append(
            {
                "source": str(src.relative_to(root)),
                "saved": str(dest.relative_to(root)),
                "sha256": sha,
            }
        )
    for folder in (lesson_dir, ad_dir):
        (folder / "Сведения о сохранении.json").write_text(
            json.dumps(
                {
                    "saved_at": stamp,
                    "job": args.job,
                    "approved_clip": args.clip,
                    "note": "Существующие экспорты сохранены без пересборки.",
                    "files": [r for r in records if str(folder.relative_to(root)) in r["saved"]],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    print("Approved exports copied and SHA-256 verified", flush=True)
    paths = sorted(p for p in (root / "output").rglob("*") if p.is_file())
    paths.extend(p for p in root.glob("*.mp4") if p.is_file())
    for advertising, label in ((False, "Инструкции 1С"), (True, "Рекламные ролики")):
        folder = root / "Архив" / label
        folder.mkdir(parents=True, exist_ok=True)
        archive = folder / f"Рабочие материалы_{stamp}.zip"
        manifest = []
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_STORED) as target:
            for path in paths:
                relative = path.relative_to(root)
                if ("derivatives" in relative.parts) != advertising:
                    continue
                target.write(path, relative.as_posix())
                manifest.append({"file": relative.as_posix(), "bytes": path.stat().st_size})
            target.writestr(
                "ARCHIVE_INDEX.json", json.dumps(manifest, ensure_ascii=False, indent=2)
            )
        with zipfile.ZipFile(archive) as check:
            bad = check.testzip()
            if bad:
                raise RuntimeError(f"Archive verification failed: {bad}")
        print(f"Verified archive: {label}; files: {len(manifest)}", flush=True)
    (root / "Архив" / "О папках.txt").write_text(
        "Инструкции 1С — исходники и рабочие материалы инструкций.\n"
        "Рекламные ролики — производные ролики, звук и материалы монтажа.\n"
        "Архивы проверены по CRC. Папка output остаётся рабочей базой приложения.\n"
        "Итоговые папки содержат независимые копии: новые сборки их не изменяют.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
