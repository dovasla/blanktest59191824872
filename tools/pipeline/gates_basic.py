#!/usr/bin/env python3
"""Basic pipeline gates: video probe and kill timing arithmetic.

Each gate returns a dict with "gate", "result" ("pass" or "fail"), and the
numbers it checked, so a build log can record the exact values.

Usage:
  python3 gates_basic.py probe <clip.mp4>
  python3 gates_basic.py timing --fps 60 --first-full 612 1040 1505
"""

import argparse
import json
import subprocess
import sys
from fractions import Fraction

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
TARGET_FPS = 60
TARGET_AUDIO_CODEC = "aac"
ONSET_LEAD_FRAMES = 3  # onset = first fully rendered row frame minus 3


def run_ffprobe(path):
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", path,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def probe_gate(path):
    data = run_ffprobe(path)
    streams = data.get("streams", [])
    fmt = data.get("format", {})

    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    checks = {}
    numbers = {}

    if video is None:
        checks["video_stream"] = False
        numbers["video_stream"] = "missing"
    else:
        w, h = int(video.get("width", 0)), int(video.get("height", 0))
        numbers["width"] = w
        numbers["height"] = h
        checks["resolution"] = (w, h) == (TARGET_WIDTH, TARGET_HEIGHT)

        rate_str = video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"
        try:
            fps = float(Fraction(rate_str))
        except (ZeroDivisionError, ValueError):
            fps = 0.0
        numbers["fps"] = round(fps, 3)
        checks["fps"] = abs(fps - TARGET_FPS) < 0.01

        v_bitrate = int(video.get("bit_rate", 0) or 0)
        numbers["video_bitrate_kbps"] = round(v_bitrate / 1000, 1)

    if audio is None:
        checks["audio_stream"] = False
        numbers["audio_codec"] = "missing"
    else:
        codec = audio.get("codec_name", "")
        numbers["audio_codec"] = codec
        checks["audio_codec"] = codec == TARGET_AUDIO_CODEC

    total_bitrate = int(fmt.get("bit_rate", 0) or 0)
    duration = float(fmt.get("duration", 0) or 0)
    numbers["total_bitrate_kbps"] = round(total_bitrate / 1000, 1)
    numbers["duration_s"] = round(duration, 3)
    checks["bitrate_present"] = total_bitrate > 0
    checks["duration_present"] = duration > 0

    failed = [k for k, ok in checks.items() if not ok]
    return {
        "gate": "probe",
        "result": "pass" if not failed else "fail",
        "failed_checks": failed,
        "numbers": numbers,
    }


def timing_gate(first_full_frames, fps=TARGET_FPS):
    """Turn first fully rendered row frames into onset frames and seconds.

    onset frame = first fully rendered frame - 3
    onset seconds = onset frame / fps
    Pass when every onset is a whole frame at or after frame 0 and the
    onsets go up in order.
    """
    onsets = []
    for f in first_full_frames:
        onset_frame = f - ONSET_LEAD_FRAMES
        onsets.append({
            "first_full_frame": f,
            "onset_frame": onset_frame,
            "onset_s": round(onset_frame / fps, 4),
        })

    non_negative = all(o["onset_frame"] >= 0 for o in onsets)
    in_order = all(
        onsets[i]["onset_frame"] < onsets[i + 1]["onset_frame"]
        for i in range(len(onsets) - 1)
    )
    failed = []
    if not non_negative:
        failed.append("onset_non_negative")
    if not in_order:
        failed.append("onset_in_order")

    return {
        "gate": "timing",
        "result": "pass" if not failed else "fail",
        "failed_checks": failed,
        "numbers": {"fps": fps, "lead_frames": ONSET_LEAD_FRAMES, "onsets": onsets},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Basic pipeline gates")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_probe = sub.add_parser("probe", help="Check resolution, fps, audio, bitrate, duration")
    p_probe.add_argument("path")

    p_timing = sub.add_parser("timing", help="Onset arithmetic from first full row frames")
    p_timing.add_argument("--fps", type=float, default=TARGET_FPS)
    p_timing.add_argument("--first-full", type=int, nargs="+", required=True)

    args = parser.parse_args(argv)
    if args.cmd == "probe":
        result = probe_gate(args.path)
    else:
        result = timing_gate(args.first_full, fps=args.fps)

    print(json.dumps(result, indent=2))
    return 0 if result["result"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
