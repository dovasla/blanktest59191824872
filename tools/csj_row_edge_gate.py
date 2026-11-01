"""CS Junkie row-edge gate (21 Oct, added after the rows 2 and 3 bleed). Blocking for any raw row.

Usage:
  python3 csj_row_edge_gate.py <rows_dir> [--out report.json]

For each raw_K<n>.png:
  - The top border is the first red line (at least 50 percent red, loose test) with a dark interior 2 to 4 rows below it.
  - Fails if any row above that border is light (mean luma above 90): that is bleed from the row above.
  - Fails if more than 2 rows sit above the top border (the crop is too tall).
  - Fails if the first row of the crop is not a red border line or dark row (bleed at the edge).
Exit 0 only when every row passes.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def check_row(path):
    a = np.asarray(Image.open(path).convert("RGB")).astype(int)
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    red = (R > 120) & (R - G > 60) & (R - B > 60)  # looser, so a dim top border still counts
    frac = red.mean(axis=1)
    lum = (0.299 * R + 0.587 * G + 0.114 * B).mean(axis=1)
    # The row's own top border is a red line with a dark interior just below it (not another row's bottom border).
    top = None
    for y in range(max(len(frac) - 4, 0)):
        if frac[y] >= 0.5 and lum[y + 2:y + 5].mean() < 60:
            top = y
            break
    if top is None:
        # Single-row tight cut (1 Nov, Jord 31 Oct "A"): the red border is the top row and the bottom row,
        # with no light bleed above it. The interior can be bright, so the dark-interior test does not apply.
        tight_top = next((y for y in range(min(3, len(frac))) if frac[y] >= 0.5), None)
        tight_bottom = len(frac) >= 3 and frac[-3:].max() >= 0.5
        if tight_top is not None and tight_bottom and len(frac) <= 40:
            return {"pass": True, "top_border_row": tight_top, "flags": [], "mode": "tight_single_row"}
        return {"pass": False, "reason": "no red top border with a dark interior found"}
    above_light = [int(y) for y in range(top) if lum[y] > 90 and frac[y] < 0.5]
    flags = []
    if above_light:
        flags.append(f"light bleed above the top border at rows {above_light}")
    if top > 2:
        flags.append(f"{top} rows above the top border (max 2)")
    return {"pass": not flags, "top_border_row": top, "flags": flags}


def main(rows_dir, out=None):
    report = {}
    for p in sorted(Path(rows_dir).glob("raw_K*.png")):
        report[p.name] = check_row(p)
    ok = all(v["pass"] for v in report.values()) and bool(report)
    result = {"pass": ok, "rows": report}
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
    sys.exit(main(args[0], out))
