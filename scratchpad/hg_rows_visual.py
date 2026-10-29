import numpy as np
from PIL import Image, ImageDraw

BASE = "/mnt/project-files/tests/heavygod/rows_v2"
DONK = "/mnt/project-files/tools/final_row1.png"
OUT = f"{BASE}/rows_1_to_4_visual_check.png"

def red_mask(a):
    a = a.astype(int)
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    return (R > 130) & (R - G > 70) & (R - B > 70)

donk = Image.open(DONK).convert("RGB")
W, H = donk.size
b = red_mask(np.asarray(donk))
S = 3
rows = [f"{BASE}/accent_K1.png", f"{BASE}/accent_K2.png", f"{BASE}/accent_K3.png", f"{BASE}/accent_K4.png"]
row_h = H * S
label_w = 40
canvas_w = label_w + (W * S) * 3 + 40
canvas_h = len(rows) * (row_h + 30) + 40
canvas = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
d = ImageDraw.Draw(canvas)

for i, path in enumerate(rows):
    hg = Image.open(path).convert("RGB")
    hg_s = hg.resize(donk.size, Image.LANCZOS)
    a = red_mask(np.asarray(hg_s))
    iou = (a & b).sum() / (a | b).sum()
    diff = np.zeros((H, W, 3), dtype=np.uint8)
    diff[a & b] = (0, 180, 0)
    diff[a & ~b] = (255, 60, 60)
    diff[~a & b] = (60, 120, 255)
    diff_img = Image.fromarray(diff)
    y = 40 + i * (row_h + 30)
    d.text((10, y + row_h // 2), f"K{i+1}", fill=(0, 0, 0))
    panels = [
        (hg.resize((hg.size[0] * S, hg.size[1] * S), Image.NEAREST), f"Heavygod row {i+1} ({hg.size[0]}x{hg.size[1]}, IoU {iou:.2f})"),
        (donk.resize((W * S, H * S), Image.NEAREST), "Donk row 1 (56 px)"),
        (diff_img.resize((W * S, H * S), Image.NEAREST), "Overlap diff: green both, red Heavygod only, blue donk only"),
    ]
    x = label_w
    for im, lab in panels:
        canvas.paste(im, (x, y))
        d.text((x, y - 16), lab, fill=(0, 0, 0))
        x += W * S + 20
canvas.save(OUT)
print(OUT, canvas.size)
