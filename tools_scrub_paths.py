#!/usr/bin/env python
"""One-off privacy scrub: remove the user's absolute home path from committed artifacts.

Committed files should carry repo-relative paths, not `C:\\Users\\<name>\\...` (privacy policy
mirrored from the sibling eClock repo). Built with chr(92) so no backslash escaping games."""
import os
from pathlib import Path

BS = chr(92)
# Derived at runtime, never hardcoded: a literal username here would defeat the purpose of the
# scrub (the script itself is committed). $SCRUB_USER overrides for other machines.
USER = os.environ.get("SCRUB_USER") or Path.home().name
DOUBLE = "C:" + BS * 2 + "Users" + BS * 2 + USER          # inside JSON strings
SINGLE = "C:" + BS + "Users" + BS + USER                  # plain text
FWD = "C:/Users/" + USER

SUBS = [
    (DOUBLE + BS * 2 + "Projects" + BS * 2 + "tts-voice-experiments" + BS * 2, ""),   # JSON -> relative
    (DOUBLE + BS * 2 + "Projects" + BS * 2 + "tts-voice-experiments", ""),
    (DOUBLE, "C:" + BS * 2 + "Users" + BS * 2 + "<user>"),
    (SINGLE, "C:" + BS + "Users" + BS + "<user>"),
    (FWD, "C:/Users/<user>"),
]

for name in ("results/birthday_harmony.json", "README.md", "audio/local/piper-amy-en.manifest.json",
             "audio/local/piper-kss-ko.manifest.json", "audio/local/sapi-zira-en.manifest.json"):
    p = Path(name)
    if not p.exists():
        continue
    text = p.read_text(encoding="utf-8")
    scrubbed = text
    for a, b in SUBS:
        scrubbed = scrubbed.replace(a, b)
    if scrubbed != text:
        p.write_text(scrubbed, encoding="utf-8")
        print(f"scrubbed {name}")
    print(f"  {name}: {text.count(USER)} -> {scrubbed.count(USER)} hit(s)")
