# TTS voice experiments — ElevenLabs/Azure/Gemini via OpenRouter, plus local engines

Date: 2026-10-10 · Windows 11 · Hermes Agent v0.21.6 (profile `engineer`)

One OpenRouter API key drives everything cloud here: speech via `POST /api/v1/audio/speech`,
verification via `POST /api/v1/audio/transcriptions`. OpenRouter routes to ElevenLabs, Azure and
Google — no separate accounts. Running alongside it are **fully offline** engines (Windows SAPI,
Piper) that cost nothing and need no key.

**Read this file top-down:** section 1 is the sample catalog (what to listen to and why), then how
the audio was produced, what was measured, the security posture, and finally what does not work.

### Status at a glance

| capability | verdict |
|---|---|
| English female/male voices, any length of text | **works** — all 21 ElevenLabs premades routed; chunked rendering proven at 3,813 chars |
| Emotion (whisper / amused / curious / serious …) | **works on eleven-v4 (inline tags) and Gemini (`instructions`)**; silently ignored on v3; read aloud on multilingual-v2 / flash |
| 50% faster speech | **works, but applied locally** (`atempo`) — the `speed` parameter is rejected by eleven-v4 |
| Korean | **works** — 3 ElevenLabs library voices, 2 Azure, 1 Gemini; emotion evidence weaker than English |
| Offline / no API key | **works** — Piper (including Korean) and Windows SAPI: intelligible, less accurate |
| Voices *singing* in harmony | **does not work acceptably** — in tune, and clearly unnatural |
| GPU local models (VibeVoice and similar) | **not possible on this machine** — no GPU |

---

## 1. Sample catalog — what to listen to

Every file below is committed and was produced by the scripts in this repo. `sec` = duration;
**sim** = STT round-trip similarity to the input text (1.000 = perfect).

### 1.1 Start here — the same paragraph, three ways

| file | what it demonstrates | sec |
|---|---|---|
| `audio/edge/01-aria.mp3`, `02-jenny.mp3`, `03-sonia.mp3` | free Microsoft Edge voices (Hermes' default path) — the baseline everything else is measured against | 28–29 |
| `audio/elevenlabs-en-full/01-sarah.mp3`, `02-alice.mp3`, `03-matilda.mp3` | the first paid delivery: three ElevenLabs premades on `eleven-v4` | 32.5 / 32.7 / 32.7 |
| `audio/emotion/en-sarah-emotion.mp3` | **the emotion version of the same paragraph** — listen to the final sentence | 31.0 |

*Listen for:* in the emotion version the last line (the ship's reply) drops into an audible whisper
while the earlier sentences stay normal — the clearest effect in the project. Compare it against
`audio/emotion/_control_plain_sarah.mp3`, the identical script rendered without markup.

### 1.2 English — all 21 premade voices, full paragraph

| set | voices | count | notes |
|---|---|---|---|
| `audio/english_female/` | sarah, alice, matilda, jessica, lily, bella, laura | 7 | all female premades |
| `audio/english_male/` | adam, george, brian, daniel, eric, callum, charlie, will, chris, roger, liam, harry, bill | 13 | all male premades (`river` is labelled neutral; not rendered) |
| `audio/english_female_fast/`, `audio/english_male_fast/` | the same 20 voices | 20 | `-fast150` = 1.5× rate, pitch preserved; originals untouched |
| `audio/english/` | sarah, alice, matilda | 3 | the excerpt-length run behind `results/english.json` |

Measured: sim 0.973–0.991 across all 20; the fast versions stay ≥ 0.973 with a duration ratio of
exactly 0.667. The headline six-and-six with ElevenLabs' own voice labels is in section 3.

### 1.3 Emotion across the whole set — `audio/emotion/` (34 files)

| group | files | what it shows |
|---|---|---|
| English, 12 voices | `en-<voice>-emotion.mp3` | per-sentence delivery from `{{curious}} {{serious}} {{amused}} {{whispering}}` |
| English, 12 voices | `en-<voice>-emotion-fast150.mp3` | the same at 1.5× |
| Korean, ElevenLabs | `ko-sora-emotion.mp3`, `ko-annakim-emotion.mp3`, `ko-jini-emotion.mp3` | tag accepted; delivery changes (consistently quieter) but no proven whisper |
| Korean, Gemini | `ko-kore-emotion.mp3` | the same markup auto-translated to `instructions` |
| Korean, Azure | `ko-haena-plain.mp3` | **no emotion** — MAI has no verified control, so the markup is stripped rather than risked being spoken |
| Single-script demos | `sci-fi-emotion-sarah.mp3`, `sci-fi-emotion-george.mp3`, `sci-fi-emotion-gemini.mp3` | one marked-up script across three engines |
| Controls | `_control_plain_sarah.mp3`, `_control_plain_gemini.mp3` | the untagged read, for honest A/B |

*Listen for:* the English files (sarah, matilda, adam, george are the clearest) whisper audibly on
the last line; the Korean files change less — that limit is documented in section 5.
`ko-haena-plain.mp3` is deliberately flat.

### 1.4 Korean — `audio/korean/` (6 voices)

| file | voice | route | sec | sim |
|---|---|---|---|---|
| `el-sora.mp3` | Sora — warm storyteller | ElevenLabs library id | 42.6 | 0.981 |
| `el-annakim.mp3` | Anna Kim — narration | ElevenLabs library id | 39.8 | 0.981 |
| `el-jini.mp3` | Jini — premium narrator | ElevenLabs library id | 37.9 | 0.977 |
| `mai-haena.mp3` | `ko-KR-Haena:MAI-Voice-2.1` | Azure MAI-Voice-2.1 | 40.7 | 0.981 |
| `mai-harper.mp3` | `ko-KR-Harper:MAI-Voice-2.1` | Azure MAI-Voice-2.1 | 50.2 | 0.977 |
| `gemini-kore.mp3` | Kore | Google Gemini TTS (PCM → MP3) | 40.9 | 0.981 |

The residual similarity gap is STT spelling variance (아르헨트/아르엔트, 40년/사십 년), not generation
error. All six files have distinct md5s — no voice silently reused another's audio.

### 1.5 Offline engines — `audio/local/`

| file | engine | voice | sec | sim | cost |
|---|---|---|---|---|---|
| `piper-amy-en.mp3` | Piper (CPU ONNX) | en_US-amy-medium | 28.8 | 0.978 | $0 |
| `piper-kss-ko.mp3` | Piper | ko_KR-kss-medium (Korean) | 36.1 | 0.932 | $0 |
| `sapi-zira-en.mp3` | Windows SAPI | Microsoft Zira Desktop | 32.0 | 0.976 | $0 |

*Listen for:* play the cloud and local versions of the same sentence back to back — local is
understandable and noticeably flatter. `sapi-zira-en.mp3` is the only local file with any emotion
mapping (SSML prosody: its whisper segment measures 10× quieter than the untagged read).

### 1.6 Special cases

| file | what it is | verdict |
|---|---|---|
| `audio/birthday/happy-birthday-to-bel-4part-harmony.mp3` | four voices (sarah, jessica, george, brian) singing "Happy Birthday to Bel" in four-part harmony, built by re-pitching spoken syllables note by note | **documented failure** — in tune, consonant, unnatural |
| `audio/birthday/reference-synth-4parts.mp3` | the same arrangement played by a synth | A/B reference for the harmony's tuning |
| `audio/renders/…/sarah.mp3` (gitignored, regenerable) | 3,813-character sample → 4 chunks → one 251.9 s file | long-text proof; per-chunk sim 0.990–0.998 |

---

## 2. Repository map

```
tts.py                  main CLI: list | probe | say | speed | verify   (cloud, any length)
local_tts.py            offline CLI: engines | voices | say            (Windows SAPI, Piper)
render.py               earlier harness: renders a voice set and STT-verifies it (writes results/*.json)
discover.py             lists which voices each speech model accepts
birthday_harmony.py     the four-part-harmony experiment (documented failure)
fetch_piper_voices.py   downloads Piper models, verifying the published md5
emotion_batch.sh        re-renders every voice from the emotion-marked scripts
tools_scrub_paths.py    one-off privacy scrub (absolute home paths → repo-relative)

samples/                the scripts that were spoken (plain + emotion-marked, EN + KO)
audio/                  every rendered sample, grouped as in section 1
models/piper/           Piper ONNX voices (gitignored; 360 MB; re-fetch with fetch_piper_voices.py)
results/                machine-readable measurements behind every claim in this file
.gitleaks.toml          secret-scan rules
.pre-commit-config.yaml local commit gate
.github/workflows/ci.yml full-history secret scan + tooling smoke test
```

### Where each measurement lives

| file | contents |
|---|---|
| `results/voice-catalog.json` | which voice ids OpenRouter accepts/rejects, with the raw 400 messages |
| `results/elevenlabs-premade-labels.json` | gender/accent/use-case labels for all 21 premades (the basis of the "top 6") |
| `results/english.json`, `korean.json`, `english_female.json`, `english_male.json` | per-voice http status, bytes, duration, two transcriptions, similarity |
| `results/english_female_fast.json`, `english_male_fast.json`, `english_fast_summary.json` | the 1.5× set: duration ratios and similarity |
| `results/emotion_probe.json`, `emotion_probe_raw.json` | the emotion mechanism matrix (works / ignored / spoken aloud) |
| `results/emotion_batch.json` | per-file duration and segment spectral measurements for the emotion batch |
| `results/birthday_harmony.json` | per-note pitch: intended, measured, cents error |
| `results/costs.json` | real per-request cost from `/api/v1/generation?id=…` |
| `results/sample_inventory.json` | every committed sample with duration and size |

---

## 3. How it works

### Hermes wiring

Hermes' TTS tool takes no voice argument — it reads provider/voice from config at call time, so
OpenRouter is reached through the OpenAI-compatible provider (`/audio/speech` is OpenAI-shaped):

```yaml
tts:
  provider: openai
  openai:
    base_url: https://openrouter.ai/api/v1
    model: elevenlabs/eleven-v4
    voice: sarah
    api_key: ${env:OPENROUTER_API_KEY}   # secret stays in the Hermes profile .env
```

Applied with `hermes config set tts.openai.<key> <value>` (never by hand-editing `config.yaml`).
`tts.openai.base_url` / `.api_key` are read by the OpenAI path but are not in the config schema, so
`hermes config set` warns "not a recognized config key" and saves anyway.

### The "top 6 female / top 6 male" selection

**"Top" is not measurable through OpenRouter** — the models API publishes no popularity ranking, so
this project did not invent one. The selection is grounded in ElevenLabs' own library metadata
(`results/elevenlabs-premade-labels.json`) and picks the voices carrying narration / assistant /
broadcast duty: female **sarah, alice, matilda, jessica, lily, bella**; male **george, adam, daniel,
brian, eric, charlie**. All 20 spoken premades were rendered and verified regardless.

### `tts.py` — the cloud entry point

| command | purpose |
|---|---|
| `list [--model M]` | validated voices with gender/accent/use-case labels merged in |
| `probe VOICE...` | test candidate ids against a model (200 vs 400 `Unknown voice`) |
| `say TEXT \| --file F` | **any length**: sentence-safe chunking, cross-chunk prosody (`previous_text`/`next_text`), resumable content-keyed cache, stitched mp3, `--speed`, `--verify`, `--emotion`, `--tags` |
| `speed FILE --factor 1.5` | pitch-preserving rate change |
| `verify FILE --expect "…"` | transcribe back and score |

```bash
python tts.py list --model elevenlabs/eleven-v4
python tts.py say --file samples/scifi-emotion-en.txt --voice sarah --verify
python tts.py say --file samples/scifi-emotion-ko.txt --voice 1BZBO072RKJTzZcDjRox
python tts.py say --file samples/scifi-emotion-en.txt --voice Kore --model google/gemini-3.8-flash-tts
python tts.py speed audio/emotion/en-sarah-emotion.mp3 --factor 1.5
```

Emotion markup lives **in the script** (`{{whispering}} … {{excited}} …`), so a long document keeps
per-line delivery, and one mapping function translates it to each provider's mechanism — inline tags
for the v4 family, `instructions` for Gemini/OpenAI. The tool refuses tag input where tags would be
read aloud, and warns where they are silently ignored.

### `local_tts.py` — the offline entry point

```bash
python local_tts.py engines
python local_tts.py say --file samples/scifi-emotion-en.txt --engine piper --voice en_US-amy-medium --verify
python local_tts.py say --file samples/scifi-emotion-ko.txt --engine piper --voice ko_KR-kss-medium
python local_tts.py say "Hello." --engine sapi --voice "Microsoft Zira Desktop"
```

### Method — every claim here was verified

1. **Discover from the API, never from docs.** `supported_voices` per model; an unavailable voice
   returns `400 Unknown voice "rachel"`, so acceptance is a fact rather than an assumption.
2. **Render, then transcribe the audio back** with an independent STT model (`elevenlabs/scribe-v2`,
   cross-checked against `openai/whisper-large-v3`) and score it against the input with normalised
   Levenshtein. A 200 status hides wrong-voice, wrong-language and truncated renders; the round trip
   does not.
3. **For emotion, compare acoustically.** `instructions`, `voice_settings` and Azure `style` all
   return 200 whether or not they do anything, so each was scored by spectral centroid, high-band
   energy and RMS against repeated baseline renders.

### Cost, measured (`results/costs.json`)

Per request on `elevenlabs/eleven-v4`: **$0.0100** for the 250-char excerpt, **$0.0180** for the
460-char paragraph — cost scales with length. Run totals: english $0.0300, korean $0.0529,
english_female $0.1263, english_male $0.2345 → **$0.4437** for all cloud work in this repo. Azure MAI
is cheaper ($0.005852/request), Gemini $0.009282; STT verification is ~$0.0001 per call; local engines
are **$0**. Where the cost lookup returns nothing the tools print `cost n/a` and count unpriced
requests — never a fabricated zero.

---

## 4. Security & privacy

Policy mirrored from the sibling `eClock` repository: **no secrets in git, with a scan that proves it.**

| layer | what it does |
|---|---|
| `.gitignore` | ignores `.env`, `.env.*`, `*.local.ini`, `secrets.json`; keeps `.env.example` (names only) |
| **where the key lives** | `~/AppData/Local/hermes/profiles/engineer/.env` (Hermes profile secret store) — **outside this repo**. Scripts read `$OPENROUTER_API_KEY` first, then that path; no key is ever read from a file inside the repo. |
| `.gitleaks.toml` | default gitleaks rules over everything except `audio/`, `models/`, `.venv/` (binary/generated content that trips lookalike heuristics). Project source stays in scope, so a real credential there is still caught. |
| `.pre-commit-config.yaml` | gitleaks (blocks the commit on a match) plus hygiene: trailing whitespace, end-of-file, YAML validity, large files, merge conflicts, private keys. Installed with `pre-commit install`. |
| `.github/workflows/ci.yml` | full-history gitleaks scan (`fetch-depth: 0`, so an old commit cannot hide a credential) plus a tooling smoke test that needs no credentials |
| **artifact privacy** | committed manifests and results carry **repo-relative** paths, never `C:\Users\<name>\…`. Enforced in code (`rel()` in `tts.py`, `local_tts.py`, `birthday_harmony.py`) and cleaned once with `tools_scrub_paths.py`. |

Run the gates yourself:

```bash
pre-commit run --all-files                                    # what every commit runs
gitleaks detect --source . --config .gitleaks.toml --redact   # full history, redacted output
```

Known and accepted: `results/*.json` contain OpenRouter generation ids and per-request costs. That is
account-linked metadata, carries no credential, and is required to reproduce the cost figures above.

---

## 5. Lessons learnt: what does NOT work

- **TTS cannot sing naturally, and no amount of engineering fixes it.** The harmony render is pitched
  *speech*: spoken timbre, no legato, no vibrato, no breath support, and up to ±14 semitones of
  formant-preserving shift per note (measured maxima F1 +14.5, M2 −13.9). It is recognisably in tune
  and it sounds wrong. For sung audio use a music model (Suno, ElevenLabs Music) — the only honest route.
- **A 200 response is not an implementation.** `instructions` on eleven-v4, `voice_settings
  {style, stability}` and Azure `style`/`styledegree` all return 200; only Gemini's `instructions`
  provably changes the audio (33.7 s → 39.1 s, centroid 818 → 1510 Hz). A tag on multilingual-v2 or
  flash is *worse than ignored*: it is read aloud as the word "Whispering."
- **Emotion tags are a v4-family feature.** eleven-v3 accepts `[whispering]` and does nothing with it
  (centroid 565 / 587 / 589 across tagged / plain / plain). Gate this in code, not in documentation.
- **Korean emotion is unproven.** Tagged Korean renders are consistently quieter than the plain ones
  (RMS 0.047 vs 0.074 for sora) but no Korean baseline variance was established, so this is a changed
  delivery, not a whisper; the bright high-frequency signature of English v4 does not appear.
- **Cache keys must cover the input.** The first `tts.py` keyed chunks on voice + chunk count, so a
  control render of *different* text silently replayed the previous audio byte-for-byte. Identical
  byte counts across two supposedly different renders is the tell — always run a control.
- **Cost must never be assumed.** The tool printed `$0.00000` when the cost lookup returned nothing;
  a fabricated zero is worse than an admitted unknown.
- **Local is worse in degree, not in kind.** Piper 0.978 / SAPI 0.976 vs ElevenLabs 0.992 on the same
  script: intelligible and free, but with no expressive range, and Piper has no emotion control at all.
- **GPU-only local models are out of reach here.** No `nvidia-smi`, so Microsoft's open-weight
  VibeVoice and similar are not an option; Piper (CPU) and Windows SAPI are.

## 6. Pitfalls found (all reproduced, not theoretical)

1. **Non-ASCII in a shell-quoted `curl -d` body is a trap.** Korean text sent inline from this
   git-bash session produced HTTP 200 with 1.2–3.2 s of nonsense (`"Where do you bink?"`) — the body
   was mangled before it left the shell. Build JSON in Python or a file, never inline in bash.
2. **Not every ElevenLabs voice exists on OpenRouter.** `rachel`, `charlotte`, `grace` and `nicole`
   return `400 Unknown voice`, even though they are standard premades in ElevenLabs' own product.
3. **ElevenLabs library (community) voices work by 20-character `voice_id`.** A bogus 20-char id is
   rejected with 400, so ids are validated and a 200 means the voice was honoured. The Korean ids came
   from the public library payload behind `kvid.ai/en/voice-library`.
4. **Gemini TTS is PCM-only**: `response_format: mp3` returns 400. Pipe PCM through
   `ffmpeg -f s16le -ar 24000 -ac 1`.
5. **Azure MAI-Voice needs the model suffix in the voice string** (`ko-KR-Haena:MAI-Voice-2.1`).
6. **`difflib.SequenceMatcher` is the wrong similarity metric here** — its autojunk heuristic scores
   two near-identical 250-character paragraphs at 0.34. Use normalised Levenshtein.
7. Hermes' TTS tool reports `provider: openai` for this route; the audio is ElevenLabs/Azure/Google.
   Read the model id, not the provider label.
8. **Pitch measurement is where TTS-singing projects die.** Raw autocorrelation reported 1128 Hz for a
   female "hap"; walking down the YIN valley reported the subharmonic (75 Hz for a ~150 Hz voice); the
   first threshold crossing biased a known 110 Hz tone to 106.9 Hz (−49 cents); a single sustained
   vowel gave a female voice 63 Hz. What worked: YIN at the first local minimum below threshold with
   parabolic refinement, a self-test on synthetic tones before any shift, and a per-voice median over
   all syllables with a gender-based plausibility guard.
9. **Per-syllable pitch, not a per-voice average, is what puts a chord in tune** — a voice-wide
   average left ~150–200 cents of error on the lower parts; per-clip measurement cut the melody to 44.
10. **Key/register choice decides whether pitched-speech singing is listenable.** A melody placed too
    high (+19 semitones) sounds strained; D major kept every part within an octave of its voice.
11. **Azure voice ids are illegal Windows directory names.** The colon in `ko-KR-Haena:MAI-Voice-2.1`
    raised `NotADirectoryError` after the API call had already succeeded. Slugify before paths.
12. **A pipeline hides the exit code.** `uv venv` ships no `pip`, and `… | tail -2 && echo INSTALLED`
    reported success while nothing was installed. Use `uv pip install --python <venv>`, and never
    chain a status check behind a pipe.
13. **Local engines need the same distrust as cloud engines** — SAPI's SSML mapping and Piper's lack of
    emotion support are measured facts (segment RMS/centroid), not documentation claims.

---

## 7. Reproduce

```bash
cd <repo>                                          # ffmpeg and ffprobe required on PATH
PY=~/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe

$PY tts.py list                                    # voices + labels, no cost
$PY tts.py say --file samples/scifi-emotion-en.txt --voice sarah --verify
bash emotion_batch.sh                              # the whole emotion set (needs the key)
$PY fetch_piper_voices.py                          # ~360 MB of Piper models, md5-verified
$PY local_tts.py say "offline hello" --engine piper --voice en_US-amy-medium
$PY render.py english                              # the earlier measurement harness
```

Cloud commands need `OPENROUTER_API_KEY` (environment, else the Hermes profile `.env`); every
`local_tts.py` command needs no key at all.

### Texts used

All English and Korean paragraphs are **original demo prose** written for this project — not
quotations from any novel. The "Happy Birthday" melody is public domain (1893 *Good Morning to All*;
the 1935 Warner/Chappell claim was invalidated in 2016). The long-text sample is likewise original.
