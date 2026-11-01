"""CS Junkie row-1 gate (28 Oct 2026, Jord: hard stop). Checks kill row 1 against donk's row before rows 2 to 5 build.

Usage:
  python3 csj_row1_gate.py <raw_K1.png> <donk_row.png> [--out report.json]

Checks (all must pass, else exit 1 and no other row may be built):
  - Border: the red outline covers at least 80 percent of each of the four sides.
  - Colour: median red border colour within 40 (per channel sum) of donk's border colour.
  - Size: height matches donk's row height after the 1.5x row scale (within 3 px), so spacing matches.
Donk's row reference is final_row1.png (donk v48), sampled once per clip.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

SIDE_MIN = 0.80
COLOUR_TOL = 40
HEIGHT_TOL = 3
SCALE = 1.5


def red_mask(a):
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    return (R > 120) & (R - G > 60) & (R - B > 60)


def sides(m):
    rows = np.where(m.sum(axis=1) >= 8)[0]
    cols = np.where(m.sum(axis=0) >= 4)[0]
    if len(rows) < 2 or len(cols) < 2:
        return None
    y0, y1, x0, x1 = rows[0], rows[-1], cols[0], cols[-1]
    return [float(m[y0, x0:x1 + 1].mean()), float(m[y1, x0:x1 + 1].mean()),
            float(m[y0:y1 + 1, x0].mean()), float(m[y0:y1 + 1, x1].mean())], (int(y0), int(y1))


def check(raw_png, donk_png):
    a = np.asarray(Image.open(raw_png).convert("RGB")).astype(int)
    d = np.asarray(Image.open(donk_png).convert("RGB")).astype(int)
    flags = []
    s = sides(red_mask(a))
    if s is None:
        flags.append("no red border found")
        sides_cov, box = [0, 0, 0, 0], None
    else:
        sides_cov, box = s
        if min(sides_cov) < SIDE_MIN:
            flags.append(f"border side coverage {min(sides_cov):.2f} below {SIDE_MIN}")
    dm = red_mask(d)
    if dm.any() and red_mask(a).any():
        cr = np.median(a[red_mask(a)], axis=0)
        cd = np.median(d[dm], axis=0)
        dist = float(np.abs(cr - cd).sum())
        if dist > COLOUR_TOL:
            flags.append(f"border colour off donk by {dist:.0f} (max {COLOUR_TOL})")
    else:
        dist = None
        flags.append("no border colour to compare")
    if abs(a.shape[0] * SCALE - d.shape[0]) > HEIGHT_TOL:
        flags.append(f"height {a.shape[0]} px at 1.5x = {a.shape[0] * SCALE:.0f}, donk {d.shape[0]} px")
    return {"pass": not flags, "side_coverage": [round(x, 3) for x in sides_cov], "border_box_y": box,
            "colour_distance": None if dist is None else round(dist, 1), "flags": flags}


if __name__ == "__main__":
    args = sys.argv[1:]
    out = None
    if "--out" in args:
        i = args.index("--out")
        out = args[i + 1]
        del args[i:i + 2]
    r = check(args[0], args[1])
    print(json.dumps(r, indent=2))
    if out:
        Path(out).write_text(json.dumps(r, indent=2))
    sys.exit(0 if r["pass"] else 1)
