#!/usr/bin/env python
"""Download Piper voice models and verify each against the md5 published in voices.json.

Local engines in this project run offline; this is the only step that touches the network, and it
checks the digest so a truncated/corrupt model cannot silently produce garbage audio.
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
MODELS = Path(__file__).resolve().parent / "models" / "piper"
WANT = ["en_US-amy-medium", "en_US-ryan-high", "en_GB-cori-high", "ko_KR-kss-medium"]


def main() -> None:
    MODELS.mkdir(parents=True, exist_ok=True)
    index = json.loads(urllib.request.urlopen(
        BASE + "voices.json", timeout=120).read().decode("utf-8"))
    for voice in WANT:
        if voice not in index:
            print(f"{voice}: not in voices.json, skipped")
            continue
        for path, meta in index[voice]["files"].items():
            if not path.endswith((".onnx", ".onnx.json")):
                continue
            dest = MODELS / Path(path).name
            if dest.exists() and dest.stat().st_size == meta["size_bytes"]:
                print(f"  {dest.name}: present ({meta['size_bytes'] / 1e6:.1f} MB)")
                continue
            print(f"  {dest.name}: downloading {meta['size_bytes'] / 1e6:.1f} MB ...")
            data = urllib.request.urlopen(BASE + path, timeout=900).read()
            digest = hashlib.md5(data).hexdigest()
            if digest != meta["md5_digest"]:
                raise SystemExit(f"{dest.name}: md5 mismatch ({digest} != {meta['md5_digest']})")
            dest.write_bytes(data)
            print(f"    ok, md5 verified")
    print("models:", sorted(p.name for p in MODELS.glob('*.onnx')))


if __name__ == "__main__":
    main()
