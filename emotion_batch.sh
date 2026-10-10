#!/usr/bin/env bash
# Re-render every voice from the earlier rounds using the emotion-marked scripts.
# Cloud voices only (ElevenLabs via OpenRouter, Gemini, Azure MAI); local engines live in
# local_tts.py. Runs are resumable - tts.py caches chunks by content hash.
set -u
P="$HOME/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe"
cd "$(dirname "$0")" || exit 1
mkdir -p audio/emotion

EN=samples/scifi-emotion-en.txt
KO=samples/scifi-emotion-ko.txt
V4=elevenlabs/eleven-v4
GEM=google/gemini-3.8-flash-tts
MAI=microsoft/mai-voice-2.1

run() {  # voice model script outfile [extra args...]
  local voice=$1 model=$2 script=$3 out=$4; shift 4
  echo "=== $voice ($model)"
  "$P" tts.py say --file "$script" --voice "$voice" --model "$model" --out "$out" "$@" 2>&1 \
    | grep -E "chars ->|instructions|warn|-> " || true
}

echo "---- English, emotion tags (eleven-v4)"
for v in sarah alice matilda jessica lily bella george adam daniel brian eric charlie; do
  run "$v" "$V4" "$EN" "audio/emotion/en-${v}-emotion.mp3"
done

echo "---- Korean, emotion tags (eleven-v4 library voices)"
run 1BZBO072RKJTzZcDjRox "$V4" "$KO" "audio/emotion/ko-sora-emotion.mp3"
run uyVNoMrnUku1dZyVEXwD "$V4" "$KO" "audio/emotion/ko-annakim-emotion.mp3"
run 0oqpliV6dVSr9XomngOW "$V4" "$KO" "audio/emotion/ko-jini-emotion.mp3"

echo "---- Korean via Gemini (markup becomes instructions)"
run Kore "$GEM" "$KO" "audio/emotion/ko-kore-emotion.mp3"

echo "---- Korean via Azure MAI (no verified emotion control: markup is stripped, plain delivery)"
run "ko-KR-Haena:MAI-Voice-2.1" "$MAI" "$KO" "audio/emotion/ko-haena-plain.mp3"

echo "---- 50% faster variants of the English set (local atempo, as before)"
for v in sarah alice matilda jessica lily bella george adam daniel brian eric charlie; do
  if [ -f "audio/emotion/en-${v}-emotion.mp3" ]; then
    "$P" tts.py speed "audio/emotion/en-${v}-emotion.mp3" --factor 1.5 2>&1 | tail -1
  fi
done
echo "BATCH DONE"
