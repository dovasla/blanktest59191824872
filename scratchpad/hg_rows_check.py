import numpy as np
from PIL import Image
import os

DONK = "/mnt/project-files/tools/final_row1.png"
BASE = "/mnt/project-files/tests/heavygod/rows_v2"

def red_mask(a):
    a = a.astype(int)
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    return (R > 130) & (R - G > 70) & (R - B > 70)

donk = Image.open(DONK).convert("RGB")
b = red_mask(np.asarray(donk))
for k in range(1, 6):
    p = f"{BASE}/raw_K{k}.png"
    if not os.path.exists(p):
        print(f"K{k}: missing {p}")
        continue
    im = Image.open(p).convert("RGB")
    s = im.resize(donk.size, Image.LANCZOS)
    a = red_mask(np.asarray(s))
    iou = (a & b).sum() / (a | b).sum()
    print(f"K{k}: size {im.size}, IoU {iou:.3f}, {'PASS' if iou >= 0.30 else 'FAIL'}")
