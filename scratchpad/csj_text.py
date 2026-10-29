"""CS Junkie top title (master skill v39 section 7). Colours are inputs, never fixed.

Usage:
  python3 csj_text.py <inputs.json> <out_dir>

Reads inputs["top_title"] and inputs["nationality_colours"] (colour_1, colour_2, colour_3 optional).
Each word takes the next colour in order: word 1 = colour 1, word 2 = colour 2, word 3 = colour 3.
With only two colours the order repeats: colour 1, colour 2, colour 1. The title is uppercase.
Writes <clip>_title_layer.png (1080x1920 RGBA, title at the top of the frame) and <clip>_title_report.json.
Placement (top band, y 60 to 200, centred) is a default. Check it against the rows before a link.
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
CANVAS = (1080, 1920)
FONT = HERE / "fonts" / "BarlowCondensed-Black.ttf"
BAND_TOP, BAND_BOTTOM = 60, 200
MAX_WIDTH = 1000


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def colours_from(inputs):
    nc = inputs.get("nationality_colours", {})
    if not nc.get("colour_1") or not nc.get("colour_2"):
        raise ValueError("nationality_colours needs colour_1 and colour_2 (colour_3 optional). No default colours.")
    return [hex_rgb(nc[k]) for k in ("colour_1", "colour_2", "colour_3") if nc.get(k)]


def word_colours(n_words, colours):
    # word i takes colour i, cycling through the colours given (2 colours repeat as 1, 2, 1)
    return [colours[i % len(colours)] for i in range(n_words)]


def render(title, colours):
    words = title.upper().split()
    cols = word_colours(len(words), colours)
    size = 200
    while True:
        font = ImageFont.truetype(str(FONT), size)
        widths = [font.getbbox(w)[2] - font.getbbox(w)[0] for w in words]
        gap = int(size * 0.18)
        total = sum(widths) + gap * (len(words) - 1)
        if total <= MAX_WIDTH or size <= 40:
            break
        size -= 6
    layer = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    x = (CANVAS[0] - total) // 2
    box_h = font.getbbox("HG")[3]
    y = BAND_TOP + (BAND_BOTTOM - BAND_TOP - box_h) // 2
    for w, c, wd in zip(words, cols, widths):
        draw.text((x - font.getbbox(w)[0], y), w, font=font, fill=c + (255,))
        x += wd + gap
    return layer, size, cols


def main(inputs_path, out_dir):
    inputs = json.loads(Path(inputs_path).read_text())
    clip = inputs["clip_id"]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    colours = colours_from(inputs)
    layer, size, cols = render(inputs["top_title"], colours)
    path = out / f"{clip}_title_layer.png"
    layer.save(path)
    report = {"clip_id": clip, "title": inputs["top_title"].upper(), "font_px": size,
              "word_colours": ["#%02X%02X%02X" % c for c in cols], "band_y": [BAND_TOP, BAND_BOTTOM],
              "layer": str(path), "placement": "default, check against rows"}
    (out / f"{clip}_title_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main(*sys.argv[1:3])
