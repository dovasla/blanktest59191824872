"""Automatic timing gate for CS Junkie clips (first-visible onsets, edge cross-check).

Usage (CLI, for a feed array already on disk):
  python3 csj_timing_gate.py --feed feed.npy --kills kills.json [--timings clip_timings.json]

Called from csj_gates.py with a KillFeed (decodes only the frames each check reads).

kills.json: list of {"kill": n, "name": "NQZ", "box": [x0,y0,x1,y1], "ref": full_register_frame}
  box = the row's slot in the 60 fps feed crop, ref = a settled full-register frame.
feed: indexable by absolute frame number; each item is the 60 fps feed crop (1620,40,300,280) as RGB.

Method per kill:
  1. Build a template from the settled frame, one mask per outline edge (top, bottom, left, right).
  2. First-visible per edge = first frame where that edge reads >= 0.30 for 3 frames in a row,
     searched from ref-120 to ref. The slot must be empty for 8 frames before the reading, else the edge is None.
  3. Cross-check: the edges must agree within 2 frames. Primary onset = median of the four edges.
  4. If build onsets are given, the build's slide start (onset_s * 60) must match the primary onset within 2 frames.
Exit 0 = pass, 1 = fail.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from csj_border_match import red_mask  # noqa: E402

FPS = 60
FEED_CROP = (1620, 40, 300, 280)  # source pixels
THR, HOLD, TOL = 0.30, 3, 2
SPREAD_TOL = 4  # max frames between the four edges. Jord chose 4 on 29 Oct.
ONSET_LEAD = 3  # locked onset rule (Jord, 28 Oct): onset = first visible frame minus 3
EMPTY_BEFORE = 8
EMPTY_LEVEL = 0.30


class KillFeed:
    """Feed-crop frames for the kill checks only: 120 frames before each ref, and the ref itself."""

    def __init__(self, source, kills, before=120):
        x, y, w, h = FEED_CROP
        self.frames = {}
        for k in kills:
            lo, hi = max(0, int(k["ref"]) - before), int(k["ref"])
            if all(f in self.frames for f in range(lo, hi + 1)):
                continue
            n = hi - lo + 1
            raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{lo / FPS:.6f}", "-i", source,
                                  "-frames:v", str(n), "-vf", f"crop={w}:{h}:{x}:{y}",
                                  "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                 capture_output=True, check=True).stdout
            arr = np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)
            for i in range(arr.shape[0]):
                self.frames[lo + i] = arr[i]

    def __getitem__(self, f):
        return self.frames[f]


def edge_templates(m, box):
    x0, y0, x1, y1 = box
    e = {
        "top": (slice(y0, y0 + 3), slice(x0, x1 + 1)),
        "bottom": (slice(y1 - 2, y1 + 1), slice(x0, x1 + 1)),
        "left": (slice(y0, y1 + 1), slice(x0, x0 + 3)),
        "right": (slice(y0, y1 + 1), slice(x1 - 2, x1 + 1)),
    }
    out = {}
    for k, (ys, xs) in e.items():
        T = np.zeros_like(m)
        T[ys, xs] = m[ys, xs]
        out[k] = T
    return out


def first_visible(feed, frames, T):
    """First frame where the edge reads >= THR for HOLD frames, after EMPTY_BEFORE empty frames. None if occupied."""
    n = T.sum()
    vals = [(red_mask(np.asarray(feed[f])) & T).sum() / n for f in frames]
    for i in range(EMPTY_BEFORE, len(vals) - HOLD + 1):
        if all(v >= THR for v in vals[i:i + HOLD]) and all(v < EMPTY_LEVEL for v in vals[i - EMPTY_BEFORE:i]):
            return frames[i]
    return None


def check_kills(feed, kills, build_onsets=None):
    """Returns (ok, records). kills: list of {"kill", "name", "box", "ref"}. build_onsets: seconds, same order."""
    records, ok_all = [], True
    for idx, k in enumerate(kills):
        ref = int(k["ref"])
        m = red_mask(np.asarray(feed[ref]))
        frames = list(range(max(0, ref - 120), ref + 1))
        edges = {name: first_visible(feed, frames, T) for name, T in edge_templates(m, k["box"]).items()}
        vals = [v for v in edges.values() if v is not None]
        rec = {"kill": k.get("kill", idx + 1), "name": k.get("name"), "edges": edges}
        if len(vals) < 4:
            rec.update({"pass": False, "reason": "no first-visible frame on some edge"})
        else:
            spread = max(vals) - min(vals)
            primary = int(np.median(vals))
            rec.update({"primary": primary, "seconds": round(primary / FPS, 4), "spread": spread})
            rec["pass"] = spread <= SPREAD_TOL
            rec["reason"] = f"edges disagree by {spread} frames" if spread > SPREAD_TOL else "edges agree"
            if build_onsets is not None:
                slide = round(build_onsets[idx] * FPS)
                diff = (slide + ONSET_LEAD) - primary
                rec["slide_frame"] = slide
                rec["expected_first_visible"] = slide + ONSET_LEAD
                rec["slide_diff"] = diff
                if abs(diff) > TOL:
                    rec["pass"] = False
                    rec["reason"] += f"; slide start differs by {diff} frames"
        ok_all = ok_all and rec["pass"]
        records.append(rec)
    return ok_all and bool(records), records


def first_visible_kill(source, box, ref):
    """First-visible frame for one kill, for csj_onset_check.py. Returns fv_* keys; fv_pass is False unless all four edges agree."""
    kills = [{"kill": 1, "name": "", "box": box, "ref": int(ref)}]
    ok, recs = check_kills(KillFeed(source, kills), kills)
    r = recs[0]
    return {"fv_pass": ok, "fv_first_visible": r.get("primary"), "fv_edges": r["edges"],
            "fv_spread": r.get("spread"), "fv_reason": r["reason"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", required=True)
    ap.add_argument("--kills", required=True)
    ap.add_argument("--timings")
    a = ap.parse_args()
    feed = np.load(a.feed, mmap_mode="r")
    kills = json.load(open(a.kills))
    build = json.load(open(a.timings))["onset_s"] if a.timings else None
    ok, recs = check_kills(feed, kills, build)
    for r in recs:
        print(json.dumps(r))
    print("TIMING GATE:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
