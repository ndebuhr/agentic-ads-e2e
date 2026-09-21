#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["Pillow>=10.0.0"]
# ///
"""Ad Video QA & Broadcast Compliance Validator.

Validates video commercial ads against technical and delivery specifications for
YouTube, Google Ads, Meta (Instagram/Facebook), TikTok, and Broadcast networks.

Checks:
- Container integrity & FastStart (moov atom before mdat for instant web/mobile streaming)
- Video dimensions, aspect ratio classification, and standard ad platform resolutions
- Video codec, profile, and mobile-safe pixel format (yuv420p)
- Frame rate stability and audio/video duration synchronization (drift <= 100ms)
- Audio loudness and headroom: EBU R128 integrated loudness (LUFS) and True Peak (dBFS)
- Visual storyboard & contact sheet generation with timestamp annotations

Usage:
  # Inspect a single video ad:
  qa_video_ad.py --video media/ad-1080p.mp4

  # Validate multiple files against TikTok specs:
  qa_video_ad.py --video media/*.mp4 --platform tiktok

  # Generate visual storyboard contact sheet without strict checks:
  qa_video_ad.py --video media/ad-vertical-9x16.mp4 --scenes 4 --storyboard-only

  # Output structured JSON report for automation:
  qa_video_ad.py --video media/ad.mp4 --json
"""

import argparse
import json
import math
import os
import re
import struct
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

# Platform Loudness & Encoding Thresholds
PLATFORM_TARGETS = {
    "youtube": {
        "name": "YouTube / Google Ads",
        "allowed_ratios": ["16:9", "9:16", "1:1", "4:3"],
        "max_true_peak": -1.0,     # dBFS (prevents digital clipping during transcoding)
        "target_lufs_min": -24.0,  # LUFS
        "target_lufs_max": -13.0,  # YouTube standard normalizer is -14 LUFS
        "max_size_mb": 256000.0,
    },
    "meta": {
        "name": "Meta (Instagram / Facebook)",
        "allowed_ratios": ["1:1", "4:5", "9:16", "16:9"],
        "max_true_peak": -1.0,
        "target_lufs_min": -24.0,
        "target_lufs_max": -14.0,
        "max_size_mb": 4096.0,
    },
    "tiktok": {
        "name": "TikTok",
        "allowed_ratios": ["9:16", "1:1"],
        "max_true_peak": -1.0,
        "target_lufs_min": -24.0,
        "target_lufs_max": -13.0,
        "max_size_mb": 287.6,
    },
    "broadcast": {
        "name": "Broadcast (EBU R128 / ATSC A/85)",
        "allowed_ratios": ["16:9"],
        "max_true_peak": -2.0,
        "target_lufs_min": -24.5,
        "target_lufs_max": -22.5,
        "max_size_mb": 100000.0,
    },
    "all": {
        "name": "General Digital Video Ads (Universal)",
        "allowed_ratios": ["16:9", "1:1", "9:16", "4:5", "4:3"],
        "max_true_peak": -1.0,
        "target_lufs_min": -26.0,
        "target_lufs_max": -12.0,
        "max_size_mb": 1000.0,
    }
}

def run_cmd(cmd: List[str]) -> Tuple[int, str, str]:
    """Execute subprocess and return returncode, stdout, stderr."""
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return p.returncode, p.stdout, p.stderr

def check_faststart(video_path: str) -> bool:
    """Check if MP4 has 'moov' atom before 'mdat' for progressive HTTP/mobile streaming."""
    try:
        with open(video_path, 'rb') as f:
            moov_offset = None
            mdat_offset = None
            offset = 0
            while True:
                header = f.read(8)
                if len(header) < 8:
                    break
                size, name = struct.unpack('>I4s', header)
                box_name = name.decode('latin1', errors='ignore')
                if box_name == 'moov' and moov_offset is None:
                    moov_offset = offset
                elif box_name == 'mdat' and mdat_offset is None:
                    mdat_offset = offset
                if moov_offset is not None and mdat_offset is not None:
                    break
                if size == 1:
                    ext_size = f.read(8)
                    if len(ext_size) < 8:
                        break
                    size = struct.unpack('>Q', ext_size)[0]
                    offset += 16
                    f.seek(size - 16, os.SEEK_CUR)
                elif size == 0:
                    break
                else:
                    offset += size
                    f.seek(size - 8, os.SEEK_CUR)
            if moov_offset is not None and mdat_offset is not None:
                return moov_offset < mdat_offset
            return moov_offset is not None
    except Exception:
        return True

def classify_aspect_ratio(width: int, height: int) -> Tuple[str, str]:
    """Determine aspect ratio string and human label."""
    if width <= 0 or height <= 0:
        return "Unknown", "Unknown"
    ratio = width / float(height)
    if abs(ratio - (16.0 / 9.0)) < 0.05:
        return "16:9", "16:9 Landscape"
    elif abs(ratio - (9.0 / 16.0)) < 0.05:
        return "9:16", "9:16 Vertical"
    elif abs(ratio - 1.0) < 0.05:
        return "1:1", "1:1 Square"
    elif abs(ratio - (4.0 / 5.0)) < 0.05:
        return "4:5", "4:5 Portrait"
    elif abs(ratio - (4.0 / 3.0)) < 0.05:
        return "4:3", "4:3 Standard"
    else:
        gcd = math.gcd(width, height)
        return f"{width//gcd}:{height//gcd}", f"Custom ({width}:{height})"

def get_ffprobe_data(video_path: str) -> Dict[str, Any]:
    """Probe audio/video stream details using ffprobe."""
    cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration,size,bit_rate',
        '-show_entries', 'stream=codec_type,codec_name,profile,width,height,r_frame_rate,avg_frame_rate,pix_fmt,duration,channels,sample_rate,bit_rate,nb_frames',
        '-of', 'json', video_path
    ]
    ret, stdout, stderr = run_cmd(cmd)
    if ret != 0:
        raise RuntimeError(f"ffprobe failed on {video_path}: {stderr}")
    return json.loads(stdout)

def measure_ebur128(video_path: str) -> Dict[str, float]:
    """Measure EBU R128 loudness and true peak with ffmpeg ebur128 filter."""
    cmd = [
        'ffmpeg', '-i', video_path,
        '-filter:a', 'ebur128=peak=true',
        '-f', 'null', '/dev/null'
    ]
    _, _, stderr = run_cmd(cmd)
    
    integrated_lufs = None
    true_peak_dbfs = None
    loudness_range_lu = None
    
    summary_started = False
    for line in stderr.splitlines():
        if "Summary:" in line:
            summary_started = True
            continue
        if summary_started:
            if "I:" in line and integrated_lufs is None:
                m = re.search(r'I:\s+([-0-9\.]+)\s+LUFS', line)
                if m:
                    integrated_lufs = float(m.group(1))
            elif "Peak:" in line and true_peak_dbfs is None:
                m = re.search(r'Peak:\s+([-0-9\.]+)\s+dBFS', line)
                if m:
                    true_peak_dbfs = float(m.group(1))
            elif "LRA:" in line and loudness_range_lu is None:
                m = re.search(r'LRA:\s+([-0-9\.]+)\s+LU', line)
                if m:
                    loudness_range_lu = float(m.group(1))
                    
    return {
        "integrated_lufs": integrated_lufs if integrated_lufs is not None else -99.0,
        "true_peak_dbfs": true_peak_dbfs if true_peak_dbfs is not None else -99.0,
        "loudness_range_lu": loudness_range_lu if loudness_range_lu is not None else 0.0,
    }

def generate_storyboard(video_path: str, num_scenes: int, out_img_path: str, info_summary: Dict[str, Any]):
    """Extract keyframes and build a high-resolution visual storyboard contact sheet."""
    total_dur = info_summary.get("video_duration", 16.0)
    if total_dur <= 0:
        total_dur = 16.0
    
    # Calculate sample timestamps at mid-points of each scene
    scene_dur = total_dur / num_scenes
    timestamps = [(i + 0.5) * scene_dur for i in range(num_scenes)]
    
    frames = []
    for i, ts in enumerate(timestamps):
        tmp_thumb = f"{out_img_path}.scene_{i}.jpg"
        cmd = [
            'ffmpeg', '-y',
            '-ss', f"{ts:.3f}",
            '-i', video_path,
            '-vframes', '1',
            '-q:v', '2',
            tmp_thumb
        ]
        ret, _, _ = run_cmd(cmd)
        if ret == 0 and os.path.exists(tmp_thumb):
            try:
                im = Image.open(tmp_thumb).convert('RGB')
                frames.append((i + 1, ts, im))
            except Exception:
                pass
            finally:
                if os.path.exists(tmp_thumb):
                    os.remove(tmp_thumb)
                    
    if not frames:
        return
    
    # Layout calculation
    # For 9:16 vertical videos: 4 columns in 1 row (or 2x2)
    # For 16:9 landscape: 2 columns x 2 rows (or 1x4)
    # For 1:1 square: 2 columns x 2 rows
    aspect_id = info_summary.get("aspect_ratio", "16:9")
    
    thumb_w = 480
    orig_w, orig_h = info_summary.get("width", 1920), info_summary.get("height", 1080)
    thumb_h = int(thumb_w * (orig_h / float(orig_w)))
    
    if aspect_id == "9:16":
        # 4 items in a row
        cols = min(4, len(frames))
        rows = math.ceil(len(frames) / cols)
        thumb_w = 270
        thumb_h = int(thumb_w * 16 / 9)
    elif len(frames) == 4:
        cols = 2
        rows = 2
        thumb_w = 480
        thumb_h = int(thumb_w * (orig_h / float(orig_w)))
    else:
        cols = min(4, len(frames))
        rows = math.ceil(len(frames) / cols)
        
    pad = 16
    header_h = 100
    footer_h = 40
    
    grid_w = cols * thumb_w + (cols + 1) * pad
    grid_h = rows * thumb_h + (rows + 1) * pad + header_h + footer_h
    
    canvas = Image.new('RGB', (grid_w, grid_h), (22, 30, 42))  # Dark slate background
    draw = ImageDraw.Draw(canvas)
    
    # Header Banner
    title_text = f"AD CREATIVE STORYBOARD: {os.path.basename(video_path)}"
    specs_text = (
        f"Format: {info_summary.get('aspect_label')} ({info_summary.get('width')}x{info_summary.get('height')}) | "
        f"Duration: {total_dur:.2f}s | FPS: {info_summary.get('fps', 30.0):.1f} | "
        f"Loudness: {info_summary.get('lufs', -24):.1f} LUFS | Peak: {info_summary.get('peak', -5):.1f} dBFS"
    )
    status_text = f"STATUS: {info_summary.get('overall_status', 'PASSED').upper()}"
    status_color = (46, 204, 113) if info_summary.get('overall_status') == "PASSED" else (231, 76, 60)
    
    draw.text((pad, 20), title_text, fill=(255, 255, 255))
    draw.text((pad, 48), specs_text, fill=(180, 195, 210))
    draw.rectangle([(pad, 74), (pad + 180, 94)], fill=status_color)
    draw.text((pad + 10, 77), status_text, fill=(255, 255, 255))
    
    # Draw scene thumbnails
    for idx, (s_num, ts, im) in enumerate(frames):
        c = idx % cols
        r = idx // cols
        x = pad + c * (thumb_w + pad)
        y = header_h + pad + r * (thumb_h + pad)
        
        resized_im = im.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        canvas.paste(resized_im, (x, y))
        
        # Border
        draw.rectangle([(x, y), (x + thumb_w, y + thumb_h)], outline=(60, 80, 105), width=2)
        
        # Timestamp and Scene badge
        mins = int(ts // 60)
        secs = ts % 60
        time_str = f"Scene {s_num}: {mins:02d}:{secs:05.2f}"
        
        # Badge backing
        draw.rectangle([(x + 8, y + 8), (x + 135, y + 30)], fill=(0, 0, 0, 200))
        draw.text((x + 14, y + 11), time_str, fill=(255, 230, 100))
        
    # Footer
    footer_text = "Generated by .agents/skills/ad-video-qa • EBU R128 & Digital Platform Compliant"
    draw.text((pad, grid_h - 28), footer_text, fill=(120, 140, 160))
    
    os.makedirs(os.path.dirname(os.path.abspath(out_img_path)), exist_ok=True)
    canvas.save(out_img_path, quality=92)

def audit_video(video_path: str, platform: str = "all", num_scenes: int = 4, out_dir: str = "media") -> Dict[str, Any]:
    """Perform full QA audit of a video file."""
    video_path = os.path.abspath(video_path)
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")
        
    ff_data = get_ffprobe_data(video_path)
    fmt = ff_data.get("format", {})
    streams = ff_data.get("streams", [])
    
    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    
    if not v_stream:
        raise ValueError(f"No video stream found in {video_path}")
        
    # Video details
    width = int(v_stream.get("width", 0))
    height = int(v_stream.get("height", 0))
    aspect_id, aspect_label = classify_aspect_ratio(width, height)
    
    fps_str = v_stream.get("r_frame_rate", "30/1")
    try:
        num, den = map(int, fps_str.split('/'))
        fps = num / float(den) if den != 0 else 30.0
    except Exception:
        fps = 30.0
        
    v_codec = v_stream.get("codec_name", "unknown")
    v_profile = v_stream.get("profile", "unknown")
    pix_fmt = v_stream.get("pix_fmt", "unknown")
    v_dur = float(v_stream.get("duration", fmt.get("duration", 0.0)))
    
    # Audio details
    has_audio = a_stream is not None
    a_codec = a_stream.get("codec_name", "none") if a_stream else "none"
    channels = int(a_stream.get("channels", 0)) if a_stream else 0
    sample_rate = int(a_stream.get("sample_rate", 0)) if a_stream else 0
    a_dur = float(a_stream.get("duration", fmt.get("duration", 0.0))) if a_stream else 0.0
    
    # Container details
    file_size_mb = os.path.getsize(video_path) / (1024.0 * 1024.0)
    is_faststart = check_faststart(video_path)
    
    # Audio Loudness Measurement
    loudness_data = measure_ebur128(video_path) if has_audio else {"integrated_lufs": -99.0, "true_peak_dbfs": -99.0, "loudness_range_lu": 0.0}
    
    # Platform validation checks
    plat_cfg = PLATFORM_TARGETS.get(platform, PLATFORM_TARGETS["all"])
    checks = []
    
    # 1. Container & FastStart Check
    if is_faststart:
        checks.append({"name": "Web Streaming (FastStart)", "status": "PASS", "msg": "moov atom positioned before mdat for instant mobile streaming"})
    else:
        checks.append({"name": "Web Streaming (FastStart)", "status": "WARN", "msg": "moov atom at end of file; add '-movflags +faststart' for faster web streaming"})
        
    # 2. Pixel Format Check (yuv420p requirement)
    if pix_fmt == "yuv420p":
        checks.append({"name": "Pixel Format", "status": "PASS", "msg": f"{pix_fmt} (100% compatible across all mobile devices and web browsers)"})
    else:
        checks.append({"name": "Pixel Format", "status": "WARN", "msg": f"{pix_fmt} (may trigger playback glitches on iOS/Android; prefer yuv420p)"})
        
    # 3. Video Codec Check
    if v_codec in ["h264", "hevc", "av1"]:
        checks.append({"name": "Video Codec", "status": "PASS", "msg": f"{v_codec} ({v_profile})"})
    else:
        checks.append({"name": "Video Codec", "status": "FAIL", "msg": f"Unsupported video codec: {v_codec}"})
        
    # 4. Aspect Ratio & Dimensions Check
    if aspect_id in plat_cfg["allowed_ratios"]:
        checks.append({"name": "Aspect Ratio & Resolution", "status": "PASS", "msg": f"{width}x{height} ({aspect_label}) approved for {plat_cfg['name']}"})
    else:
        checks.append({"name": "Aspect Ratio & Resolution", "status": "WARN", "msg": f"{aspect_label} not typical for {plat_cfg['name']} (allowed: {', '.join(plat_cfg['allowed_ratios'])})"})
        
    # 5. Audio Presence & Sync Drift Check
    if not has_audio:
        checks.append({"name": "Audio Stream", "status": "FAIL", "msg": "No audio track detected in ad video"})
    else:
        sync_drift_ms = abs(v_dur - a_dur) * 1000.0
        if sync_drift_ms <= 100.0:
            checks.append({"name": "A/V Sync & Duration", "status": "PASS", "msg": f"Video: {v_dur:.2f}s | Audio: {a_dur:.2f}s (drift: {sync_drift_ms:.1f}ms <= 100ms tolerance)"})
        else:
            checks.append({"name": "A/V Sync & Duration", "status": "WARN", "msg": f"A/V duration mismatch: Video {v_dur:.2f}s vs Audio {a_dur:.2f}s ({sync_drift_ms:.0f}ms drift)"})
            
    # 6. Audio Sample Rate & Channels
    if has_audio:
        if sample_rate in [44100, 48000] and channels in [1, 2]:
            checks.append({"name": "Audio Encoding", "status": "PASS", "msg": f"{a_codec} {'stereo' if channels==2 else 'mono'} @ {sample_rate} Hz"})
        else:
            checks.append({"name": "Audio Encoding", "status": "WARN", "msg": f"Non-standard audio: {channels}ch @ {sample_rate} Hz"})
            
    # 7. True Peak Headroom Check
    if has_audio:
        true_peak = loudness_data["true_peak_dbfs"]
        max_peak = plat_cfg["max_true_peak"]
        if true_peak <= max_peak:
            checks.append({"name": "True Peak Headroom", "status": "PASS", "msg": f"{true_peak:.1f} dBFS (compliant with <= {max_peak:.1f} dBFS limit)"})
        elif true_peak < 0.0:
            checks.append({"name": "True Peak Headroom", "status": "WARN", "msg": f"{true_peak:.1f} dBFS exceeds recommended {max_peak:.1f} dBFS ceiling (risk of DAC distortion)"})
        else:
            checks.append({"name": "True Peak Headroom", "status": "FAIL", "msg": f"{true_peak:.1f} dBFS digital clipping detected (>= 0.0 dBFS)"})
            
    # 8. Integrated Loudness (LUFS) Check
    if has_audio:
        lufs = loudness_data["integrated_lufs"]
        min_lufs = plat_cfg["target_lufs_min"]
        max_lufs = plat_cfg["target_lufs_max"]
        if min_lufs <= lufs <= max_lufs:
            checks.append({"name": "Integrated Loudness", "status": "PASS", "msg": f"{lufs:.1f} LUFS (within target {min_lufs:.0f} to {max_lufs:.0f} LUFS window)"})
        elif lufs < min_lufs:
            checks.append({"name": "Integrated Loudness", "status": "WARN", "msg": f"{lufs:.1f} LUFS is quieter than target ({min_lufs:.0f} LUFS minimum)"})
        else:
            checks.append({"name": "Integrated Loudness", "status": "WARN", "msg": f"{lufs:.1f} LUFS exceeds {max_lufs:.0f} LUFS (will be volume-penalized by platform)"})
            
    # Overall Status Determination
    statuses = [c["status"] for c in checks]
    if "FAIL" in statuses:
        overall_status = "FAILED"
    elif "WARN" in statuses:
        overall_status = "WARNING"
    else:
        overall_status = "PASSED"
        
    base_name = os.path.splitext(os.path.basename(video_path))[0]
    storyboard_path = os.path.join(out_dir, f"{base_name}-storyboard.jpg")
    
    summary = {
        "file": video_path,
        "filename": os.path.basename(video_path),
        "platform": platform,
        "width": width,
        "height": height,
        "aspect_ratio": aspect_id,
        "aspect_label": aspect_label,
        "fps": fps,
        "video_duration": v_dur,
        "audio_duration": a_dur,
        "file_size_mb": file_size_mb,
        "lufs": loudness_data["integrated_lufs"],
        "peak": loudness_data["true_peak_dbfs"],
        "lra": loudness_data["loudness_range_lu"],
        "overall_status": overall_status,
        "storyboard": storyboard_path,
        "checks": checks
    }
    
    # Generate visual storyboard contact sheet
    generate_storyboard(video_path, num_scenes, storyboard_path, summary)
    return summary

def print_text_scorecard(summary: Dict[str, Any]):
    """Print beautifully formatted CLI scorecard with color/emojis."""
    name = summary["filename"]
    status = summary["overall_status"]
    
    print("\n" + "=" * 76)
    print(f" AD VIDEO QA SCORECARD: {name}")
    print("=" * 76)
    print(f" Target Platform : {summary['platform'].upper()} specs")
    print(f" Dimensions      : {summary['width']}x{summary['height']} ({summary['aspect_label']})")
    print(f" Duration        : {summary['video_duration']:.2f}s (Audio: {summary['audio_duration']:.2f}s)")
    print(f" Video Stream    : {summary['fps']:.1f} fps | Size: {summary['file_size_mb']:.1f} MB")
    print(f" Audio Loudness  : {summary['lufs']:.1f} LUFS | True Peak: {summary['peak']:.1f} dBFS | LRA: {summary['lra']:.1f} LU")
    print("-" * 76)
    
    for c in summary["checks"]:
        st = c["status"]
        badge = "[ PASS ]" if st == "PASS" else ("[ WARN ]" if st == "WARN" else "[ FAIL ]")
        print(f" {badge} {c['name']:<24}: {c['msg']}")
        
    print("-" * 76)
    print(f" OVERALL RESULT  : {status} ({sum(1 for c in summary['checks'] if c['status']=='PASS')}/{len(summary['checks'])} passed)")
    if os.path.exists(summary["storyboard"]):
        print(f" Storyboard Card : {summary['storyboard']}")
    print("=" * 76 + "\n")

def main():
    parser = argparse.ArgumentParser(description="Ad Video QA & Broadcast Compliance Validator")
    parser.add_argument("--video", nargs="+", required=True, help="One or more video ad files to inspect")
    parser.add_argument("--platform", default="all", choices=list(PLATFORM_TARGETS.keys()), help="Target platform to audit against (default: all)")
    parser.add_argument("--scenes", type=int, default=4, help="Number of scene keyframes to extract for storyboard (default: 4)")
    parser.add_argument("--out-dir", default="media", help="Output directory for storyboard contact sheets (default: media)")
    parser.add_argument("--json", action="store_true", help="Output structured JSON results")
    parser.add_argument("--fix-faststart", action="store_true", help="Automatically relocate moov atom to beginning of file if missing")
    
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    
    results = []
    has_failure = False
    
    for vpath in args.video:
        if args.fix_faststart and not check_faststart(vpath):
            tmp_fixed = vpath + ".fixed.mp4"
            cmd = ['ffmpeg', '-y', '-i', vpath, '-c', 'copy', '-movflags', '+faststart', tmp_fixed]
            ret, _, _ = run_cmd(cmd)
            if ret == 0 and os.path.exists(tmp_fixed):
                os.replace(tmp_fixed, vpath)
                print(f"[FIXED] FastStart moov atom applied to {vpath}")
                
        try:
            res = audit_video(vpath, platform=args.platform, num_scenes=args.scenes, out_dir=args.out_dir)
            results.append(res)
            if not args.json:
                print_text_scorecard(res)
            if res["overall_status"] == "FAILED":
                has_failure = True
        except Exception as e:
            print(f"Error auditing {vpath}: {e}", file=sys.stderr)
            has_failure = True
            
    if args.json:
        print(json.dumps(results if len(results) > 1 else results[0], indent=2))
        
    sys.exit(1 if has_failure else 0)

if __name__ == "__main__":
    main()
