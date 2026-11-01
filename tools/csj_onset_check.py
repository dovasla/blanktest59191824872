"""CS Junkie onset check (csj-process v3, Step 2). Runs before any build.

Usage:
  python3 csj_onset_check.py <inputs.json> <candidates.json> <onsets_out.json>

candidates.json: {"kills": [{"seconds": 8.10}, ...]} from the onset search (own-kill rows, in order).
For each candidate, the feed crop is decoded only around that candidate (+/- 1.5 s), so memory stays small.

Strict full-border rule (Brev, 21 Oct): the onset is the first frame where the row's red outline is complete on
ALL FOUR sides at once. A side is complete when at least 80% of its length is red. The row box is found in the
same frame from the red pixels. The onset must also be within 0.20 s of the candidate, or the kill is flagged.

The name check (csj_onsets.py name, still a stub) is NOT part of this script. Every kill is marked name_check: "not run".

Output: onsets JSON with "pass": true only when every kill passes. csj_build.py refuses to build when pass is false.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import csj_feedcache  # noqa: E402
import csj_timing_gate  # noqa: E402

FEED_CROP = (1620, 40, 300, 280)  # source pixels, csj-process Step 2
SIDE_FRACTION = 0.80
FLASH_FRAC = 0.25  # share of the feed crop changing in one frame that marks a flash or scene cut
SIDE_MIN = 0.60  # per-clip calibration (21 Oct, P5): anti-aliased outlines reach 0.6 to 1.0 per side
MAX_OFFSET_S = 0.20
WINDOW_S = 1.5
LEAD_FRAMES = 3  # locked onset rule (Jord, 28 Oct): onset = first visible frame minus 3


def red_mask(frames):
    """Red outline pixels, fixed rule (csj-process Step 2). Tried a saturation-relative rule on P5 on
    21 Oct: it caught the orange map and broke the other kills, so the fixed rule is restored."""
    r, g, b = frames[..., 0], frames[..., 1], frames[..., 2]
    return (r > 200) & (g < 50) & (b < 50)


def decode_window(source, start, dur, fps):
    x, y, w, h = FEED_CROP
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{max(start, 0):.3f}", "-i", source, "-t", f"{dur:.3f}",
           "-vf", f"crop={w}:{h}:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)
    return frames, max(start, 0.0)


def side_scores(mask):
    """Coverage of each side of the row box in one frame: (box, min side coverage)."""
    rows = np.where(mask.sum(axis=1) >= 8)[0]
    cols = np.where(mask.sum(axis=0) >= 4)[0]
    if len(rows) < 2 or len(cols) < 2:
        return None, 0.0
    y0, y1, x0, x1 = rows[0], rows[-1], cols[0], cols[-1]
    if x1 - x0 < 20 or y1 - y0 < 10:
        return None, 0.0
    sides = [mask[y0, x0:x1 + 1].mean(), mask[y1, x0:x1 + 1].mean(),
             mask[y0:y1 + 1, x0].mean(), mask[y0:y1 + 1, x1].mean()]
    return [int(x0), int(y0), int(x1), int(y1)], float(min(sides))


def full_border(mask):
    """Return (box, ok). box is x0, y0, x1, y1 of the red pixels, ok when all four sides are complete."""
    rows = np.where(mask.sum(axis=1) >= 8)[0]
    cols = np.where(mask.sum(axis=0) >= 4)[0]
    if len(rows) < 2 or len(cols) < 2:
        return None, False
    y0, y1, x0, x1 = rows[0], rows[-1], cols[0], cols[-1]
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    if bw < 20 or bh < 10:
        return None, False
    top = mask[y0, x0:x1 + 1].mean()
    bottom = mask[y1, x0:x1 + 1].mean()
    left = mask[y0:y1 + 1, x0].mean()
    right = mask[y0:y1 + 1, x1].mean()
    ok = min(top, bottom, left, right) >= SIDE_FRACTION
    return [int(x0), int(y0), int(x1), int(y1)], bool(ok)


def feed_threshold(source, fps, dur):
    """Per-clip rise threshold (21 Oct review fix 4). Rows drawn smaller give fewer red pixels, so the
    fixed 300 px is scaled from this clip's own feed: 0.3 x the 98th percentile of red counts, clamped to
    [120, 300]. Stops (returns None) when the feed is not found (98th percentile below 120 px)."""
    scan = csj_feedcache.SCAN_FPS
    if fps % scan == 0 and fps >= scan:
        # Speed (1 Nov 2026, Jord): the whole-clip scan runs at 30 fps, not the source rate. Every third
        # 30 fps count is the same frame the fps=10 filter returned, so the threshold is unchanged.
        counts = csj_feedcache.scan_red_counts(source, scan)[::scan // 10][:int(np.ceil(dur * 10))]
    elif fps % 10 == 0:
        # Speed (27 Oct 2026): read every step-th frame of the cached source-rate red counts, the same
        # frames the fps=10 filter returned (checked on 68790a62: same p98). One decode per source.
        step = int(fps // 10)
        counts = csj_feedcache.red_counts(source)[::step][:int(np.ceil(dur * 10))]
    else:
        x, y, w, h = FEED_CROP
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", source, "-t", f"{dur:.3f}", "-vf",
                              f"fps=10,crop={w}:{h}:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True, check=True).stdout
        fr = np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3).astype(np.int16)
        counts = red_mask(fr).sum(axis=(1, 2))
    p98 = float(np.percentile(counts, 98))
    if p98 < 120:
        return None, p98
    return int(min(300, max(120, 0.3 * p98))), p98


def outline_pixels(frames, g, before, fallback):
    """Per-clip outline calibration (21 Oct, P5). The outline is the reddish pixels that CHANGED between the
    frame before the row appeared and the frame it is complete. Calibrated from this clip's own pixels, so
    the darker outline on P5 is found without a fixed colour rule. Falls back to the fixed-rule mask."""
    a = frames[g].astype(np.int16)
    b = frames[before].astype(np.int16)
    changed = np.abs(a - b).sum(axis=2) > 120
    reddish = (a[..., 0] - np.maximum(a[..., 1], a[..., 2])) > 50
    m = changed & reddish & ~(frames[before].astype(np.int16)[..., 0] - np.maximum(b[..., 1], b[..., 2]) > 50) | (changed & reddish & fallback)
    return m


def find_onset(frames, fps, t0, candidate, after_s, rise_min=300):
    """Border-appearance frame for one kill. A rise counts only when its 6-frame 'before' frame is after the previous kill's onset (after_s).
    The row's outline is the NEW red pixels (red now, not red 6 frames earlier), so earlier rows in the
    stack do not change the box or the side checks."""
    mask = red_mask(frames.astype(np.int16))
    # Rise count on changed reddish pixels (21 Oct, P5): a row appearing is a change, a scene cut is not
    # reddish-only, so the rise is found at the row, not at a flash.
    changed_red = np.zeros(mask.shape, bool)
    for i in range(6, len(frames)):
        changed_red[i] = outline_pixels(frames, i, i - 6, mask[i] & ~mask[i - 6])
    counts = changed_red.sum(axis=(1, 2))
    # Flash or scene-cut frames change most of the crop at once. Exclude them from the outline search.
    diff_all = np.zeros(len(frames))
    for i in range(1, len(frames)):
        diff_all[i] = (np.abs(frames[i].astype(np.int16) - frames[i - 1].astype(np.int16)).sum(axis=2) > 120).mean()
    flash = diff_all > FLASH_FRAC
    centre = int(round((candidate - t0) * fps))
    lo, hi = max(6, centre - int(WINDOW_S * fps)), min(len(frames), centre + int(WINDOW_S * fps))
    for f in range(lo, hi):
        if t0 + (f - 6) / fps < after_s:
            continue  # the rise must start after the previous kill's outline is complete
        if counts[f] - counts[f - 6] < rise_min or counts[f] - counts[f - 6] <= 0:
            continue
        best = None
        for g in range(f, min(f + 6, len(frames))):
            if flash[g]:
                continue  # flash or scene-cut frame (21 Oct, P5 fourth calibration): not an outline frame
            new = outline_pixels(frames, g, f - 6, mask[g] & ~mask[f - 6])
            box, score = side_scores(new)
            if box and (best is None or score > best[2]):
                best = (g, box, score)
        if best and best[2] >= SIDE_MIN:
            g, box, score = best
            return {"frame": g, "seconds": round(t0 + g / fps, 4), "bbox": box,
                    "side_min": round(score, 3), "border_frames": int(min(f + 6, len(frames)) - f)}
        return {"frame": None, "reason": f"outline rose; best side coverage {best[2]:.2f} < {SIDE_MIN}" if best else "outline rose; no row box"}
    return {"frame": None, "reason": "no red rise near candidate"}


def check(inputs, candidates):
    fps = float(inputs["fps"])
    source = inputs["source"]
    kills = []
    flags = []
    after = -1.0
    rise_min, p98 = feed_threshold(source, fps, float(inputs["window_end"]) + 2)
    if rise_min is None:
        return {"clip_id": inputs["clip_id"], "fps": fps, "kills": [], "pass": False, "rise_min": None,
                "feed_p98": round(p98, 1), "flags": ["feed not found: red outline count too low, stopped"]}
    for i, cand in enumerate(sorted(candidates["kills"], key=lambda k: k["seconds"]), start=1):
        c = float(cand["seconds"])
        frames, t0 = decode_window(source, c - WINDOW_S - 0.1, 2 * WINDOW_S + 0.2, fps)
        res = find_onset(frames, fps, t0, c, after, rise_min)
        rec = {"kill": i, "candidate_s": c, "name_check": "not run", "status": "pass"}
        if res.get("frame") is None:
            rec.update({"status": "flag", "reason": res["reason"], "seconds": None})
            flags.append(f"kill {i}: {res['reason']}")
        else:
            off = abs(res["seconds"] - c)
            rec.update(res)
            rec["box_feed"] = res["bbox"]
            # settled frame for the timing gate: 12 frames after the border is complete (0.2 s), so every edge is drawn
            rec["crop_frame"] = int(round(res["seconds"] * fps)) + 12
            fv = csj_timing_gate.first_visible_kill(source, rec["box_feed"], rec["crop_frame"])
            rec.update(fv)
            if fv["fv_pass"]:
                rec["complete_seconds"] = res["seconds"]
                rec["seconds"] = round((fv["fv_first_visible"] - LEAD_FRAMES) / fps, 4)
            else:
                rec["status"] = "flag"
                flags.append(f"kill {i}: first visible frame not agreed on all four edges: {fv['fv_reason']}")
            after = res["seconds"]
            if off > MAX_OFFSET_S:
                rec["status"] = "flag"
                flags.append(f"kill {i}: onset {res['seconds']} is {off:.2f}s from candidate {c}")
        kills.append(rec)
    return {"clip_id": inputs["clip_id"], "fps": fps, "rule": "strict full-border, 80% per side",
            "rise_min": rise_min, "feed_p98": round(p98, 1),
            "kills": kills, "flags": flags, "pass": len(flags) == 0 and len(kills) > 0}


if __name__ == "__main__":
    inputs = json.loads(Path(sys.argv[1]).read_text())
    cands = json.loads(Path(sys.argv[2]).read_text())
    out = check(inputs, cands)
    Path(sys.argv[3]).write_text(json.dumps(out, indent=2))
    print(json.dumps({"pass": out["pass"], "flags": out["flags"],
                      "onsets": [k.get("seconds") for k in out["kills"]]}, indent=2))
    sys.exit(0 if out["pass"] else 1)
