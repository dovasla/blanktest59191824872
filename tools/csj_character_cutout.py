"""CS Junkie character cut-out (1 Nov 2026, Jord: every character gets a transparent cut-out first).

Usage:
  python3 csj_character_cutout.py <character.png> <out_rgba.png> [--rect x,y,w,h]

Method: OpenCV GrabCut seeded with a rectangle (default: the central 90 percent of the image), then keeps
the largest connected foreground blob, fills enclosed holes (eyes, teeth, gaps inside the figure), and
softens the outer edge by 1 px. Output is RGBA: transparent background, solid figure.
Needs opencv-python-headless and numpy. Check the result by eye before use.
"""
import sys
import numpy as np
import cv2
from PIL import Image


def cutout(src, out, rect=None):
    img = cv2.imread(src, cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    if rect is None:
        rect = (int(w * 0.05), int(h * 0.03), int(w * 0.9), int(h * 0.94))
    mask = np.zeros((h, w), np.uint8)
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(img, mask, rect, bgd, fgd, 6, cv2.GC_INIT_WITH_RECT)
    fg = np.where((mask == 1) | (mask == 3), 255, 0).astype(np.uint8)
    # keep the largest blob
    n, lab, stats, _ = cv2.connectedComponentsWithStats(fg)
    if n > 1:
        big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        fg = np.where(lab == big, 255, 0).astype(np.uint8)
    # fill holes: flood the background from the border, anything not reached is inside the figure
    inv = cv2.bitwise_not(fg)
    ff = inv.copy()
    cv2.floodFill(ff, np.zeros((h + 2, w + 2), np.uint8), (0, 0), 0)
    fg = np.where(ff == 255, 255, fg).astype(np.uint8)
    fg = cv2.GaussianBlur(fg, (3, 3), 0.7)
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    rgba = np.dstack([rgb, fg])
    Image.fromarray(rgba, "RGBA").save(out)
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    rect = None
    if "--rect" in a:
        i = a.index("--rect")
        rect = tuple(int(v) for v in a[i + 1].split(","))
        del a[i:i + 2]
    print(cutout(a[0], a[1], rect))
