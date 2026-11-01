"""CS Junkie feed cache (27 Oct 2026 speed-up). Decode the kill-feed crop once per source and reuse it.

red_counts(source) returns the red-outline pixel count of the feed crop for every source frame
(same rule as csj_gates.red_counts and csj_onset_check.red_mask). The first call decodes the whole
source once (about 10 s for 64 s at 60 fps). Later calls, from the onset threshold, the gates and the
checker, read the cached array. The cache key holds the file name, size, modified time and crop, so a
changed source decodes again. Cache files live in the build folder (CSJ_BUILD_CACHE, set by csj_run and
deleted when the run ends), or in the temp folder for a manual run. Nothing is kept for later clips (1 Nov).
"""
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

FEED_CROP = (1620, 40, 300, 280)  # source pixels, csj-process Step 2


def _cache_path(source):
    st = Path(source).stat()
    key = f"{Path(source).name}|{st.st_size}|{int(st.st_mtime)}|{FEED_CROP}"
    d = Path(os.environ.get("CSJ_BUILD_CACHE") or (Path(tempfile.gettempdir()) / "csj_feed_cache"))
    d.mkdir(parents=True, exist_ok=True)
    return d / (hashlib.md5(key.encode()).hexdigest() + "_red.npy")


def red_counts(source):
    """Red outline pixels per source frame in the feed crop, streamed in chunks and cached."""
    cp = _cache_path(source)
    if cp.exists():
        try:
            return np.load(cp)
        except (OSError, ValueError):
            pass
    x, y, w, h = FEED_CROP
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", source, "-vf", f"crop={w}:{h}:{x}:{y}",
                             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    counts, size, chunk = [], w * h * 3, 120
    while True:
        buf = proc.stdout.read(size * chunk)
        if not buf:
            break
        frames = np.frombuffer(buf, np.uint8).reshape(-1, h, w, 3).astype(np.int16)
        red = (frames[..., 0] > 200) & (frames[..., 1] < 50) & (frames[..., 2] < 50)
        counts.extend(red.sum(axis=(1, 2)).tolist())
    proc.wait()
    arr = np.array(counts)
    tmp = cp.with_suffix(".tmp.npy")
    np.save(tmp, arr)
    tmp.replace(cp)
    return arr


def clear_build_cache():
    """Delete the feed cache of the current build (1 Nov). csj_run calls this when the run ends."""
    d = os.environ.get("CSJ_BUILD_CACHE")
    if d:
        shutil.rmtree(d, ignore_errors=True)
