#!/usr/bin/env python
"""Generate a GitHub Pages listening room (docs/players.html + docs/index.html).

Why this exists: GitHub's markdown sanitizer strips <audio>/<video>, the blob view of an mp3
offers only a Download button, and raw.githubusercontent.com sends
`content-disposition: attachment` (also a download). A plain HTML page served by GitHub Pages is
the only place an <audio controls> player actually appears inline - so every sample gets one here,
and the README links to this page.

Run:  python tools_gen_players.py
"""
from __future__ import annotations

import html
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
SKIP_PARTS = {"renders", "raw", "parts", "_speed_probe", "emotion_probe"}

GROUPS = [
    ("Baselines — the same paragraph, three ways", "audio/edge", "Free Microsoft Edge voices (Hermes' default path)."),
    ("ElevenLabs premades — first delivery", "audio/elevenlabs-en-full", "Paid `eleven-v4`, full sci-fi paragraph."),
    ("English premades — all 20 voices", "audio/english_female", "All 7 female premades."),
    ("", "audio/english_male", "All 13 male premades (`river` is labelled neutral and was not rendered)."),
    ("", "audio/english_female_fast", "The same voices at 1.5x (local atempo, pitch preserved)."),
    ("", "audio/english_male_fast", "The same voices at 1.5x."),
    ("Emotion — per-sentence delivery", "audio/emotion", "English tags on eleven-v4, Korean, Gemini instructions and the untagged controls."),
    ("Korean — 6 female voices", "audio/korean", "3 ElevenLabs library ids, 2 Azure MAI voices, 1 Gemini voice."),
    ("Local / offline engines", "audio/local", "Windows SAPI and Piper — no API key, $0 per character."),
    ("Long text", "audio/longtext", "3,813 characters (samples/long-text-sample.txt) rendered as one stitched file — the chunked long-form path."),
    ("Special cases", "audio/birthday", "The four-part harmony experiment (a documented failure) and its synth reference."),
]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def repo_slug() -> tuple[str, str]:
    url = git("remote", "get-url", "origin")
    slug = url.rstrip("/").removesuffix(".git").split("github.com")[-1].lstrip("/:")
    owner, _, name = slug.partition("/")
    return owner, name


def durations() -> dict[str, float]:
    inv = ROOT / "results" / "sample_inventory.json"
    if not inv.exists():
        return {}
    return {r["path"]: r["seconds"] for r in json.loads(inv.read_text(encoding="utf-8"))}


def main() -> None:
    owner, name = repo_slug()
    branch = git("rev-parse", "--abbrev-ref", "HEAD") or "master"
    dur = durations()
    pages = f"https://{owner.lower()}.github.io/{name}"
    cdn = f"https://cdn.jsdelivr.net/gh/{owner}/{name}@{branch}"

    sections, count = [], 0
    for title, folder, blurb in GROUPS:
        files = sorted((ROOT / folder).glob("*.mp3"))
        if not files:
            continue
        rows = []
        for p in files:
            rel = p.relative_to(ROOT).as_posix()
            secs = dur.get(rel)
            dur_text = f"{secs:g} s" if secs else "?"
            rows.append(
                f'      <li id="{html.escape(p.stem)}">'
                f'<a class="name" href="s/{html.escape(p.stem)}.html" title="player, transcript and measurements">{html.escape(p.name)}</a>'
                f'<span class="dur">{dur_text}</span>'
                f'<audio controls preload="none" src="{cdn}/{rel}"></audio>'
                f'<a class="repo" href="https://github.com/{owner}/{name}/blob/{branch}/{rel}">file</a>'
                f"</li>")
            count += 1
        head = f"    <h2>{html.escape(title)}</h2>\n" if title else ""
        sections.append(f'{head}    <p class="blurb">{blurb}</p>\n    <ul>\n' + "\n".join(rows) + "\n    </ul>")

    DOCS.mkdir(exist_ok=True)
    (DOCS / "players.html").write_text(f"""<!DOCTYPE html>
<meta charset="utf-8">
<title>TTS voice experiments — listening room</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 16px/1.5 -apple-system, Segoe UI, Roboto, sans-serif; max-width: 62rem; margin: 2rem auto; padding: 0 1rem; }}
  h1 {{ margin-bottom: .2rem; }}
  h2 {{ margin-top: 2.4rem; border-bottom: 1px solid #8884; padding-bottom: .3rem; }}
  .blurb {{ color: #888; margin: .3rem 0 1rem; }}
  ul {{ list-style: none; padding: 0; }}
  li {{ display: grid; grid-template-columns: minmax(14rem, 22rem) 4.5rem 1fr auto; align-items: center; gap: .6rem; padding: .25rem 0; border-bottom: 1px solid #8882; }}
  .name {{ font-family: ui-monospace, Menlo, Consolas, monospace; font-size: .86rem; overflow-wrap: anywhere; }}
  .dur {{ color: #888; font-size: .85rem; text-align: right; }}
  audio {{ width: 100%; height: 2rem; }}
  .repo {{ font-size: .8rem; }}
  header p {{ color: #888; }}
</style>
<header>
  <h1>TTS voice experiments — listening room</h1>
  <p>{count} samples, rendered through OpenRouter (ElevenLabs, Azure, Google) and locally
     (Windows SAPI, Piper). Audio is served from jsDelivr; GitHub's markdown sanitiser strips
     embedded players, which is why this page exists.
     <a href="https://github.com/{owner}/{name}">Repository and README</a>.</p>
</header>
{chr(10).join(sections)}
""", encoding="utf-8")

    (DOCS / "index.html").write_text(f"""<!DOCTYPE html>
<meta charset="utf-8">
<title>TTS voice experiments</title>
<style>body {{ font: 16px/1.6 -apple-system, Segoe UI, Roboto, sans-serif; max-width: 40rem; margin: 4rem auto; padding: 0 1rem; }}</style>
<h1>TTS voice experiments</h1>
<p>Audio rendered with ElevenLabs, Azure and Google models through OpenRouter, plus offline
   engines (Windows SAPI, Piper). Every take was verified by transcribing it back.</p>
<p><a href="players.html">Open the listening room &rarr;</a></p>
<p><a href="https://github.com/{owner}/{name}">README, measurements and scripts</a></p>
""", encoding="utf-8")

    print(f"wrote docs/players.html ({count} players) and docs/index.html")
    print(f"pages url after enabling Pages: {pages}/players.html")


if __name__ == "__main__":
    main()
