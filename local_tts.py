#!/usr/bin/env python
"""Local (offline) TTS: Windows' built-in Microsoft voices and Piper.

Why: the cloud path costs money per character and needs a network round-trip per chunk. This runs
on this machine with no API key, no network, and no per-request cost. Quality is lower than
ElevenLabs and there is no verified emotion control - see README for the measured comparison.

Engines
  sapi    Windows System.Speech (Microsoft David / Zira / Mark). Offline, instant, WAV out.
  piper   Piper neural TTS (CPU, .onnx voices in models/piper). Better prosody than SAPI.

Emotion: neither engine is a neural emotion model. `{{markup}}` is mapped to SAPI's SSML prosody
for a coarse approximation (rate/pitch/volume) and is honest about being mechanical; Piper has no
equivalent, so markup is stripped and a warning printed - never read aloud.

Commands
  engines                       what is installed and usable right now
  voices [--engine E]           list available voices for an engine
  say TEXT | --file F           render to mp3 wav->mp3 (--out, --engine, --voice, --speed, --verify)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODELS = ROOT / "models" / "piper"
OUT_DIR = ROOT / "audio" / "local"
ENV = Path(os.path.expanduser("~")) / "AppData/Local/hermes/profiles/engineer/.env"
PIPER_PY = ROOT / ".venv" / "Scripts" / "python.exe"

MARKUP = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")

# Coarse SSML mapping for SAPI. Not an emotion model - just rate/pitch/volume, which is audible
# and verifiable (centroid/energy move) but nothing like ElevenLabs' expressive tags.
SAPI_SSML = {
    "whispering":  '<prosody volume="x-soft" rate="-20%" pitch="-5%">',
    "whisper":     '<prosody volume="x-soft" rate="-20%" pitch="-5%">',
    "excited":     '<prosody rate="+22%" pitch="+15%" volume="loud">',
    "cheerfully":  '<prosody rate="+12%" pitch="+10%">',
    "cheerful":    '<prosody rate="+12%" pitch="+10%">',
    "amused":      '<prosody rate="+5%" pitch="+6%">',
    "curious":     '<prosody rate="+4%" pitch="+8%">',
    "serious":     '<prosody rate="-8%" pitch="-4%">',
    "sad":         '<prosody rate="-18%" pitch="-10%" volume="soft">',
    "angry":       '<prosody rate="+10%" pitch="-6%" volume="loud">',
    "urgent":      '<prosody rate="+25%" pitch="+5%">',
}


def ps(script: str) -> str:
    """Run PowerShell from a temp .ps1 - avoids the bash quoting maze around SSML."""
    with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8") as f:
        f.write(script)
        path = f.name
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path],
                           capture_output=True, text=True, timeout=600)
        return r.stdout + r.stderr
    finally:
        os.unlink(path)


def sapi_voices() -> list[str]:
    out = ps('Add-Type -AssemblyName System.Speech\n'
             '(New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() | '
             'ForEach-Object { $_.VoiceInfo.Name }')
    return [l.strip() for l in out.splitlines() if l.strip() and "|" not in l]


def piper_voices() -> list[Path]:
    return sorted(MODELS.glob("*.onnx"))


def to_mp3(wav: Path, mp3: Path, speed: float | None = None) -> None:
    filters = ["-af", f"atempo={speed}"] if speed and abs(speed - 1.0) > 0.01 else []
    subprocess.run(["ffmpeg", "-y", "-i", str(wav), *filters, "-b:a", "160k", str(mp3)],
                   capture_output=True, check=True, timeout=600)


def build_ssml(text: str) -> str:
    """Wrap each {{emotion}} segment in its SAPI prosody tag (properly closed, XML-escaped)."""
    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    parts = MARKUP.split(text)          # [pre, emotion, segment, emotion, segment, ...]
    out = [esc(parts[0])]
    for i in range(1, len(parts), 2):
        seg = parts[i + 1] if i + 1 < len(parts) else ""
        tag = SAPI_SSML.get(parts[i].strip().lower(), "")
        out.append(f"{tag}{esc(seg)}</prosody>" if tag else esc(seg))
    return "".join(out)


def sapi_say(text: str, voice: str, wav: Path, rate: int = 0) -> None:
    """SSML with the markup mapped to prosody; plain text otherwise."""
    ssml = ('<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">'
            + build_ssml(text) + "</speak>")
    ssml_path = wav.with_suffix(".ssml.xml")
    ssml_path.write_text(ssml, encoding="utf-8")
    out = ps(f'Add-Type -AssemblyName System.Speech\n'
             f'$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n'
             f'$s.SelectVoice("{voice}")\n'
             f'$s.Rate = {rate}\n'
             f'$s.SetOutputToWaveFile("{wav}")\n'
             f'$s.SpeakSsml([System.IO.File]::ReadAllText("{ssml_path}"))\n'
             f'$s.Dispose()\n')
    if "Exception" in out:
        raise SystemExit(f"System.Speech failed: {out[:400]}")
    ssml_path.unlink(missing_ok=True)


def piper_say(text: str, model: Path, wav: Path, length_scale: float | None = None) -> None:
    body = MARKUP.sub("", text)          # piper has no emotion control: strip, never speak it
    cmd = [str(PIPER_PY), "-m", "piper", "--model", str(model), "--output_file", str(wav)]
    if length_scale:
        cmd += ["--length_scale", str(length_scale)]
    if model.stem.startswith("ko_"):
        cmd += []                        # piper infers the language from the voice
    r = subprocess.run(cmd, input=body.encode("utf-8"), capture_output=True, timeout=900)
    if r.returncode != 0 or not wav.exists():
        raise SystemExit(f"piper failed: {r.stderr.decode('utf-8', 'replace')[:400]}")


def api_key() -> str:
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("no OPENROUTER_API_KEY for verification")


def transcribe(path: Path, language: str | None) -> dict:
    boundary = "----localtool"
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\nelevenlabs/scribe-v2\r\n'.encode()]
    if language:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\n{language}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                 f'Content-Type: audio/mpeg\r\n\r\n'.encode())
    parts.append(path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request("https://openrouter.ai/api/v1/audio/transcriptions", data=b"".join(parts),
                                 method="POST", headers={"Authorization": f"Bearer {api_key()}",
                                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code}


def similarity(a: str, b: str) -> float:
    a = re.sub(r"\s+", " ", re.sub(r"\{\{[^}]*\}\}", "", a)).strip()
    b = re.sub(r"\s+", " ", b).strip()
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return round(1 - prev[-1] / max(len(a), len(b)), 3)


def duration(p: Path) -> float | None:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(p)], capture_output=True, text=True)
    try:
        return round(float(out.stdout.strip()), 2)
    except ValueError:
        return None


def cmd_engines(_: argparse.Namespace) -> None:
    print("sapi :", ", ".join(sapi_voices()) or "unavailable")
    print("piper:", f"{PIPER_PY} {'present' if PIPER_PY.exists() else 'MISSING'}, "
          f"{len(piper_voices())} voice model(s) in {MODELS}")


def cmd_voices(args: argparse.Namespace) -> None:
    if args.engine in ("sapi", "all"):
        print("sapi:")
        for v in sapi_voices():
            print("   ", v)
    if args.engine in ("piper", "all"):
        print("piper:")
        for p in piper_voices():
            print(f"    {p.stem}")
        if not piper_voices():
            print("    (none - run fetch_piper_voices.py)")


def cmd_say(args: argparse.Namespace) -> None:
    text = Path(args.file).read_text(encoding="utf-8") if args.file else args.text
    if not text:
        raise SystemExit("no text given")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    wav = OUT_DIR / "_tmp.wav"
    out = Path(args.out) if args.out else OUT_DIR / f"{args.voice}-{args.engine}.mp3"
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.engine == "sapi":
        found = MARKUP.findall(text)
        if found:
            print(f"note: SAPI has no emotion model - {{emotions}} map to coarse SSML prosody "
                  f"({', '.join(sorted(set(found)))})")
        sapi_say(text, args.voice, wav, rate=args.rate)
    elif args.engine == "piper":
        model = next((p for p in piper_voices()
                      if p.stem == args.voice or p.stem.startswith(args.voice)), None)
        if model is None:
            raise SystemExit(f"no piper model matching {args.voice!r}; see 'voices --engine piper'")
        if MARKUP.search(text):
            print("note: piper has no emotion control - the {{markup}} was stripped (not spoken)")
        piper_say(text, model, wav, length_scale=(1 / args.speed if args.speed else None))
    else:
        raise SystemExit(f"unknown engine {args.engine}")
    to_mp3(wav, out, speed=args.speed if args.engine == "sapi" else None)
    wav.unlink(missing_ok=True)
    print(f"-> {out}  ({out.stat().st_size} bytes, {duration(out)}s, local, $0.00000)")
    if args.verify:
        r = transcribe(out, args.language)
        txt = r.get("text", f"error {r.get('error')}")
        print(f"   STT: {txt[:120]!r}")
        print(f"   similarity to input: {similarity(text, txt)}")
    (OUT_DIR / f"{out.stem}.manifest.json").write_text(json.dumps(
        {"engine": args.engine, "voice": args.voice, "text_chars": len(text), "output": (out.relative_to(ROOT).as_posix() if ROOT in out.resolve().parents else out.name),
         "cost_usd": 0.0, "network": "offline synthesis; STT verification only if --verify"},
        ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("engines").set_defaults(func=cmd_engines)
    pv = sub.add_parser("voices"); pv.add_argument("--engine", default="all", choices=["sapi", "piper", "all"]); pv.set_defaults(func=cmd_voices)
    ps_ = sub.add_parser("say")
    ps_.add_argument("text", nargs="?")
    ps_.add_argument("--file")
    ps_.add_argument("--engine", default="piper", choices=["sapi", "piper"])
    ps_.add_argument("--voice", default="en_US-amy-medium")
    ps_.add_argument("--out")
    ps_.add_argument("--rate", type=int, default=0, help="SAPI rate -10..10")
    ps_.add_argument("--speed", type=float, default=None)
    ps_.add_argument("--verify", action="store_true")
    ps_.add_argument("--language", default=None)
    ps_.set_defaults(func=cmd_say)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
