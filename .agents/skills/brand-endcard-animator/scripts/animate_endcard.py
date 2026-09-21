#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["Pillow>=10.0.0", "numpy>=1.24.0"]
# ///
"""Animated brand end-card and logo pop-up motion graphic generator.

Creates high-contrast, spring-eased animated brand medallions and call-to-action
end-cards over video scenes or static backgrounds.

Usage:
  # Composite animated medallion over an existing 4-second video clip:
  animate_endcard.py \
    --logo brand_assets/logo-white-1x1-transparent.png \
    --bg-video media/scene4_product.mp4 \
    --backing-color "#1c2938" \
    --size 490 \
    --start-time 0.83 \
    --anim-duration 0.50 \
    --out media/scene4_animated_endcard.mp4

  # Build standalone brand badge asset with shadow:
  animate_endcard.py \
    --logo brand_assets/logo-white-1x1-transparent.png \
    --make-badge \
    --backing-color "#1c2938" \
    --out media/brand_medallion.png
"""

import argparse
import math
import os
import subprocess
import sys
import tempfile
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

def create_contrast_medallion(logo_img, backing_color_hex="#1c2938", padding=20):
    """Mount a logo onto a clean circular brand backing disc with soft drop shadow."""
    w, h = logo_img.size
    dim = max(w, h) + padding * 2
    
    # 1. Circle backing disc
    disc = Image.new('RGBA', (dim, dim), (0, 0, 0, 0))
    draw = ImageDraw.Draw(disc)
    # Parse hex color
    hex_clean = backing_color_hex.lstrip('#')
    rgb = tuple(int(hex_clean[i:i+2], 16) for i in (0, 2, 4))
    draw.ellipse([padding, padding, dim - padding, dim - padding], fill=rgb + (255,))
    
    # 2. Paste logo centered
    lx = (dim - w) // 2
    ly = (dim - h) // 2
    disc.paste(logo_img, (lx, ly), logo_img)
    
    # 3. Add soft outer drop shadow
    shadow_margin = 40
    total_dim = dim + shadow_margin * 2
    shadow_canvas = Image.new('RGBA', (total_dim, total_dim), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow_canvas)
    s_box = [
        shadow_margin + padding + 4,
        shadow_margin + padding + 8,
        shadow_margin + dim - padding + 4,
        shadow_margin + dim - padding + 8
    ]
    sdraw.ellipse(s_box, fill=(0, 0, 0, 160))
    shadow_canvas = shadow_canvas.filter(ImageFilter.GaussianBlur(radius=18))
    
    # 4. Composite disc on top of shadow
    shadow_canvas.paste(disc, (shadow_margin, shadow_margin), disc)
    return shadow_canvas

def extract_video_frames(video_path, tmp_dir, target_fps=30, total_frames=120):
    """Extract frames from background video using ffmpeg."""
    os.makedirs(tmp_dir, exist_ok=True)
    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-r', str(target_fps),
        '-vframes', str(total_frames),
        os.path.join(tmp_dir, 'f_%03d.png')
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def main():
    parser = argparse.ArgumentParser(description="Generate animated brand logo endcard")
    parser.add_argument("--logo", required=True, help="Path to logo image (PNG/transparent)")
    parser.add_argument("--bg-video", help="Optional background video to composite over")
    parser.add_argument("--backing-color", default="#1c2938", help="Hex color for contrast disc backing")
    parser.add_argument("--size", type=int, default=490, help="Final badge diameter in 720p pixels (default 490)")
    parser.add_argument("--start-time", type=float, default=0.83, help="Timestamp in seconds when animation starts")
    parser.add_argument("--anim-duration", type=float, default=0.50, help="Duration of spring entrance in seconds")
    parser.add_argument("--fps", type=int, default=30, help="Target frame rate")
    parser.add_argument("--duration", type=float, default=4.0, help="Total clip duration in seconds")
    parser.add_argument("--make-badge", action="store_true", help="Only generate static contrast medallion")
    parser.add_argument("--out", required=True, help="Output file path (.mp4 or .png)")
    
    args = parser.parse_args()
    
    # 1. Load and clean logo
    raw_logo = Image.open(args.logo).convert('RGBA')
    # If logo has solid black background, strip it to transparent
    data = np.array(raw_logo)
    r, g, b, a = data[:, :, 0], data[:, :, 1], data[:, :, 2], data[:, :, 3]
    black_mask = (r < 25) & (g < 25) & (b < 25)
    data[:, :, 3] = np.where(black_mask, 0, a)
    cleaned_logo = Image.fromarray(data)
    
    # 2. Build Medallion
    badge = create_contrast_medallion(cleaned_logo, args.backing_color)
    
    if args.make_badge:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        badge.save(args.out)
        print(f"Saved brand contrast medallion to {args.out}")
        return

    if not args.bg_video:
        sys.exit("Video animation requires --bg-video or --make-badge")
        
    total_frames = int(args.duration * args.fps)
    start_frame = int(args.start_time * args.fps)
    anim_frames = max(1, int(args.anim_duration * args.fps))
    
    # Spring physics easing constants (overshoot)
    c1 = 1.6
    c3 = c1 + 1.0
    
    with tempfile.TemporaryDirectory() as tmp_in_dir, tempfile.TemporaryDirectory() as tmp_out_dir:
        print("Extracting background video frames...")
        extract_video_frames(args.bg_video, tmp_in_dir, target_fps=args.fps, total_frames=total_frames)
        
        print(f"Compositing spring animation ({total_frames} frames)...")
        for f in range(1, total_frames + 1):
            in_fn = os.path.join(tmp_in_dir, f"f_{f:03d}.png")
            if not os.path.exists(in_fn):
                break
            frame = Image.open(in_fn).convert('RGBA')
            cx = frame.width // 2
            cy = frame.height // 2
            
            idx = f - 1
            if idx >= start_frame:
                p = min(1.0, (idx - start_frame) / float(anim_frames))
                if p < 1.0:
                    scale = 1.0 + c3 * ((p - 1.0) ** 3) + c1 * ((p - 1.0) ** 2)
                    scale = max(0.05, scale)
                else:
                    scale = 1.0
                
                cur_size = int(args.size * scale)
                cur_badge = badge.resize((cur_size, cur_size), Image.Resampling.LANCZOS)
                
                # Opacity fade-in over first 5 frames
                alpha_mult = min(1.0, (idx - start_frame) / 5.0)
                if alpha_mult < 1.0:
                    br, bg, bb, ba = cur_badge.split()
                    ba = ba.point(lambda x: int(x * alpha_mult))
                    cur_badge.putalpha(ba)
                
                bx = cx - cur_size // 2
                by = cy - cur_size // 2
                frame.paste(cur_badge, (bx, by), cur_badge)
            
            out_fn = os.path.join(tmp_out_dir, f"c_{f:03d}.jpg")
            frame.convert('RGB').save(out_fn, quality=95)
            
        print("Encoding final animated endcard video...")
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        cmd = [
            'ffmpeg', '-y',
            '-r', str(args.fps),
            '-i', os.path.join(tmp_out_dir, 'c_%03d.jpg'),
            '-c:v', 'libx264', '-crf', '17', '-preset', 'slow', '-pix_fmt', 'yuv420p',
            args.out
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"Successfully generated animated endcard at {args.out}")

if __name__ == "__main__":
    main()
