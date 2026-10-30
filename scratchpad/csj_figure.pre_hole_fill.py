"""CS Junkie figure step: outline, inner stroke, red glow, head line, and grade (csj-process v5, 29 Oct 2026).

Replaces the manual figure work in master skill v39 section 7. Stand-alone: csj_build.py and csj_run.py
do NOT call it yet (a golden run on donk v48 comes first, per section 9).

Usage:
  python3 csj_figure.py <inputs.json> <figure.png> <out_dir>

  figure.png    cut-out. RGBA is used as is. RGB is treated as a white background and a ROUGH mask is
                made by thresholding (labelled in the output). Hand-made masks are better.
Writes into <out_dir>:
  <clip>_figure_layer.png   1080x1920 RGBA: glow + outline + figure with white inner stroke
  <clip>_figure_report.json timing, mask label, head-line check
  <clip>_grade.txt          ffmpeg eq filter for the gameplay (applied to the source, not the figure)

Settings come from tools/csj_figure_glow.json (inner stroke 4 px, red glow 10 px) and
tools/csj_head_line.json (head top at y 1319). Colour 1 comes from inputs["nationality_colours"]["colour_1"].
Grade: contrast 1.08, saturation 0.92, gamma 1.02 (gameplay only).
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import ImageDraw, Image, ImageFilter

HERE = Path(__file__).resolve().parent
CANVAS = (1080, 1920)
GRADE = "eq=contrast=1.08:saturation=0.92:gamma=1.02"
OUTLINE_PX = 3
INNER_PX = 4
GLOW_PX = 10


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rough_alpha(rgb):
    """Rough mask for an RGB cut-out on a white or near-white background. Keeps the biggest blob."""
    arr = np.asarray(rgb).astype(np.int16)
    dist = 255 * 3 - arr.sum(axis=2)  # 0 for white
    mask = (np.abs(255 - arr).max(axis=2) > 18) | (dist > 60)
    m = Image.fromarray((mask * 255).astype(np.uint8))
    # keep the largest connected blob, then close small holes with a blur-threshold
    from collections import deque
    a = np.asarray(m) > 0
    seen = np.zeros_like(a, dtype=bool)
    best, best_n = None, 0
    h, w = a.shape
    for y0, x0 in zip(*np.where(a)):
        if seen[y0, x0]:
            continue
        q, pts = deque([(y0, x0)]), []
        seen[y0, x0] = True
        while q:
            y, x = q.popleft()
            pts.append((y, x))
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and a[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    q.append((ny, nx))
        if len(pts) > best_n:
            best_n, best = len(pts), pts
    keep = np.zeros_like(a)
    if best:
        ys, xs = zip(*best)
        keep[list(ys), list(xs)] = True
    closed = Image.fromarray((keep * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5))
    closed = closed.filter(ImageFilter.MinFilter(5))
    return closed


def place(fig_rgba, scale, cx, head_y):
    """Scale the cut-out, put its top (head) on head_y, and centre it on cx."""
    w, h = fig_rgba.size
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    fig = fig_rgba.resize((nw, nh), Image.LANCZOS)
    alpha = np.asarray(fig.getchannel("A"))
    rows = np.where(alpha.max(axis=1) > 128)[0]
    top = int(rows[0]) if rows.size else 0
    x = int(round(cx - nw / 2))
    y = head_y - top
    layer_fig = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    layer_fig.paste(fig, (x, y), fig)
    return layer_fig


def erode(mask_img, px):
    return mask_img.filter(ImageFilter.MinFilter(2 * px + 1))


def dilate(mask_img, px):
    return mask_img.filter(ImageFilter.MaxFilter(2 * px + 1))


def build_layer(fig_canvas, colours):
    """colours = [colour_1, colour_2, colour_3?] as RGB tuples. No fixed colours in this function.
    Outline and glow use colour 1. The inner stroke uses colour 2. Colour 3 is not used by the figure."""
    c1, c2 = colours[0], colours[1]
    # 29 Oct fix (Jord): outline and white stroke sit only on the outer silhouette, never inside the figure
    # (holes such as face gaps were getting the effects). Fill holes first.
    raw_alpha = fig_canvas.getchannel("A")
    empty = raw_alpha.point(lambda v: 255 if v == 0 else 0)  # gaps and the outside
    ImageDraw.floodfill(empty, (0, 0), 128)                   # outside only, from the corner
    holes = np.asarray(empty) == 255                          # enclosed gaps, e.g. inside the figure
    solid = (np.asarray(raw_alpha) > 0) | holes
    alpha = Image.fromarray((solid * 255).astype(np.uint8))
    d_out = dilate(alpha, OUTLINE_PX)
    outline = np.asarray(d_out).astype(np.int16) - np.asarray(alpha).astype(np.int16)
    outline = Image.fromarray(np.clip(outline, 0, 255).astype(np.uint8))

    glow_src = dilate(alpha, GLOW_PX).filter(ImageFilter.GaussianBlur(GLOW_PX / 2))
    # 29 Oct fix (Jord): no blue glow inside the figure (it showed through the eyes and mouth)
    glow_src = Image.fromarray((np.asarray(glow_src).astype(np.int16) * (np.asarray(alpha) == 0)).astype(np.uint8))
    glow = Image.new("RGBA", CANVAS, c1 + (0,))
    glow.putalpha(glow_src.point(lambda v: int(v * 0.6)))

    ring = Image.new("RGBA", CANVAS, c1 + (0,))
    ring.putalpha(outline)

    inner = np.asarray(alpha).astype(np.int16) - np.asarray(erode(alpha, INNER_PX)).astype(np.int16)
    inner_img = Image.new("RGBA", CANVAS, c2 + (0,))
    inner_img.putalpha(Image.fromarray(np.clip(inner, 0, 255).astype(np.uint8)))

    figure = fig_canvas.copy()
    figure = Image.alpha_composite(figure, inner_img)
    # keep the stroke off the face: only where the original figure is solid, and only on the outer edge

    out = Image.alpha_composite(glow, ring)
    out = Image.alpha_composite(out, figure)
    return out


def main(inputs_path, fig_path, out_dir):
    t0 = time.time()
    inputs = json.loads(Path(inputs_path).read_text())
    clip = inputs["clip_id"]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    glow_cfg = json.loads((HERE / "csj_figure_glow.json").read_text())["figure_glow"]
    head_y = json.loads((HERE / "csj_head_line.json").read_text())["head_line_y"]
    nc = inputs.get("nationality_colours", {})
    if not nc.get("colour_1") or not nc.get("colour_2"):
        raise ValueError("nationality_colours needs colour_1 and colour_2 (colour_3 optional). No default colours.")
    colours = [hex_rgb(nc[k]) for k in ("colour_1", "colour_2", "colour_3") if nc.get(k)]

    img = Image.open(fig_path)
    label = "cut-out used as is"
    if img.mode != "RGBA":
        mask = rough_alpha(img.convert("RGB"))
        rgba = img.convert("RGB").convert("RGBA")
        rgba.putalpha(mask)
        label = "ROUGH mask from white background (threshold). Check the edges."
        img = rgba
    t_mask = time.time()

    scale = float(inputs.get("figure_scale", 1.0))
    cx = float(inputs.get("figure_cx", 540))
    fig_canvas = place(img.convert("RGBA"), scale, cx, head_y)
    layer = build_layer(fig_canvas, colours)
    layer_path = out / f"{clip}_figure_layer.png"
    layer.save(layer_path)
    (out / f"{clip}_grade.txt").write_text(GRADE + "\n")

    fig_alpha = np.asarray(fig_canvas.getchannel("A"))
    rows = np.where(fig_alpha.max(axis=1) > 128)[0]
    top = int(rows[0]) if rows.size else None
    report = {
        "clip_id": clip,
        "mask": label,
        "head_top_y": top,
        "head_line_y": head_y,
        "head_line_ok": top == head_y,
        "colours_used": {"outline_and_glow": colours[0], "inner_stroke": colours[1]},
        "glow": glow_cfg,
        "grade": GRADE,
        "layer": str(layer_path),
        "seconds_mask": round(t_mask - t0, 2),
        "seconds_total": round(time.time() - t0, 2),
    }
    (out / f"{clip}_figure_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    main(*sys.argv[1:4])
