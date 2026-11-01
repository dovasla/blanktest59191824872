"""CS Junkie slide gate (csj-process v5, Step 6 gate 5). Blocking for every export.

Every kill row must slide in from the right edge over 0.2 s and land on its stack slot.
A still row (a hard cut, or no movement) fails the export.

Usage:
  python3 -I csj_slide_gate.py <export.mp4> <layout.json> [--out report.json]

layout.json:
  {"slide": 0.2, "fps": 60, "kills": [
     {"kill": 1, "slide_start_s": 2.0167, "y0": 460, "y1": 530, "x_land": 812}, ...]}
  slide_start_s: clip time where the slide starts (onset minus window start, plus the cover hold).
  y0, y1: the row's band in output pixels, from its stack slot (inclusive).
  x_land: the row's left edge on its stack slot (1050 minus the scaled row width).

A kill passes when all of these hold:
  - the row is visible during the slide and moves at least 100 px (a still row fails);
  - the left edge never moves back right by more than 2 px (monotone slide);
  - no single 1/fps step moves more than 40 percent of the total slide (a hard cut fails);
  - the last frame of the slide sits within 2 px of x_land.
Exit 0 only when every kill passes.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np


def red_left_edges(path, t0, dur, y0, y1, fps):
    """Leftmost red column per frame in the row band, or None when no red is visible."""
    # yuv420 crops snap to even sizes, so the band height is made even here to keep the reshape exact
    h = (y1 - y0 + 1) // 2 * 2
    y0 = y0 // 2 * 2
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-ss", f"{t0:.4f}", "-t", f"{dur:.4f}",
           "-vf", f"crop=1080:{h}:0:{y0}", "-r", str(fps), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, h, 1080, 3).astype(np.int16)
    out = []
    for fr in frames:
        r, g, b = fr[..., 0], fr[..., 1], fr[..., 2]
        red = (r > 120) & (r - np.maximum(g, b) > 90)
        red[:, :600] = False  # kill rows only sit at x 600 and right (1 Nov, Jord "build it"); left side is game background
        cols = np.nonzero(red.sum(axis=0) >= 4)[0]
        out.append(int(cols[0]) if cols.size else None)
    return out


def check_kill(path, k, slide, fps):
    t0 = k["slide_start_s"]
    dur = slide + 2 / fps
    xs = red_left_edges(path, t0, dur, k["y0"], k["y1"], fps)
    visible = [x for x in xs if x is not None]
    flags = []
    if len(visible) < 3:
        return {"pass": False, "flags": ["row not visible for at least 3 frames in the slide window"], "xs": xs}
    travel = visible[0] - visible[-1]
    if travel < 100:
        flags.append(f"still row: moved {travel} px in {slide} s")
    back = [b - a for a, b in zip(visible, visible[1:]) if b - a > 2]
    if back:
        flags.append(f"moves back right by {max(back)} px")
    steps = [a - b for a, b in zip(visible, visible[1:])]
    if travel > 0 and steps and max(steps) > 0.4 * travel:
        flags.append(f"hard step of {max(steps)} px (over 40 percent of the slide)")
    if abs(visible[-1] - k["x_land"]) > 2:
        flags.append(f"lands at x {visible[-1]}, expected {k['x_land']} (2 px tolerance)")
    return {"pass": not flags, "travel_px": travel, "flags": flags, "landing_x": visible[-1]}


def main(video, layout_path, out=None):
    layout = json.loads(Path(layout_path).read_text())
    slide, fps = layout["slide"], layout["fps"]
    report = {f"K{k['kill']}": check_kill(video, k, slide, fps) for k in layout["kills"]}
    ok = bool(report) and all(v["pass"] for v in report.values())
    result = {"pass": ok, "kills": report}
    print(json.dumps(result, indent=2))
    if out:
        Path(out).write_text(json.dumps(result, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    out = None
    if "--out" in args:
        i = args.index("--out")
        out = args[i + 1]
        del args[i:i + 2]
    sys.exit(main(args[0], args[1], out))
