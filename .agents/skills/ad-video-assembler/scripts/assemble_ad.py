#!/usr/bin/env python3
"""Multi-scene video ad assembler with voiceover, music bed, ducking, and dual-resolution packaging.

Usage:
  # From JSON/YAML manifest:
  assemble_ad.py --manifest manifest.json --out-dir media/

  # Quick CLI assembly:
  assemble_ad.py \
    --scenes media/scene1.mp4 media/scene2.mp4 media/scene3.mp4 media/scene4.mp4 \
    --vo media/vo1.mp3 media/vo2.mp3 media/vo3.mp3 media/vo4.mp3 \
    --vo-delays 350 4100 8250 12200 \
    --music media/folk_instrumental.mp3 \
    --music-vol 0.20 \
    --name example-ad \
    --out-dir media/

  # Quick audio-only replacement (zero video re-encoding loss):
  assemble_ad.py --replace-audio --video media/ad-1080p.mp4 --audio media/new_mix.wav --out media/ad-1080p.mp4
"""

import argparse
import json
import os
import subprocess
import sys

def run_cmd(cmd, check=True):
    p = subprocess.run(cmd, shell=isinstance(cmd, str), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and p.returncode != 0:
        print(f"Error running command: {cmd}\nSTDERR: {p.stderr}", file=sys.stderr)
        sys.exit(p.returncode)
    return p

def get_media_info(path):
    cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'stream=codec_type,codec_name,width,height,r_frame_rate,duration,nb_frames',
        '-show_entries', 'format=duration,size,bit_rate',
        '-of', 'json', path
    ]
    p = run_cmd(cmd)
    data = json.loads(p.stdout)
    res = {"format": data.get("format", {})}
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and "video" not in res:
            res["video"] = s
        elif s.get("codec_type") == "audio" and "audio" not in res:
            res["audio"] = s
    return res

def replace_audio(video_path, audio_path, output_path):
    """Mux a new audio track into an existing video without re-encoding video."""
    video_path = os.path.abspath(video_path)
    audio_path = os.path.abspath(audio_path)
    output_path = os.path.abspath(output_path)
    
    tmp_out = output_path + ".tmp.mp4"
    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-i', audio_path,
        '-map', '0:v:0',
        '-map', '1:a:0',
        '-c:v', 'copy',
        '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
        tmp_out
    ]
    run_cmd(cmd)
    os.replace(tmp_out, output_path)
    print(f"Successfully replaced audio in {output_path}")

def build_audio_mix(music_path, vo_files, vo_delays_ms, total_duration_s, music_vol, vo_vol, out_audio_path):
    """Mix voiceover stems over a background music bed with timing offsets and fades."""
    inputs = ['-i', music_path]
    for vo in vo_files:
        inputs.extend(['-i', vo])
    
    filter_parts = []
    vo_labels = []
    for i, (vo, delay) in enumerate(zip(vo_files, vo_delays_ms)):
        idx = i + 1
        filter_parts.append(f"[{idx}:a]adelay={delay}|{delay},volume={vo_vol}[a{idx}]")
        vo_labels.append(f"[a{idx}]")
    
    filter_parts.append(f"{''.join(vo_labels)}amix=inputs={len(vo_files)}:dropout_transition=0:normalize=0[vo]")
    fade_start = max(0.0, total_duration_s - 1.5)
    filter_parts.append(
        f"[0:a]atrim=0:{total_duration_s},afade=t=in:ss=0:d=0.4,afade=t=out:st={fade_start}:d=1.5,volume={music_vol}[bgm]"
    )
    filter_parts.append("[bgm][vo]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]")
    
    cmd = ['ffmpeg', '-y'] + inputs + [
        '-filter_complex', ';'.join(filter_parts),
        '-map', '[aout]',
        '-ar', '48000', '-ac', '2',
        out_audio_path
    ]
    run_cmd(cmd)
    
    # Measure volume
    vcheck = run_cmd(f"ffmpeg -i {out_audio_path} -filter:a volumedetect -f null /dev/null", check=False)
    mean_vol, max_vol = "N/A", "N/A"
    for line in vcheck.stderr.splitlines():
        if "mean_volume:" in line: mean_vol = line.split("mean_volume:")[1].strip()
        if "max_volume:" in line: max_vol = line.split("max_volume:")[1].strip()
    print(f"Mixed master audio: {out_audio_path} (Mean: {mean_vol}, Max: {max_vol})")

def assemble_scenes(scene_files, scene_durations, fps=30):
    """Generate ffmpeg complex filter string to trim and concat scene video streams."""
    filter_parts = []
    scene_labels = []
    for i, (fn, dur) in enumerate(zip(scene_files, scene_durations)):
        filter_parts.append(f"[{i}:v]trim=0:{dur},setpts=PTS-STARTPTS,fps={fps}[v{i}]")
        scene_labels.append(f"[v{i}]")
    filter_parts.append(f"{''.join(scene_labels)}concat=n={len(scene_files)}:v=1:a=0[vout]")
    return ';'.join(filter_parts)

def main():
    parser = argparse.ArgumentParser(description="Assemble multi-scene video ad with audio bed & VO")
    parser.add_argument("--manifest", help="Path to JSON/YAML configuration manifest")
    parser.add_argument("--scenes", nargs="+", help="List of video scene files")
    parser.add_argument("--durations", nargs="+", type=float, help="Durations for each scene in seconds (default 4.0s each)")
    parser.add_argument("--vo", nargs="+", help="List of voiceover audio files")
    parser.add_argument("--vo-delays", nargs="+", type=int, help="Delay in milliseconds for each voiceover clip")
    parser.add_argument("--vo-vol", type=float, default=1.15, help="Voiceover volume multiplier (default 1.15)")
    parser.add_argument("--music", help="Background music audio file")
    parser.add_argument("--music-vol", type=float, default=0.20, help="Background music volume multiplier (default 0.20)")
    parser.add_argument("--name", default="commercial-ad", help="Base deliverable name")
    parser.add_argument("--out-dir", default="media", help="Output directory")
    parser.add_argument("--replace-audio", action="store_true", help="Quick mode: replace audio stream in an existing video")
    parser.add_argument("--video", help="Video file for --replace-audio mode")
    parser.add_argument("--audio", help="Audio file for --replace-audio mode")
    parser.add_argument("--out", help="Output file for --replace-audio mode")
    
    args = parser.parse_args()
    
    if args.replace_audio:
        if not args.video or not args.audio or not args.out:
            sys.exit("--replace-audio requires --video, --audio, and --out")
        replace_audio(args.video, args.audio, args.out)
        return

    os.makedirs(args.out_dir, exist_ok=True)
    scenes = args.scenes or []
    durations = args.durations or [4.0] * len(scenes)
    vo_files = args.vo or []
    vo_delays = args.vo_delays or [int(sum(durations[:i]) * 1000) for i in range(len(vo_files))]
    total_duration = sum(durations)
    
    # 1. Mix Audio
    out_audio = os.path.join(args.out_dir, f"{args.name}-audio-master.wav")
    if args.music and vo_files:
        build_audio_mix(args.music, vo_files, vo_delays, total_duration, args.music_vol, args.vo_vol, out_audio)
    
    # 2. Render 720p Ad
    out_720p = os.path.join(args.out_dir, f"{args.name}.mp4")
    scene_filter = assemble_scenes(scenes, durations, fps=30)
    
    inputs = []
    for s in scenes:
        inputs.extend(['-i', s])
    inputs.extend(['-i', out_audio])
    
    cmd_720p = ['ffmpeg', '-y'] + inputs + [
        '-filter_complex', scene_filter,
        '-map', '[vout]',
        '-map', f'{len(scenes)}:a',
        '-c:v', 'libx264', '-crf', '18', '-preset', 'slow', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
        out_720p
    ]
    print(f"Rendering 720p ad to {out_720p}...")
    run_cmd(cmd_720p)
    
    # 3. Upscale to 1080p Master with Lanczos
    out_1080p = os.path.join(args.out_dir, f"{args.name}-1080p.mp4")
    cmd_1080p = [
        'ffmpeg', '-y',
        '-i', out_720p,
        '-vf', 'scale=1920:1080:flags=lanczos',
        '-c:v', 'libx264', '-crf', '17', '-preset', 'slow', '-pix_fmt', 'yuv420p',
        '-c:a', 'copy',
        out_1080p
    ]
    print(f"Upscaling to 1080p Full HD master at {out_1080p}...")
    run_cmd(cmd_1080p)
    
    info_720 = get_media_info(out_720p)
    info_1080 = get_media_info(out_1080p)
    print("\nAssembly Complete!")
    print(f"  • 720p:  {out_720p} ({info_720['video']['width']}x{info_720['video']['height']}, {float(info_720['format']['duration']):.2f}s, {int(info_720['format']['size'])/1024/1024:.1f} MB)")
    print(f"  • 1080p: {out_1080p} ({info_1080['video']['width']}x{info_1080['video']['height']}, {float(info_1080['format']['duration']):.2f}s, {int(info_1080['format']['size'])/1024/1024:.1f} MB)")

if __name__ == "__main__":
    main()
