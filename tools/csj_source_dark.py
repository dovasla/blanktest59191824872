"""CS Junkie source-dark check (29 Oct 2026). Warning only: it adds a NOT FINAL label, it never blocks.

Finds source time inside the clip window where the frame is near black (mean luma below 10 on a 64x36 sample).
Jord's 28 Oct default: a source-dark spot passes and is labelled.
Usage:
  python3 csj_source_dark.py <inputs.json>
"""
import json
import subprocess
import sys

import numpy as np

DARK_LUMA = 10.0
RATE = 4  # samples per second


def check(inputs):
    ws, we = float(inputs["window_start"]), float(inputs["window_end"])
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{ws:.3f}", "-i", inputs["source"],
                          "-t", f"{we - ws:.3f}", "-vf", f"fps={RATE},scale=64:36,format=gray",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 36, 64).astype(np.float32)
    dark = fr.mean(axis=(1, 2)) < DARK_LUMA
    spans, i = [], 0
    while i < len(dark):
        if dark[i]:
            j = i
            while j + 1 < len(dark) and dark[j + 1]:
                j += 1
            spans.append([round(ws + i / RATE, 2), round(ws + (j + 1) / RATE, 2)])
            i = j + 1
        else:
            i += 1
    return {"samples": int(len(dark)), "dark_samples": int(dark.sum()), "spans": spans,
            "found": bool(dark.any()), "blocking": False}


if __name__ == "__main__":
    print(json.dumps(check(json.loads(open(sys.argv[1]).read())), indent=2))
