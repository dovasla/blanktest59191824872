"""CS Junkie onset script (skill v23, Step 1). Read-only: FFmpeg decodes, nothing is rendered.

Usage:
  python3 csj_onsets.py decode  <video> <workdir>
      Decode the feed crop once at source fps to <workdir>/feed.npy (uint8 N x H x W x 3),
      and write <workdir>/probe.json (fps, frame count, size).
  python3 csj_onsets.py border  <workdir>
      Per frame, count red-outline pixels in the feed; write <workdir>/red_count.npy.
  python3 csj_onsets.py name    <workdir> <template.png> <kills.json> <out.json>
      Name check: kills.json lists own-kill search starts (seconds). Matches the victim-name
      template by normalised cross-correlation, forward only, and writes onsets JSON.

STATUS: decode and border are smoke-tested. The name check is a STUB and not validated:
it scores the template against the top-left corner of each frame, not a real 2-D search.
Do not use its output until the search is written and checked against a known clip.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

CROP = (1620, 40, 300, 280)  # x, y, w, h at source resolution (feed crop, skill Config)


def probe(video):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=width,height,r_frame_rate,nb_read_frames",
         "-of", "json", video],
        capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return {"fps": float(num) / float(den), "frames": int(s["nb_read_frames"]),
            "width": int(s["width"]), "height": int(s["height"])}


def decode(video, workdir):
    work = Path(workdir)
    work.mkdir(parents=True, exist_ok=True)
    info = probe(video)
    x, y, w, h = CROP
    # Single decode pass: crop the feed, emit raw RGB frames to stdout.
    cmd = ["ffmpeg", "-v", "error", "-i", video, "-vf",
           f"crop={w}:{h}:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)
    np.save(work / "feed.npy", frames)
    info.update({"crop": CROP, "decoded_frames": int(frames.shape[0])})
    (work / "probe.json").write_text(json.dumps(info, indent=2))
    print(json.dumps(info))


def border(workdir):
    work = Path(workdir)
    feed = np.load(work / "feed.npy", mmap_mode="r")
    r, g, b = (feed[..., i].astype(np.int16) for i in range(3))
    # Red outline: strong red, low green and blue (thresholds to be checked on a real frame).
    red = (r > 150) & (g < 80) & (b < 80)
    counts = red.reshape(red.shape[0], -1).sum(axis=1)
    np.save(work / "red_count.npy", counts)
    print(json.dumps({"frames": int(counts.size), "max_red": int(counts.max())}))


def ncc(patch, tmpl):
    p = patch - patch.mean()
    t = tmpl - tmpl.mean()
    denom = np.sqrt((p * p).sum() * (t * t).sum())
    return float((p * t).sum() / denom) if denom > 0 else 0.0


def name_check(workdir, template_png, kills_json, out_json):
    work = Path(workdir)
    feed = np.load(work / "feed.npy", mmap_mode="r")
    info = json.loads((work / "probe.json").read_text())
    fps = info["fps"]
    gray = feed.mean(axis=3).astype(np.float32)
    tmpl = np.asarray(Image.open(template_png).convert("L"), np.float32)
    th, tw = tmpl.shape
    kills = json.loads(Path(kills_json).read_text())  # [{"start_s": .., "search_s": ..}, ...]
    results = []
    cursor = 0
    for k in kills:
        start = max(cursor, int(k["start_s"] * fps))
        end = min(gray.shape[0] - 1, start + int(k.get("search_s", 3.0) * fps))
        scores = []
        for f in range(start, end + 1):
            # STUB: only the top-left corner is scored. Replace with a real 2-D search.
            scores.append(ncc(gray[f, :th, :tw], tmpl))
        best = int(np.argmax(scores)) if scores else 0
        onset = start + best
        results.append({"start_frame": start, "onset_frame": onset,
                        "onset_s": round(onset / fps, 3),
                        "score": round(scores[best], 3) if scores else None})
        cursor = onset + 1
    Path(out_json).write_text(json.dumps({"fps": fps, "kills": results}, indent=2))
    print(json.dumps({"kills": len(results)}))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "decode":
        decode(sys.argv[2], sys.argv[3])
    elif cmd == "border":
        border(sys.argv[2])
    elif cmd == "name":
        name_check(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
    else:
        sys.exit(__doc__)
