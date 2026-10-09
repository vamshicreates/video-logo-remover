# Removal modes and tuning

## Box mode

Box mode uses FFmpeg's `delogo` filter and is the most predictable option for a stationary overlay.

Syntax:

```text
--box "x,y,width,height"
--box "x,y,width,height@start-end"
```

Coordinates are pixels measured from the top-left corner. Add 2–8 pixels around the visible logo so its antialiased edge is included. Several `--box` arguments are applied in sequence. A timed box is active only between the given timestamps.

Use `--padding N` to expand every box without recalculating coordinates. Large boxes produce softer and more noticeable reconstruction.

## Automatic mode

Automatic mode samples the whole video and looks for compact edges that remain stable across time. It is designed for a stationary overlay at any position. It can confuse genuinely static scene elements, burned-in captions, scoreboards, and UI overlays with a logo.

Outputs:

- `<output-stem>-detection.jpg`: representative frame with the proposed region.
- `<output-stem>-detection.json`: coordinates, confidence, and detector details.

When confidence is below the built-in threshold, the command stops with exit code 2 before modifying the video. Use the diagnostic to specify `--box`. `--force-auto` exists for reviewed diagnostics, not unattended use.

Useful tuning:

```text
--samples 32       More temporal samples for long or highly active videos.
--padding 6        Expand the detected rectangle.
--force-auto       Proceed after a human has reviewed the diagnostic.
--dry-run          Detect and write diagnostics without encoding a video.
```

## Template mode

Template mode performs edge-based template tracking. Use a tight native-resolution crop of the logo from the same video. Transparent PNG templates use their alpha channel as the removal mask; opaque templates remove the matched rectangle.

Useful tuning:

```text
--template-threshold 0.58   Lower only if a reviewed run misses the logo.
--search-margin 80          Increase when the logo moves quickly.
--inpaint-radius 5          Increase slightly for thicker marks.
```

Frames whose match score is below the threshold are left unchanged. This avoids removing unrelated content when the logo disappears.

## Quality and encoding

The output is H.264/AAC MP4 by default, with `yuv420p` and fast-start metadata for broad compatibility. Adjust `--crf`: lower values increase quality and file size. `18` is high quality; `20–23` is a smaller delivery file.

Logo removal is strongest when the overlay is small and surrounded by textured background. Review motion around the removed region, not just a single still frame.
