"""CS Junkie kill scan by code (29 Oct 2026). Replaces the onset placeholder for kills 2 to 4.

Usage:
  python3 csj_name_scan.py <inputs.json> <out_dir>

Two stages, to keep frame reads low:
  1. Cheap scan: the feed crop is read at 10 fps over the clip window only. A kill is a jump in outline
     pixels of at least rise_min between two samples (0.1 s apart). Rises closer than 0.5 s are merged.
  2. Refine at 60 fps, only -0.3 s to +0.6 s around each candidate. The row's new outline pixels (red now,
     not red 6 frames earlier) must form a box with all four sides at least 80% red. The first such frame
     is the first fully rendered frame. Onset = that frame minus 3 frames (locked rule, Jord 28 Oct).

Outline rule: dim red counts (R > 80, R well above G and B). The strict bright-red rule missed the dim
bottom edge on heavygod (29 Oct), so the row was never seen.

Writes:
  <out_dir>/onsets.json  candidates, per-kill onset, status, frame reads
  <out_dir>/kill_N.png   the row crop for each kill, scaled 3x, for an eye check of the killer name

Names are NOT read by code. Kill count comes from inputs["kill_count"]. A scan that finds a different
count is flagged, not changed.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

FEED_CROP = (1620, 40, 300, 280)
SAMPLE_FPS = 10
FPS = 60
MERGE_S = 0.5
LEAD_FRAMES = 3
SIDE_MIN = 0.80
REFINE_BEFORE_S = 0.3
REFINE_AFTER_S = 0.6
LOOKBACK = 6  # frames, the row's outline is "new" against this frame


def outline_mask(frames):
    """Dim-or-bright red outline pixels. frames: (n, h, w, 3) int16."""
    r, g, b = frames[..., 0], frames[..., 1], frames[..., 2]
    return (r > 80) & ((r - np.maximum(g, b)) > 60)


def decode(source, start, dur, fps):
    x, y, w, h = FEED_CROP
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(start, 0):.3f}", "-i", source,
                          "-t", f"{dur:.3f}", "-vf", f"fps={fps},crop={w}:{h}:{x}:{y}",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3).astype(np.int16)


def box_sides(mask):
    """Row box of a mask and the coverage of each of its four sides. Returns (box, min_side)."""
    rows = np.where(mask.sum(axis=1) >= 40)[0]
    cols = np.where(mask.sum(axis=0) >= 8)[0]
    if len(rows) < 2 or len(cols) < 2:
        return None, 0.0
    y0, y1, x0, x1 = rows[0], rows[-1], cols[0], cols[-1]
    if x1 - x0 < 60 or y1 - y0 < 4:
        return None, 0.0
    sides = [mask[y0, x0:x1 + 1].mean(), mask[y1, x0:x1 + 1].mean(),
             mask[y0:y1 + 1, x0].mean(), mask[y0:y1 + 1, x1].mean()]
    return [int(x0), int(y0), int(x1), int(y1)], float(min(sides))


def stage1(source, start, end):
    """10 fps scan of the window. Returns candidate seconds, frame reads, and the rise threshold."""
    frames = decode(source, start, end - start, SAMPLE_FPS)
    counts = outline_mask(frames).sum(axis=(1, 2))
    p98 = float(np.percentile(counts, 98))
    if p98 < 120:
        return [], len(frames), None
    rise_min = int(min(300, max(60, 0.3 * p98)))
    times, last = [], -1e9
    for i in range(1, len(counts)):
        if counts[i] - counts[i - 1] >= rise_min / 2:
            t = start + i / SAMPLE_FPS
            if t - last >= MERGE_S:
                times.append(round(t, 3))
            last = t
    return times, len(frames), rise_min


def _clusters(idx):
    """Group sorted row numbers into runs of consecutive rows: list of (start, end)."""
    runs = []
    for y in idx:
        if runs and y - runs[-1][1] <= 2:
            runs[-1][1] = int(y)
        else:
            runs.append([int(y), int(y)])
        # keep plain ints so the result can be written as JSON
    return runs


def newest_row(mask):
    """Newest row box in one frame. Rows are red-edged boxes stacked downward and may share an edge line,
    so the newest row is the lowest pair of horizontal edge lines at least 15 px apart.
    Edge lines are runs of rows that are at least half red across the row's own width.
    Returns ([x0, top, x1, bottom], min_side). min_side is the lowest of the four side coverages."""
    h_lines = _clusters(np.where(mask.sum(axis=1) >= 40)[0])
    if len(h_lines) < 2:
        return None, 0.0
    bottom_run = h_lines[-1]
    top_cands = [r for r in h_lines if bottom_run[1] - r[1] >= 15]
    if not top_cands:
        return None, 0.0
    top_run = top_cands[-1]
    top, bottom = top_run[0], bottom_run[1]
    band = mask[top:bottom + 1]
    cols = np.where(band.mean(axis=0) >= 0.5)[0]
    if len(cols) < 2 or cols[-1] - cols[0] < 60:
        return None, 0.0
    x0, x1 = int(cols[0]), int(cols[-1])
    top, bottom = int(top), int(bottom)
    sides = [mask[top, x0:x1 + 1].mean(), mask[bottom, x0:x1 + 1].mean(),
             band[:, x0].mean(), band[:, x1].mean()]
    return [x0, int(top), x1, int(bottom)], float(min(sides))


def refine(source, cand):
    """60 fps refine around one candidate. Returns (first_full_frame_seconds, box, reads)."""
    t0 = cand - REFINE_BEFORE_S
    frames = decode(source, t0 - LOOKBACK / FPS, REFINE_BEFORE_S + REFINE_AFTER_S + LOOKBACK / FPS, FPS)
    mask = outline_mask(frames)
    first_t0 = t0 - LOOKBACK / FPS
    for g in range(LOOKBACK, len(frames)):
        box, side = newest_row(mask[g])
        if not box or side < SIDE_MIN:
            continue
        # Rows stack downward and share edges, so the row is new when either of its edge lines was not
        # drawn 6 frames earlier.
        x0, top, x1, bottom = box
        new_top = mask[g - LOOKBACK, top, x0:x1 + 1].mean() < 0.5
        new_bottom = mask[g - LOOKBACK, bottom, x0:x1 + 1].mean() < 0.5
        if not (new_top or new_bottom):
            continue
        return round(first_t0 + g / FPS, 4), box, len(frames)
    return None, None, len(frames)


def save_row_crop(source, seconds, box, out_path):
    x, y, w, h = FEED_CROP
    x0, y0, x1, y1 = box
    pad = 6
    cx, cy = x + max(0, x0 - pad), y + max(0, y0 - pad)
    cw, ch = (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{seconds:.4f}", "-i", source, "-frames:v", "1",
                    "-vf", f"crop={cw}:{ch}:{cx}:{cy},scale=iw*3:ih*3:flags=neighbor", str(out_path)], check=True)


def _write_flags(path, clip_id, entries):
    """Replace this clip's entries in the learning log with this run's flags. Each flag says what was unclear,
    what was tried, and what to do next time. Other clips' entries are kept."""
    path.parent.mkdir(parents=True, exist_ok=True)
    keep = []
    if path.exists():
        keep = [l for l in path.read_text().splitlines() if l.strip() and json.loads(l).get("clip_id") != clip_id]
    path.write_text("\n".join(keep + [json.dumps(e) for e in entries]) + "\n")


def main(inputs_path, out_dir):
    inputs = json.loads(Path(inputs_path).read_text())
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    source = inputs["source"]
    start, end = float(inputs["window_start"]), float(inputs["window_end"])
    n_expected = int(inputs["kill_count"])

    times, reads1, rise_min = stage1(source, start, end)
    result = {"clip_id": inputs["clip_id"], "sample_fps": SAMPLE_FPS, "rise_min": rise_min,
              "candidates": times, "frame_reads_stage1": reads1, "kill_count_expected": n_expected,
              "flags": [], "kills": [], "pass": False}
    if rise_min is None:
        result["flags"].append("feed not found in window, stopped")
        (out / "onsets.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
        return 1
    if len(times) != n_expected:
        result["flags"].append(f"scan found {len(times)} rises, kill_count is {n_expected}. Check by eye.")

    reads2 = 0
    for i, c in enumerate(times, start=1):
        sec, box, n = refine(source, c)
        reads2 += n
        rec = {"kill": i, "candidate_s": c, "status": "pass", "name_check": "by eye (row crop)"}
        if sec is None:
            # Estimate from the 10 fps candidate: the rise is seen in the 0.1 s sample before it, so the
            # onset is about 0.1 s before the candidate. Labelled ESTIMATED, not a confirmed onset.
            est = round(c - 0.1, 3)
            rec.update({"status": "estimated", "seconds": est, "label": "ESTIMATED",
                        "reason": "no fully rendered row box near candidate"})
            result["flags"].append(f"kill {i} at {c}: no fully rendered row box, ESTIMATED at {est}")
        else:
            rec.update({"first_full_s": sec, "seconds": round(sec - LEAD_FRAMES / FPS, 4), "box_feed": box})
            crop = out / f"kill_{i}.png"
            save_row_crop(source, sec + 0.1, box, crop)
            rec["row_crop"] = str(crop)
        result["kills"].append(rec)

    entries = []
    for rec in result["kills"]:
        if rec["status"] in ("flag", "estimated"):
            entries.append({"clip_id": inputs["clip_id"], "kill": rec["kill"], "candidate_s": rec["candidate_s"],
                            "reason": rec["reason"],
                            "tried": ["10 fps rise scan", "60 fps newest-row box, both edge lines",
                                      "dim red outline rule R>80 and R-max(G,B)>60"],
                            "next_time": "Likely a fade-in or a row stacked on an older one. Check this row at 60 fps "
                                         "by eye before any link. Do not set the onset by hand."})
    if len(times) != n_expected:
        entries.append({"clip_id": inputs["clip_id"], "kill": None, "candidate_s": None,
                        "reason": f"scan found {len(times)} rises, kill_count is {n_expected}",
                        "tried": ["10 fps rise scan with merge at 0.5 s"],
                        "next_time": "Check each rise by eye in the feed. Kill count comes from the caption, not the scan."})
    _write_flags(Path("/mnt/project-files/research/kill_timing_flags.jsonl"), inputs["clip_id"], entries)
    result["frame_reads_stage2"] = reads2
    result["frame_reads_total"] = reads1 + reads2
    result["pass"] = not result["flags"] and len(times) == n_expected
    result["estimated"] = [k["kill"] for k in result["kills"] if k["status"] == "estimated"]
    (out / "onsets.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({"pass": result["pass"], "candidates": times, "flags": result["flags"],
                      "onsets": [k.get("seconds") for k in result["kills"]],
                      "frame_reads_total": result["frame_reads_total"]}, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
