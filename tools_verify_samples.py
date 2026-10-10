#!/usr/bin/env python
"""STT-verify every committed sample and record the result in results/verification.json.

The README's rule is that no audio claim is made by ear: each take is transcribed back and scored
against the text it was rendered from. The first passes only covered the voices in results/*.json,
so the emotion batch, the local engines, the long-text file and the special cases had no recorded
check. This fills that gap once, and tools_gen_sample_pages.py reads the file afterwards.

Skips anything already verified (results/*.json) and resumes: re-running is cheap.

  python tools_verify_samples.py            # verify what is missing
  python tools_verify_samples.py --all      # re-verify everything
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV = Path.home() / "AppData/Local/hermes/profiles/engineer/.env"
OUT = ROOT / "results" / "verification.json"
MODEL = "elevenlabs/scribe-v2"

# script per sample directory; None = nothing to score against (still transcribes)
SCRIPTS = {
    "audio/edge": ("samples/scifi-emotion-en-plain.txt", "en"),
    "audio/elevenlabs-en-full": ("samples/scifi-emotion-en-plain.txt", "en"),
    "audio/english": ("samples/scifi-emotion-en-plain.txt", "en"),
    "audio/english_female": ("samples/scifi-emotion-en-plain.txt", "en"),
    "audio/english_male": ("samples/scifi-emotion-en-plain.txt", "en"),
    "audio/english_female_fast": ("samples/scifi-emotion-en-plain.txt", "en"),
    "audio/english_male_fast": ("samples/scifi-emotion-en-plain.txt", "en"),
    "audio/emotion": ("samples/scifi-emotion-en.txt", "en"),
    "audio/korean": ("samples/scifi-emotion-ko.txt", "ko"),
    "audio/local": ("samples/scifi-emotion-en.txt", "en"),
    "audio/longtext": ("samples/long-text-sample.txt", "en"),
    "audio/birthday": (None, "en"),
}
KOREAN_EMOTION_PREFIXES = ("ko-",)


def api_key() -> str:
    if (k := __import__("os").environ.get("OPENROUTER_API_KEY")):
        return k
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("OPENROUTER_API_KEY not found")


def strip_markup(text: str) -> str:
    return re.sub(r"\{\{[^}]*\}\}", " ", text)


def similarity(a: str, b: str) -> float:
    a, b = re.sub(r"\s+", " ", a).strip(), re.sub(r"\s+", " ", b).strip()
    if not a or not b:
        return 0.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return round(1 - prev[-1] / max(len(a), len(b)), 3)


def transcribe(path: Path, language: str, attempts: int = 4) -> str:
    """One transcription, with backoff. 61 unpaced uploads in a row earned a 403 from the
    provider, so pace the calls and retry rather than losing the run."""
    import time
    boundary = "----verify"
    body = b"".join([
        f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n{MODEL}\r\n'.encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\n{language}\r\n'.encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        f'Content-Type: audio/mpeg\r\n\r\n'.encode(),
        path.read_bytes(), f"\r\n--{boundary}--\r\n".encode()])
    for i in range(attempts):
        req = urllib.request.Request("https://openrouter.ai/api/v1/audio/transcriptions", data=body,
                                     method="POST", headers={"Authorization": f"Bearer {api_key()}",
                                     "Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.loads(r.read()).get("text", "")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:160]
            if e.code in (403, 429, 500, 502, 503, 504) and i < attempts - 1:
                wait = 8 * (i + 1)
                print(f"      {e.code} ({detail}) - waiting {wait}s")
                time.sleep(wait)
                continue
            raise RuntimeError(f"HTTP {e.code}: {detail}") from e
    raise RuntimeError("exhausted retries")


def already_verified() -> set[str]:
    done = set()
    for f in (ROOT / "results").glob("*.json"):
        if f.name == "verification.json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict) and data.get("results"):
            for r in data["results"]:
                tr = (r.get("transcriptions") or {}).get(MODEL) or {}
                if tr.get("similarity") is not None:
                    done.add(r.get("label", ""))
    return done


def main() -> None:
    force = "--all" in sys.argv
    inv = json.loads((ROOT / "results/sample_inventory.json").read_text(encoding="utf-8"))
    out = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() and not force else {}
    known = already_verified() if not force else set()

    todo = []
    for s in inv:
        path = s["path"]
        folder = path.rsplit("/", 1)[0]
        if path in out and not force:
            continue
        # skip the ones already covered by the measurement runs (matched by label == file stem)
        if Path(path).stem in known and not force:
            continue
        if folder not in SCRIPTS:
            continue
        todo.append(s)

    print(f"{len(todo)} sample(s) to verify ({len(out)} already recorded)")
    for i, s in enumerate(todo, 1):
        path = s["path"]
        folder = path.rsplit("/", 1)[0]
        script_rel, lang = SCRIPTS[folder]
        stem = Path(path).stem
        # Korean script/language for the emotion set and for any local render of the Korean voice.
        # Careful with 'en-gemini-kore-emotion': it is English text read by the voice "Kore", so the
        # rule keys on a 'ko-' prefix or '-ko' suffix, not on the substring 'kore'. Getting this
        # wrong graded Korean audio against the English script and reported similarity 0.153.
        if stem.startswith("ko-") or stem.endswith("-ko"):
            script_rel, lang = "samples/scifi-emotion-ko.txt", "ko"
        expect = strip_markup((ROOT / script_rel).read_text(encoding="utf-8")) if script_rel else None
        try:
            text = transcribe(ROOT / path, lang)
        except (RuntimeError, urllib.error.URLError, TimeoutError) as e:
            print(f"  [{i}/{len(todo)}] {path}: FAILED {e}")
            continue
        import time as _t
        _t.sleep(2.5)   # pace: unpaced bursts get 403'd
        rec = {"model": MODEL, "language": lang, "transcript": text,
               "scored_against": script_rel,
               "similarity": similarity(expect, text) if expect else None}
        out[path] = rec
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  [{i}/{len(todo)}] {path.rsplit('/', 1)[-1]:34s} similarity={rec['similarity']}")
    print(f"\nwrote {OUT.relative_to(ROOT)} with {len(out)} entries")


if __name__ == "__main__":
    main()
