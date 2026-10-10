#!/usr/bin/env python
"""Generate one HTML page per sample: docs/s/<slug>.html (served by GitHub Pages).

Why: a GitHub README cannot embed a player - `<audio>` is stripped by the sanitiser, the blob
page for an mp3 offers only a download, and raw.githubusercontent.com sends
`content-disposition: attachment`. Only real HTML plays audio in place, so every sample gets a
page with the player, the text that was spoken, the STT transcript and the measurements.

Metadata is merged from results/*.json; anything not measured is reported as unknown rather than
guessed. Run after adding renders:  python tools_gen_sample_pages.py
"""
from __future__ import annotations

import html
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
PAGES_DIR = DOCS / "s"

# directory -> (display name, engine, spoken script, how it was made)
GROUPS: dict[str, tuple[str, str, str | None, str]] = {
    "audio/edge": ("Microsoft Edge voices", "Microsoft Edge TTS (free, no key)",
                   "samples/scifi-emotion-en-plain.txt", "Hermes' default TTS path - the free baseline."),
    "audio/elevenlabs-en-full": ("ElevenLabs premades - first delivery", "ElevenLabs eleven-v4",
                                 "samples/scifi-emotion-en-plain.txt", "The first paid render of the sci-fi paragraph."),
    "audio/english": ("ElevenLabs premades - excerpt run", "ElevenLabs eleven-v4",
                      "samples/scifi-emotion-en-plain.txt", "Excerpt-length run behind results/english.json."),
    "audio/english_female": ("English female premades", "ElevenLabs eleven-v4",
                             "samples/scifi-emotion-en-plain.txt", "Full paragraph, all female premades."),
    "audio/english_male": ("English male premades", "ElevenLabs eleven-v4",
                           "samples/scifi-emotion-en-plain.txt", "Full paragraph, all male premades."),
    "audio/english_female_fast": ("English female premades - 1.5x", "ElevenLabs eleven-v4 + local atempo",
                                  "samples/scifi-emotion-en-plain.txt", "Same voice, 1.5x rate, pitch preserved."),
    "audio/english_male_fast": ("English male premades - 1.5x", "ElevenLabs eleven-v4 + local atempo",
                                "samples/scifi-emotion-en-plain.txt", "Same voice, 1.5x rate, pitch preserved."),
    "audio/emotion": ("Emotion renders", "ElevenLabs eleven-v4 / Gemini / Azure",
                      "samples/scifi-emotion-en.txt", "Per-sentence delivery from {{emotion}} markup."),
    "audio/korean": ("Korean voices", "ElevenLabs library / Azure MAI / Gemini",
                     "samples/scifi-emotion-ko.txt", "Six female Korean voices, one paragraph."),
    "audio/local": ("Local engines", "Windows SAPI / Piper (offline, $0)",
                    "samples/scifi-emotion-en.txt", "No API key, no network."),
    "audio/longtext": ("Long text", "ElevenLabs eleven-v4",
                       "samples/long-text-sample.txt", "3,813 characters stitched from 4 chunks."),
    "audio/birthday": ("Happy Birthday to Bel", "ElevenLabs eleven-v4 + ffmpeg rubberband",
                       None, "Four voices in harmony, built note by note - a documented failure."),
}

# results file -> directory that its labels live in
RESULT_DIRS = {
    "results/english.json": "audio/english",
    "results/english_female.json": "audio/english_female",
    "results/english_male.json": "audio/english_male",
    "results/english_female_fast.json": "audio/english_female_fast",
    "results/english_male_fast.json": "audio/english_male_fast",
    "results/korean.json": "audio/korean",
}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def repo_slug() -> tuple[str, str, str]:
    slug = git("remote", "get-url", "origin").rstrip("/").removesuffix(".git").split("github.com")[-1].lstrip("/:")
    owner, _, name = slug.partition("/")
    return owner, name, (git("rev-parse", "--abbrev-ref", "HEAD") or "master")


def similarity(a: str, b: str) -> float:
    """1 - normalised Levenshtein, whitespace-normalised."""
    import re
    a = re.sub(r"\s+", " ", a).strip()
    b = re.sub(r"\s+", " ", b).strip()
    if not a or not b:
        return 0.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return round(1 - prev[-1] / max(len(a), len(b)), 3)


def load_metadata() -> tuple[dict, dict, dict]:
    """(perf by path, cost by path, emotion-metrics by path)"""
    perf: dict[str, dict] = {}
    for res, folder in RESULT_DIRS.items():
        p = ROOT / res
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        for r in data.get("results", []):
            path = f"{folder}/{r['label']}.mp3"
            tr = r.get("transcriptions") or {}
            best = tr.get("elevenlabs/scribe-v2") or {}
            perf[path] = {
                "model": r.get("model"), "voice": r.get("voice"), "note": r.get("note"),
                "transcript": best.get("text"), "similarity": best.get("similarity"),
                "source_seconds": r.get("source_seconds"), "speedup": (r.get("speedup") or {}).get("factor"),
            }
    cost: dict[str, float] = {}
    p = ROOT / "results/costs.json"
    if p.exists():
        for r in json.loads(p.read_text(encoding="utf-8")).get("requests", []):
            c = r.get("tts_cost") or {}
            if c.get("usd") is not None:
                cost[f"{RESULT_DIRS.get('results/' + r['experiment'] + '.json', 'audio/' + r['experiment'])}/{r['label']}.mp3"] = c["usd"]
    emo: dict[str, dict] = {}
    p = ROOT / "results/emotion_batch.json"
    if p.exists():
        for r in json.loads(p.read_text(encoding="utf-8")):
            emo[f"audio/emotion/{r['file']}"] = r
    ver: dict[str, dict] = {}
    p = ROOT / "results/verification.json"
    if p.exists():
        ver = json.loads(p.read_text(encoding="utf-8"))
    return perf, cost, emo, ver


# Voice/model for samples that predate the results JSONs or were rendered by other tools.
# Each entry mirrors how the file was actually produced (edge/ElevenLabs delivery, the emotion
# batch, the local engines) - kept explicit rather than guessed from the file name.
VOICE_HINTS: list[tuple[str, str, str]] = [
    (r"audio/edge/01-aria\.mp3", "Microsoft Edge TTS", "en-US-AriaNeural (US, female)"),
    (r"audio/edge/02-jenny\.mp3", "Microsoft Edge TTS", "en-US-JennyNeural (US, female)"),
    (r"audio/edge/03-sonia\.mp3", "Microsoft Edge TTS", "en-GB-SoniaNeural (UK, female)"),
    (r"audio/elevenlabs-en-full/01-sarah\.mp3", "elevenlabs/eleven-v4", "sarah"),
    (r"audio/elevenlabs-en-full/02-alice\.mp3", "elevenlabs/eleven-v4", "alice"),
    (r"audio/elevenlabs-en-full/03-matilda\.mp3", "elevenlabs/eleven-v4", "matilda"),
    (r"audio/emotion/en-(?P<v>[a-z]+)-emotion(-fast150)?\.mp3", "elevenlabs/eleven-v4", r"\g<v> (with {{emotion}} markup)"),
    (r"audio/emotion/en-gemini-kore-emotion\.mp3", "google/gemini-3.8-flash-tts", "Kore (instructions, English text)"),
    (r"audio/emotion/ko-sora-emotion\.mp3", "elevenlabs/eleven-v4", "1BZBO072RKJTzZcDjRox (Sora)"),
    (r"audio/emotion/ko-annakim-emotion\.mp3", "elevenlabs/eleven-v4", "uyVNoMrnUku1dZyVEXwD (Anna Kim)"),
    (r"audio/emotion/ko-jini-emotion\.mp3", "elevenlabs/eleven-v4", "0oqpliV6dVSr9XomngOW (Jini)"),
    (r"audio/emotion/ko-kore-emotion\.mp3", "google/gemini-3.8-flash-tts", "Kore (instructions)"),
    (r"audio/emotion/ko-haena-plain\.mp3", "microsoft/mai-voice-2.1", "ko-KR-Haena (no emotion control: plain)"),
    (r"audio/local/piper-amy-en\.mp3", "Piper (CPU, offline)", "en_US-amy-medium"),
    (r"audio/local/piper-kss-ko\.mp3", "Piper (CPU, offline)", "ko_KR-kss-medium"),
    (r"audio/local/sapi-zira-en\.mp3", "Windows SAPI (offline)", "Microsoft Zira Desktop"),
    (r"audio/local/control-plain-zira-en\.mp3", "Windows SAPI (offline)", "Microsoft Zira Desktop (untagged control)"),
    (r"audio/longtext/long-text-sarah\.mp3", "elevenlabs/eleven-v4", "sarah (4 chunks, 3,813 chars)"),
    (r"audio/birthday/reference-synth-4parts\.mp3", "numpy synth (no TTS)", "reference rendering of the same note grid"),
    (r"audio/birthday/happy-birthday.*\.mp3", "elevenlabs/eleven-v4 + rubberband", "sarah/jessica/george/brian, four parts"),
]


def hints_for(path: str) -> tuple[str | None, str | None]:
    for pattern, model, voice in VOICE_HINTS:
        m = re.match(pattern, path)
        if m:
            return model, m.expand(voice) if m.groups() else voice
    return None, None


def slug_of(path: str) -> str:
    return Path(path).stem


def folder_of(path: str) -> str:
    """POSIX-style parent. Path(...).parent yields backslashes on Windows, which silently missed
    every GROUPS/RESULT_DIRS lookup and rendered all 110 pages with 'unknown' engine metadata."""
    return path.rsplit("/", 1)[0] if "/" in path else ""


def page(sample: dict, metas: tuple[dict, dict, dict], owner: str, repo: str, branch: str,
         prev_next: tuple[str | None, str | None]) -> str:
    perf, cost, emo, ver = metas
    path = sample["path"]
    folder = folder_of(path)
    group, engine, script, how = GROUPS.get(folder, ("Samples", "unknown", None, ""))
    cdn = f"https://cdn.jsdelivr.net/gh/{owner}/{repo}@{branch}/{path}"
    m = perf.get(path, {})
    e = emo.get(path, {})
    # fall back to the hints table, then to the standalone verification file
    hint_model, hint_voice = hints_for(path)
    v = ver.get(path, {})
    model = m.get("model") or hint_model
    voice = m.get("voice") or hint_voice
    transcript = m.get("transcript") or v.get("transcript")
    sim = m.get("similarity")
    if sim is None:
        sim = v.get("similarity")
    dur = sample.get("seconds")

    facts = [("duration", f"{dur} s" if dur else "?"),
             ("size", f"{sample['kb']} KB"),
             ("md5", sample.get("md5", "?")),
             ("engine", engine)]
    if model:
        facts.append(("model", model))
    if voice:
        facts.append(("voice", voice))
    if m.get("speedup"):
        facts.append(("rate", f"{m['speedup']}x (from {m.get('source_seconds')} s)"))
    if path in cost:
        facts.append(("cost (measured)", f"${cost[path]:.5f}"))
    elif folder.startswith("audio/emotion") or folder in ("audio/local", "audio/longtext"):
        facts.append(("cost", "not measured"))
    if sim is not None:
        facts.append(("STT round-trip", f"{sim}"))
    if e:
        facts.append(("last-5s centroid", f"{e['last5s_centroid']} Hz"))
        facts.append(("last-5s high-band energy", f"{e['last5s_hi']}"))

    text_block = ""
    if script and (ROOT / script).exists():
        body = (ROOT / script).read_text(encoding="utf-8")
        text_block = (f'<h2>The script</h2><p class="muted"><code>{html.escape(script)}</code></p>'
                      f"<pre>{html.escape(body.strip())}</pre>")
    transcript_block = ""
    if transcript:
        sim_note = (f'Similarity to the input: <b>{sim}</b> &mdash; this is how every claim in '
                    f'the README was verified, not by ear.' if sim is not None else
                    'Scored against the input text.')
        transcript_block = (f'<h2>Transcribed back (STT check)</h2>'
                            f'<p class="muted">{sim_note}</p>'
                            f"<pre>{html.escape(transcript.strip())}</pre>")

    p_prev, p_next = prev_next
    nav = []
    if p_prev:
        nav.append(f'<a href="{slug_of(p_prev)}.html">&larr; {html.escape(Path(p_prev).stem)}</a>')
    nav.append('<a href="../players.html">listening room</a>')
    if p_next:
        nav.append(f'<a href="{slug_of(p_next)}.html">{html.escape(Path(p_next).stem)} &rarr;</a>')

    return f"""<!DOCTYPE html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(Path(path).name)} — {html.escape(group)}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 16px/1.6 -apple-system, Segoe UI, Roboto, sans-serif; max-width: 46rem; margin: 2rem auto; padding: 0 1rem; }}
  h1 {{ font-size: 1.3rem; margin-bottom: .2rem; }}
  h2 {{ font-size: 1rem; margin-top: 2rem; border-bottom: 1px solid #8884; padding-bottom: .25rem; }}
  .muted {{ color: #888; }}
  audio {{ width: 100%; margin: .6rem 0; }}
  table {{ border-collapse: collapse; width: 100%; }}
  td {{ padding: .25rem .5rem; border-bottom: 1px solid #8882; vertical-align: top; }}
  td:first-child {{ color: #888; white-space: nowrap; }}
  pre {{ background: #8881; padding: .8rem; border-radius: .4rem; overflow-x: auto; white-space: pre-wrap; }}
  nav {{ display: flex; gap: 1rem; margin-bottom: 1.2rem; }}
  .file {{ font-family: ui-monospace, Menlo, Consolas, monospace; font-size: .85rem; }}
</style>
<nav>{' &nbsp;|&nbsp; '.join(nav)}</nav>
<h1>{html.escape(Path(path).name)}</h1>
<p class="muted">{html.escape(group)} — {html.escape(how)}</p>
<audio id="p" controls preload="auto" src="{cdn}"></audio>
<p class="muted file">If nothing starts, press play. Direct audio:
  <a href="{cdn}">{html.escape(Path(path).name)}</a> &nbsp;|&nbsp;
  <a href="https://github.com/{owner}/{repo}/blob/{branch}/{path}">in the repo</a></p>
<table>{''.join(f'<tr><td>{html.escape(k)}</td><td>{html.escape(str(v))}</td></tr>' for k, v in facts)}</table>
{transcript_block}
{text_block}
<script>
  // a click on the README link is a gesture on another origin, so a hard autoplay may be refused;
  // try quietly and leave the controls visible either way.
  const a = document.getElementById('p');
  a.play().catch(() => {{}});
</script>
"""


def main() -> None:
    owner, repo, branch = repo_slug()
    metas = load_metadata()
    inventory = json.loads((ROOT / "results/sample_inventory.json").read_text(encoding="utf-8"))
    PAGES_DIR.mkdir(parents=True, exist_ok=True)

    by_folder: dict[str, list[dict]] = {}
    for s in sorted(inventory, key=lambda s: s["path"]):
        folder = folder_of(s["path"])
        by_folder.setdefault(folder, []).append(s)

    count = 0
    for folder, items in by_folder.items():
        for i, s in enumerate(items):
            prev_next = (items[i - 1]["path"] if i else None,
                         items[i + 1]["path"] if i + 1 < len(items) else None)
            out = PAGES_DIR / f"{slug_of(s['path'])}.html"
            out.write_text(page(s, metas, owner, repo, branch, prev_next), encoding="utf-8")
            count += 1
    print(f"wrote {count} sample pages to docs/s/")
    print(f"example: https://{owner.lower()}.github.io/{repo}/s/{slug_of(by_folder['audio/emotion'][0]['path'])}.html")


if __name__ == "__main__":
    main()
