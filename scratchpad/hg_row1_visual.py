import numpy as np
from PIL import Image, ImageDraw

HG = "/mnt/project-files/tests/heavygod/rows_v2/accent_K1.png"
DONK = "/mnt/project-files/clips/woxic_WOXIC_FIVE_MERCY/work/rows_donk/raw_K1.png"
OUT = "/mnt/project-files/tests/heavygod/rows_v2/row1_visual_check.png"

def red_mask(a):
    a = a.astype(int)
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    return (R > 130) & (R - G > 70) & (R - B > 70)

hg = Image.open(HG).convert("RGB")
donk = Image.open(DONK).convert("RGB")
hg_s = hg.resize(donk.size, Image.LANCZOS)

a = red_mask(np.asarray(hg_s))
b = red_mask(np.asarray(donk))
diff = np.zeros(donk.size[::-1] + (3,), dtype=np.uint8)
diff[a & b] = (0, 180, 0)      # both red: green
diff[a & ~b] = (255, 60, 60)   # heavygod only: red
diff[~a & b] = (60, 120, 255)  # donk only: blue
diff_img = Image.fromarray(diff)

S = 4
W, H = donk.size
canvas = Image.new("RGB", (W * S * 3 + 40, H * S + 60), (255, 255, 255))
labels = ["Heavygod row 1 + accents", "Donk row 1", "Overlap diff (green both, red Heavygod only, blue donk only)"]
for i, im in enumerate([hg_s, donk, diff_img]):
    x = i * (W * S + 20)
    canvas.paste(im.resize((W * S, H * S), Image.NEAREST), (x, 30))
    ImageDraw.Draw(canvas).text((x, 8), labels[i], fill=(0, 0, 0))
canvas.save(OUT)
print(OUT, canvas.size)
