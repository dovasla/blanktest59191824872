"""CS Junkie stacked-row kill detection (29 Oct 2026). Dry run only: reads the source, writes JSON, never uploads or posts.

Usage:
  python3 csj_stack_detect.py <source.mp4> <out_dir> [window_start] [window_end]

Method (new, separate from csj_kill_timing.py):
  1. Decode the feed crop (x 1620, y 40, 300 x 280) for the window at the source fps.
  2. Per frame, find horizontal red border lines (a row's top and bottom edges).
     Each kill row is a red box, so each kill adds two border lines.
  3. Track the border-line count over time. A kill is found when the count steps up.
  4. Onset = first frame of the step, minus 3 frames (locked rule). Marked ESTIMATED.
Writes out_dir/stack_detect.json with the per-frame counts and the estimated kills.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

FEED_X, FEED_Y, FEED_W, FEED_H = 1620, 40, 300, 280
SOURCE_W, SOURCE_H = 1920, 1080
MIN_RED_PX = 120  # a border line spans most of the row width
ONSET_OFFSET_FRAMES = 3


def read_frames(path, fps, start, end):
    """Yield (frame_index, feed crop as HxWx3 uint8) for the window."""
    cmd = ["ffmpeg", "-loglevel", "error", "-ss", str(start), "-t", str(end - start),
           "-i", path, "-vf", f"crop={FEED_W}:{FEED_H}:{FEED_X}:{FEED_Y},fps={fps}",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    size = FEED_W * FEED_H * 3
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    index = int(round(start * fps))
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        yield index, np.frombuffer(buf, np.uint8).reshape(FEED_H, FEED_W, 3)
        index += 1
    proc.stdout.close()
    proc.wait()


def border_lines(frame):
    """Return the y centres of red border lines in one feed crop."""
    r = frame[:, :, 0].astype(np.int16)
    g = frame[:, :, 1].astype(np.int16)
    b = frame[:, :, 2].astype(np.int16)
    red = (r > 150) & (r - g > 100) & (r - b > 100)
    per_row = red.sum(axis=1)
    hits = np.where(per_row >= MIN_RED_PX)[0]
    lines = []
    for y in hits:
        if lines and y - lines[-1][-1] <= 1:
            lines[-1].append(int(y))
        else:
            lines.append([int(y)])
    return [round(sum(group) / len(group), 1) for group in lines]


RISE_PX = 400  # a new row adds this many red pixels in one frame or two
RISE_FRAMES = 2


def rise_onsets(source, fps, start, end):
    """Find frames where red border pixels jump up. Each jump is a new row fading in.

    Onset = first frame of the jump, minus 3 frames (locked rule). Works on any clip, same feed crop.
    """
    counts = []
    for idx, frame in read_frames(source, fps, start, end):
        r = frame[:, :, 0].astype(np.int16)
        g = frame[:, :, 1].astype(np.int16)
        b = frame[:, :, 2].astype(np.int16)
        red = (r > 90) & (r - g > 50) & (r - b > 50)
        counts.append((idx, int(red.sum())))
    onsets = []
    for i in range(1, len(counts)):
        idx, c = counts[i]
        base = counts[max(0, i - RISE_FRAMES)][1]
        prev = counts[i - 1][1]
        if c - base >= RISE_PX and c - prev >= RISE_PX // 4:
            if not onsets or idx - onsets[-1]["first_frame"] > 30:
                onsets.append({"first_frame": idx, "candidate_s": round(idx / fps, 4),
                               "onset_frame": idx - ONSET_OFFSET_FRAMES,
                               "onset_s": round((idx - ONSET_OFFSET_FRAMES) / fps, 4),
                               "status": "ESTIMATED"})
    return onsets


SLOT_CENTERS = [34.5, 64.5, 98.5, 132.5]  # crop y of each stack slot's top border (1080p feed crop)
SLOT_MIN_RED = 120  # red px across the slot line, same test as a full row border
SLOT_MIN_FRAMES = 6  # a slot must stay on this many frames to count, drops flicker


def slot_states(source, fps, start, end):
    """Per frame, which stack slots show a red top border. Slots fill top to bottom, so a kill is a new slot turning on."""
    rows = []
    for idx, frame in read_frames(source, fps, start, end):
        r = frame[:, :, 0].astype(np.int16)
        g = frame[:, :, 1].astype(np.int16)
        b = frame[:, :, 2].astype(np.int16)
        red = (r > 150) & (r - g > 100) & (r - b > 100)
        on = []
        for c in SLOT_CENTERS:
            y = int(round(c))
            on.append(bool(red[y - 1:y + 2].sum(axis=1).max() >= SLOT_MIN_RED))
        rows.append((idx, on))
    return rows


def slot_onsets(source, fps, start, end):
    """Kill = a slot turns on and stays on. Onset = first frame it is on, minus 3 frames (locked rule)."""
    states = slot_states(source, fps, start, end)
    found = []
    seen_count = 0
    for k, slot in enumerate(range(len(SLOT_CENTERS))):
        first = None
        run = 0
        for idx, on in states:
            run = run + 1 if on[slot] else 0
            if run == SLOT_MIN_FRAMES and first is None:
                first = idx - SLOT_MIN_FRAMES + 1
                break
        if first is not None:
            found.append((first, slot))
    found.sort()
    out = []
    for first, slot in found:
        seen_count += 1
        out.append({"kill": seen_count, "slot": slot, "first_frame": first,
                    "candidate_s": round(first / fps, 4),
                    "onset_frame": first - ONSET_OFFSET_FRAMES,
                    "onset_s": round((first - ONSET_OFFSET_FRAMES) / fps, 4),
                    "status": "ESTIMATED"})
    return out


ROW_GAP_MIN, ROW_GAP_MAX = 22, 36  # top edge to bottom edge of one kill row, crop px
DARK_LUM = 100  # interior of a row is dark


def row_pairs(frame):
    """Pair red edge lines into rows. Top edge = line whose box interior below is dark. Returns top edge y list."""
    r = frame[:, :, 0].astype(np.int16)
    g = frame[:, :, 1].astype(np.int16)
    b = frame[:, :, 2].astype(np.int16)
    red = (r > 150) & (r - g > 100) & (r - b > 100)
    lum = frame.mean(axis=2)
    edges = [y for y in range(frame.shape[0]) if red[y].sum() >= MIN_RED_PX]
    lines = []
    for y in edges:
        if lines and y - lines[-1][-1] <= 1:
            lines[-1].append(y)
        else:
            lines.append([y])
    centres = [int(round(sum(g_) / len(g_))) for g_ in lines]
    tops, used = [], set()
    for i, y in enumerate(centres):
        if i in used:
            continue
        for j in range(i + 1, len(centres)):
            gap = centres[j] - y
            if gap > ROW_GAP_MAX:
                break
            if gap >= ROW_GAP_MIN and lum[y + 3:y + 8].mean() < DARK_LUM:
                tops.append(y)
                used.add(j)
                break
    return tops


def top_edge_onsets(source, fps, start, end):
    """Kill = a top edge that was not on screen in the frame before and stays for 6 frames.

    Rows leave from the top and the stack shifts, so a count alone misses kills.
    Onset = first frame of the new top edge, minus 3 frames (locked rule).
    """
    frames = list(read_frames(source, fps, start, end))
    tops_by_frame = [(idx, row_pairs(f)) for idx, f in frames]
    onsets, last = [], -999
    for i in range(1, len(tops_by_frame)):
        idx, tops = tops_by_frame[i]
        prev = set(tops_by_frame[i - 1][1])
        new = [y for y in tops if all(abs(y - q) > 3 for q in prev)]
        if not new or idx - last <= 30:
            continue
        stay = all(any(abs(new[0] - q) <= 3 for q in tops_by_frame[j][1])
                   for j in range(i, min(i + 6, len(tops_by_frame))))
        if stay:
            last = idx
            onsets.append({"kill_no": len(onsets) + 1, "first_frame": idx,
                           "candidate_s": round(idx / fps, 4),
                           "onset_frame": idx - ONSET_OFFSET_FRAMES,
                           "onset_s": round((idx - ONSET_OFFSET_FRAMES) / fps, 4),
                           "status": "ESTIMATED", "top_y": new})
    return onsets


def main(source, out_dir, start=3.0, end=20.0, fps=60.0):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    timeline = []
    best = 0
    steps = []
    for idx, frame in read_frames(source, fps, start, end):
        lines = border_lines(frame)
        count = len(lines)
        timeline.append({"frame": idx, "s": round(idx / fps, 4), "lines": lines})
        if count > best:
            steps.append({"frame": idx, "s": round(idx / fps, 4), "lines": lines})
            best = count

    kills = []
    for n, step in enumerate(steps, start=1):
        first = step["frame"]
        kills.append({
            "step": n,
            "first_frame": first,
            "candidate_s": step["s"],
            "onset_frame": first - ONSET_OFFSET_FRAMES,
            "onset_s": round((first - ONSET_OFFSET_FRAMES) / fps, 4),
            "status": "ESTIMATED",
            "lines_at_step": step["lines"],
        })

    result = {
        "source": source,
        "fps": fps,
        "window": [start, end],
        "max_border_lines": best,
        "note": "Count of red border lines per frame. Steps are candidate kill rows. ESTIMATED until checked by eye.",
        "kills": kills,
    }
    result["top_edge_onsets"] = top_edge_onsets(source, fps, start, end)
    result["slot_onsets"] = slot_onsets(source, fps, start, end)
    result["rise_onsets"] = rise_onsets(source, fps, start, end)
    (out / "stack_detect.json").write_text(json.dumps(result, indent=2))
    (out / "timeline.json").write_text(json.dumps(timeline))
    for k in kills:
        print(f"step {k['step']} | frame {k['first_frame']} | onset {k['onset_s']} s | lines {k['lines_at_step']} | ESTIMATED")
    print(f"max border lines seen: {best}")
    for k in result["top_edge_onsets"]:
        print(f"TOP kill {k['kill_no']} | first frame {k['first_frame']} | onset {k['onset_s']} s | ESTIMATED")
    for k in result["slot_onsets"]:
        print(f"SLOT kill {k['kill']} (slot {k['slot']+1}) | first frame {k['first_frame']} | onset {k['onset_s']} s | ESTIMATED")
    for k in result["rise_onsets"]:
        print(f"rise at frame {k['first_frame']} | onset {k['onset_s']} s | ESTIMATED")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    src, dst = args[0], args[1]
    w0 = float(args[2]) if len(args) > 2 else 3.0
    w1 = float(args[3]) if len(args) > 3 else 20.0
    sys.exit(main(src, dst, w0, w1))
