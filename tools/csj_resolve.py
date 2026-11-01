"""CS Junkie input resolver (29 Oct 2026). Finds the source reel in every upload folder before anyone asks Jord.

Usage:
  python3 csj_resolve.py [--length S] [--tol 0.1] [--fps 60] [--name PART]

Searches every upload root for a video that is 1920x1080, at the given fps, with a length within --tol seconds
of --length (if given). Prints every match, newest first. Exit 0 when at least one match is found, 1 when none.
Ask Jord only when nothing matches, and name the missing item in one line.
Roots (v39 section 2): /mnt/attach/project-files/uploads/hearth/, /mnt/user-data/uploads/hearth/,
/root/.claude/uploads/, /mnt/project-files/uploads/hearth/, /mnt/project-files/.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOTS = [
    "/mnt/attach/project-files/uploads/hearth",
    "/mnt/user-data/uploads/hearth",
    "/root/.claude/uploads",
    "/mnt/project-files/uploads/hearth",
    "/mnt/project-files",
]
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm"}


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return None
    d = json.loads(out.stdout or "{}")
    if not d.get("streams"):
        return None
    s = d["streams"][0]
    num, den = (s.get("r_frame_rate") or "0/1").split("/")
    fps = float(num) / float(den) if float(den) else 0.0
    return {"w": s.get("width"), "h": s.get("height"), "fps": round(fps, 3),
            "duration": float(d.get("format", {}).get("duration", 0) or 0)}


def resolve(length=None, tol=0.1, fps=60.0, name=None):
    seen, matches = set(), []
    for root in ROOTS:
        r = Path(root)
        if not r.exists():
            continue
        for p in r.rglob("*"):
            if p.suffix.lower() not in VIDEO_EXT or not p.is_file():
                continue
            key = str(p.resolve())
            if key in seen:
                continue
            seen.add(key)
            if name and name.lower() not in p.name.lower():
                continue
            info = probe(p)
            if not info or info["w"] != 1920 or info["h"] != 1080:
                continue
            if abs(info["fps"] - fps) > 0.05:
                continue
            if length is not None and abs(info["duration"] - length) > tol:
                continue
            matches.append({"path": str(p), "mtime": p.stat().st_mtime, **info})
    matches.sort(key=lambda m: m["mtime"], reverse=True)
    return matches


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--length", type=float)
    ap.add_argument("--tol", type=float, default=0.1)
    ap.add_argument("--fps", type=float, default=60.0)
    ap.add_argument("--name")
    a = ap.parse_args()
    m = resolve(a.length, a.tol, a.fps, a.name)
    print(json.dumps(m, indent=2))
    sys.exit(0 if m else 1)
