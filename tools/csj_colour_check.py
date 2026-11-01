"""CS Junkie colour check (master skill v40 section 5 and 16). Blocking check in csj_run, before the build.

Colour order (default, OPEN for Jord in v40 section 5). colour_1, colour_2, colour_3 come from inputs:
  outline           = colour 1
  top title         = one colour per word, in order 1, 2, 3 (2 colours repeat 1, 2, 1)
  top-left stripes  = colour 2, colour 3, colour 1 (stripe 1, 2, 3). With 2 colours, stripe 2 uses colour 1.
  top-right bars   = colour 1

check(inputs, layers_dir=None) -> {"pass": bool, "flags": [...], "colours": [...], "checked": [...]}
  1. Colours: colour_1 and colour_2 required (no default colours). colour_3 optional. Hex, distinct.
     Canada and Turkey: no blue (v40 section 8). Set "nation" in inputs to enable.
  2. Build check: the title, accents and figure layers are made by the same functions the build uses
     (csj_text.render, csj_accents.draw_layer, csj_figure.build_layer). Their pixels are read back and
     compared with the order above. A wrong order fails here.
  3. Saved layers: if layers_dir is given, the saved <clip>_title_layer.png, <clip>_accents_layer.png and
     <clip>_figure_layer.png in that folder are read back and checked the same way.

Usage:
  python3 csj_colour_check.py <inputs.json> [layers_dir]
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import csj_accents  # noqa: E402
import csj_figure  # noqa: E402
import csj_text  # noqa: E402

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
NO_BLUE = {"canada", "turkey"}
TOL = 12                      # colour match tolerance, sum of absolute RGB differences
MIN_PIXELS = 50               # a colour that appears on a layer must cover at least this many pixels
ACCENT_ORIGIN = (0, 460)      # same row origin the accents tool uses by default


def is_blue(rgb):
    r, g, b = rgb
    return b > 120 and b > r + 40 and b > g + 20


def hex_rgb(h):
    return tuple(int(h.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))


def plan(colours):
    """The colour order the build must use. colours = [c1, c2, c3?] as RGB tuples."""
    c1, c2 = colours[0], colours[1]
    c3 = colours[2] if len(colours) > 2 else c1
    return {"outline": c1, "title": colours, "stripes": [c2, c3, c1], "bars": c1}


def solid_rgb(layer):
    a = np.asarray(layer.convert("RGBA")).astype(int)
    return a[..., :3], a[..., 3] > 250


def hits(rgb, solid, colour):
    return solid & (np.abs(rgb - np.array(colour)).sum(axis=-1) <= TOL)


def dominant(rgb, solid, palette):
    """Colour with the most solid pixels in the box, and its count."""
    counts = {c: int(hits(rgb, solid, c).sum()) for c in set(palette)}
    best = max(counts, key=counts.get)
    return best, counts[best], counts


def name(colour, colours):
    """'colour 1' style name for an RGB value, or the hex when it is not one of the clip's colours."""
    for i, c in enumerate(colours, start=1):
        if tuple(c) == tuple(colour):
            return f"colour {i}"
    return "#%02X%02X%02X" % tuple(colour)


def check_title(layer, colours, title):
    words = str(title or "").upper().split()
    if not words:
        return ["top_title is missing or empty"]
    rgb, solid = solid_rgb(layer)
    flags = []
    # the colour index of each column that holds solid title pixels
    seq = []
    for x in range(rgb.shape[1]):
        col_hits = [i for i, c in enumerate(colours) if hits(rgb[:, x:x + 1], solid[:, x:x + 1], c).any()]
        if not col_hits:
            continue
        if len(col_hits) > 1:
            flags.append(f"title column {x} mixes colours {[i + 1 for i in col_hits]}")
            continue
        if not seq or seq[-1] != col_hits[0]:
            seq.append(col_hits[0])
    # expected: word i takes colour i, cycling (2 colours: 1, 2, 1)
    expected = []
    for i in range(len(words)):
        v = i % len(colours)
        if not expected or expected[-1] != v:
            expected.append(v)
    got = [f"colour {i + 1}" for i in seq]
    want = [f"colour {i + 1}" for i in expected]
    if seq != expected:
        flags.append(f"title colour order is {got}, expected {want} (word order 1, 2, 3)")
    return flags


def check_accents(layer, colours, origin=ACCENT_ORIGIN):
    flags = []
    p = plan(colours)
    rgb, solid = solid_rgb(layer)
    ox, oy = origin
    for i, (sx, want) in enumerate(zip(csj_accents.STRIPE_X, p["stripes"]), start=1):
        x0 = ox + sx
        box = (slice(oy + 6, oy + 16), slice(x0, x0 + 8))
        got, n, counts = dominant(rgb[box], solid[box], colours)
        if got != want or counts[want] < 4:
            flags.append(f"stripe {i} is {name(got, colours)}, expected {name(want, colours)}")
    # fix2 layout (31 Oct, scratch copy): red bar then white bar at the row's top right, no gap between them
    bh = csj_accents.BAR_H
    rgbt, st = rgb[oy:oy + bh], solid[oy:oy + bh]
    def full_cols(c):
        m = st & (rgbt[..., 0] == c[0]) & (rgbt[..., 1] == c[1]) & (rgbt[..., 2] == c[2])
        return np.nonzero(m.sum(axis=0) == bh)[0]
    red_cols, white_cols = full_cols(colours[0]), full_cols(colours[1])
    if red_cols.size < 0.9 * csj_accents.BAR_W or white_cols.size < 0.9 * csj_accents.BAR_W:
        flags.append(f"accent bars not found: red {red_cols.size} px, white {white_cols.size} px")
    elif not (white_cols.min() == red_cols.max() + 1 and red_cols.max() < white_cols.min()):
        flags.append("accent bars: red and white do not touch, or are in the wrong order")
    return flags


def check_outline(layer, colours, outside=None):
    """Outline is colour 1. With outside (a mask of pixels that are not the figure), the ring pixels there
    must be colour 1. The inner stroke (colour 2) sits inside the figure, so it is not counted.
    Without a mask (a saved layer), only presence of colour 1 is checked."""
    rgb, solid = solid_rgb(layer)
    want = plan(colours)["outline"]
    if outside is None:
        n = int(hits(rgb, solid, want).sum())
        return [] if n >= MIN_PIXELS else [f"outline has no colour 1 pixels ({n} found)"]
    ring_rgb = rgb[solid & outside]
    counts = {c: int((np.abs(ring_rgb - np.array(c)).sum(axis=-1) <= TOL).sum()) for c in colours}
    got = max(counts, key=counts.get)
    if got != want or counts[want] < MIN_PIXELS:
        return [f"outline is {name(got, colours)}, expected colour 1 ({counts[want]} colour 1 pixels)"]
    return []


def build_layers(colours, title):
    """Layers made by the build's own functions, no files written. Also returns the mask of pixels
    outside the synthetic figure, where only the outline can be."""
    title_layer, _, _ = csj_text.render(str(title or "").upper() or "X", colours)
    accents_layer = csj_accents.draw_layer(colours, *ACCENT_ORIGIN, row_w=508)
    fig = Image.new("RGBA", csj_figure.CANVAS, (0, 0, 0, 0))
    ImageDraw.Draw(fig).ellipse((380, 600, 700, 1300), fill=(128, 128, 128, 255))
    figure_layer = csj_figure.build_layer(fig, colours)
    outside = np.asarray(fig.getchannel("A")) == 0
    return {"title": title_layer, "accents": accents_layer, "figure": figure_layer}, outside


def check_layer(kind, layer, colours, title, outside=None, origin=None):
    if kind == "title":
        return check_title(layer, colours, title)
    if kind == "accents":
        return check_accents(layer, colours, origin or ACCENT_ORIGIN)
    return check_outline(layer, colours, outside)


def check(inputs, layers_dir=None, accent_origin=None):
    flags = []
    checked = []
    nc = inputs.get("nationality_colours", {})
    keys = [k for k in ("colour_1", "colour_2", "colour_3") if nc.get(k)]
    if "colour_1" not in keys or "colour_2" not in keys:
        flags.append("colour_1 and colour_2 are required. No default colours.")
    for k in keys:
        if not HEX.match(nc[k]):
            flags.append(f"{k} is not a hex colour: {nc[k]}")
    rgbs = [hex_rgb(nc[k]) for k in keys if HEX.match(nc[k])]
    if len(set(rgbs)) != len(rgbs):
        flags.append("two colours are the same")
    nation = str(inputs.get("nation", "")).lower()
    if nation in NO_BLUE and any(is_blue(c) for c in rgbs):
        flags.append(f"{nation} has no blue. A blue colour is set.")

    if not flags:
        title = inputs.get("top_title")
        layers, outside = build_layers(rgbs, title)
        for kind, layer in layers.items():
            mask = outside if kind == "figure" else None
            flags += [f"built {kind}: {f}" for f in check_layer(kind, layer, rgbs, title, mask)]
            checked.append(f"built {kind} layer")
        if layers_dir:
            clip = inputs["clip_id"]
            for kind in ("title", "accents", "figure"):
                p = Path(layers_dir) / f"{clip}_{kind}_layer.png"
                if not p.exists():
                    continue
                layer = Image.open(p).convert("RGBA")
                flags += [f"saved {kind}: {f}" for f in check_layer(kind, layer, rgbs, title, origin=accent_origin)]
                checked.append(f"saved {kind} layer")

    return {"pass": not flags, "flags": flags, "colours": [nc.get(k) for k in keys], "checked": checked}


if __name__ == "__main__":
    inp = json.loads(Path(sys.argv[1]).read_text())
    res = check(inp, sys.argv[2] if len(sys.argv) > 2 else None)
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["pass"] else 1)
