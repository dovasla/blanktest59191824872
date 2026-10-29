import numpy as np
from PIL import Image, ImageDraw

RAW = "/mnt/project-files/tests/heavygod/rows_v2/raw_K1.png"
DONK = "/mnt/project-files/clips/woxic_WOXIC_FIVE_MERCY/work/rows_donk/raw_K1.png"
OUT = "/mnt/project-files/tests/heavygod/rows_v2/accent_K1.png"
SS = 8
WHITE, BLUE, RED = (255, 255, 255), (0, 57, 166), (213, 43, 30)  # default guess (Chile palette, Jord said pick best guess)
# Heavygod default colours are not given, so the flag order is white, blue, red (spec), marked as DEFAULT.

raw = Image.open(RAW).convert("RGBA")
W, H = raw.size
layer = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
d = ImageDraw.Draw(layer)

# top-left: 3 stepped 45-degree stripes, 2.2 px thick, from the row's left corner
for sx, col in zip((4, 9, 14), (WHITE, BLUE, RED)):
    x0, y0 = sx, 14
    x1, y1 = sx + 7, 7
    d.line([(x0 * SS, y0 * SS), (x1 * SS, y1 * SS)], fill=col + (255,), width=round(2.2 * SS))

# top-right: 3 bars, 50 px each, 2.2 px high, centred at y 2.5, right-aligned at W - 3 - 150
block_x = W - 3 - 150
for i, col in enumerate((WHITE, BLUE, RED)):
    bx = block_x + 50 * i
    d.rectangle([bx * SS, (2.5 - 1.1) * SS, (bx + 50) * SS - 1, (2.5 + 1.1) * SS - 1], fill=col + (255,))

small = layer.resize((W, H), Image.LANCZOS)
out = Image.alpha_composite(raw, small).convert("RGB")
out.save(OUT)

# row-one overlap vs donk: red-border masks, donk size as the target
def red_mask(a):
    a = a.astype(int)
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    return (R > 130) & (R - G > 70) & (R - B > 70)

donk = Image.open(DONK).convert("RGB")
hg_small = out.resize(donk.size, Image.LANCZOS)
a = red_mask(np.asarray(hg_small))
b = red_mask(np.asarray(donk))
inter = (a & b).sum()
union = (a | b).sum()
print("raw size", raw.size, "donk size", donk.size)
print("overlap IoU accent row vs donk", round(float(inter / union), 3))
print("pixel-wise overlap, share of donk red covered", round(float(inter / b.sum()), 3))
