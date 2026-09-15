---
name: genmedia-video-editing
description: >-
  Generates, extends, and edits ad videos with Veo 3.1, Gemini Omni, and
  ffmpeg via the local genmedia MCP servers (genmedia-veo, genmedia-omni,
  genmedia-avtool). Use this skill whenever the user asks to create, extend,
  edit, trim, resize, concatenate, or add audio to video creative.
---

# GenMedia Video Editing Skill

This skill provides a runbook for producing ad video with the `genmedia-*` MCP
servers. Veo and Omni are long-running models the hosted `geap-*` servers
cannot reach; these local servers wrap the polling so tools return finished
files.

| Server | Purpose |
|---|---|
| `genmedia-veo` | Veo 3.1 text/image/reference-to-video and video extension |
| `genmedia-omni` | Gemini Omni natural-language video editing |
| `genmedia-avtool` | ffmpeg compositing: trim, concat, reframe, overlay, audio |

If a server is missing from `call_mcp_tool`, run
`bash .agents/skills/genmedia-video-editing/scripts/setup.sh` and refresh the
MCP list. Outside Antigravity, `scripts/mcp_call.py <binary> <tool> '<json>'`
calls a tool over stdio.

## Workflow

### 1. Stage Inputs
* Veo and Omni read `gs://` URIs. Upload sources to
  `gs://$GENMEDIA_BUCKET/input/` with `gcloud storage cp`.
* Normalize external footage first; Veo fails with `code 14` on anything
  other than 24 fps H.264 with 48 kHz stereo AAC:
  ```bash
  ffmpeg -y -i src.mp4 -r 24 -c:v libx264 -pix_fmt yuv420p -c:a aac -ar 48000 -ac 2 src-veo.mp4
  ```

### 2. Generate or Extend (`genmedia-veo`)
* **New clip:** `veo_t2v` (`prompt`), `veo_i2v` (`image_uri`),
  `veo_reference_to_video` (`reference_image_uris`, up to 3 product shots).
  Params: `model`, `duration` (4, 6, 8), `aspect_ratio` (`16:9`, `9:16`),
  `num_videos`, `generate_audio`, `output_directory`, `output_filename`.
* **Extend:** `veo_extend_video` with `video_uri` and `prompt`. Adds 7 s per
  call; chain calls for longer. Pass `model: "veo-3.1-lite-generate-001"`
  explicitly, as it is the only model this server release allows for
  extension. For the fast or full model use
  `scripts/veo_extend_rest.py --video gs://... --prompt "..." --model veo-3.1-fast-generate-001 --download media --name NAME`.
* Models: `veo-3.1-generate-001` (final), `veo-3.1-fast-generate-001`
  (default), `veo-3.1-lite-generate-001` (drafts, cheapest).

### 3. Edit with Natural Language (`genmedia-omni`)
`omni_video_generation` with the source in `videos` and the change in
`prompt` (lighting, wardrobe, props, continuation). Optional `images`
(references), `sample_count`, `output_directory`, `output_filename`. A logged
`signBlob` permission error is harmless; the file is still saved.

### 4. Composite and Finish (`genmedia-avtool`)
Tools accept local absolute paths or `gs://` URIs plus `output_local_dir`,
`output_file_name`, `output_gcs_bucket`. Typical order: concat clips,
normalize loudness, reframe per placement, overlay logo/CTA.
* `ffmpeg_trim_media`: `start_time` / `duration` are numbers in seconds; add
  `re_encode: true` for frame-accurate cuts (default snaps to keyframes).
* `ffmpeg_concatenate_media_files`: `input_media_uris`.
* `ffmpeg_resize_reframe`: pass explicit `width` and `height` (720x1280 for
  Shorts, 1080x1080 for feed) with `reframe_mode`; aspect ratio alone gives
  odd sizes.
* `ffmpeg_overlay_image_on_video`: image is placed at native size at
  `x_coordinate` / `y_coordinate`; scale logos with ffmpeg first.
* `ffmpeg_normalize_loudness`, `ffmpeg_combine_audio_and_video`,
  `ffmpeg_get_media_info`, `ffmpeg_video_to_gif`.
* Anything else (text burn-in, speed ramps, fps changes): call `ffmpeg`
  directly.

### 5. Review & Deliver
1. Set `output_directory` / `output_local_dir` to the absolute path of the
   workspace `media/` directory (the servers are not started with a fixed
   `cwd`) so files land locally as well as in the bucket.
2. Verify duration, resolution, and audio with `ffmpeg_get_media_info`.
3. Link deliverables as `[name.mp4](file:///absolute/path/media/name.mp4)`
   and suggest placements (16:9 YouTube/PMax, 9:16 Shorts, 1:1 feed) with
   paired headlines.

## Notes
* Veo and Omni jobs take 1 to 5 minutes and bill per second of output. Draft
  with lite and `num_videos: 1`, then re-render finals.
* Veo errors surface only after the job completes, so fix inputs before
  calling rather than retrying.
* Keep generated MP4s in `media/` and the bucket, not in git.
