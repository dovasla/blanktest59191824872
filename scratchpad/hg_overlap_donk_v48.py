import numpy as np
from PIL import Image

HG = "/mnt/project-files/tests/heavygod/rows_v2/accent_K1.png"
DONK = "/mnt/project-files/tools/final_row1.png"  # donk v48 row 1, per csj_donk_v48_build_method.md / csj_row1_gate.py

def red_mask(a):
    a = a.astype(int)
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    return (R > 130) & (R - G > 70) & (R - B > 70)

hg = Image.open(HG).convert("RGB")
donk = Image.open(DONK).convert("RGB")
hg_s = hg.resize(donk.size, Image.LANCZOS)
a = red_mask(np.asarray(hg_s))
b = red_mask(np.asarray(donk))
inter = (a & b).sum(); union = (a | b).sum()
print("donk file", DONK, donk.size)
print("IoU", round(float(inter / union), 3), "share of donk red covered", round(float(inter / b.sum()), 3))
