#!/usr/bin/env python
"""Four TTS voices singing "Happy Birthday to Bel" in four-part harmony.

Why the pitch pipeline is needed: OpenRouter's TTS endpoints serve *speech* models. ElevenLabs
eleven-v4 rejects `speed`, and no speech model follows a melody - so a "sung" line has to be
built from spoken syllables re-pitched note by note.

Pipeline per voice:
  1. render a sustained vowel -> measure that voice's natural pitch (YIN). Each voice has its
     own natural pitch, so the per-note shift must be measured per voice, not taken from the
     melody.
  2. render each lyric syllable once (phonetic spelling to force held vowels).
  3. per note: rubberband time-stretch to the note's duration AND formant-preserving pitch shift
     to the note's target in a single pass (rubberband takes tempo+pitch, so no atempo clamp).
  4. sum the four parts, light reverb, normalise.

Key choice matters: speech-derived voices sit near their speaking pitch (female ~200 Hz,
male ~120-160 Hz), so the arrangement is in D major - melody A3-A4 - which keeps every part
within roughly an octave of its voice's natural pitch. (The first attempt used G major,
melody D4-D5, pushing the female parts +19 semitones.)

Verification: the pitch of every placed note is re-measured (YIN) and compared with the
intended note (cents error); the final mix is transcribed back with STT.

Music: the "Happy Birthday" melody (Good Morning to All, 1893) is public domain; the 1935
Warner/Chappell claim was invalidated in 2016. The arrangement is built from diatonic
thirds/sixths plus an octave doubling, so every vertical interval is a consonance.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import urllib.request
from pathlib import Path

import numpy as np
from scipy.io import wavfile

API = "https://openrouter.ai/api/v1"
ROOT = Path(__file__).resolve().parent
WORK = ROOT / "audio" / "birthday"
RAW, PARTS_DIR = WORK / "raw", WORK / "parts"
ENV = Path(os.path.expanduser("~")) / "AppData/Local/hermes/profiles/engineer/.env"
MODEL = "elevenlabs/eleven-v4"

VOICES = {                       # part -> (premade voice, gender)
    "F1": ("sarah", "female"),   # melody
    "F2": ("jessica", "female"), # a diatonic 3rd below the melody
    "M1": ("george", "male"),    # a diatonic 6th below
    "M2": ("brian", "male"),     # an octave below (bass doubling of the melody)
}
PART_STEPS = {"F1": 0, "F2": -2, "M1": -5, "M2": -7}   # scale steps below the melody

BASE_MIDI = 50                                          # D3 -> song in D major
SCALE = [0, 2, 4, 5, 7, 9, 11]                          # D E F# G A B C#
SYLLABLES = {"hap": "hap", "pee": "pee", "burt": "burt", "day": "day",
             "too": "too", "yoo": "yoo", "deer": "deer", "bel": "bell"}

LINES = [
    [("hap", 4, .5), ("pee", 4, .5), ("burt", 5, 1), ("day", 4, 1), ("too", 7, 1), ("yoo", 6, 2)],
    [("hap", 4, .5), ("pee", 4, .5), ("burt", 5, 1), ("day", 4, 1), ("too", 8, 1), ("yoo", 7, 2)],
    [("hap", 4, .5), ("pee", 4, .5), ("burt", 11, 1), ("day", 9, 1), ("deer", 7, 1), ("bel", 6, 2)],
    [("hap", 10, .5), ("pee", 10, .5), ("burt", 9, 1), ("day", 7, 1), ("too", 8, 2), ("yoo", 7, 3)],
]
BPM = 96.0
BEAT = 60.0 / BPM
SR = 24000


def step_to_midi(step: int) -> int:
    octave, idx = divmod(step, 7)
    return BASE_MIDI + 12 * octave + SCALE[idx]


def midi_of(hz: float) -> float:
    return 69 + 12 * math.log2(hz / 440.0) if hz > 0 else 0.0


def api_key() -> str:
    return next(l.split("=", 1)[1].strip()
                for l in ENV.read_text(encoding="utf-8").splitlines()
                if l.startswith("OPENROUTER_API_KEY="))


def sh(cmd: list[str]) -> None:
    subprocess.run(cmd, capture_output=True, check=True, timeout=300)


def render(voice: str, text: str, tag: str) -> Path:
    RAW.mkdir(parents=True, exist_ok=True)
    out = RAW / f"{voice}-{tag}.mp3"
    if out.exists() and out.stat().st_size > 0:
        return out
    body = json.dumps({"model": MODEL, "input": text, "voice": voice,
                       "response_format": "mp3"}).encode()
    req = urllib.request.Request(f"{API}/audio/speech", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {api_key()}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        out.write_bytes(r.read())
    return out


def to_wav(src: Path, dst: Path) -> np.ndarray:
    sh(["ffmpeg", "-y", "-i", str(src), "-ac", "1", "-ar", str(SR), "-f", "wav", str(dst)])
    _, data = wavfile.read(dst)
    return data.astype(np.float64) / 32768.0


def _yin_one(seg: np.ndarray, sr: int, fmin: float, fmax: float, threshold: float) -> tuple[float, float]:
    """Single-window YIN -> (f0, clarity). Clarity = 1 - cmnd at the chosen lag."""
    seg = seg - seg.mean()
    if not np.any(seg):
        return 0.0, 0.0
    tau_min, tau_max = int(sr / fmax), min(int(sr / fmin), seg.size - 1)
    if tau_max <= tau_min:
        return 0.0, 0.0
    d = np.zeros(tau_max + 1)
    for tau in range(1, tau_max + 1):
        diff = seg[:seg.size - tau] - seg[tau:]
        d[tau] = float(np.dot(diff, diff))
    cum = np.cumsum(d[1:]) / np.arange(1, tau_max + 1)
    cmnd = np.ones(tau_max + 1)
    cmnd[1:] = d[1:] / (cum + 1e-12)
    # First LOCAL MINIMUM below threshold. Taking the first threshold crossing instead biases the
    # estimate (a 110 Hz test tone read 106.9 Hz, -49 cents); walking to the deepest point in the
    # valley biases the other way, onto the subharmonic.
    for tau in range(tau_min + 1, tau_max):
        if cmnd[tau] < threshold and cmnd[tau] <= cmnd[tau - 1] and cmnd[tau] <= cmnd[tau + 1]:
            a, b, c = cmnd[tau - 1], cmnd[tau], cmnd[tau + 1]
            denom = a - 2 * b + c
            refined = tau + (0.5 * (a - c) / denom if abs(denom) > 1e-12 else 0.0)
            return sr / refined, float(1 - b)
    tau = tau_min + int(np.argmin(cmnd[tau_min:tau_max + 1]))
    return (sr / tau, float(1 - cmnd[tau])) if cmnd[tau] < 0.6 else (0.0, 0.0)


def yin_f0(x: np.ndarray, sr: int = SR, fmin: float = 60.0, fmax: float = 1000.0,
           window: float = 0.05, threshold: float = 0.18, hop_ratio: float = 2) -> float:
    """Median YIN pitch over all windows of the signal.

    The first version used raw autocorrelation and reported harmonics/octave errors on short
    syllables (1128 Hz for a female "hap", 816 Hz for a male one), which would have produced
    wrong shift amounts.
    """
    x = np.asarray(x, dtype=np.float64)
    if x.size < sr // 20 or np.abs(x).max() < 1e-6:
        return 0.0
    x = x / np.abs(x).max()
    n = min(int(window * sr), x.size)
    hop = max(1, int(n / hop_ratio))
    est = []
    for i in range(0, max(1, x.size - n) + 1, hop):
        seg = x[i:i + n]
        if np.sqrt(np.mean(seg ** 2)) < 0.05:      # skip silence / very quiet frames
            continue
        f, clarity = _yin_one(seg, sr, fmin, fmax, threshold)
        if f > 0 and clarity > 0.7:
            est.append(f)
    return float(np.median(est)) if est else 0.0


def selftest() -> None:
    """The measurement is the foundation of every shift - check it on known tones first."""
    t = np.arange(int(0.5 * SR)) / SR
    for target in (110.0, 200.0, 440.0):
        tone = 0.6 * np.sin(2 * np.pi * target * t) * (1 + 0.02 * np.sin(2 * np.pi * 5 * t))
        got = yin_f0(tone)
        err = 1200 * math.log2(got / target) if got else float("inf")
        print(f"  selftest {target:6.1f} Hz -> {got:7.2f} Hz  ({err:+6.1f} cents)")
        if got <= 0 or abs(err) > 25:
            raise SystemExit(f"pitch estimator self-test failed at {target} Hz")


def shift_stretch(src: Path, dst: Path, target_seconds: float, semitones: float) -> None:
    """rubberband tempo (pitch-preserving stretch) + pitch (formant-preserving) in one pass."""
    dur = len(wavfile.read(src)[1]) / SR
    tempo = max(0.2, min(5.0, dur / target_seconds)) if target_seconds > 0 else 1.0
    sh(["ffmpeg", "-y", "-i", str(src), "-filter:a",
        f"rubberband=tempo={tempo:.5f}:pitch={2 ** (semitones / 12):.6f}:formant=preserved",
        "-ac", "1", "-ar", str(SR), "-f", "wav", str(dst)])


def voice_reference(voice: str, syllables: list[str], gender: str) -> tuple[float, float, dict]:
    """Robust natural-pitch estimate for one voice: median (in MIDI) over its syllable clips,
    with MAD-based outlier rejection, plus a plausibility guard by gender.

    A single sustained vowel was not reliable - jessica's "aaah" measured 63 Hz (a subharmonic),
    which would have shifted her whole part off by an octave. Using every syllable and taking the
    median in log/frequency space is stable, and disagreements between syllables are just the
    voice's natural intonation, which is worth keeping rather than flattening.
    """
    per: dict[str, float] = {}
    for syl in syllables:
        wav = RAW / f"{voice}-{syl}.wav"
        if not wav.exists():
            to_wav(render(voice, SYLLABLES[syl], syl), wav)
        hz = yin_f0(wavfile.read(wav)[1].astype(np.float64) / 32768.0)
        if hz > 0:
            per[syl] = hz
    if not per:
        raise SystemExit(f"no voiced syllables measured for {voice}")
    midis = np.array([midi_of(h) for h in per.values()])
    med = float(np.median(midis))
    keep = np.abs(midis - med) < 1.5          # drop octave/harmonic outliers
    if keep.sum() >= 3:
        midis = midis[keep]
        med = float(np.median(midis))
    lo, hi = (140.0, 320.0) if gender == "female" else (80.0, 210.0)
    hz = 440.0 * 2 ** ((med - 69) / 12)
    if not lo <= hz <= hi:
        raise SystemExit(f"implausible reference pitch for {voice} ({hz:.1f} Hz, {gender}): "
                         f"expected {lo}-{hi} Hz - measurement is wrong, not the voice")
    spread = float(np.std(midis) * 100)       # cents
    print(f"  reference {voice:9s} {hz:7.2f} Hz ({med:6.2f} MIDI) from {len(midis)} syllables, "
          f"intonation spread {spread:4.0f} cents")
    return med, spread, {k: round(v, 1) for k, v in per.items()}


def main() -> None:
    selftest()
    for d in (RAW, PARTS_DIR):
        d.mkdir(parents=True, exist_ok=True)

    # 1. robust reference pitch per voice, from all of its syllable clips
    references: dict[str, float] = {}
    for part, (voice, gender) in VOICES.items():
        references[voice] = voice_reference(voice, list(SYLLABLES), gender)[0]

    # 2. place every part on the note grid
    report, tracks = [], {}
    for part, (voice, gender) in VOICES.items():
        ref_midi = references[voice]
        # Per-syllable pitch: chords only lock in tune if every note is shifted from the pitch of
        # the clip it came from. The voice median is the fallback when a single syllable's own
        # measurement is unreliable (unvoiced, or implausibly far from the voice).
        syl_midi: dict[str, float] = {}
        for syl in SYLLABLES:
            wav = RAW / f"{voice}-{syl}.wav"
            if not wav.exists():
                to_wav(render(voice, SYLLABLES[syl], syl), wav)
            hz = yin_f0(wavfile.read(wav)[1].astype(np.float64) / 32768.0)
            m = midi_of(hz)
            syl_midi[syl] = m if (hz > 0 and abs(m - ref_midi) < 3.0) else ref_midi
        total = sum(b for line in LINES for _, _, b in line) * BEAT + 0.8
        buf = np.zeros(int(total * SR) + SR // 2)
        t, placed = 0.0, []
        for line in LINES:
            for syl, step, beats in line:
                src = RAW / f"{voice}-{syl}.wav"
                if not src.exists():
                    to_wav(render(voice, SYLLABLES[syl], syl), src)
                target = step_to_midi(step + PART_STEPS[part])
                semis = target - syl_midi[syl]
                dst = PARTS_DIR / f"{part}-{syl}-{target}.wav"
                shift_stretch(src, dst, beats * BEAT * 0.94, semis)
                seg = wavfile.read(dst)[1].astype(np.float64) / 32768.0
                i0 = int(t * SR)
                n = min(len(seg), len(buf) - i0 - 1)
                buf[i0:i0 + n] += seg[:n]
                measured = yin_f0(seg)
                placed.append({
                    "syllable": syl, "melody_midi": step_to_midi(step), "target_midi": target,
                    "shift_semitones": round(semis, 2), "measured_hz": round(measured, 1),
                    "measured_midi": round(midi_of(measured), 2) if measured else None,
                    "cents_error": round(100 * (midi_of(measured) - target), 1) if measured else None,
                })
                t += beats * BEAT
        tracks[part] = buf
        errs = [p["cents_error"] for p in placed if p["cents_error"] is not None]
        report.append({"part": part, "voice": voice, "gender": gender,
                       "reference_midi": round(references[voice], 2),
                       "reference_hz": round(440.0 * 2 ** ((references[voice] - 69) / 12), 1),
                       "notes": placed})
        print(f"  part {part} ({voice:7s}) {len(placed)} notes, unvoiced={len(placed) - len(errs)}, "
              f"mean|cents|={np.mean(np.abs(errs)) if errs else float('nan'):5.1f}  "
              f"worst={np.max(np.abs(errs)) if errs else float('nan'):5.1f}")

    # 3. mix: match RMS per part, gentle reverb, encode
    length = max(len(b) for b in tracks.values())
    mix = np.zeros(length)
    for buf in tracks.values():
        b = np.zeros(length); b[:len(buf)] = buf
        mix += b / (np.sqrt(np.mean(b ** 2)) + 1e-9)
    mix /= np.abs(mix).max() + 1e-9
    mix *= 0.92
    wet = WORK / "birthday-mix-raw.wav"
    wavfile.write(wet, SR, (mix * 32767).astype(np.int16))
    final = WORK / "happy-birthday-to-bel-4part-harmony.mp3"
    sh(["ffmpeg", "-y", "-i", str(wet), "-af", "aecho=0.8:0.6:55:0.25",
        "-b:a", "160k", str(final)])

    (ROOT / "results" / "birthday_harmony.json").write_text(json.dumps({
        "song": "Happy Birthday to Bel", "model": MODEL, "bpm": BPM, "key": "D major",
        "arrangement": {p: {"voice": v, "gender": g, "interval_steps": PART_STEPS[p],
                            "reference_hz": round(440.0 * 2 ** ((references[v] - 69) / 12), 1)}
                        for p, (v, g) in VOICES.items()},
        "output": str(final), "parts": report,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {final} ({final.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
