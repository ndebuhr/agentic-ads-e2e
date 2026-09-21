---
name: ad-video-qa
description: >-
  Validates video ads for broadcast and digital platform compliance (YouTube/Google Ads,
  Meta, TikTok, Broadcast). Checks moov atom FastStart, pixel format (yuv420p),
  video/audio duration sync, EBU R128 integrated loudness (-24 to -13 LUFS), and true peak
  headroom (<= -1.0 dBFS), while generating automated visual storyboard contact sheets.
---

# Ad Video QA & Broadcast Compliance Skill

This skill provides an automated quality assurance and broadcast compliance pipeline for commercial video ads. It verifies technical encoding specs, audio loudness, streaming readiness, and visual layout before ad creative is published to ad platforms or delivered to clients.

Outputs go to `media/`.

```bash
Q=.agents/skills/ad-video-qa/scripts/qa_video_ad.py
```

## Features

1. **EBU R128 Audio Compliance**:
   - Accurately measures Integrated Loudness (`LUFS`), Loudness Range (`LRA LU`), and True Peak (`dBFS`) via ffmpeg's ITU-R BS.1770 filter.
   - Verifies digital headroom ($\le -1.0\text{ dBFS}$) to eliminate inter-sample clipping during platform transcoding.
   - Enforces target loudness windows (e.g. $-14$ to $-24\text{ LUFS}$ for digital, $-23 \pm 1\text{ LUFS}$ for television).

2. **A/V Sync & Duration Drift**:
   - Detects duration mismatches between video and audio streams (flags drift $> 100\text{ms}$).

3. **Web & Mobile Streaming Optimization**:
   - Checks that the MP4 `moov` atom is positioned at the start of the file (`FastStart`) so video streams instantly without downloading the entire file.
   - Auto-remedies unoptimized files in-place with `--fix-faststart`.

4. **Encoding & Compatibility Guardrails**:
   - Confirms mobile-safe `yuv420p` pixel format (prevents playback errors and color shifts on iOS Safari / Android WebViews).
   - Validates standard ad aspect ratios ($16:9$, $1:1$, $9:16$, $4:5$) and resolutions.

5. **Visual Storyboard Contact Sheets**:
   - Extracts mid-point keyframes from each scene and renders a branded, high-resolution contact sheet image annotated with timestamps, format specs, and a Pass/Fail scorecard badge.

---

## Workflow & Usage

### 1. Universal Video Ad Audit
Audit any video ad against general digital ad standards and generate a visual contact sheet:

```bash
uv run $Q --video media/example-ad-1080p.mp4
```

### 2. Platform-Specific Compliance
Validate against strict platform guidelines for YouTube, Meta, or TikTok:

```bash
# Audit against YouTube & Google Ads specs:
uv run $Q --video media/ad-1080p.mp4 --platform youtube

# Audit against Meta (Instagram/Facebook) specs:
uv run $Q --video media/ad-square-1x1.mp4 --platform meta

# Audit against TikTok (Vertical 9:16) specs:
uv run $Q --video media/ad-vertical-9x16.mp4 --platform tiktok
```

### 3. Auto-Fix Streaming with FastStart
If an MP4 was rendered without `+faststart` (moov atom at EOF), pass `--fix-faststart` to relocate it without re-encoding video or audio:

```bash
uv run $Q --video media/ad-master.mp4 --fix-faststart
```

### 4. Batch Audit & JSON Output
Audit all deliverables in a folder and return machine-readable JSON for CI/CD or agent pipelines:

```bash
uv run $Q --video media/*.mp4 --json > media/qa_report.json
```

---

## Platform Compliance Reference

| Platform | Recommended Ratio | Resolutions | Max True Peak | Target Loudness | Max File Size |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **YouTube / Google Ads** | 16:9, 9:16, 1:1 | $1920\times 1080$, $1080\times 1920$, $1080\times 1080$ | $\le -1.0\text{ dBFS}$ | $-14$ to $-24\text{ LUFS}$ | $256\text{ GB}$ |
| **Meta (IG / FB)** | 1:1, 4:5, 9:16, 16:9 | $1080\times 1080$, $1080\times 1350$, $1080\times 1920$ | $\le -1.0\text{ dBFS}$ | $-14$ to $-24\text{ LUFS}$ | $4\text{ GB}$ |
| **TikTok** | 9:16 (preferred), 1:1 | $1080\times 1920$, $720\times 1280$ | $\le -1.0\text{ dBFS}$ | $-13$ to $-24\text{ LUFS}$ | $287.6\text{ MB}$ |
| **Broadcast TV** | 16:9 | $1920\times 1080$ | $\le -2.0\text{ dBFS}$ | $-23.0 \pm 1.0\text{ LUFS}$ (EBU) / $-24.0 \pm 1.0$ (ATSC) | Unlimited |

---

## Quality Checklist

When reviewing generated storyboard cards:
- [ ] **Scene 1**: Establishing shot clearly introduces environment and hooks viewer within $0.5\text{s}$.
- [ ] **Scene 2**: Hero character/subject has ample headroom and side margins; no squeezed or bloated framing.
- [ ] **Scene 3**: Real, authentic product appearance without AI hallucination artifacts.
- [ ] **Scene 4**: High-contrast brand end-card with mobile UI safe margins ($\ge 180\text{px}$ clearance on 9:16 vertical).
