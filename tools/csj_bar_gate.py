# Edge-band gate: fails an export whose top or bottom band is near-black in any sampled frame.
# Usage: python3 bar_gate.py <video.mp4> [band_px=60] [luma_max=12] [sample_every_s=0.5]
import subprocess, sys
import numpy as np

path = sys.argv[1]
band = int(sys.argv[2]) if len(sys.argv) > 2 else 60
luma_max = float(sys.argv[3]) if len(sys.argv) > 3 else 12.0
step = float(sys.argv[4]) if len(sys.argv) > 4 else 0.5

probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height", "-of", "csv=p=0", path],
                       capture_output=True, text=True, check=True).stdout.strip().split(",")
w, h = int(probe[0]), int(probe[1])
# One gray frame every `step` seconds, read straight from ffmpeg.
raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"fps=1/{step},format=gray",
                      "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
frames = np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(np.float32)
# A row counts as a dark row when its mean luma is below luma_max. A bar is a run of dark rows
# at the edge. Fail a frame when 10 or more rows in the top or bottom band are dark.
rows_top = (frames[:, :band, :].mean(axis=2) < luma_max).sum(axis=1)
rows_bot = (frames[:, h - band:, :].mean(axis=2) < luma_max).sum(axis=1)
bad = int(np.sum((rows_top >= 10) | (rows_bot >= 10)))
ok = bad == 0
print(f"frames={len(frames)} band={band}px luma_max={luma_max} max_dark_rows_top={int(rows_top.max())} max_dark_rows_bottom={int(rows_bot.max())} bad_frames={bad} -> {'PASS' if ok else 'FAIL'}")
sys.exit(0 if ok else 1)
