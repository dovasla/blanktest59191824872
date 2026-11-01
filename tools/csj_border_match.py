"""Border template match. Reads crops only.

Template = the red outline pixels of one row in a frame where its border is complete (chosen by
eye on the contact sheet, then fixed). Score per frame = share of template pixels still red in that
frame (1 px tolerance). Onset = first frame at or after the search start where the score is at or
above SCORE_MIN and stays there for HOLD frames. Flash frames (red share above 25 percent) score 0.
"""
import numpy as np


SCORE_MIN = 0.90
HOLD = 4          # frames the score must stay high (0.067 s at 60 fps)
FLASH_RED = 0.25


def red_mask(fr):
    r = fr[..., 0].astype(np.int16)
    g = fr[..., 1].astype(np.int16)
    b = fr[..., 2].astype(np.int16)
    return (r > 120) & (r - np.maximum(g, b) > 90) & (g < 110) & (b < 110)


def dilate(m, k=1):
    out = m.copy()
    for dy in range(-k, k + 1):
        for dx in range(-k, k + 1):
            out |= np.roll(np.roll(m, dy, 0), dx, 1)
    return out


def template(feed, ref_frame, box):
    x0, y0, x1, y1 = box
    m = red_mask(feed[ref_frame])
    t = np.zeros_like(m)
    sub = m[y0:y1 + 1, x0:x1 + 1]
    # keep only the outline: red pixels on the four border bands of the box
    band = np.zeros_like(sub)
    band[:3] = True; band[-3:] = True; band[:, :3] = True; band[:, -3:] = True
    t[y0:y1 + 1, x0:x1 + 1] = sub & band
    return t


def scores(feed, tmpl):
    tmpl_idx = np.where(tmpl)
    out = np.zeros(len(feed))
    for i in range(len(feed)):
        m = red_mask(feed[i])
        if m.mean() > FLASH_RED:
            continue
        md = dilate(m, 1)
        out[i] = md[tmpl_idx].mean()
    return out


def onset(sc, search_start, search_end, fps):
    for f in range(search_start, search_end):
        if all(sc[f + k] >= SCORE_MIN for k in range(HOLD)):
            return f
    return None
