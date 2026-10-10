#!/usr/bin/env python
"""Discovery steps used to find the voices in this experiment (all via OpenRouter).

1. Which models do speech at all:
     GET /api/v1/models?output_modalities=speech
2. Which voice ids does a model accept (authoritative list):
     models[].supported_voices  ->  for elevenlabs/* this is the 21 premade names;
                                    for microsoft/mai-voice-2.1 it is the full Azure
                                    (<locale>-<Name>:<Model>) list including ko-KR-*.
3. Validate a candidate voice without guessing (400 = not available to OpenRouter):
     POST /api/v1/audio/speech  {model, input, voice, response_format}  -> 200/400
4. ElevenLabs *library* (community) voices are not in supported_voices. They are
   addressable by their 20-char voice_id (a bogus 20-char id returns 400, so ids are
   validated, not silently ignored). The Korean library ids used here were taken from
   the public library payload served to https://kvid.ai/en/voice-library
   (GET /api/strapi-proxy/voice-generation/voice-library?page_size=48&sort_direction=desc,
   same-origin fetch, then filter labels.language == 'ko' && labels.gender == 'female').
"""
import json, os, urllib.request
from pathlib import Path

API = "https://openrouter.ai/api/v1"
ENV = Path(os.path.expanduser("~")) / "AppData/Local/hermes/profiles/engineer/.env"
KEY = next(l.split("=", 1)[1].strip() for l in ENV.read_text(encoding="utf-8").splitlines()
           if l.startswith("OPENROUTER_API_KEY="))


def get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {KEY}"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read())


if __name__ == "__main__":
    models = get(f"{API}/models?output_modalities=speech")["data"]
    out = []
    for m in models:
        voices = m.get("supported_voices") or []
        out.append({"id": m["id"], "name": m.get("name"), "voice_count": len(voices),
                    "korean_voices": [v for v in voices if v.startswith("ko-KR")]})
        print(f"{m['id']:45s} voices={len(voices):>4} korean={len(out[-1]['korean_voices'])}")
    Path("results/voice-catalog.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nwrote results/voice-catalog.json")
