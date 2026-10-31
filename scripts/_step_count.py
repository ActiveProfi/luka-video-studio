import json
from pathlib import Path

def count_steps(text):
    words = [w for w in str(text or "").strip().split() if w]
    if not words: return 0
    return sum(len(w) for w in words) + max(0, len(words)-1)

clean = json.loads(Path("output/job_20260616_054936/clean_transcript.json").read_text(encoding="utf-8"))
trans = json.loads(Path("output/job_20260616_054936/transcript.json").read_text(encoding="utf-8"))
print("id | slot | budget(orig) | total(edit) | budget(trans)")
for c, t in zip(clean["segments"], trans["segments"]):
    slot = c["end"]-c["start"]
    bo = count_steps(c.get("original_text",""))
    bt = count_steps(c["text"])
    btr = count_steps(t["text"])
    print(f"{c['segment_id']} | {slot:.1f}s | {bo} | {bt} | {btr}")
