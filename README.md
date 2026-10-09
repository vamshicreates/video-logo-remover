# Video Logo Remover Skill

A local Codex skill for detecting and removing visible overlay logos or watermarks from authorized video files. It preserves the original file and audio while producing a separate cleaned MP4.

## Capabilities

- Automatic stationary-logo detection across the full frame
- Explicit rectangle removal for maximum reliability
- Reference-template tracking for moving logos
- MP4, MOV, WebM, and other FFmpeg-readable inputs
- Detection diagnostics and JSON reports
- Local processing; videos are not uploaded

## Install

Download `video-logo-remover.skill` from the latest GitHub release and install it in Codex, or copy the `video-logo-remover` directory into your Codex skills directory.

## Use with Codex

```text
Use $video-logo-remover to remove the visible logo from /path/video.mp4 and save a clean copy.
```

## Direct commands

```bash
# Automatically locate a stationary logo
bash scripts/run.sh remove input.mp4 --output input-clean.mp4 --auto

# Remove a known region
bash scripts/run.sh remove input.mp4 --output input-clean.mp4 \
  --box "x,y,width,height"

# Track a moving logo using a tight reference crop
bash scripts/run.sh remove input.mp4 --output input-clean.mp4 \
  --template logo-crop.png

# Generate a contact sheet for inspection
bash scripts/run.sh inspect input.mp4 --output contact-sheet.jpg
```

## Requirements

- FFmpeg and FFprobe
- Python 3
- OpenCV and NumPy are installed into a private runtime automatically on the first automatic or template-tracking run.

## Limitations

The tool reconstructs pixels hidden by a logo through spatial inpainting. It cannot recover exact source pixels that were never present. Large logos, faces, detailed text, rapid motion, and complex backgrounds may show artifacts. Use only with media you own or are authorized to modify.
