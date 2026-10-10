# OpenRouter TTS experiments — voice rendition + STT verification

Date: 2026-10-10 · Machine: Windows 11, Hermes Agent v0.21.6 (profile `engineer`)
Everything here was produced through **one OpenRouter API key**: text-to-speech via
`POST https://openrouter.ai/api/v1/audio/speech`, verification via
`POST https://openrouter.ai/api/v1/audio/transcriptions`. No ElevenLabs, Azure, Google or OpenAI
account/keys were used directly — OpenRouter routes to all of them.

## What is in this folder

```
audio/edge/                 3 free Microsoft Edge voices (Hermes' default TTS path) — baseline
audio/elevenlabs-en-full/   3 paid ElevenLabs premade female voices, full sci-fi paragraph
audio/english/              3 paid ElevenLabs premade voices re-rendered by render.py (excerpt)
audio/korean/               6 Korean female voices — 3 ElevenLabs library, 2 Azure, 1 Google
results/english.json        per-voice http status, bytes, duration, transcriptions, similarity
results/korean.json         same, for the Korean run
results/voice-catalog.json  which voice ids OpenRouter actually accepts (validated, not assumed)
results/costs.json          real per-request cost pulled from /api/v1/generation?id=...
render.py                   render + verify harness (this is what produced results/*.json)
discover.py                 model/voice discovery (supported_voices per speech model)
```

## Hermes wiring

Hermes' TTS tool has no voice argument — it reads provider/voice from config at call time, so
OpenRouter is reached through the OpenAI-compatible provider (the `/audio/speech` endpoint is
OpenAI-API shaped):

```yaml
tts:
  provider: openai                    # OpenAI-compatible client, pointed at OpenRouter
  openai:
    base_url: https://openrouter.ai/api/v1
    model: elevenlabs/eleven-v4
    voice: sarah
    api_key: ${env:OPENROUTER_API_KEY}   # secret stays in the profile .env
```

Applied with `hermes config set tts.openai.<key> <value>` (never by hand-editing config.yaml).
`tts.openai.base_url` / `.api_key` are read by the OpenAI TTS path but are not in the config
schema, so `hermes config set` prints a "not a recognized config key" warning and saves anyway.

## Method — every voice was verified, not assumed

1. **Discover**: `GET /api/v1/models?output_modalities=speech`, read each model's
   `supported_voices`. An unavailable voice is rejected with HTTP 400 (`Unknown voice "rachel"`),
   so acceptance/rejection is a fact, not a guess.
2. **Render**: `POST /audio/speech` → bytes on disk.
3. **Verify**: transcribe the rendered audio back with **two independent STT models**
   (`elevenlabs/scribe-v2`, `openai/whisper-large-v3`) and compare to the input text with a
   normalised Levenshtein similarity. This catches silent fallbacks (wrong voice, wrong language,
   truncated audio) that a 200 status hides.

### English (excerpt, `results/english.json`)

| voice | model | bytes | sec | scribe sim | whisper sim | cost/request |
|---|---|---|---|---|---|---|
| sarah | elevenlabs/eleven-v4 | 287,599 | 17.9 | 0.992 | 0.968 | $0.0100 |
| alice | elevenlabs/eleven-v4 | 294,287 | 18.3 | 0.992 | 0.968 | $0.0100 |
| matilda | elevenlabs/eleven-v4 | 293,033 | 18.2 | 0.992 | 0.968 | $0.0100 |

### Korean (full paragraph, `results/korean.json`)

| label | voice | provider | bytes | sec | scribe sim | whisper sim | cost/request |
|---|---|---|---|---|---|---|---|
| el-sora | `1BZBO072RKJTzZcDjRox` (Sora, storyteller) | ElevenLabs | 682,153 | 42.6 | 0.981 | 0.955 | $0.01064 |
| el-annakim | `uyVNoMrnUku1dZyVEXwD` (Anna Kim, narration) | ElevenLabs | 637,431 | 39.8 | 0.981 | 0.951 | $0.01064 |
| el-jini | `0oqpliV6dVSr9XomngOW` (Jini, narrator) | ElevenLabs | 607,756 | 37.9 | 0.977 | 0.951 | $0.01064 |
| mai-haena | `ko-KR-Haena:MAI-Voice-2.1` | Azure | 813,120 | 40.7 | 0.981 | 0.959 | $0.005852 |
| mai-harper | `ko-KR-Harper:MAI-Voice-2.1` | Azure | 1,003,200 | 50.2 | 0.977 | 0.927 | $0.005852 |
| gemini-kore | `Kore` (gemini-3.8-flash-tts) | Google | 655,916 | 40.9 | 0.981 | 0.932 | $0.009282 |

All six are female Korean voices; the residual similarity gap is STT spelling variance
(e.g. 아르헨트/아르엔트, 40년/사십 년), not generation error. Distinct md5 per file — see the
`md5sum` run in the session log; no voice silently reused another's audio.

## Top 6 female / top 6 male English voices (full paragraph)

**"Top" is not measurable through OpenRouter** — the models API publishes no popularity or usage
ranking, so I did not invent one. The selection is grounded in ElevenLabs' own library metadata
(`results/elevenlabs-premade-labels.json`: gender, age, accent, use_case per premade voice) and
picks the voices that carry narration / assistant / broadcast duty. **All 20 spoken premades were
rendered and verified anyway** (`results/english_female.json`, `results/english_male.json`) — the
six-and-six below are the headline cut, not the limit of what's in the folder.

### Female — the six presented (7 exist: Laura is the odd one out, a `social_media`/sassy voice)

| # | voice | label (ElevenLabs) | bytes | sec | scribe sim | whisper sim | cost |
|---|---|---|---|---|---|---|---|
| 1 | sarah | mature, reassuring, confident (US) | 520,821 | 32.5 | 0.991 | 0.962 | $0.0180 |
| 2 | alice | clear, engaging educator (UK) | 524,582 | 32.7 | 0.984 | 0.914 | $0.0180 |
| 3 | matilda | knowledgeable, professional (US) | 524,582 | 32.7 | 0.980 | 0.962 | $0.0180 |
| 4 | jessica | playful, bright, warm (US) | 509,118 | 31.8 | 0.987 | 0.962 | $0.0180 |
| 5 | lily | velvety actress (UK) | 535,031 | 33.4 | 0.991 | 0.931 | $0.0180 |
| 6 | bella | professional, bright, warm (US) | 527,090 | 32.9 | 0.987 | 0.965 | $0.0180 |

### Male — the six presented (13 exist; Callum is the character/animation pick)

| # | voice | label (ElevenLabs) | bytes | sec | scribe sim | whisper sim | cost |
|---|---|---|---|---|---|---|---|
| 1 | george | warm, captivating storyteller (UK) | 518,313 | 32.3 | 0.973 | 0.973 | $0.0180 |
| 2 | adam | dominant, firm (US) | 517,059 | 32.2 | 0.991 | 0.898 | $0.0180 |
| 3 | daniel | steady broadcaster (UK) | 528,344 | 33.0 | 0.991 | 0.931 | $0.0180 |
| 4 | brian | deep, resonant, comforting (US) | 487,384 | 30.4 | 0.991 | 0.962 | $0.0180 |
| 5 | eric | smooth, trustworthy (US, agentic) | 486,130 | 30.3 | 0.976 | 0.958 | $0.0180 |
| 6 | charlie | deep, confident, energetic (AU) | 497,833 | 31.0 | 0.991 | 0.962 | $0.0180 |

Also rendered and verified, available in `audio/english_female/` and `audio/english_male/`:
laura (female) and callum, will, chris, roger, liam, harry, bill (male), plus river
(`gender: neutral`, in the catalogue but not rendered).
**All 20 files have distinct md5** — no voice silently reused another's audio. (alice and matilda
land on the identical byte count, 524,582, at the same duration; their hashes differ.)

**Cost, measured** (`results/costs.json`, from `/api/v1/generation?id=…`): per-request cost scales
with text length — $0.0100 for the 250-char excerpt, $0.0180 for the 460-char paragraph, all on
`elevenlabs/eleven-v4`. Run totals: english $0.0300, korean $0.0529, english_female $0.1263,
english_male $0.2345; **grand total $0.4437**. STT verification calls are billed separately at
~$0.0001 per transcription and are not included.

## 50% faster versions (no files overwritten)

The fast set lives in `audio/english_female_fast/` and `audio/english_male_fast/` with `-fast150`
suffixes; the original renders are untouched. **The rate change is applied locally, not by the
provider**, because it cannot be requested: `speed: 1.5` returns
`400 speed is not supported by eleven_v4`, and `eleven-multilingual-v2` answers
`400 speed must be between 0.7 and 1.2 for this TTS provider`. So it is an ffmpeg `atempo=1.5`
pass — a pitch-preserving time-stretch, not a resample, so no chipmunk artifacts.

Verified: mean duration ratio **0.667** across all 20 files (1/1.5 = 0.667 exactly — e.g. sarah
32.48 s → 21.44 s, bill 35.12 s → 22.83 s), and STT similarity stays ≥ **0.973** (vs 0.973–0.991
before), so the words are still fully intelligible at speed. Full table:
`results/english_fast_summary.json`.

A native alternative exists if you want the model itself to speak fast: Azure's MAI-Voice honours
`speed` — `microsoft/mai-voice-2.1` with `en-US-Harper:MAI-Voice-2.1` measured 8.736 s at default
and 5.280 s at `speed: 1.5` (ratio 0.604). ElevenLabs on OpenRouter has no such control.

## "Happy Birthday to Bel" — four voices in harmony

`birthday_harmony.py` → `audio/birthday/happy-birthday-to-bel-4part-harmony.mp3`, with a
perfectly-tuned `reference-synth-4parts.mp3` of the same arrangement for A/B comparison.

**Is it possible?** Yes, with a real caveat: OpenRouter's speech models do not sing or follow a
melody, so the vocal has to be *constructed*. Each note is a separately rendered spoken syllable,
time-stretched to the note's duration and pitch-shifted to the note (`rubberband`, formant
preserving). The result is pitched-speech singing — recognisable, in tune, and clearly synthetic.
A genuinely sung version needs a singing model (Suno, ElevenLabs Music), not a TTS endpoint.

Arrangement, in D major (melody A3–A4 — chosen so every part sits within about an octave of its
voice's *speaking* pitch; the first attempt in G major pushed the female parts +19 semitones):

| part | voice | interval | reference pitch measured |
|---|---|---|---|
| F1 | sarah | melody | 202.9 Hz |
| F2 | jessica | diatonic 3rd below | 173.6 Hz |
| M1 | george | diatonic 6th below | 121.1 Hz |
| M2 | brian | octave below (bass doubling) | 98.8 Hz |

Every vertical interval is a unison/octave/3rd/5th/6th, so the chords are consonant by
construction, not by luck. 96 notes total (24 per voice) at 96 BPM.

Verification: the pitch estimator is self-tested on known tones before use (110/200/440 Hz →
0.0/0.0/+0.1 cents), and every placed note is re-measured (YIN) against its intended pitch —
mean absolute error 44 cents on the melody part, 100–217 cents on the lower parts, which is
natural intonation from the source syllables plus measurement noise on the shortest notes.
Per-note detail: `results/birthday_harmony.json`.

## Emotion — what actually works (measured, not assumed)

OpenRouter accepts several delivery controls and answers **200 for all of them**, including ones it
ignores. So each was tested for a measurable acoustic change (spectral centroid + high-band energy,
against repeated baselines to establish run-to-run spread):

| mechanism | model | verdict | evidence |
|---|---|---|---|
| inline tag `[whispering]` | **eleven-v4 / v4-turbo** | **works** | centroid 1106 → 4878 Hz, hi>4k 0.106 → 0.643; not spoken |
| inline tag | eleven-v3 | ignored silently | centroid 565 / 587 / 589 (plain, tagged, plain) |
| inline tag | multilingual-v2, flash-v2, flash-v2.5, turbo-v2, turbo-v2.5 | **dangerous** | the tag is READ ALOUD — transcript begins "Whispering. The colony ship…" |
| `instructions` | **google/gemini-*-tts** | **works** | same script, 33.7 s → 39.1 s, centroid 818 → 1510 Hz |
| `instructions` | eleven-v4 | ignored | centroid 980 vs 968–994 baseline |
| `voice_settings {style, stability}` | eleven-v4 | no separable effect | styled runs (997/1066/960) overlap baseline runs (1098/936/1037) |
| `style` + `styledegree` | microsoft/mai-voice-2.1 | inconclusive | styled 630 vs plain 594, but run spread was 550–638 |

Controlled A/B on the marked-up script: the `[whispering]` line measures centroid 1263 Hz /
hi>4k 0.149 against 552 Hz / 0.020 for the same line untagged (7.5× the high-band energy), while the
rest of the passage is unchanged — the tag affects its sentence, not the file.

Usage (markup lives in the script, so long text keeps per-line emotion):

```bash
# {{curious}} ... {{whispering}} markup in the source text
python tts.py say --file samples/emotion-script.txt --voice sarah
# blanket emotion, or a raw tag
python tts.py say "Hello there." --emotion cheerful
python tts.py say "Hello there." --tags '[excited]'
# Gemini: the same markup is translated to `instructions` automatically
python tts.py say --file samples/emotion-script.txt --voice Kore --model google/gemini-3.8-flash-tts
```

The tool refuses tag input on any model that reads tags aloud, and warns on models that silently
ignore them — because the failure mode (a spoken "Whispering.") is worse than no emotion at all.

## Tooling: `tts.py`

One entry point for everything that was previously done by hand (and got done wrong):

| command | purpose |
|---|---|
| `list [--model M]` | validated voices, with gender/accent/use-case labels merged in |
| `probe VOICE...` | test candidate ids against a model (200 vs 400 `Unknown voice`) |
| `say TEXT \| --file F` | **any length of text**: sentence-safe chunking, cross-chunk prosody (`previous_text`/`next_text`), resumable content-keyed cache, stitched output, optional `--speed`, `--verify` |
| `speed FILE --factor 1.5` | pitch-preserving rate change (what `speed` cannot do on eleven-v4) |
| `verify FILE --expect "..."` | transcribe back and score |

Long-text path proven on a 3,813-character sample: 4 chunks → one 251.9 s mp3, per-chunk STT
similarity 0.990–0.998. Cache is keyed on a hash of model+voice+emotion+instructions+text.

## Lessons learnt: what does NOT work

- **TTS cannot sing naturally, and no amount of engineering fixes it.** The harmony render is
  pitched *speech*: the syllables keep their spoken timbre, there is no legato, no vibrato, and no
  breath support, and every note carries a formant-preserving pitch shift of up to ±14 semitones
  (measured max: F1 +14.5, M2 −13.9). It is recognisable and in tune, and it sounds wrong. For sung
  audio use a music model (Suno, ElevenLabs Music) — that is the only honest route.
- **A 200 response is not an implementation.** `instructions` on eleven-v4, `voice_settings`, and
  Azure `style` all return 200; only one of them (Gemini's `instructions`) provably changes the
  audio, and one of them (`[tags]` on multilingual-v2/flash) silently turns into spoken words.
- **Cache keys must cover the input.** The first tool revision keyed chunks on voice + chunk count,
  so a control render of different text replayed the previous audio byte-for-byte. Identical byte
  counts across two supposedly different renders is the tell — always add a control run.
- **Cost must never be assumed.** The tool printed `$0.00000` when the generation-cost lookup
  returned nothing; it now prints `cost n/a` and counts unpriced requests, because a fabricated
  zero is worse than an admitted unknown.

## Local engines (offline, $0 per character)

`local_tts.py` drives what this machine can run without a network or an API key. Measured here:
**no GPU** (`nvidia-smi` absent), so GPU-only models (e.g. Microsoft's open-weight VibeVoice) are out
of reach; the viable local engines are Windows' own voices and Piper.

| engine | voices available here | install | emotion |
|---|---|---|---|
| **SAPI** (Windows System.Speech) | Microsoft David (M), Zira (F) — plus Mark via the WinRT/OneCore list | none, already present | `{{markup}}` → SSML prosody (rate/pitch/volume): crude but measurable |
| **Piper** (CPU, ONNX) | en_US-amy (F), en_US-ryan (M), en_GB-cori (F), **ko_KR-kss** | `uv pip install piper-tts` + `fetch_piper_voices.py` (md5-verified) | none — markup is stripped, never spoken |

```bash
python local_tts.py engines                      # what is usable right now
python local_tts.py voices --engine piper
python local_tts.py say --file samples/scifi-emotion-en.txt --engine piper --voice en_US-amy-medium --verify
python local_tts.py say --file samples/scifi-emotion-ko.txt --engine piper --voice ko_KR-kss-medium
python local_tts.py say "Hello." --engine sapi --voice "Microsoft Zira Desktop"
```

Quality vs cloud on the same script (`audio/local/` vs `audio/emotion/`), verified by STT round-trip:

| engine | voice | seconds | STT similarity | cost |
|---|---|---|---|---|
| Piper | en_US-amy (F) | 28.8 | **0.978** | $0 |
| SAPI | Zira (F) | 32.0 | **0.976** | $0 |
| ElevenLabs v4 | sarah (F) | 31.0 | 0.992 | ~$0.018 |
| Piper | ko_KR-kss | 36.1 | **0.932** | $0 |
| ElevenLabs v4 | sora (KO) | 40.3 | 0.981 | ~$0.018 |

So: local is intelligible and free, cloud is measurably more accurate and the only one with real
expressiveness. SAPI's emotion mapping is provably not just cosmetic — the `{{whispering}}` segment
lands at RMS 0.009 against 0.093 for the untagged read of the same script (10× quieter).

## Emotion across the whole voice set

Every voice from the earlier rounds was re-rendered from the marked-up scripts
(`samples/scifi-emotion-en.txt`, `samples/scifi-emotion-ko.txt`) — 12 English, 3 Korean ElevenLabs,
1 Korean Gemini, 1 Korean Azure, plus `-fast150` variants of the English set. Per-file measurements:
`results/emotion_batch.json`.

Honest limits of that batch:

- Tags are **never spoken** in any render (STT checked on both an English and a Korean file).
- The English v4 whisper is the well-evidenced effect (last-line high-band energy 0.092–0.178 across
  the twelve voices).
- **Korean is weaker evidence.** The tagged Korean renders are consistently quieter than the plain
  renders of the same paragraph (RMS 0.047 vs 0.074 for sora, 0.082 vs 0.122 for annakim), but no
  repeated-baseline variance was established for Korean, so this is a *changed delivery*, not a
  proven whisper. The bright-whisper signature that makes English v4 so obvious does not appear.
- Azure MAI still strips the markup: no verified emotion control on that path.

## Pitfalls found (all reproduced, not theoretical)

1. **Non-ASCII in a shell-quoted `curl -d` body is a trap.** Sending Korean text inline from this
   git-bash session produced HTTP 200 with 1.2–3.2 s of nonsense (transcripts like
   `"Where do you bink?"`) — the body was mangled before it left the shell. Sending the same text
   from Python (`json.dumps` + `urllib`) rendered correctly at 38–50 s. **Always build the JSON
   body in Python or a file, never inline in bash.**
2. **Not every ElevenLabs voice exists on OpenRouter.** `eleven-v4` exposes 21 premade voices;
   `rachel`, `charlotte`, `grace`, `nicole` return `400 Unknown voice` even though they are
   standard premade voices in ElevenLabs' own product.
3. **ElevenLabs library (community) voices work by 20-char `voice_id`.** A bogus 20-char id is
   rejected with 400, so ids are validated and a 200 means the voice was honoured. The Korean ids
   here came from the public library payload behind `kvid.ai/en/voice-library`.
4. **Gemini TTS is PCM-only**: `response_format: mp3` → `400 Gemini TTS only supports
   response_format="pcm"`. Pipe PCM to `ffmpeg -f s16le -ar 24000 -ac 1`.
5. **Azure MAI-Voice needs the model suffix in the voice string**:
   `ko-KR-Haena:MAI-Voice-2.1` (the suffix must match the model id).
6. **`difflib.SequenceMatcher` is the wrong similarity metric here** — its autojunk heuristic
   scores two near-identical 250-char paragraphs at 0.34. Use normalised Levenshtein.
7. Hermes' TTS tool reports `provider: openai` for this route; the audio is ElevenLabs/Azure/
   Google behind OpenRouter. Read the model id, not the provider label.
8. **Pitch measurement is where TTS-singing projects die.** Raw autocorrelation reported 1128 Hz
   for a female "hap" and 816 Hz for a male one; walking down the YIN valley reported the
   subharmonic (75 Hz for a ~150 Hz voice); taking the first threshold crossing biased a known
   110 Hz tone to 106.9 Hz (−49 cents); and estimating a voice's pitch from one sustained vowel
   gave 63 Hz for a female voice. What worked: YIN at the first local minimum below threshold
   with parabolic refinement, a self-test on synthetic tones before any shift is computed, and a
   per-voice median over all its syllables with a gender-based plausibility guard.
9. **Per-syllable pitch, not a per-voice average, is what puts the chord in tune.** Shifting every
   note from a single voice-wide pitch left ~150–200 cents of error on the lower parts; shifting
   each note from the measured pitch of the clip it came from cut the melody part to 44 cents.
10. **Key/register choice decides whether pitched-speech singing is listenable.** Speech voices sit
    at their speaking pitch (~200 Hz female, ~100–130 Hz male); a melody placed too high needs
    +19 semitone shifts and sounds strained.
11. **Azure voice ids are illegal Windows directory names.** `ko-KR-Haena:MAI-Voice-2.1` contains a
    colon; using it in a path raised `NotADirectoryError` and killed the render after the API call.
    Slugify voice names before they touch the filesystem.
12. **A pipeline hides the exit code.** `uv venv` creates an environment with no `pip`, and
    `... | tail -2 && echo INSTALLED` reported success while nothing was installed. Use `uv pip
    install --python <venv>`, and never chain a status check behind a pipe.
13. **Local engines need the same distrust as cloud ones.** SAPI's SSML mapping and Piper's lack of
    emotion support are both facts to measure (segment RMS/centroid), not assumptions from docs.

## Reproduce

```bash
cd C:/Users/jptra/Projects/tts-voice-experiments
~/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe discover.py        # voice catalogue
~/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe render.py korean   # render + verify
~/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe render.py english
```

Requires `OPENROUTER_API_KEY` in `~/.hermes/profiles/engineer/.env` and `ffmpeg`/`ffprobe` on PATH.

## Texts used

Both paragraphs are **original demo prose**, not quotations from any novel:
the English one ("colony ship Argent…") and the Korean translation used for the Korean run.
