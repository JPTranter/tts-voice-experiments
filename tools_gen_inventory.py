#!/usr/bin/env python
"""Regenerate results/sample_inventory.json — every committed audio sample with duration/size.

The README catalog reads durations from this file, and it doubles as the quick answer to
"what samples exist and how long are they". Run after adding renders: python tools_gen_inventory.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKIP_PARTS = {"renders", "raw", "parts", "_speed_probe", "emotion_probe"}


def duration(p: Path) -> float | None:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    try:
        return round(float(out.stdout.strip()), 2)
    except ValueError:
        return None


def main() -> None:
    rows = []
    for p in sorted((ROOT / "audio").rglob("*.mp3")):
        if SKIP_PARTS & set(p.parts):
            continue
        rows.append({"path": p.relative_to(ROOT).as_posix(), "seconds": duration(p),
                     "kb": round(p.stat().st_size / 1024),
                     # md5 so "every take is distinct" is a checkable claim, not a memory
                     "md5": hashlib.md5(p.read_bytes()).hexdigest()[:12]})
    out = ROOT / "results" / "sample_inventory.json"
    # trailing newline: end-of-file-fixer (pre-commit) rejects files without one, and it would
    # otherwise block every commit that includes this generated file.
    out.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    total = sum(r["seconds"] or 0 for r in rows)
    print(f"{len(rows)} samples, {total / 60:.1f} minutes of audio, {sum(r['kb'] for r in rows) / 1024:.1f} MB")
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
