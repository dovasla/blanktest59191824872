"""CS Junkie kill rows by code: each row gets its accents inside its own red border, then rows are overlaid.

Accents (Jord, 29 Oct 2026):
  Top left: three diagonal stripes running up to the right, inside the row box at its top left corner.
  Top right: one solid band per nationality colour, inside the row box at its top right corner.
    Two colours give two bands, three colours give three bands, in the order the colours are listed.
  The row box is measured from the row's own red border on every row, so nothing sits at a fixed offset.
  The accents are drawn into the row PNG, so they show on the same frame as the row.

Usage:
  python3 csj_kill_rows.py <inputs.json> <out_dir> [--render]

inputs.json keys:
  clip_id, source, scale (default 1.5), colours (list of hex, e.g. ["#0038B8", "#FFFFFF"]),
  right_edge (default 1868), row_y0 (default 460), row_step (default 60), hold_s (default 5.0),
  rows: [{kill, png, onset_s, onset_status}]   onset_status is VERIFIED or ESTIMATED.
--render also writes a test MP4 (dry run: nothing is uploaded, posted or scheduled).

Geometry is in row pixels at scale 1.0, measured from the red border, then multiplied by scale.
Drawn at 8x and shrunk for clean edges.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

SS = 8                        # supersample factor for clean edges
STRIPE_DX = (0, 5, 10)        # stripe start x, from the red border's inner left edge
STRIPE_LEN = (5, 6.5, 8)      # stripe lengths inside the box
STRIPE_START_DY = 9           # stripe start, px below the red border's top edge
BAND_W, BAND_H = 20, 1.5              # top right thin line: one segment per colour, joined with no gap
INSET = 1                     # px inside the red border


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


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


def build_row(png_path, scale, colours):
    """Return an RGBA row image with accents inside its red border."""
    row, (L, T, R, B) = clean_border(Image.open(png_path).convert("RGB"))
    w, h = round(row.width * scale), round(row.height * scale)
    img = row.resize((w, h), Image.LANCZOS).convert("RGBA")
    blue, white = colours[0], colours[1]

    big = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    n = (0.7071, 0.7071)
    stripe_cols = (white, blue, white)
    for dx, length, col in zip(STRIPE_DX, STRIPE_LEN, stripe_cols):
        ax = (L + INSET + dx) * scale
        ay = (T + STRIPE_START_DY) * scale
        bx = ax + length * scale * 0.7071
        by = ay - length * scale * 0.7071
        t = 2.2 * scale / 2
        pts = [(ax + n[0] * t, ay + n[1] * t), (bx + n[0] * t, by + n[1] * t),
               (bx - n[0] * t, by - n[1] * t), (ax - n[0] * t, ay - n[1] * t)]
        d.polygon([(px * SS, py * SS) for px, py in pts], fill=col + (255,))

    top = (T + INSET) * scale            # thin line just inside the top border, in the top right corner
    band_h = BAND_H * scale
    seg_w = BAND_W * scale
    x_right = (R - INSET + 1) * scale    # flush to the inner right edge of the box
    count = len(colours)
    x_start = x_right - count * seg_w
    for j, col in enumerate(colours):    # segments share edges, so the line has no gap
        x0 = x_start + j * seg_w
        x1 = x0 + seg_w
        d.rectangle([x0 * SS, top * SS, x1 * SS, (top + band_h) * SS], fill=col + (255,))

    accents = big.resize((w, h), Image.LANCZOS)
    return Image.alpha_composite(img, accents)


def contact_sheet(rows, path):
    width = max(r.width for r in rows) + 40
    height = sum(r.height + 30 for r in rows) + 20
    sheet = Image.new("RGBA", (width, height), (90, 90, 90, 255))
    y = 10
    for r in rows:
        sheet.alpha_composite(r, (20, y))
        y += r.height + 30
    sheet.convert("RGB").save(path)


def render(inputs, placed, out_dir, clip):
    src = inputs["source"]
    out_mp4 = out_dir / f"{clip}_rows_test.mp4"
    cmd = ["ffmpeg", "-y", "-i", src]
    for p in placed:
        cmd += ["-loop", "1", "-i", str(p["layer_path"])]
    chain, last = [], "[0:v]"
    for i, p in enumerate(placed, start=1):
        out_label = f"[v{i}]"
        chain.append(f"{last}[{i}:v]overlay={p['x']}:{p['y']}:enable='between(t,{p['on']:.3f},{p['off']:.3f})'{out_label}")
        last = out_label
    cmd += ["-filter_complex", ";".join(chain), "-map", last, "-map", "0:a?",
            "-t", str(inputs.get("render_seconds", 20)),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "copy", str(out_mp4)]
    subprocess.run(cmd, check=True)
    return out_mp4


def main(inputs_path, out_dir, flag=""):
    inputs = json.loads(Path(inputs_path).read_text())
    clip = inputs["clip_id"]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    scale = float(inputs.get("scale", 1.5))
    colours = [hex_rgb(c) for c in inputs["colours"]]
    right_edge = int(inputs.get("right_edge", 1868))
    y0 = int(inputs.get("row_y0", 460))
    step = int(inputs.get("row_step", 60))
    hold = float(inputs.get("hold_s", 5.0))

    rows, placed, report = [], [], []
    for i, r in enumerate(sorted(inputs["rows"], key=lambda r: r["onset_s"])):
        img = build_row(r["png"], scale, colours)
        rows.append(img)
        layer_path = out / f"{clip}_K{r['kill']}_row.png"
        img.save(layer_path)
        x = right_edge - img.width
        y = y0 + i * step
        placed.append({"layer_path": layer_path, "x": x, "y": y,
                       "on": r["onset_s"], "off": r["onset_s"] + hold})
        report.append({"kill": r["kill"], "onset_s": r["onset_s"], "onset_status": r["onset_status"],
                       "row_png": str(layer_path), "x": x, "y": y, "size": list(img.size)})

    contact_sheet(rows, out / f"{clip}_rows_contact.png")
    (out / f"{clip}_rows_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))

    if flag == "--render":
        mp4 = render(inputs, placed, out, clip)
        print(f"test render: {mp4}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
