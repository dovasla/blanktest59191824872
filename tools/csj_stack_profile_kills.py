"""Find kills by watching the feed stack as one signal (dry-run test tool).

Idea: each kill adds one red-bordered row to the feed stack. Per frame we
count how many red bands are in the feed crop. A kill is a frame where the
band count goes up and stays up for a few frames. No templates, no training.

Usage: python3 csj_stack_profile_kills.py SOURCE.mp4 [fps_scan]
"""
import subprocess
import sys

import numpy as np

CROP = (1620, 40, 300, 280)  # x, y, w, h (feed crop from the process)
W_PX, H_PX = 1920, 1080


def read_frames(path, fps):
    x, y, w, h = CROP
    cmd = [
        "ffmpeg", "-v", "error", "-i", path,
        "-vf", f"fps={fps},crop={w}:{h}:{x}:{y}",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    frame = w * h * 3
    arr = np.frombuffer(raw, np.uint8)
    return arr[: (arr.size // frame) * frame].reshape(-1, h, w, 3)


def band_count(frame):
    r, g, b = (frame[..., i].astype(int) for i in range(3))
    red = (r > 150) & (g < 90) & (b < 90)
    rows = red.sum(axis=1) >= 6  # a border line is a long run of red
    bands, prev = 0, False
    for on in rows:
        if on and not prev:
            bands += 1
        prev = on
    return bands


def main():
    path = sys.argv[1]
    fps = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    counts = np.array([band_count(f) for f in read_frames(path, fps)])
    # median of 5 frames removes one-frame spikes; two borders make one row
    smooth = np.array([np.median(counts[max(0, i - 2):i + 3]) for i in range(len(counts))])
    rows = np.floor(smooth / 2).astype(int)
    kills, last_t, prev = [], -1.0, 0
    for i in range(len(rows)):
        later = rows[min(i + int(fps * 0.3), len(rows) - 1)]
        if rows[i] > prev and rows[i] == later:  # step up and stays up 0.3 s
            t = round(i / fps, 2)
            if t - last_t >= 0.5:
                kills.append(t)
                last_t = t
        prev = rows[i]
    print({"fps": fps, "kills": len(kills), "times": kills})


if __name__ == "__main__":
    main()
