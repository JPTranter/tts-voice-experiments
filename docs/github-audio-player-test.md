# GitHub audio-player test (temporary)

Testing which forms of embedding survive GitHub's markdown sanitizer, so the README catalog
links can be made to actually play. The raw CDN URL is
`https://raw.githubusercontent.com/JPTranter/tts-voice-experiments/master/audio/edge/01-aria.mp3`.

## A — markdown link to the blob page (what the README uses now)

[▶ A: blob link](audio/edge/01-aria.mp3)

## B — markdown link to the raw file

[▶ B: raw link](https://raw.githubusercontent.com/JPTranter/tts-voice-experiments/master/audio/edge/01-aria.mp3)

## C — HTML audio tag

<audio controls src="https://raw.githubusercontent.com/JPTranter/tts-voice-experiments/master/audio/edge/01-aria.mp3"></audio>

## D — HTML video tag pointed at the mp3

<video controls src="https://raw.githubusercontent.com/JPTranter/tts-voice-experiments/master/audio/edge/01-aria.mp3"></video>

## E — jsDelivr CDN in an audio tag

<audio controls src="https://cdn.jsdelivr.net/gh/JPTranter/tts-voice-experiments@master/audio/edge/01-aria.mp3"></audio>
