"""CS Junkie banner fit (master skill v39 section 5, donk v48 section 4). Stand-alone helper, called by csj_build.

banner_layer(banner_path, colours_unused=None) -> (RGBA 1080x1920 layer, report)
  - Box 1100x600 at x -10, y 1180 (v39 section 5).
  - The banner keeps its aspect ratio and is centred in the box. Nothing is stretched or cropped.
  - Soft edges: 140 px smoothstep alpha ramp on all four sides.
  - Time fade (visible 0 to 4 s, fade 3.5 to 4.0 s) is applied in csj_build, not here.
  - Banner text must match the top title: checked by the caller, not here.

Usage (test):
  python3 csj_banner.py <banner.png> <out_dir> <clip_id>
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

CANVAS = (1080, 1920)
BOX_W, BOX_H = 1100, 600
BOX_X, BOX_Y = -10, 1100  # 29 Oct: moved up 80 px (Jord)
EDGE_PX = 140


def smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


def edge_alpha(w, h, edge):
    x = np.arange(w)[None, :].astype(float)
    y = np.arange(h)[:, None].astype(float)
    ax = smoothstep(np.minimum(x, w - 1 - x) / edge)
    ay = smoothstep(np.minimum(y, h - 1 - y) / edge)
    return (ax * ay * 255).astype(np.uint8)


def banner_layer(banner_path):
    img = Image.open(banner_path).convert("RGBA")
    iw, ih = img.size
    if (iw, ih) != (BOX_W, BOX_H):
        # locked (skill section 5): the banner file is used as is, never resized. Wrong size stops the build.
        raise ValueError(f"banner is {iw}x{ih}, must be {BOX_W}x{BOX_H} and used as is")
    nw, nh = iw, ih
    fit = img
    alpha = np.asarray(fit.getchannel("A")).astype(float) / 255.0
    fade = edge_alpha(nw, nh, min(EDGE_PX, nw // 2, nh // 2)).astype(float) / 255.0
    fit.putalpha(Image.fromarray((alpha * fade * 255).astype(np.uint8)))
    layer = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    ox = BOX_X + (BOX_W - nw) // 2
    oy = BOX_Y + (BOX_H - nh) // 2
    layer.paste(fit, (ox, oy), fit)
    report = {"banner_in": [iw, ih], "fit": [nw, nh], "placed_at": [ox, oy],
              "stretched": False, "cropped": False, "edge_px": min(EDGE_PX, nw // 2, nh // 2),
              "note": "aspect kept; box is 1100x600 at x -10 y 1180"}
    return layer, report


def main(banner_path, out_dir, clip_id):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    layer, report = banner_layer(banner_path)
    p = out / f"{clip_id}_banner_layer.png"
    layer.save(p)
    report["layer"] = str(p)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main(*sys.argv[1:4])
