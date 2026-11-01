"""CS Junkie candidate pass (csj-process v3, Step 2 quick triage). Writes candidates.json for csj_onset_check.py.

Usage:
  python3 csj_candidates.py <source.mp4> <candidates_out.json> [--start S] [--end E] [--rise 120]

Finds every red-outline rise in the feed crop (any team). Rises closer than 0.3 s are merged.
Own-kill filtering is NOT automatic yet: the name check (csj_onsets.py) is still a stub. Keep only the
featured player's rows (killer name, yellow or blue team per Step 1) before running csj_run.py, and say so
in the approval message.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

FEED_CROP = (1620, 40, 300, 280)


def main(src, out, start=0.0, end=None, rise=120):
    x, y, w, h = FEED_CROP
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-i", src]
    if end is not None:
        cmd += ["-t", f"{end - start:.3f}"]
    cmd += ["-vf", f"crop={w}:{h}:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3).astype(np.int16)
    red = (fr[..., 0] > 200) & (fr[..., 1] < 50) & (fr[..., 2] < 50)
    cnt = red.sum(axis=(1, 2))
    fps = 60.0
    idx = [i for i in range(6, len(cnt)) if cnt[i] - cnt[i - 6] >= rise]
    kills, last = [], -1e9
    for i in idx:
        if (i - last) / fps >= 0.3:
            kills.append({"seconds": round(start + i / fps, 3)})
        last = i
    Path(out).write_text(json.dumps({"kills": kills}, indent=2))
    print(json.dumps({"candidates": [k["seconds"] for k in kills], "rise": rise}))


if __name__ == "__main__":
    a = sys.argv
    kw = {}
    if "--start" in a: kw["start"] = float(a[a.index("--start") + 1])
    if "--end" in a: kw["end"] = float(a[a.index("--end") + 1])
    if "--rise" in a: kw["rise"] = int(a[a.index("--rise") + 1])
    main(a[1], a[2], **kw)
