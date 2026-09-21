---
name: ad-video-assembler
description: >-
  Assembles multi-scene video commercial ads from raw video clips, voiceover stems,
  and background music beds. Automates millisecond audio alignment, vocal ducking,
  lossless stream copying, and multi-resolution (1080p & 720p) packaging.
---

# Ad Video Assembler Skill

This skill provides a battle-tested pipeline for assembling complete commercial ads
from individual scene clips (e.g. from Veo or runway), separate voiceover lines
(e.g. from ElevenLabs), and instrumental music beds.

Outputs go to `media/`.

```bash
A=.agents/skills/ad-video-assembler/scripts/assemble_ad.py
```

## Workflow

### 1. Assemble Full Commercial Spot
Takes raw video clips, trims each to the target scene duration, synchronizes voiceover
lines with scene onsets, ducks background music under vocals, and exports both 720p and
1080p Full HD master videos:

```bash
$A \
  --scenes media/scene1.mp4 media/scene2.mp4 media/scene3.mp4 media/scene4.mp4 \
  --durations 4.0 4.0 4.0 4.0 \
  --vo media/vo1.mp3 media/vo2.mp3 media/vo3.mp3 media/vo4.mp3 \
  --vo-delays 350 4100 8250 12200 \
  --music media/folk_instrumental.mp3 \
  --music-vol 0.20 \
  --vo-vol 1.15 \
  --name example-ad \
  --out-dir media/
```

### 2. Lossless Audio Stream Replacement
When updating voiceover lines, fixing a script word, or rebalancing audio, never
re-encode the entire video stream. Use `--replace-audio` to swap the audio track
losslessly in under one second with zero generational video compression loss:

```bash
$A --replace-audio \
  --video media/example-ad-1080p.mp4 \
  --audio media/new_audio_mix.wav \
  --out media/example-ad-1080p.mp4
```

### 3. Timing & Pacing Guidelines
* **Scene Onset Delays**: Allow 300–400ms at the beginning of Scene 1 for the music bed
  to establish the scene before voiceover begins.
* **Scene Transitions**: Ensure voiceover lines end at least 150–250ms before the next
  scene cut to give viewers cognitive breathing room.
* **Audio Ducking**: Keep instrumental music beds at `volume=0.18` to `volume=0.22`
  (-14 dB to -15 dB relative to vocals) to prevent music from muddying the narration.
* **Master Headroom**: Maintain master audio peaks between -4 dB and -6 dB with mean
  loudness around -20 dB to -24 dB to comply with YouTube/broadcast loudness targets.
