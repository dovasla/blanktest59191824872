"""Visual gates for clip builds.

Gates:
  row_edge    kill row right edge must sit at x=1039 (tolerance 2 px)
  edge_bands  60 px bands inside each edge of a region must match the
              band just outside it (max mean luma gap 12)
  slide       measured element position must match expected (tolerance 2 px)

Each gate returns (passed: bool, numbers: dict).
"""

import numpy as np
from PIL import Image

ROW_EDGE_X = 1039
ROW_EDGE_TOL_PX = 2
BAND_PX = 60
BAND_LUMA_LIMIT = 12.0
SLIDE_TOL_PX = 2


def load_rgb(path):
    """Load an image as a uint8 RGB array of shape (H, W, 3)."""
    return np.asarray(Image.open(path).convert("RGB"))


def luma(rgb):
    """Rec. 601 luma as float array."""
    rgb = rgb.astype(np.float32)
    return 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]


def gate_row_edge(measured_right_x):
    """Pass if the measured kill-row right edge is within 2 px of x=1039."""
    gap = abs(float(measured_right_x) - ROW_EDGE_X)
    return gap <= ROW_EDGE_TOL_PX, {
        "measured_x": float(measured_right_x),
        "expected_x": ROW_EDGE_X,
        "gap_px": gap,
        "tol_px": ROW_EDGE_TOL_PX,
    }


def gate_edge_bands(frame_rgb, box):
    """Compare each 60 px band inside the box edges with the band just outside.

    box = (x0, y0, x1, y1) in pixels. Pass if every edge gap is <= 12 luma.
    """
    x0, y0, x1, y1 = box
    Y = luma(frame_rgb)
    h, w = Y.shape
    b = BAND_PX
    pairs = {
        "left": (Y[y0:y1, x0:x0 + b], Y[y0:y1, max(x0 - b, 0):x0]),
        "right": (Y[y0:y1, x1 - b:x1], Y[y0:y1, x1:min(x1 + b, w)]),
        "top": (Y[y0:y0 + b, x0:x1], Y[max(y0 - b, 0):y0, x0:x1]),
        "bottom": (Y[y1 - b:y1, x0:x1], Y[y1:min(y1 + b, h), x0:x1]),
    }
    numbers = {}
    passed = True
    for name, (inside, outside) in pairs.items():
        if inside.size == 0 or outside.size == 0:
            gap = float("inf")
        else:
            gap = abs(float(inside.mean()) - float(outside.mean()))
        numbers[name + "_luma_gap"] = gap
        if gap > BAND_LUMA_LIMIT:
            passed = False
    numbers["limit"] = BAND_LUMA_LIMIT
    numbers["band_px"] = b
    return passed, numbers


def gate_slide(measured_xy, expected_xy):
    """Pass if the element position is within 2 px of the expected position."""
    dx = abs(float(measured_xy[0]) - float(expected_xy[0]))
    dy = abs(float(measured_xy[1]) - float(expected_xy[1]))
    return dx <= SLIDE_TOL_PX and dy <= SLIDE_TOL_PX, {
        "dx_px": dx,
        "dy_px": dy,
        "tol_px": SLIDE_TOL_PX,
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("usage: gates_visual.py <frame.png>")
        sys.exit(2)
    frame = load_rgb(sys.argv[1])
    ok, nums = gate_edge_bands(frame, (1564, 40, 1920, 240))
    print("edge_bands", "pass" if ok else "fail", nums)
