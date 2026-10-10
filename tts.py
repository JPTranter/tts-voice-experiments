#!/usr/bin/env python
"""ElevenLabs (via OpenRouter) voice helper - discovery, long-text rendering, verification.

Why this exists: Hermes' TTS tool takes no voice argument (it reads provider/voice from config),
OpenRouter exposes no popularity ranking, several ElevenLabs voices are simply not routed, and
`speed` is rejected by eleven-v4. Doing all of that by hand, per request, is what produced the
shell-encoding and voice-name mistakes in this project. This is the one entry point.

Commands
  list                      validated voices per model (labels merged from the saved catalogue)
  probe VOICE [...]         check which candidate voice ids a model accepts (200 vs 400)
  say TEXT | --file F       render any length of text to mp3 (chunked, resumable, stitched)
  speed FILE --factor 1.5   pitch-preserving rate change (what `speed` cannot do on eleven-v4)
  verify FILE --expect ...  transcribe a file back and score it against the expected text

Examples
  python tts.py list --model elevenlabs/eleven-v4
  python tts.py say --file chapter1.txt --voice sarah --verify --speed 1.25
  python tts.py probe rachel charlotte grace sarah alice
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://openrouter.ai/api/v1"
ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "audio" / "renders"
ENV = Path(os.path.expanduser("~")) / "AppData/Local/hermes/profiles/engineer/.env"
CATALOG = ROOT / "results" / "elevenlabs-premade-labels.json"

DEFAULT_MODEL = "elevenlabs/eleven-v4"
# Character cap per request, by model family. OpenRouter/OpenRouter-blog limits are the hard
# ceiling; the default is deliberately lower so a long book export stays resumable and one bad
# chunk does not cost the whole chapter.
MODEL_CAPS = {"elevenlabs/eleven-v4": 10000, "elevenlabs/eleven-v4-turbo": 10000,
              "elevenlabs/eleven-v3": 5000, "elevenlabs/eleven-v3-conversational": 5000,
              "elevenlabs/eleven-multilingual-v2": 10000,
              "elevenlabs/eleven-flash-v2.5": 40000, "elevenlabs/eleven-flash-v2": 30000,
              "elevenlabs/eleven-turbo-v2.5": 40000, "elevenlabs/eleven-turbo-v2": 30000}
DEFAULT_CHUNK = 2800
VERIFY_MODEL = "elevenlabs/scribe-v2"

# --- emotion support, measured rather than assumed (see results/emotion_probe.json) ------------
# Inline audio tags are performed ONLY by the v4 family: "[whispering]" moved the spectral
# centroid 1106 Hz -> 4878 Hz with high-band energy 0.106 -> 0.643. eleven-v3 accepted the tag
# but ignored it (centroid 565/587/589 = no change), and multilingual-v2 / flash-v2.5 READ THE TAG
# ALOUD ("Whispering. The colony ship..."), which is worse than not supporting it.
TAG_MODELS = {"elevenlabs/eleven-v4", "elevenlabs/eleven-v4-turbo"}
TAG_SPOKEN_ALOUD = {"elevenlabs/eleven-multilingual-v2", "elevenlabs/eleven-flash-v2",
                    "elevenlabs/eleven-flash-v2.5", "elevenlabs/eleven-turbo-v2",
                    "elevenlabs/eleven-turbo-v2.5"}
# `instructions` is documented for OpenAI/Gemini TTS: on gemini-3.8-flash-tts it moved the centroid
# 661 Hz -> 3490 Hz. On eleven-v4 it produced no measurable change (ignored).
INSTRUCTION_MODELS = ("google/gemini", "openai/gpt")
# Free-text tags ElevenLabs' v4 engine performs; anything else is passed through as-is.
EMOTION_TAG_MAP = {
    "whisper": "[whispering]", "whispering": "[whispering]", "sad": "[sad]", "angry": "[angry]",
    "excited": "[excited]", "cheerful": "[cheerfully]", "happy": "[happy]", "calm": "[calm]",
    "tired": "[tired]", "afraid": "[scared]", "scared": "[scared]", "urgent": "[urgent]",
    "serious": "[serious]", "curious": "[curious]", "amused": "[amused]", "sarcastic": "[sarcastic]",
    "laughs": "[laughs]", "sighs": "[sighs]", "crying": "[crying]", "breathless": "[breathless]",
}


def emotion_tag(emotion: str) -> str:
    """Map a plain emotion word/phrase to an ElevenLabs v4 inline tag (idempotent for raw tags)."""
    e = emotion.strip()
    if e.startswith("[") and e.endswith("]"):
        return e
    key = e.lower().rstrip(".!")
    return EMOTION_TAG_MAP.get(key, f"[{key}]")


def emotion_instruction(emotion: str) -> str:
    return f"Speak in a {emotion.strip().rstrip('.')} tone."


def tag_guard(model: str) -> None:
    if model in TAG_SPOKEN_ALOUD:
        raise SystemExit(
            f"{model} does not perform audio tags and READS THEM ALOUD (a tag becomes the spoken "
            f"word 'Whispering.'). Use {DEFAULT_MODEL}, or drop --emotion/--tags for this model.")
    if model not in TAG_MODELS:
        print(f"warning: {model} is not known to perform audio tags (only the v4 family does) - "
              f"the tag may be ignored without error.", file=sys.stderr)


def api_key() -> str:
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"]
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit(f"OPENROUTER_API_KEY not found (checked env and {ENV})")


def post(path: str, payload: dict, timeout: int = 300) -> tuple[int, bytes, dict]:
    req = urllib.request.Request(f"{API}{path}", data=json.dumps(payload).encode("utf-8"),
                                 headers={"Authorization": f"Bearer {api_key()}",
                                          "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers or {})


def get(path: str) -> dict:
    req = urllib.request.Request(f"{API}{path}", headers={"Authorization": f"Bearer {api_key()}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def speech(text: str, voice: str, model: str, fmt: str = "mp3", speed: float | None = None,
           prev_text: str | None = None, next_text: str | None = None,
           instructions: str | None = None) -> tuple[int, bytes, str]:
    payload = {"model": model, "input": text, "voice": voice, "response_format": fmt}
    if speed:
        payload["speed"] = speed
    if instructions:
        payload["instructions"] = instructions       # honoured by Gemini/OpenAI TTS only
    if prev_text or next_text:
        # cross-chunk prosody continuity; ElevenLabs uses the neighbours for pacing/intonation
        opts = {k: v for k, v in (("previous_text", prev_text), ("next_text", next_text)) if v}
        payload["provider"] = {"options": {"elevenlabs": opts}}
    status, body, headers = post("/audio/speech", payload)
    return status, body, headers.get("X-Generation-Id")


def transcribe(path: Path, language: str | None = None, model: str = VERIFY_MODEL) -> dict:
    boundary = "----hermesTTStool"
    parts = [f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n{model}\r\n".encode()]
    if language:
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"language\"\r\n\r\n{language}\r\n".encode())
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
                 f"Content-Type: audio/mpeg\r\n\r\n".encode())
    parts.append(path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request(f"{API}/audio/transcriptions", data=b"".join(parts), method="POST",
                                 headers={"Authorization": f"Bearer {api_key()}",
                                          "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode("utf-8", "replace")[:200]}


def slug(name: str, limit: int = 24) -> str:
    """Filesystem-safe voice name. Azure voice ids contain ':' (ko-KR-Haena:MAI-Voice-2.1) which is
    illegal in a Windows path and crashed the render."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:limit] or "voice"


def similarity(a: str, b: str) -> float:
    """1 - normalised Levenshtein. (difflib's autojunk heuristic scores near-identical long
    strings around 0.34, which is useless as a gate.)"""
    a, b = re.sub(r"\s+", " ", a).strip(), re.sub(r"\s+", " ", b).strip()
    if not a and not b:
        return 1.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return round(1 - prev[-1] / max(len(a), len(b)), 3)


def duration(path: Path) -> float | None:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=60)
        return round(float(out.stdout.strip()), 2)
    except Exception:
        return None


def chunks_of(text: str, limit: int) -> list[str]:
    """Split on sentence boundaries, never mid-word, packing as much as fits under `limit`."""
    text = re.sub(r"[ \t]+", " ", text.strip())
    if len(text) <= limit:
        return [text]
    sentences = re.split(r"(?<=[.!?…])\s+", text)
    out, cur = [], ""
    for s in sentences:
        while len(s) > limit:                      # a single monster sentence: split on clauses
            cut = max(s.rfind(",", 0, limit), s.rfind(";", 0, limit), s.rfind(" ", 0, limit))
            cut = cut if cut > limit // 2 else limit
            out.append(s[:cut].strip())
            s = s[cut:].strip()
        if len(cur) + len(s) + 1 <= limit:
            cur = f"{cur} {s}".strip()
        else:
            if cur:
                out.append(cur)
            cur = s
    if cur:
        out.append(cur)
    return out


TAG_MARKUP = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")


def apply_emotion(text: str, model: str, emotion: str | None, tags: str | None) -> tuple[str, str | None]:
    """Turn emotion into whatever the model actually honours.

    Supports inline markup in the source text (`{{whispering}} ... {{excited}} ...`), a blanket
    `--emotion`, and raw `--tags`. Returns (text, instructions) - instructions is only used by
    Gemini/OpenAI, whose delivery controls are prompt-shaped rather than tag-shaped.
    """
    found = TAG_MARKUP.findall(text)
    if found and model in TAG_SPOKEN_ALOUD:
        raise SystemExit(f"{model} reads audio tags aloud; remove the {{{{emotion}}}} markup or use "
                         f"{DEFAULT_MODEL}.")
    instructions = None
    if found:
        if model in TAG_MODELS:
            text = TAG_MARKUP.sub(lambda m: emotion_tag(m.group(1)) + " ", text)
        elif any(model.startswith(p) for p in INSTRUCTION_MODELS):
            instructions = emotion_instruction(", ".join(dict.fromkeys(found)))
            text = TAG_MARKUP.sub("", text)
        else:
            print(f"warning: {model} has no verified emotion control - the {{{{...}}}} markup will "
                  f"be stripped (a model without tag support may read it aloud otherwise).",
                  file=sys.stderr)
            text = TAG_MARKUP.sub("", text)
    if tags:
        if model in TAG_SPOKEN_ALOUD:
            raise SystemExit(f"{model} reads audio tags aloud; --tags is unsafe here.")
        text = f"{tags} {text}"
    if emotion:
        if model in TAG_MODELS:
            text = f"{emotion_tag(emotion)} {text}"
        elif any(model.startswith(p) for p in INSTRUCTION_MODELS):
            instructions = emotion_instruction(emotion)
        else:
            raise SystemExit(f"{model} has no verified emotion control. Proven mechanisms: inline "
                             f"tags on {sorted(TAG_MODELS)}, `instructions` on Gemini/OpenAI TTS.")
    return text, instructions


def generation_cost(gid: str | None, retries: int = 2) -> float | None:
    """None means 'not known' - never report an unmeasured cost as $0."""
    if not gid:
        return None
    for attempt in range(retries + 1):
        try:
            data = (get(f"/generation?id={gid}").get("data") or {})
            if data.get("total_cost") is not None:
                return float(data["total_cost"])
        except Exception:
            pass
        if attempt < retries:
            import time
            time.sleep(2)
    return None


def cmd_list(args: argparse.Namespace) -> None:
    labels = {}
    if CATALOG.exists():
        for v in json.loads(CATALOG.read_text(encoding="utf-8")):
            labels[v["name"]] = v["labels"]
    models = get("/models?output_modalities=speech")["data"]
    for m in models:
        if args.model and m["id"] != args.model:
            continue
        voices = m.get("supported_voices") or []
        print(f"\n{m['id']}  ({len(voices)} voices)")
        for v in voices:
            lb = labels.get(v.capitalize(), {})
            tag = " ".join(x for x in (lb.get("gender"), lb.get("accent"), lb.get("use_case")) if x)
            print(f"    {v:34s} {tag}")


def cmd_probe(args: argparse.Namespace) -> None:
    for v in args.voices:
        status, body, _ = speech("Voice check.", v, args.model)
        ok = status == 200 and len(body) > 1000
        detail = "" if ok else body.decode("utf-8", "replace")[:90]
        print(f"  {v:34s} {'OK' if ok else f'REJECTED ({status})'} {detail}")


def cmd_say(args: argparse.Namespace) -> None:
    text = Path(args.file).read_text(encoding="utf-8") if args.file else args.text
    if not text:
        raise SystemExit("no text given (positional text or --file)")
    text, instructions = apply_emotion(text, args.model, args.emotion, args.tags)
    cap = MODEL_CAPS.get(args.model, 5000)
    limit = min(args.chunk, cap)
    chunks = chunks_of(text, limit)
    # Cache key MUST cover everything that changes the audio. Keying on voice + chunk count alone
    # meant a control render of *different* text silently replayed the previous audio (identical
    # byte counts gave it away) - a wrong output that looks like a successful render.
    fingerprint = hashlib.sha1(
        f"{args.model}|{args.voice}|{args.emotion}|{args.tags}|{instructions}|{text}".encode("utf-8")
    ).hexdigest()[:10]
    work = OUT_DIR / f"{slug(args.voice)}-{fingerprint}"
    work.mkdir(parents=True, exist_ok=True)
    print(f"{args.model} / {args.voice}: {len(text)} chars -> {len(chunks)} chunk(s) "
          f"(limit {limit}, model cap {cap}, key {fingerprint})"
          + (f" | instructions: {instructions!r}" if instructions else ""))
    manifest, cost, unknown = [], 0.0, 0
    fmt = "pcm" if args.model.startswith("google/") else "mp3"   # Gemini TTS is PCM-only (mp3 = 400)
    for i, chunk in enumerate(chunks):
        f = work / f"chunk-{i:03d}.mp3"
        if f.exists() and f.stat().st_size > 1000 and not args.force:
            print(f"  [{i}] cached  {f.stat().st_size} bytes")
            manifest.append({"index": i, "chars": len(chunk), "file": str(f), "cached": True,
                             "text": chunk[:200]})
            continue
        prev_text = chunks[i - 1][-400:] if i else None
        next_text = chunks[i + 1][:400] if i + 1 < len(chunks) else None
        status, body, gid = speech(chunk, args.voice, args.model, fmt=fmt, prev_text=prev_text,
                                   next_text=next_text, instructions=instructions)
        if status != 200 or len(body) < 1000:
            raise SystemExit(f"chunk {i} failed ({status}): {body.decode('utf-8', 'replace')[:200]}")
        if fmt == "pcm":
            raw = f.with_suffix(".pcm")
            raw.write_bytes(body)
            subprocess.run(["ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", str(raw),
                            "-b:a", "160k", str(f)], capture_output=True, check=True, timeout=300)
            raw.unlink(missing_ok=True)
        else:
            f.write_bytes(body)
        c = generation_cost(gid)
        if c is None:
            unknown += 1
            costlabel = "cost n/a"
        else:
            cost += c
            costlabel = f"${c:.5f}"
        print(f"  [{i}] {len(chunk):5d} chars -> {f.stat().st_size:7d} bytes  "
              f"{duration(f):6.2f}s  {costlabel}")
        manifest.append({"index": i, "chars": len(chunk), "file": str(f), "bytes": f.stat().st_size,
                         "seconds": duration(f), "generation_id": gid, "cost_usd": c,
                         "emotion_tags": sorted(set(re.findall(r"\[[a-z]+\]", chunk)))})

    listf = work / "concat.txt"
    listf.write_text("".join(f"file '{Path(m['file']).as_posix()}'\n" for m in manifest), encoding="utf-8")
    base = Path(args.out) if args.out else work / f"{args.voice}.mp3"
    base.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listf), "-c", "copy",
                    str(base)], capture_output=True, check=True, timeout=600)
    final = base
    if args.speed and abs(args.speed - 1.0) > 0.01:
        # eleven-v4 rejects `speed` (400 "speed is not supported by eleven_v4"); this is the local
        # equivalent - pitch-preserving time-stretch, so no chipmunk effect.
        final = base.with_name(f"{base.stem}-fast{int(args.speed * 100)}{base.suffix}")
        subprocess.run(["ffmpeg", "-y", "-i", str(base), "-filter:a", f"atempo={args.speed}",
                        "-b:a", "160k", str(final)], capture_output=True, check=True, timeout=600)
    total = f"${cost:.5f}" + (f" + {unknown} unpriced" if unknown else "")
    print(f"-> {final}  ({final.stat().st_size} bytes, {duration(final)}s, total {total})")

    if args.verify:
        print("verify (STT round-trip):")
        for m in manifest:
            r = transcribe(Path(m["file"]), args.language)
            txt = r.get("text", r.get("error", ""))
            m["transcript"] = txt
            m["similarity"] = similarity(chunks[m["index"]], txt)
            print(f"  [{m['index']}] similarity {m['similarity']}  {txt[:80]!r}")
    (work / "manifest.json").write_text(json.dumps(
        {"model": args.model, "voice": args.voice, "text_chars": len(text), "chunks": manifest,
         "output": str(final), "speed": args.speed, "cost_usd": round(cost, 6)},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"manifest: {work / 'manifest.json'}")


def cmd_speed(args: argparse.Namespace) -> None:
    src = Path(args.file)
    out = Path(args.out) if args.out else src.with_name(f"{src.stem}-fast{int(args.factor * 100)}{src.suffix}")
    if out.exists() and not args.force:
        raise SystemExit(f"{out} exists (use --force)")
    subprocess.run(["ffmpeg", "-y", "-i", str(src), "-filter:a", f"atempo={args.factor}",
                    "-b:a", "160k", str(out)], capture_output=True, check=True, timeout=600)
    print(f"{src.name} {duration(src)}s -> {out.name} {duration(out)}s "
          f"(ratio {duration(out) / duration(src):.3f}, expected {1 / args.factor:.3f})")


def cmd_verify(args: argparse.Namespace) -> None:
    path = Path(args.file)
    r = transcribe(path, args.language)
    txt = r.get("text", r.get("error", ""))
    print(txt)
    if args.expect:
        print(f"similarity: {similarity(args.expect, txt)}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="validated voices per model")
    pl.add_argument("--model")
    pl.set_defaults(func=cmd_list)

    pp = sub.add_parser("probe", help="check which voice ids a model accepts")
    pp.add_argument("voices", nargs="+")
    pp.add_argument("--model", default=DEFAULT_MODEL)
    pp.set_defaults(func=cmd_probe)

    ps = sub.add_parser("say", help="render text of any length")
    ps.add_argument("text", nargs="?", help="text to speak (or use --file)")
    ps.add_argument("--file", help="read the text from a file (long text, book chapters, ...)")
    ps.add_argument("--voice", default="sarah")
    ps.add_argument("--model", default=DEFAULT_MODEL)
    ps.add_argument("--out")
    ps.add_argument("--chunk", type=int, default=DEFAULT_CHUNK, help="chars per request")
    ps.add_argument("--speed", type=float, default=None, help="e.g. 1.5 (post-processed)")
    ps.add_argument("--verify", action="store_true", help="STT round-trip every chunk")
    ps.add_argument("--language", help="ISO-639-1 hint for verification")
    ps.add_argument("--force", action="store_true", help="re-render cached chunks")
    ps.add_argument("--emotion", help="blanket emotion for the whole text, e.g. 'whispering'")
    ps.add_argument("--tags", help="raw provider tag prefix, e.g. '[excited]'")
    ps.set_defaults(func=cmd_say)

    pf = sub.add_parser("speed", help="pitch-preserving rate change")
    pf.add_argument("file")
    pf.add_argument("--factor", type=float, default=1.5)
    pf.add_argument("--out")
    pf.add_argument("--force", action="store_true")
    pf.set_defaults(func=cmd_speed)

    pv = sub.add_parser("verify", help="transcribe a file back")
    pv.add_argument("file")
    pv.add_argument("--expect")
    pv.add_argument("--language")
    pv.set_defaults(func=cmd_verify)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
