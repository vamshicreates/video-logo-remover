#!/usr/bin/env python3
"""Remove small visible overlay logos from authorized local videos."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, NoReturn


EXIT_LOW_CONFIDENCE = 2


def fail(message: str, code: int = 1) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


def require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        fail(f"{name} is required but was not found on PATH")
    return path


def require_cv() -> tuple[Any, Any]:
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        fail("automatic/template mode needs OpenCV and NumPy; run scripts/run.sh setup")
    return cv2, np


def run_checked(command: list[str]) -> None:
    subprocess.run(command, check=True)


def probe_video(path: Path) -> dict[str, Any]:
    ffprobe = require_binary("ffprobe")
    result = subprocess.run(
        [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    data = json.loads(result.stdout)
    videos = [stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"]
    if not videos:
        fail(f"no video stream found in {path}")
    stream = videos[0]
    duration = float(stream.get("duration") or data.get("format", {}).get("duration") or 0)
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    rate_text = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "30/1"
    try:
        numerator, denominator = rate_text.split("/", 1)
        fps = float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError):
        fps = 30.0
    if fps <= 0:
        fps = 30.0
    if width <= 0 or height <= 0:
        fail("video dimensions could not be determined")
    return {"width": width, "height": height, "duration": duration, "fps": fps, "raw": data}


def validate_input(path_text: str) -> Path:
    path = Path(path_text).expanduser().resolve()
    if not path.is_file():
        fail(f"input video does not exist: {path}")
    return path


def default_output(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}-clean.mp4")


def validate_output(input_path: Path, output_text: str | None, overwrite: bool) -> Path:
    output = Path(output_text).expanduser().resolve() if output_text else default_output(input_path)
    if output == input_path:
        fail("refusing to overwrite the source; choose a different output path")
    if output.exists() and not overwrite:
        fail(f"output already exists: {output}; pass --overwrite only after approving replacement")
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def parse_box(spec: str) -> dict[str, float | int | None]:
    region, marker, time_range = spec.partition("@")
    parts = region.split(",")
    if len(parts) != 4:
        fail(f"invalid box '{spec}'; expected x,y,width,height[@start-end]")
    try:
        x, y, width, height = (int(value.strip()) for value in parts)
    except ValueError:
        fail(f"invalid integer in box '{spec}'")
    if min(x, y) < 0 or width <= 0 or height <= 0:
        fail(f"invalid box dimensions in '{spec}'")
    start: float | None = None
    end: float | None = None
    if marker:
        times = time_range.split("-")
        if len(times) != 2:
            fail(f"invalid time range in '{spec}'; expected start-end in seconds")
        try:
            start, end = float(times[0]), float(times[1])
        except ValueError:
            fail(f"invalid time range in '{spec}'")
        if start < 0 or end <= start:
            fail(f"invalid time range in '{spec}'")
    return {"x": x, "y": y, "w": width, "h": height, "start": start, "end": end}


def expand_box(
    box: dict[str, float | int | None], padding: int, frame_w: int, frame_h: int
) -> dict[str, float | int | None]:
    x = max(0, int(box["x"] or 0) - padding)
    y = max(0, int(box["y"] or 0) - padding)
    right = min(frame_w, int(box["x"] or 0) + int(box["w"] or 0) + padding)
    bottom = min(frame_h, int(box["y"] or 0) + int(box["h"] or 0) + padding)
    expanded = dict(box)
    expanded.update({"x": x, "y": y, "w": right - x, "h": bottom - y})
    return expanded


def delogo_filter(boxes: list[dict[str, float | int | None]]) -> str:
    filters: list[str] = []
    for box in boxes:
        expr = f"delogo=x={box['x']}:y={box['y']}:w={box['w']}:h={box['h']}:show=0"
        if box.get("start") is not None:
            expr += f":enable='between(t,{box['start']},{box['end']})'"
        filters.append(expr)
    return ",".join(filters)


def encode_boxes(
    input_path: Path,
    output_path: Path,
    boxes: list[dict[str, float | int | None]],
    crf: int,
) -> None:
    ffmpeg = require_binary("ffmpeg")
    command = [
        ffmpeg,
        "-hide_banner",
        "-y",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-vf",
        delogo_filter(boxes),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    run_checked(command)


def diagnostic_paths(output_path: Path) -> tuple[Path, Path]:
    base = output_path.with_suffix("")
    return Path(f"{base}-detection.jpg"), Path(f"{base}-detection.json")


def sample_frames(
    input_path: Path, sample_count: int, max_width: int = 960
) -> tuple[list[Any], float, tuple[int, int]]:
    _, np = require_cv()
    ffmpeg = require_binary("ffmpeg")
    info = probe_video(input_path)
    width = info["width"]
    height = info["height"]
    duration = max(float(info["duration"]), 0.1)
    scale = min(1.0, max_width / width)
    analysis_w = max(2, int(round(width * scale)) // 2 * 2)
    analysis_h = max(2, int(round(height * scale)) // 2 * 2)
    sampling_fps = sample_count / duration
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vf",
        f"fps={sampling_fps:.8f},scale={analysis_w}:{analysis_h}",
        "-frames:v",
        str(sample_count),
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "pipe:1",
    ]
    result = subprocess.run(command, check=True, stdout=subprocess.PIPE)
    frame_bytes = analysis_w * analysis_h * 3
    frames = []
    for offset in range(0, len(result.stdout) - frame_bytes + 1, frame_bytes):
        frame = np.frombuffer(result.stdout[offset : offset + frame_bytes], dtype=np.uint8)
        frames.append(frame.reshape((analysis_h, analysis_w, 3)).copy())
    if len(frames) < max(6, sample_count // 3):
        fail("too few frames could be sampled for automatic detection")
    return frames, scale, (width, height)


def detect_stationary_logo(
    input_path: Path, sample_count: int
) -> tuple[dict[str, int], float, Any, dict[str, Any]]:
    cv2, np = require_cv()
    frames, scale, original_size = sample_frames(input_path, sample_count)
    gray_frames = [cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) for frame in frames]
    stack = np.stack(gray_frames).astype(np.float32)
    temporal_median = np.median(stack, axis=0)
    mad = np.median(np.abs(stack - temporal_median), axis=0)
    median = temporal_median.astype(np.uint8)

    edge_hits = [(cv2.Canny(gray, 70, 150) > 0).astype(np.float32) for gray in gray_frames]
    edge_frequency = np.mean(np.stack(edge_hits), axis=0)
    stable = mad < 10.0
    candidate_pixels = ((edge_frequency > 0.56) & stable).astype(np.uint8) * 255

    kernel_size = max(5, int(round(min(median.shape) * 0.012)))
    if kernel_size % 2 == 0:
        kernel_size += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    grouped = cv2.morphologyEx(candidate_pixels, cv2.MORPH_CLOSE, kernel, iterations=2)
    grouped = cv2.dilate(grouped, kernel, iterations=1)

    count, _, stats, _ = cv2.connectedComponentsWithStats(grouped, connectivity=8)
    frame_h, frame_w = median.shape
    frame_area = frame_w * frame_h
    components: list[tuple[int, int, int, int]] = []
    for label in range(1, count):
        x, y, w, h, _ = (int(value) for value in stats[label])
        box_area = w * h
        if w < 4 or h < 4 or box_area > frame_area * 0.14 or box_area < frame_area * 0.00002:
            continue
        if w / max(h, 1) < 0.06 or w / max(h, 1) > 16:
            continue
        components.append((x, y, w, h))

    # Logos commonly contain disconnected letters or symbols. Merge nearby
    # persistent components before scoring so one wordmark becomes one region.
    merge_gap = max(kernel_size * 5, int(round(min(frame_w, frame_h) * 0.08)))
    merged = components[:]
    changed = True
    while changed:
        changed = False
        next_boxes: list[tuple[int, int, int, int]] = []
        while merged:
            ax, ay, aw, ah = merged.pop()
            ar, ab = ax + aw, ay + ah
            joined = False
            for index, (bx, by, bw, bh) in enumerate(merged):
                br, bb = bx + bw, by + bh
                separated = (
                    ar + merge_gap < bx
                    or br + merge_gap < ax
                    or ab + merge_gap < by
                    or bb + merge_gap < ay
                )
                if not separated:
                    nx, ny = min(ax, bx), min(ay, by)
                    nr, nb = max(ar, br), max(ab, bb)
                    merged[index] = (nx, ny, nr - nx, nb - ny)
                    changed = True
                    joined = True
                    break
            if not joined:
                next_boxes.append((ax, ay, aw, ah))
        merged = next_boxes

    global_stability = float(stable.mean())
    ranked: list[tuple[float, tuple[int, int, int, int], dict[str, float]]] = []
    for x, y, w, h in merged:
        box_area = w * h
        if w < 14 or h < 10 or box_area > frame_area * 0.14 or box_area < frame_area * 0.00008:
            continue
        aspect = w / max(h, 1)
        if aspect < 0.12 or aspect > 10:
            continue
        ys = slice(y, y + h)
        xs = slice(x, x + w)
        local_edges = candidate_pixels[ys, xs] > 0
        persistence = float(edge_frequency[ys, xs][local_edges].mean()) if local_edges.any() else 0.0
        stability = float(stable[ys, xs].mean())
        stability_contrast = float(
            np.clip((stability - global_stability) / max(1.0 - global_stability, 0.05), 0, 1)
        )
        density = float(local_edges.mean())
        compactness = min(1.0, float(grouped[ys, xs].mean() / 255.0) / 0.35)
        size_penalty = max(0.35, 1.0 - box_area / (frame_area * 0.16))
        confidence = float(
            np.clip(
                (
                    0.30 * min(1.0, density / 0.07)
                    + 0.25 * min(1.0, persistence / 0.65)
                    + 0.30 * stability_contrast
                    + 0.15 * compactness
                )
                * size_penalty,
                0,
                1,
            )
        )
        ranked.append(
            (
                confidence,
                (x, y, w, h),
                {
                    "edge_persistence": persistence,
                    "temporal_stability": stability,
                    "global_stability": global_stability,
                    "stability_contrast": stability_contrast,
                    "edge_density": density,
                    "compactness": compactness,
                },
            )
        )

    if not ranked:
        fail("no stationary overlay candidate was found; use inspect and --box", EXIT_LOW_CONFIDENCE)
    ranked.sort(key=lambda item: item[0], reverse=True)
    confidence, (x, y, w, h), metrics = ranked[0]
    inv_scale = 1.0 / scale
    box = {
        "x": max(0, round(x * inv_scale)),
        "y": max(0, round(y * inv_scale)),
        "w": min(original_size[0], round(w * inv_scale)),
        "h": min(original_size[1], round(h * inv_scale)),
    }
    representative = frames[len(frames) // 2].copy()
    cv2.rectangle(
        representative,
        (x, y),
        (x + w, y + h),
        (0, 0, 255),
        max(2, kernel_size // 4),
    )
    details = {
        "mode": "auto-stationary",
        "sample_count": len(frames),
        "analysis_scale": scale,
        "candidate_count": len(ranked),
        "metrics": metrics,
        "candidates": [
            {
                "confidence": round(item[0], 4),
                "box": {
                    "x": round(item[1][0] * inv_scale),
                    "y": round(item[1][1] * inv_scale),
                    "w": round(item[1][2] * inv_scale),
                    "h": round(item[1][3] * inv_scale),
                },
            }
            for item in ranked[:10]
        ],
    }
    return box, confidence, representative, details


def write_detection_diagnostics(
    output_path: Path,
    frame: Any,
    box: dict[str, int | float | None],
    confidence: float,
    details: dict[str, Any],
) -> tuple[Path, Path]:
    cv2, _ = require_cv()
    image_path, json_path = diagnostic_paths(output_path)
    cv2.imwrite(str(image_path), frame)
    report = dict(details)
    report.update(
        {
            "box": box,
            "confidence": round(confidence, 4),
            "diagnostic_image": str(image_path),
        }
    )
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return image_path, json_path


def encode_tracked_template(
    input_path: Path,
    output_path: Path,
    template_path: Path,
    threshold: float,
    search_margin: int,
    inpaint_radius: int,
    crf: int,
) -> dict[str, Any]:
    cv2, np = require_cv()
    ffmpeg = require_binary("ffmpeg")
    info = probe_video(input_path)
    width = info["width"]
    height = info["height"]
    fps = info["fps"]
    total = int(round(info["duration"] * fps)) if info["duration"] else 0

    template_rgba = cv2.imread(str(template_path), cv2.IMREAD_UNCHANGED)
    if template_rgba is None:
        fail(f"could not read template image: {template_path}")
    if template_rgba.shape[0] >= height or template_rgba.shape[1] >= width:
        fail("template must be a tight crop smaller than the video frame")
    if template_rgba.ndim == 3 and template_rgba.shape[2] == 4:
        alpha = template_rgba[:, :, 3]
        template_bgr = template_rgba[:, :, :3]
        template_mask = (alpha > 16).astype(np.uint8) * 255
    else:
        template_bgr = (
            template_rgba[:, :, :3]
            if template_rgba.ndim == 3
            else cv2.cvtColor(template_rgba, cv2.COLOR_GRAY2BGR)
        )
        template_mask = np.full(template_bgr.shape[:2], 255, dtype=np.uint8)
    template_edge = cv2.Canny(cv2.cvtColor(template_bgr, cv2.COLOR_BGR2GRAY), 60, 150)
    th, tw = template_edge.shape
    if int((template_edge > 0).sum()) < 12:
        fail("template has too few visible edges for reliable tracking")

    decode_command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "pipe:1",
    ]
    decoder = subprocess.Popen(decode_command, stdout=subprocess.PIPE)
    if decoder.stdout is None:
        fail("could not open FFmpeg decoder pipe")

    encode_command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s",
        f"{width}x{height}",
        "-r",
        f"{fps:.8f}",
        "-i",
        "pipe:0",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a?",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    encoder = subprocess.Popen(encode_command, stdin=subprocess.PIPE)
    if encoder.stdin is None:
        fail("could not open FFmpeg frame pipe")

    previous: tuple[int, int] | None = None
    matched = 0
    frame_index = 0
    scores: list[float] = []
    frame_size = width * height * 3
    try:
        while True:
            raw = decoder.stdout.read(frame_size)
            if len(raw) < frame_size:
                break
            frame = np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 3)).copy()
            frame_edge = cv2.Canny(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 60, 150)
            offset_x = 0
            offset_y = 0
            search = frame_edge
            if previous is not None and frame_index % 30 != 0:
                px, py = previous
                left = max(0, px - search_margin)
                top = max(0, py - search_margin)
                right = min(width, px + tw + search_margin)
                bottom = min(height, py + th + search_margin)
                if right - left >= tw and bottom - top >= th:
                    search = frame_edge[top:bottom, left:right]
                    offset_x, offset_y = left, top
            result = cv2.matchTemplate(search, template_edge, cv2.TM_CCOEFF_NORMED)
            _, score, _, location = cv2.minMaxLoc(result)
            x, y = location[0] + offset_x, location[1] + offset_y
            if score < threshold and (offset_x or offset_y):
                result = cv2.matchTemplate(frame_edge, template_edge, cv2.TM_CCOEFF_NORMED)
                _, score, _, location = cv2.minMaxLoc(result)
                x, y = location
            scores.append(float(score))
            if score >= threshold:
                mask = np.zeros((height, width), dtype=np.uint8)
                mask[y : y + th, x : x + tw] = np.maximum(
                    mask[y : y + th, x : x + tw], template_mask
                )
                mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)
                frame = cv2.inpaint(frame, mask, inpaint_radius, cv2.INPAINT_TELEA)
                previous = (x, y)
                matched += 1
            else:
                previous = None
            encoder.stdin.write(frame.tobytes())
            frame_index += 1
            if total and frame_index % max(1, int(fps * 5)) == 0:
                print(f"processed {frame_index}/{total} frames", file=sys.stderr)
    except BrokenPipeError:
        fail("FFmpeg stopped while receiving processed frames")
    finally:
        decoder.stdout.close()
        encoder.stdin.close()
    decoder_code = decoder.wait()
    encoder_code = encoder.wait()
    if decoder_code != 0:
        fail(f"FFmpeg decoder exited with code {decoder_code}")
    if encoder_code != 0:
        fail(f"FFmpeg encoder exited with code {encoder_code}")
    return {
        "mode": "template-tracking",
        "frames": frame_index,
        "matched_frames": matched,
        "match_rate": matched / max(frame_index, 1),
        "mean_match_score": sum(scores) / max(len(scores), 1),
    }


def make_contact_sheet(input_path: Path, output_path: Path, columns: int) -> None:
    info = probe_video(input_path)
    duration = max(info["duration"], 1.0)
    sample_count = 12
    interval = max(duration / sample_count, 0.1)
    rows = math.ceil(sample_count / columns)
    ffmpeg = require_binary("ffmpeg")
    vf = f"fps=1/{interval:.6f},scale=480:-2,tile={columns}x{rows}:padding=4:margin=4"
    command = [
        ffmpeg,
        "-hide_banner",
        "-y",
        "-i",
        str(input_path),
        "-vf",
        vf,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(output_path),
    ]
    run_checked(command)


def verify_output(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        fail(f"output was not created correctly: {path}")
    probe_video(path)


def command_remove(args: argparse.Namespace) -> None:
    input_path = validate_input(args.input)
    output_path = validate_output(input_path, args.output, args.overwrite)
    info = probe_video(input_path)

    if args.template:
        template_path = Path(args.template).expanduser().resolve()
        if not template_path.is_file():
            fail(f"template does not exist: {template_path}")
        report = encode_tracked_template(
            input_path,
            output_path,
            template_path,
            args.template_threshold,
            args.search_margin,
            args.inpaint_radius,
            args.crf,
        )
        report_path = Path(f"{output_path.with_suffix('')}-tracking.json")
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        verify_output(output_path)
        print(json.dumps({"output": str(output_path), "report": str(report_path), **report}, indent=2))
        return

    if args.box:
        boxes = [
            expand_box(parse_box(spec), args.padding, info["width"], info["height"])
            for spec in args.box
        ]
        for box in boxes:
            if int(box["w"] or 0) < 2 or int(box["h"] or 0) < 2:
                fail("expanded box is outside the video frame")
        encode_boxes(input_path, output_path, boxes, args.crf)
        verify_output(output_path)
        print(json.dumps({"output": str(output_path), "mode": "box", "boxes": boxes}, indent=2))
        return

    box, confidence, representative, details = detect_stationary_logo(input_path, args.samples)
    expanded = expand_box(box, args.padding, info["width"], info["height"])
    image_path, report_path = write_detection_diagnostics(
        output_path, representative, expanded, confidence, details
    )
    print(f"automatic candidate confidence: {confidence:.3f}", file=sys.stderr)
    print(f"diagnostic: {image_path}", file=sys.stderr)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "mode": "auto",
                    "box": expanded,
                    "confidence": confidence,
                    "diagnostic": str(image_path),
                    "report": str(report_path),
                },
                indent=2,
            )
        )
        return
    if confidence < args.minimum_confidence and not args.force_auto:
        fail(
            f"automatic detection confidence {confidence:.3f} is below {args.minimum_confidence:.3f}; "
            f"review {image_path} and rerun with --box, or use --force-auto after review",
            EXIT_LOW_CONFIDENCE,
        )
    encode_boxes(input_path, output_path, [expanded], args.crf)
    verify_output(output_path)
    print(
        json.dumps(
            {
                "output": str(output_path),
                "mode": "auto",
                "box": expanded,
                "confidence": confidence,
                "diagnostic": str(image_path),
                "report": str(report_path),
            },
            indent=2,
        )
    )


def command_inspect(args: argparse.Namespace) -> None:
    input_path = validate_input(args.input)
    output = (
        Path(args.output).expanduser().resolve()
        if args.output
        else input_path.with_name(f"{input_path.stem}-contact-sheet.jpg")
    )
    if output.exists() and not args.overwrite:
        fail(f"output already exists: {output}; pass --overwrite to replace it")
    output.parent.mkdir(parents=True, exist_ok=True)
    make_contact_sheet(input_path, output, args.columns)
    print(str(output))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Detect and remove small visible overlay logos from authorized videos."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    remove = subparsers.add_parser("remove", help="create a cleaned copy of a video")
    remove.add_argument("input", help="input video path")
    remove.add_argument("--output", "-o", help="output path; defaults to <stem>-clean.mp4")
    modes = remove.add_mutually_exclusive_group()
    modes.add_argument(
        "--auto",
        action="store_true",
        help="detect a stationary overlay anywhere in the frame (default)",
    )
    modes.add_argument(
        "--box", action="append", help="x,y,width,height[@start-end]; may be repeated"
    )
    modes.add_argument("--template", help="tight logo crop for moving-logo tracking")
    remove.add_argument(
        "--padding", type=int, default=4, help="pixels added around automatic or box regions (default: 4)"
    )
    remove.add_argument(
        "--samples", type=int, default=24, help="frames sampled in automatic mode (default: 24)"
    )
    remove.add_argument(
        "--minimum-confidence", type=float, default=0.42, help="automatic-mode threshold (default: 0.42)"
    )
    remove.add_argument(
        "--force-auto", action="store_true", help="encode an automatically detected region below the threshold after review"
    )
    remove.add_argument(
        "--dry-run", action="store_true", help="detect and write diagnostics without encoding"
    )
    remove.add_argument(
        "--template-threshold", type=float, default=0.58, help="template match threshold (default: 0.58)"
    )
    remove.add_argument(
        "--search-margin", type=int, default=80, help="template tracking search radius (default: 80)"
    )
    remove.add_argument(
        "--inpaint-radius", type=int, default=5, help="template-mode inpainting radius (default: 5)"
    )
    remove.add_argument(
        "--crf",
        type=int,
        default=18,
        choices=range(0, 52),
        metavar="0..51",
        help="H.264 quality; lower is better (default: 18)",
    )
    remove.add_argument(
        "--overwrite", action="store_true", help="replace an existing destination, never the source"
    )
    remove.set_defaults(func=command_remove)

    inspect = subparsers.add_parser("inspect", help="create a 12-frame contact sheet")
    inspect.add_argument("input", help="input video path")
    inspect.add_argument("--output", "-o", help="JPEG output path")
    inspect.add_argument("--columns", type=int, default=4, choices=range(1, 7), metavar="1..6")
    inspect.add_argument("--overwrite", action="store_true")
    inspect.set_defaults(func=command_inspect)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if getattr(args, "padding", 0) < 0:
        fail("padding cannot be negative")
    if getattr(args, "samples", 24) < 6:
        fail("automatic mode needs at least 6 samples")
    confidence = getattr(args, "minimum_confidence", 0.42)
    if confidence < 0 or confidence > 1:
        fail("minimum confidence must be between 0 and 1")
    args.func(args)


if __name__ == "__main__":
    main()
