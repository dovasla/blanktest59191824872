"""CS Junkie killer-name read by code (29 Oct 2026). Dry run tool: no upload, post or schedule.

Usage:
  python3 tools/csj_killer_names.py <inputs.json> <onsets.json> <out_dir> --source <clip.mp4>
      [--template-t 4.6] [--template-box 30 38 150 62] [--thr 0.6]

Reads the killer name of each kill with no OCR. It matches the killer slot against a template cut from one
legible kill row of the featured player. Only bright, coloured text pixels are used (yellow or blue in the
feed), so the team colour of the row does not matter. The victim name sits outside the killer zone.

Per kill:
  1. Decode the feed crop at 60 fps from 0.6 s before to 1.0 s after the onset.
  2. Score every place the template could sit in the killer zone: 2 * |T and P| / (|T| + |P|).
  3. Ignore places that already held a name just before the row appeared (older rows).
  4. Best new score at or above --thr is a match. Anything below is flagged for review.

Template check: the template row is read by eye. The output records the time and box used, so a wrong
template shows up as every kill failing or every kill matching at once.

Writes:
  <out_dir>/killer_names.json   per kill: status, name, score, match time, position, flags
  <out_dir>/kill_N_zone.png     the killer zone at the best frame, 3x, for an eye check

Onsets come from the onsets file and are not changed here. The kill count is not changed here.
"""
import argparse
import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

FEED_CROP = (1620, 40, 300, 280)  # source x, y, w, h
FPS = 60
TEXT_MAX_MIN = 150  # brightest channel of a text pixel
TEXT_SAT_MIN = 90  # brightest minus darkest channel: coloured text passes, grey icons, white rifle and red border do not
ZONE_X = (30, 150)  # killer zone, top-left x of the template window in the feed crop
PRE_S, POST_S = 0.6, 1.0
BEFORE_FROM_S, BEFORE_TO_S = 0.6, 0.1  # reference frames just before the row appears


def decode(source, t0, dur):
    x, y, w, h = FEED_CROP
    t0 = max(t0, 0.0)
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}", "-i", source, "-t", f"{dur:.3f}",
           "-vf", f"fps={FPS},crop={w}:{h}:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3).astype(np.int16), t0


def text_mask(frames):
    mx = frames.max(axis=-1)
    mn = frames.min(axis=-1)
    return (mx >= TEXT_MAX_MIN) & ((mx - mn) >= TEXT_SAT_MIN)


def build_template(source, t, box):
    """Killer-name template from one legible row. box is x0, y0, x1, y1 in feed crop coordinates."""
    frames, _ = decode(source, t, 1 / FPS)
    mask = text_mask(frames[:1])[0]
    x0, y0, x1, y1 = box
    sub = mask[y0:y1, x0:x1]
    ys, xs = np.where(sub)
    if len(ys) == 0:
        raise SystemExit(f"template box has no text pixels at {t} s. Pick another row or box.")
    tpl = sub[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(float)
    return tpl


def score_maps(masks, tpl):
    """Overlap score at every place in the killer zone, for each frame. masks: (n, h, w) bool."""
    th, tw = tpl.shape
    tsum = tpl.sum()
    x_lo, x_hi = ZONE_X
    region = masks[:, :, x_lo:x_hi + tw].astype(np.float32)
    n, h, w = region.shape
    hp, wp = h - th + 1, w - tw + 1
    inter = np.zeros((n, hp, wp), np.float32)
    for i, j in zip(*np.nonzero(tpl)):  # shift-and-add: one term per template pixel
        inter += region[:, i:i + hp, j:j + wp]
    ii = np.zeros((n, h + 1, w + 1), np.float32)  # integral image for window sums
    ii[:, 1:, 1:] = region.cumsum(axis=1).cumsum(axis=2)
    psum = ii[:, th:th + hp, tw:tw + wp] - ii[:, 0:hp, tw:tw + wp] - ii[:, th:th + hp, 0:wp] + ii[:, 0:hp, 0:wp]
    return 2 * inter / (tsum + psum + 1e-9)


def read_kill(source, onset, tpl, thr, kill_no, out_dir):
    frames, t0 = decode(source, onset - PRE_S, PRE_S + POST_S)
    masks = text_mask(frames)
    times = t0 + np.arange(len(frames)) / FPS
    before = np.where((times >= onset - BEFORE_FROM_S) & (times <= onset - BEFORE_TO_S))[0]
    after = np.where((times >= onset) & (times <= onset + POST_S))[0]
    if len(before) == 0 or len(after) == 0:
        return {"kill": kill_no, "onset_s": round(onset, 3), "status": "flag", "name": None,
                "reason": "no frames in the read window (clip edge)"}
    scores = score_maps(masks, tpl)
    old_ref = scores[before].max(axis=0)  # places that already held a name before the row appeared
    after_scores = scores[after]
    new_scores = np.where(old_ref[None] < thr, after_scores, 0.0)
    best_any = float(after_scores.max())
    k, py, px = np.unravel_index(np.argmax(new_scores), new_scores.shape)
    best_new = float(new_scores[k, py, px])
    frame_i = after[k]
    match_s = float(times[frame_i])
    x_lo = ZONE_X[0] + px
    th, tw = tpl.shape
    result = {"kill": kill_no, "onset_s": round(onset, 3), "best_score": round(best_new, 3),
              "best_any_score": round(best_any, 3), "match_s": round(match_s, 3),
              "pos_xy": [int(x_lo), int(py)]}
    if best_new >= thr:
        result.update({"status": "match", "name": None, "reason": "template match in a new row"})
    else:
        result.update({"status": "flag", "name": None,
                       "reason": f"no new row matched; best new score {best_new:.2f} below {thr}"})
    zone = frames[frame_i][max(py - 6, 0):py + th + 6, max(x_lo - 6, 0):x_lo + tw + 6].astype(np.uint8)
    Image.fromarray(zone).resize((zone.shape[1] * 3, zone.shape[0] * 3), Image.NEAREST).save(
        out_dir / f"kill_{kill_no}_zone.png")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs")
    ap.add_argument("onsets")
    ap.add_argument("out_dir")
    ap.add_argument("--source", required=True)
    ap.add_argument("--template-t", type=float, default=4.6)
    ap.add_argument("--template-box", type=int, nargs=4, default=[30, 38, 150, 62])
    ap.add_argument("--thr", type=float, default=0.6)
    args = ap.parse_args()

    inputs = json.loads(Path(args.inputs).read_text())
    onsets = json.loads(Path(args.onsets).read_text())["kills"]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tpl = build_template(args.source, args.template_t, tuple(args.template_box))
    kills = []
    for k in onsets:
        r = read_kill(args.source, float(k["seconds"]), tpl, args.thr, int(k["kill"]), out_dir)
        if r["status"] == "match":
            r["name"] = inputs["player_name"]
        kills.append(r)

    flags = [f"kill {r['kill']}: {r['reason']}" for r in kills if r["status"] != "match"]
    result = {
        "player_name": inputs["player_name"],
        "dry_run": True,
        "template": {"from_t": args.template_t, "box_xyxy": args.template_box,
                     "shape": list(tpl.shape), "text_px": int(tpl.sum()),
                     "note": "template row read by eye as the featured name; code does not check the letters"},
        "thr": args.thr,
        "kills": kills,
        "flags": flags,
        "pass": not flags,
    }
    (out_dir / "killer_names.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
