"""CS Junkie row crop (29 Oct 2026, Jord: crop each kill row tight to its own red border).

Usage:
  python3 csj_row_crop.py <source.mp4> <onsets.json> <out_dir> --kills N --window-start WS
                          [--feed 1620,40,300,280] [--scale 1.5]

For each kill (first N by onset, onset in source seconds):
  - Reads the feed crop 0.3 s before the kill and 0.8 s after it (AFTER_DELAY).
  - Finds every red-bordered row box in both frames. The kill row is the box that is new after the kill:
    a box whose interior is not found (within a small shift) in the frame before.
  - Crops that box tight to its red border: the crop starts on the border's left column and ends on its
    right column, so nothing from the feed sits outside the border.
  - Writes <out_dir>/raw_K<n>.png (RGB, the same raw rows the build reads).

Stack slots (Jord, 28 Oct): oldest row on top at y 460 in the 1080x1920 frame, each later kill 60 px lower,
downward only. Right edge at x 1049. The 1080x1080 square sits at y 420 in the frame, so the square y is
40 + 60 * (n - 1). Rows are scaled by --scale (1.5, LANCZOS, as in csj_build.py).

Writes <out_dir>/rows_crop.json with each row's box in feed coordinates, its size, and its stack slot.
Stops with exit 1 and names the kill when a kill has no single new row box. Never guesses a box.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

AFTER_DELAY = 0.4     # seconds after the onset to read the frame with the new row
SLOT_Y0 = 460        # frame y of the oldest row (Jord 28 Oct)
SLOT_STEP = 60       # px lower for each later kill
SLOT_RIGHT = 1049    # right edge of every row
SQUARE_Y = 420       # the 1080x1080 square's top in the frame
MIN_RUN = 60         # a border line is at least this many red pixels long (accent bars are 50)
MIN_H, MAX_H = 24, 40  # border-to-border height in feed pixels (rows are about 32 px)
MAX_LUMA = 100      # median luma of a row interior is dark (text and guns lift the mean)


def grab(src, t, crop):
    """One RGB frame at time t, cropped to crop = (x, y, w, h), read straight from ffmpeg."""
    x, y, w, h = crop
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{t:.4f}", "-i", src, "-frames:v", "1",
           "-vf", f"crop={w}:{h}:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 3).astype(int)


def red_mask(a):
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return (r > 110) & (r - np.maximum(g, b) > 70)


def longest_run(row):
    """(length, start, end) of the longest run of True in a 1-D bool array."""
    best = (0, 0, 0)
    start = None
    for x, v in enumerate(list(row) + [False]):
        if v and start is None:
            start = x
        elif not v and start is not None:
            if x - start > best[0]:
                best = (x - start, start, x - 1)
            start = None
    return best


def find_boxes(a):
    """Every red-bordered box in the crop as (x0, y0, x1, y1), inclusive.

    A box is a pair of border lines (top and bottom) with a red side border on each end. Rows can touch
    or sit close, and the corners are bevelled, so the side search uses the longer of the two border lines.
    """
    m = red_mask(a)
    H = m.shape[0]
    runs = [longest_run(m[y]) for y in range(H)]
    line = [runs[y][0] >= MIN_RUN for y in range(H)]
    tops = [y for y in range(H) if line[y] and (y == 0 or not line[y - 1])]
    bottoms = [y for y in range(H) if line[y] and (y == H - 1 or not line[y + 1])]
    found = {}
    for t in tops:
        for b in bottoms:
            if not MIN_H <= b - t <= MAX_H:
                continue
            _, xs, xe = max(runs[t], runs[b])
            side = m[t:b + 1].mean(axis=0)
            cols = np.nonzero(side >= 0.5)[0]
            left = cols[(cols >= xs - 25) & (cols <= xs + 8)]
            right = cols[(cols >= xe - 8) & (cols <= xe + 25)]
            if not left.size or not right.size:
                continue  # no side borders
            # Take the strongest side column in each window, so a stray red pixel cannot move the edge.
            x0 = int(left[np.argmax(side[left])])
            x1 = int(right[np.argmax(side[right])])
            if x1 - x0 < MIN_RUN or m[b, x0:x1 + 1].mean() < 0.8:
                continue  # bottom line does not span the box
            inner = a[t + 2:b - 1, x0 + 2:x1 - 1]
            if inner.size == 0 or np.median(0.299 * inner[..., 0] + 0.587 * inner[..., 1] + 0.114 * inner[..., 2]) > MAX_LUMA:
                continue  # interior is not a dark row
            key = (x0, t, x1)
            if key not in found or b < found[key]:
                found[key] = b  # same top and sides: keep the nearest bottom line
    boxes = [(x0, t, x1, b) for (x0, t, x1), b in found.items()]
    # A box whose top line is the bottom line of another box is that box's own border, not a row: drop it.
    boxes = [bx for bx in boxes if not any(o != bx and abs(bx[1] - o[3]) <= 1 and _xov(bx, o) > 0.5 for o in boxes)]
    # Rows that overlap on screen: keep the box with the most red on its border (the true row).
    score = {bx: int(m[bx[1]:bx[1] + 1, bx[0]:bx[2] + 1].sum() + m[bx[3]:bx[3] + 1, bx[0]:bx[2] + 1].sum()) for bx in boxes}
    kept = []
    for bx in sorted(boxes, key=lambda q: -score[q]):
        if all(_iou(bx, k) < 0.5 for k in kept):
            kept.append(bx)
    return sorted(kept)


def _xov(p, q):
    """Share of the narrower box's width that sits under the other box."""
    ov = max(0, min(p[2], q[2]) - max(p[0], q[0]) + 1)
    return ov / float(min(p[2] - p[0], q[2] - q[0]) + 1)


def _iou(p, q):
    ix = max(0, min(p[2], q[2]) - max(p[0], q[0]) + 1)
    iy = max(0, min(p[3], q[3]) - max(p[1], q[1]) + 1)
    inter = ix * iy
    area = lambda r: (r[2] - r[0] + 1) * (r[3] - r[1] + 1)
    return inter / float(area(p) + area(q) - inter)


def new_box(a_before, a_after, kill_no):
    """The one row box after the kill that has no partner before it.

    Rows keep their width while the feed moves them, but the edge detection wobbles by a few px. So each box
    is paired with the closest box before it (within 12 px on each side), and each old box pairs once.
    The new row is the single box left without a partner.
    """
    before = find_boxes(a_before)
    after = find_boxes(a_after)
    pairs = sorted(((abs(b[0] - o[0]) + abs(b[2] - o[2]), i, j)
                    for i, b in enumerate(after) for j, o in enumerate(before)
                    if abs(b[0] - o[0]) <= 12 and abs(b[2] - o[2]) <= 12))
    used_a, used_b = set(), set()
    for _, i, j in pairs:
        if i not in used_a and j not in used_b:
            used_a.add(i)
            used_b.add(j)
    fresh = [after[i] for i in range(len(after)) if i not in used_a]
    if len(fresh) != 1:
        raise ValueError(f"kill {kill_no}: expected one new row box, found {len(fresh)} {fresh}")
    return fresh[0]


def tight_crop(a, box):
    x0, y0, x1, y1 = box
    return Image.fromarray(a[y0:y1 + 1, x0:x1 + 1].astype(np.uint8), "RGB")


def slot(n, w_scaled, h_scaled):
    """Frame position and square position for stack slot n (1-based)."""
    y_frame = SLOT_Y0 + SLOT_STEP * (n - 1)
    x = SLOT_RIGHT - w_scaled
    return {"x": x, "y_frame": y_frame, "y_square": y_frame - SQUARE_Y, "h": h_scaled}


def run(src, onsets_path, out_dir, kills, window_start, feed, scale):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    onsets = json.loads(Path(onsets_path).read_text())
    kill_list = sorted(onsets["kills"], key=lambda k: k["seconds"])[:kills]
    if len(kill_list) < kills:
        raise ValueError(f"onsets file has {len(kill_list)} kills, asked for {kills}")
    report = []
    for n, k in enumerate(kill_list, start=1):
        t = k["seconds"]
        before = grab(src, t - 0.3, feed)
        after = grab(src, t + AFTER_DELAY, feed)  # the row is fully drawn about 0.8 s after the onset
        box = new_box(before, after, n)
        img = tight_crop(after, box)
        img.save(out_dir / f"raw_K{n}.png")
        w, h = img.size
        scaled = (round(w * scale), round(h * scale))
        s = slot(n, scaled[0], scaled[1])
        report.append({
            "kill": n,
            "onset_source_s": t,
            "onset_window_s": round(t - window_start, 4),
            "box_in_feed": list(box),
            "raw_size": [w, h],
            "scaled_size": list(scaled),
            "stack": s,
        })
    result = {"feed": list(feed), "scale": scale, "rows": report}
    (out_dir / "rows_crop.json").write_text(json.dumps(result, indent=1))
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("source")
    p.add_argument("onsets")
    p.add_argument("out_dir")
    p.add_argument("--kills", type=int, required=True)
    p.add_argument("--window-start", type=float, required=True)
    p.add_argument("--feed", default="1620,40,300,280")
    p.add_argument("--scale", type=float, default=1.5)
    args = p.parse_args(argv)
    feed = tuple(int(v) for v in args.feed.split(","))
    try:
        res = run(args.source, args.onsets, args.out_dir, args.kills, args.window_start, feed, args.scale)
    except ValueError as e:
        print(f"row crop refused: {e}", file=sys.stderr)
        return 1
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
