#!/usr/bin/env python
"""OpenRouter TTS experiment harness: render + verify.

Renders text with candidate voices through OpenRouter's /api/v1/audio/speech
and verifies each output by transcribing it back through /api/v1/audio/transcriptions.
Results (per-voice metadata, byte sizes, transcriptions, similarity) are written
to results/ as JSON so claims in the README are reproducible.

Usage:  python render.py <experiment-name>
        experiment-name: korean | english
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

API = "https://openrouter.ai/api/v1"
ROOT = Path(__file__).resolve().parent
ENV = Path(os.path.expanduser("~")) / "AppData/Local/hermes/profiles/engineer/.env"


def similarity(a: str, b: str) -> float:
    """1 - normalized Levenshtein distance. (difflib's SequenceMatcher applies an
    'autojunk' heuristic that treats common characters as junk on longer strings and
    reports nonsense ratios - ~0.34 for two near-identical English paragraphs.)"""
    a, b = a.strip(), b.strip()
    if not a and not b:
        return 1.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return round(1 - prev[-1] / max(len(a), len(b)), 3)


def api_key() -> str:
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("OPENROUTER_API_KEY not found in profile .env")


KEY = api_key()

KOREAN_TEXT = (
    "식민선 아르헨트는 명암 경계선을 지나 표류했다. 선체는 사십 년 동안 쌓인 미세 운석이 "
    "열을 내려놓으며 똑똑, 소리를 냈다. 안에서 미라는 뷰포트 위로 행성의 새벽이 기어오는 것을 "
    "지켜보았다. 인간이 한 번도 만져본 적 없는, 녹과 얼음의 세계였다. \"우리는 집을 기대하고 "
    "왔어요.\" 그녀가 말했다. \"그런데 우리가 찾은 것은 질문이었습니다.\" 등 뒤에서 함선의 "
    "지성이 눈 내리는 듯한 목소리로 대답했다. \"그렇다면 우리는 평생 그것을 제대로 묻는 법을 "
    "배우게 될 것입니다.\""
)

ENGLISH_TEXT = (
    "The colony ship Argent drifted past the terminator line, its hull ticking as forty years "
    "of micrometeorites gave up their heat. Inside, Mira watched the planet's dawn crawl across "
    "the viewport - a world of rust and ice that no human had ever touched."
)

FULL_EN = (
    "The colony ship Argent drifted past the terminator line, its hull ticking as forty years of "
    "micrometeorites gave up their heat. Inside, Mira watched the planet's dawn crawl across the "
    "viewport \u2014 a world of rust and ice that no human had ever touched. \"We came expecting a "
    "home,\" she said. \"Instead we found a question.\" Behind her, the ship's mind answered in a "
    "voice like falling snow: \"Then we shall spend our lives learning how to ask it properly.\""
)

# All 21 ElevenLabs premade voices exposed by eleven-v4 on OpenRouter, with the gender labels
# published in the ElevenLabs voice-library metadata (results/elevenlabs-premade-labels.json).
FEMALE = ["sarah", "alice", "matilda", "jessica", "lily", "bella", "laura"]
MALE = ["adam", "george", "brian", "daniel", "eric", "callum", "charlie", "will",
        "chris", "roger", "liam", "harry", "bill"]

# name -> (model, voice, response_format, text, note)
EXPERIMENTS = {
    "korean": [
        ("mai-haena", "microsoft/mai-voice-2.1", "ko-KR-Haena:MAI-Voice-2.1", "mp3", KOREAN_TEXT,
         "Microsoft MAI-Voice-2.1 native ko-KR voice"),
        ("mai-harper", "microsoft/mai-voice-2.1", "ko-KR-Harper:MAI-Voice-2.1", "mp3", KOREAN_TEXT,
         "Microsoft MAI-Voice-2.1 native ko-KR voice"),
        ("el-jini", "elevenlabs/eleven-v4", "0oqpliV6dVSr9XomngOW", "mp3", KOREAN_TEXT,
         "ElevenLabs library voice: Jini (Korean female, narrator)"),
        ("el-sora", "elevenlabs/eleven-v4", "1BZBO072RKJTzZcDjRox", "mp3", KOREAN_TEXT,
         "ElevenLabs library voice: Sora (Korean female, storyteller)"),
        ("el-annakim", "elevenlabs/eleven-v4", "uyVNoMrnUku1dZyVEXwD", "mp3", KOREAN_TEXT,
         "ElevenLabs library voice: Anna Kim (Korean female, narration)"),
        ("gemini-kore", "google/gemini-3.8-flash-tts", "Kore", "pcm", KOREAN_TEXT,
         "Gemini TTS voice Kore (multilingual, PCM only -> ffmpeg mp3)"),
    ],
    "english": [
        ("el-sarah", "elevenlabs/eleven-v4", "sarah", "mp3", ENGLISH_TEXT, "premade Sarah"),
        ("el-alice", "elevenlabs/eleven-v4", "alice", "mp3", ENGLISH_TEXT, "premade Alice"),
        ("el-matilda", "elevenlabs/eleven-v4", "matilda", "mp3", ENGLISH_TEXT, "premade Matilda"),
    ],
}

# Full-paragraph sweeps over every premade voice, split by gender label.
EXPERIMENTS["english_female"] = [
    (f"en-f-{v}", "elevenlabs/eleven-v4", v, "mp3", FULL_EN, f"premade {v} (female)") for v in FEMALE
]
EXPERIMENTS["english_male"] = [
    (f"en-m-{v}", "elevenlabs/eleven-v4", v, "mp3", FULL_EN, f"premade {v} (male)") for v in MALE
]

VERIFY_MODELS = ["elevenlabs/scribe-v2", "openai/whisper-large-v3"]


def post_json(url: str, payload: dict, timeout: int = 120) -> tuple[int, bytes, dict]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers or {})


def transcribe(path: Path, model: str, language: str) -> dict:
    """Multipart upload to /audio/transcriptions (stdlib only)."""
    boundary = "----hermesTTSverify"
    parts = []
    for field, value in (("model", model), ("language", language)):
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"\r\n\r\n{value}\r\n".encode()
        )
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
        f"Content-Type: audio/mpeg\r\n\r\n".encode()
    )
    parts.append(path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(
        f"{API}/audio/transcriptions",
        data=body,
        headers={
            "Authorization": f"Bearer {KEY}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode("utf-8", "replace")[:200]}


def atempo(src: Path, dst: Path, factor: float) -> None:
    """Pitch-preserving time-stretch: ffmpeg's atempo changes speaking rate without the
    'chipmunk' pitch shift of a naive resample."""
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-filter:a", f"atempo={factor}", "-b:a", "128k", str(dst)],
        capture_output=True, timeout=300, check=True,
    )


def duration(path: Path) -> float | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        return round(float(out.stdout.strip()), 2)
    except Exception:
        return None


def run(name: str) -> None:
    fast = name.endswith("_fast")
    base_name = name[: -len("_fast")] if fast else name
    audio_dir = ROOT / "audio" / name
    audio_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for label, model, voice, fmt, text, note in EXPERIMENTS[base_name]:
        if fast:
            label = f"{label}-fast150"
        out = audio_dir / f"{label}.mp3"
        status, body, headers = post_json(f"{API}/audio/speech", {
            "model": model, "input": text, "voice": voice, "response_format": fmt,
        })
        record = {
            "label": label, "model": model, "voice": voice, "note": note,
            "http": status, "response_format": fmt,
            "content_type": headers.get("Content-Type"),
            "generation_id": headers.get("X-Generation-Id"),
        }
        if status == 200 and body:
            if fmt == "pcm":
                raw = out.with_suffix(".pcm")
                raw.write_bytes(body)
                subprocess.run(
                    ["ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", str(raw),
                     "-b:a", "128k", str(out)], capture_output=True, timeout=120,
                )
                raw.unlink(missing_ok=True)
            else:
                out.write_bytes(body)
            if fast:
                # 50% faster = 1.5x rate. Not a provider parameter: eleven-v4 rejects `speed`
                # (400 "speed is not supported by eleven_v4") and eleven-multilingual-v2 clamps it
                # to 0.7-1.2, so the rate change is applied locally, pitch-preserving.
                tmp = out.with_name(out.stem + "-raw.mp3")
                out.rename(tmp)
                record["source_seconds"] = duration(tmp)
                atempo(tmp, out, 1.5)
                tmp.unlink(missing_ok=True)
                record["speedup"] = {"applied": "ffmpeg atempo=1.5", "factor": 1.5}
            record["bytes"] = out.stat().st_size
            record["seconds"] = duration(out)
            record["transcriptions"] = {}
            for vm in VERIFY_MODELS:
                t = transcribe(out, vm, "ko" if name == "korean" else "en")
                txt = t.get("text", t.get("error", ""))
                record["transcriptions"][vm] = {
                    "text": txt,
                    "similarity": similarity(text, txt),
                }
        else:
            record["error"] = body.decode("utf-8", "replace")[:300]
        print(f"[{name}] {label:12s} http={status} "
              f"{record.get('bytes', '-')}B {record.get('seconds', '-')}s")
        for vm, tr in (record.get("transcriptions") or {}).items():
            print(f"    {vm:28s} sim={tr['similarity']:<5} {tr['text'][:110]}")
        if record.get("error"):
            print(f"    ERROR {record['error']}")
        results.append(record)

    outfile = ROOT / "results" / f"{name}.json"
    outfile.parent.mkdir(parents=True, exist_ok=True)
    outfile.write_text(json.dumps({"text": EXPERIMENTS[base_name][0][4],
                                   "results": results}, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    print(f"\nwrote {outfile}")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "korean")
