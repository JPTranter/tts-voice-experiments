#!/usr/bin/env python
"""Report tracked files that nothing else in the repo references.

"Referenced" = its path (or its file name) appears in another tracked text file: the README,
a script, a doc, or a results JSON. Binary samples are normally referenced by the README catalog
that tools_gen_catalog.py generates, so a sample that no longer appears anywhere is either dead
weight or a missing documentation link - both worth knowing.

Run:  python tools_find_orphans.py [--verbose]
Exit code 1 when orphans exist, so it can gate a cleanup commit.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEXT_SUFFIXES = {".md", ".py", ".sh", ".txt", ".json", ".yml", ".yaml", ".html", ".toml"}


# Files that legitimately have no textual reference: git reads them itself.
EXPECTED_UNREFERENCED = {".gitattributes"}


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout
    return [l.strip() for l in out.splitlines() if l.strip()]


def main() -> None:
    verbose = "--verbose" in sys.argv
    files = tracked()
    missing = [f for f in files if not (ROOT / f).exists()]        # deleted but not yet committed
    blobs = {}
    for f in files:
        p = ROOT / f
        if not p.exists():
            continue
        if p.suffix.lower() in TEXT_SUFFIXES and p.stat().st_size < 2_000_000:
            try:
                blobs[f] = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                pass

    orphans = []
    for target in files:
        if target in missing:
            continue
        name = Path(target).name
        refs = []
        for other, text in blobs.items():
            if other == target:
                continue
            if target in text or name in text:
                refs.append(other)
        # a generated catalog/players page referencing it counts, but report what refers to what
        if not refs and target not in EXPECTED_UNREFERENCED:
            orphans.append((target, 0))
        elif verbose:
            print(f"{target}  <- {len(refs)} ref(s): {', '.join(refs[:3])}")

    if missing:
        print(f"staged deletions (ignored): {', '.join(missing)}")
    print(f"\n{len(files)} tracked files, {len(orphans)} unreferenced:")
    for t, _ in orphans:
        print(f"  {t}  ({((ROOT / t).stat().st_size / 1024):.0f} KB)")
    sys.exit(1 if orphans else 0)


if __name__ == "__main__":
    main()
