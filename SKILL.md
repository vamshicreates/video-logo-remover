---
name: video-logo-remover
description: Detect and remove visible overlay logos or watermarks from authorized local video files, preserving audio and the original file. Use for MP4, MOV, WebM, and other FFmpeg-readable videos; supports automatic stationary-logo detection, explicit regions, and tracked template removal.
---

# Video Logo Remover

Create a separate cleaned copy of a local video while preserving the source. Use only on media the user owns or is authorized to modify. Do not use this workflow to misrepresent provenance, evade attribution requirements, or alter protected media without permission.

## Run

The entrypoint is `scripts/run.sh`. Quote all paths.

```bash
# Automatic detection for a stationary overlay anywhere in the frame
bash scripts/run.sh remove "/path/input.mp4" --output "/path/input-clean.mp4" --auto

# Most reliable: remove one or more known rectangles
bash scripts/run.sh remove "/path/input.mp4" --output "/path/input-clean.mp4" \
  --box "x,y,width,height"

# Track a moving logo using a tight reference crop
bash scripts/run.sh remove "/path/input.mp4" --output "/path/input-clean.mp4" \
  --template "/path/logo-crop.png"
```

Automatic and template modes create a private Python runtime on first use and install OpenCV and NumPy. FFmpeg and FFprobe must already be available. The box mode only needs FFmpeg.

## Mode selection

- Prefer `--box` when the location is known or when accuracy matters. Repeat it for multiple logos. Add a time range with `--box "x,y,w,h@start-end"`, where times are seconds.
- Use `--auto` for a logo that remains fixed on screen. Detection searches the full frame, not only the corners. It writes a diagnostic image and JSON report next to the output.
- Use `--template` for a moving logo. Supply a tight crop of the logo at its native video size. A transparent PNG gives the best removal mask.
- Run `inspect` to generate a 12-frame contact sheet when coordinates are unclear:

```bash
bash scripts/run.sh inspect "/path/input.mp4" --output "/path/contact-sheet.jpg"
```

Read [references/modes.md](references/modes.md) when automatic detection is uncertain, the logo moves, or the result needs tuning.

## Operating rules

1. Resolve the input to an existing local file and choose a new output path. Never overwrite the source. Use `--overwrite` only for an already-generated destination after the user approves replacing it.
2. Default the output to `<stem>-clean.mp4` when the user does not name one.
3. For an unreviewed video, try `--auto` first. If it exits with code 2 or reports low confidence, inspect the diagnostic/contact sheet and use `--box`; do not force an uncertain detection silently.
4. Verify the output with FFprobe, confirm it contains a video stream, and report the output path plus the selected mode. Mention that reconstruction is inpainted and cannot recover pixels that were never present.
5. Keep diagnostic files unless the user asks to remove them; they explain what region was modified.

## Important limitation

General logos are opaque or partially opaque overlays. Unlike a fixed alpha watermark with a known mask, their hidden background pixels cannot be recovered exactly. This skill reconstructs those pixels spatially; complex motion, large logos, faces, text, or logos covering important detail may show artifacts. A clean source, alternate take, or licensed unwatermarked master remains the only exact solution.
