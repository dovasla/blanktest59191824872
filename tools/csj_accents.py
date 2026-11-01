"""CS Junkie accents: top-left stepped stripes and top-right bars for a kill row (master skill v39 section 6).
Colours are inputs, never fixed. Geometry is the v39 spec and is NOT yet checked against donk row one.

Usage:
  python3 csj_accents.py <inputs.json> <out_dir>

Stripe colours default to [colour_2, colour_3, colour_1] (stripe 1, 2, 3). Top-right bars use colour 1.
Canada and Turkey have no blue, so a stripe that would be blue uses colour 3 when set. Confirm this with Jord.
The layer is drawn for one row origin (row_x, row_y in the 1080x1920 frame). Writes <clip>_accents_layer.png.
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

CANVAS = (1080, 1920)
STRIPE_X = (4, 9, 14)      # left edge of each stripe, from the row's corner (v39 section 6)
STRIPE_T = 2.2             # thickness in px
BAR_X = (120, 170, 220)    # top-right bars, from the row's left edge. 29 Oct: Jord chose bars that fit the row (were 277, 327, 377, which ran past the frame)
BAR_W, BAR_H = 50, 8       # bar height is not in the spec: 8 px, check against donk
BAR_RIGHT_GAP = 6          # 30 Oct: gap from the row's right edge to the white bar
BAR_GAP = 0                # 30 Oct (Jord): no gap between the red and white bars, always


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def colours_from(inputs):
    nc = inputs.get("nationality_colours", {})
    if not nc.get("colour_1") or not nc.get("colour_2"):
        raise ValueError("nationality_colours needs colour_1 and colour_2 (colour_3 optional). No default colours.")
    return [hex_rgb(nc[k]) for k in ("colour_1", "colour_2", "colour_3") if nc.get(k)]


def draw_layer(colours, row_x, row_y, stripe_colours=None, bar_colour=None, row_w=None):
    c1, c2 = colours[0], colours[1]
    c3 = colours[2] if len(colours) > 2 else c1
    stripe_colours = stripe_colours or [c2, c3, c1]
    layer = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    # stepped 45 degree stripes: each is a thin diagonal from the border down-left
    for i, (sx, col) in enumerate(zip(STRIPE_X, stripe_colours)):
        x0, y0 = row_x + sx, row_y + 14
        x1, y1 = row_x + sx + 7, row_y + 7
        d.line([(x0, y0), (x1, y1)], fill=col + (255,), width=round(STRIPE_T))
    if row_w is None:
        # old path: bars from the row's left edge (kept only for old callers)
        for bx in BAR_X:
            d.rectangle([row_x + bx, row_y, row_x + bx + BAR_W - 1, row_y + BAR_H - 1], fill=c1 + (255,))
        return layer
    # 30 Oct (Jord): the top-right accent sits at the row's top right corner, not the middle of the feed box.
    # Two lines, red then white (the nationality colours, as the row text uses red and white).
    # Bars are anchored to the row's right edge, so they follow the row's width.
    right = row_x + row_w - 1 - BAR_RIGHT_GAP
    if len(colours) >= 3:
        # 31 Oct (Jord): three blocks only, colour 1, colour 2, colour 3 (blue, yellow, red for Romania).
        # The colours come from the player's nationality input. Nothing is fixed to one nation here.
        blocks = [c1, c2, c3]
        bw = min(BAR_W, (row_w - BAR_RIGHT_GAP - 1) // len(blocks))
        x = right - bw * len(blocks) + 1
        for col in blocks:
            d.rectangle([x, row_y, x + bw - 1, row_y + BAR_H - 1], fill=tuple(col) + (255,))
            x += bw
        return layer
    white_x0 = right - BAR_W + 1
    red_x0 = white_x0 - BAR_GAP - BAR_W
    d.rectangle([red_x0, row_y, red_x0 + BAR_W - 1, row_y + BAR_H - 1], fill=c1 + (255,))
    d.rectangle([white_x0, row_y, white_x0 + BAR_W - 1, row_y + BAR_H - 1], fill=c2 + (255,))
    return layer


def main(inputs_path, out_dir, row_x="0", row_y="460"):
    # row_x, row_y: top-left corner of the kill row's red border in the frame. The row's x comes from its width.
    inputs = json.loads(Path(inputs_path).read_text())
    clip = inputs["clip_id"]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    colours = colours_from(inputs)
    layer = draw_layer(colours, int(row_x), int(row_y))
    path = out / f"{clip}_accents_layer.png"
    layer.save(path)
    print(json.dumps({"clip_id": clip, "layer": str(path), "stripe_colours_default": "colour 2, 3, 1",
                      "bar_colour": "colour 1", "status": "v39 geometry, not checked against donk row one"}, indent=2))


if __name__ == "__main__":
    main(*sys.argv[1:4])


# 30 Oct (Jord): border cleaning moved here from csj_kill_rows. Used on raw rows; csj_build is not changed.
import numpy as np  # noqa: E402


def clean_border(row):
    """Clear stray red pixels from a raw row. Returns (image, box) with box = (L, T, R, B).

    The border is the rows and columns that are mostly red. Where a crop cut a border off, the
    crop edge is used instead. Red pixels outside the box are cleared (for example a bit of the row
    above that the crop picked up), and so are red specks inside the box on the top and bottom
    second lines, away from the side borders.
    """
    arr = np.asarray(row).astype(int).copy()
    mask = (arr[:, :, 0] > 150) & (arr[:, :, 1] < 90) & (arr[:, :, 2] < 90)
    h, w = mask.shape
    if not mask.any():
        raise ValueError("no red border found in row")
    cols, rws = mask.sum(0), mask.sum(1)
    xs = [x for x in range(w) if cols[x] >= 0.5 * h] or [0, w - 1]
    ys = [y for y in range(h) if rws[y] >= 0.5 * w] or [0, h - 1]
    L, R = min(xs[0], xs[-1]), max(xs[0], xs[-1])
    T, B = min(ys[0], ys[-1]), max(ys[0], ys[-1])
    if L == 0 and R == w - 1 and T == 0 and B == h - 1 and not (cols >= 0.5 * h).any():
        L, R = 0, w - 1
    src = arr.copy()                              # colours to copy from, taken before any change
    outside = mask.copy()
    outside[T:B + 1, L:R + 1] = False
    for y, x in zip(*np.nonzero(outside)):        # stray red outside the box: copy the nearest border colour
        arr[y, x] = src[min(max(y, T), B), min(max(x, L), R)]
    for y, from_y in ((T + 1, T), (B - 1, B)):    # specks on the second border lines, between the side borders
        if 0 <= y < h and rws[y] < 0.5 * w:
            for x in range(L + 2, R - 1):
                if mask[y, x]:
                    arr[y, x] = src[from_y, x]
    return Image.fromarray(arr.astype(np.uint8)), (L, T, R, B)

