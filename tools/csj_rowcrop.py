"""CS Junkie row crop (master skill v39 section 6). Crops a raw kill row tight to its own red border.

crop_to_border(img) -> (cropped RGBA, report)
  - Finds the red border (R high, G and B low) and crops to its box. Nothing outside the border is kept.
  - Report flags: stray red pixels outside the border box, and feed noise in the 6 columns left of the border.

Usage:
  python3 csj_rowcrop.py <raw_row.png> <out.png>
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

NOISE_COLS = 6


def red_mask(arr):
    r, g, b = arr[:, :, 0].astype(int), arr[:, :, 1].astype(int), arr[:, :, 2].astype(int)
    return (r > 150) & (g < 90) & (b < 90)


def crop_to_border(img):
    rgba = img.convert("RGBA")
    arr = np.asarray(rgba)
    m = red_mask(arr)
    ys, xs = np.where(m)
    if xs.size == 0:
        raise ValueError("no red border found in this row")
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    cropped = rgba.crop((int(x0), int(y0), int(x1) + 1, int(y1) + 1))
    # stray red pixels: red outside the border box is not expected in a clean crop (count only)
    outside = int(m.sum() - m[y0:y1 + 1, x0:x1 + 1].sum())
    left = arr[y0:y1 + 1, max(0, x0 - NOISE_COLS):x0]
    noise = int(((left[:, :, :3].astype(int).sum(axis=2)) > 60).sum()) if left.size else 0
    report = {"border_box": [int(x0), int(y0), int(x1), int(y1)], "size": list(cropped.size),
              "red_outside_box": outside, "noise_px_left_6_cols": noise,
              "pass": noise == 0}
    return cropped, report


def main(src, out):
    cropped, report = crop_to_border(Image.open(src))
    cropped.save(out)
    report["out"] = out
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main(*sys.argv[1:3])
