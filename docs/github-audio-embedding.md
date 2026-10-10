# How audio can (and cannot) be played from a GitHub README

Measured on this repository, 2026-10-10, because "just embed a player" does not work on GitHub and
the obvious alternatives silently download instead of playing.

## What each option actually does

| form | result | evidence |
|---|---|---|
| `<audio controls src="…">` in markdown | **stripped by GitHub** | rendered page contained 0 `audio` elements and no escaped literal either |
| `<video controls src="…mp3">` | **stripped by GitHub** | 0 `video` elements rendered |
| `<source>` inside either | stripped too | 0 `source` elements |
| `[…](audio/x.mp3)` relative link | opens the blob page, **no player** — only a Download button | blob page DOM had 0 `audio`/`video` elements; page reported the file size and a raw download link |
| `[…](https://raw.githubusercontent.com/…/x.mp3)` | **downloads** — the browser does not play it | response header `content-disposition: attachment; filename=…` |
| `[…](https://cdn.jsdelivr.net/gh/OWNER/REPO@BRANCH/x.mp3)` | **plays** — the browser opens its media player | response headers `content-type: audio/mpeg`, **no** `content-disposition`; navigating to it produced a media element with `controls: true` |
| a GitHub **Pages** page with `<audio controls>` | **plays**, and is the nicest reading experience | `docs/players.html`, one `<audio preload="none">` per sample |

## Consequences for this repository

1. The README links every sample at the **jsDelivr** URL, so a click starts playback instead of a
   download. The link's tooltip carries the repo path (`title="audio/…"`) so the file is still
   identifiable.
2. `docs/players.html` (published by GitHub Pages) is the "listening room": 108 native players in
   one page, grouped the same way as the README catalog. Regenerate it with
   `python tools_gen_players.py`.
3. Two dependencies are worth knowing: jsDelivr only serves **public** repositories, and its cache
   (`s-maxage=43200`, 12 h) can briefly lag a brand-new file. Pages needs neither to be re-enabled
   nor re-deployed by hand — pushing to `master` republishes.

## Reproducing the checks

```bash
curl -sI https://raw.githubusercontent.com/<owner>/<repo>/master/audio/edge/01-aria.mp3   # content-disposition: attachment
curl -sI https://cdn.jsdelivr.net/gh/<owner>/<repo>@master/audio/edge/01-aria.mp3          # audio/mpeg, no attachment
```
