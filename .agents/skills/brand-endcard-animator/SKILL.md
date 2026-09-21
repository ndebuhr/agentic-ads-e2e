---
name: brand-endcard-animator
description: >-
  Generates broadcast-quality animated brand end-cards and logo pop-up motion graphics
  for video ads. Handles adaptive contrast backings (discs/halos), spring physics
  overshoot animations, and compositing over video clips.
---

# Brand Endcard Animator Skill

This skill provides a motion graphic pipeline for generating animated brand end-cards
and logo pop-ups. It solves the contrast and legibility problem when placing brand
logos over dynamic generative video footage.

Outputs go to `media/`.

```bash
E=.agents/skills/brand-endcard-animator/scripts/animate_endcard.py
```

## Workflow

### 1. Generate Animated Video Endcard
Composites an animated brand medallion over an existing video clip (e.g. Scene 4 of
a commercial spot) using spring physics easing (`scale = 1 + c3*(p-1)^3 + c1*(p-1)^2`):

```bash
uv run $E \
  --logo brand_assets/logo-white-1x1-transparent.png \
  --bg-video media/scene4_product.mp4 \
  --backing-color "#1c2938" \
  --size 490 \
  --start-time 0.83 \
  --anim-duration 0.50 \
  --out media/scene4_animated_endcard.mp4
```

### 2. Generate Static High-Contrast Medallion
Creates a clean, contrast-backed brand medallion PNG with a soft Gaussian blur drop shadow
for use across ads or print assets:

```bash
uv run $E \
  --logo brand_assets/logo-white-1x1-transparent.png \
  --make-badge \
  --backing-color "#1c2938" \
  --out media/brand_medallion.png
```

## Best Practices & Guidelines
* **Contrast Backing**: When overlaying white or light linework logos on variable natural
  backgrounds (rocks, foliage, mountains), always mount on a dark slate/brand disc
  (for example `#1c2938` for a navy brand) with a soft outer drop shadow to guarantee 100% contrast.
* **Timing & Overshoot**:
  * Trigger the pop-up entrance at $t \approx 0.8\text{s}$ into the final 4.0-second scene,
    coinciding with the brand name or URL mention in the voiceover (*"...at example.com"*).
  * An animation duration of 0.45s–0.55s with spring constant $c_1=1.6$ delivers an energetic,
    tactile bounce that feels polished and agency-grade.
* **Resolution & Sizing**:
  * For standard 720p footage, badge sizes of 460px–500px provide commanding visual
    presence without crowding screen edges.
  * When upscaling to 1080p Full HD, the medallion scales cleanly with Lanczos interpolation.
