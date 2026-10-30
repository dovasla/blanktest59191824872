import os
import numpy as np
from PIL import Image, ImageDraw

BASE = "/mnt/project-files/tests/heavygod/rows_v2"
DONK = "/mnt/project-files/tools/final_row1.png"
SS = 8
WHITE, BLUE = (255, 255, 255), (0, 56, 184)
THIRD = BLUE  # no red given for Heavygod; third slot blue

def draw_accents(raw):
    W, H = raw.size
    layer = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for sx, col in zip((4, 9, 14), (WHITE, BLUE, THIRD)):
        d.line([(sx * SS, 14 * SS), ((sx + 7) * SS, 7 * SS)], fill=col + (255,), width=round(2.2 * SS))
    block_x = W - 3 - 150
    for i, col in enumerate((WHITE, BLUE, THIRD)):
        bx = block_x + 50 * i
        d.rectangle([bx * SS, (2.5 - 1.1) * SS, (bx + 50) * SS - 1, (2.5 + 1.1) * SS - 1], fill=col + (255,))
    small = layer.resize((W, H), Image.LANCZOS)
    return Image.alpha_composite(raw.convert("RGBA"), small).convert("RGB")

def red_mask(a):
    a = a.astype(int)
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    return (R > 130) & (R - G > 70) & (R - B > 70)

donk = Image.open(DONK).convert("RGB")
b = red_mask(np.asarray(donk))
for k in (2, 3, 4):
    raw = Image.open(f"{BASE}/raw_K{k}.png").convert("RGB")
    out = draw_accents(raw)
    out.save(f"{BASE}/accent_K{k}.png")
    s = out.resize(donk.size, Image.LANCZOS)
    a = red_mask(np.asarray(s))
    iou = (a & b).sum() / (a | b).sum()
    print(f"K{k}: size {raw.size}, IoU {iou:.3f}, {'PASS' if iou >= 0.30 else 'FAIL'}, accents drawn")
