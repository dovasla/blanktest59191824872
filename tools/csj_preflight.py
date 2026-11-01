"""CS Junkie preflight (29 Oct 2026). Runs once per session; a passed result is kept in the temp folder.

Checks ffmpeg and ffprobe, numpy and Pillow (required), and the Barlow font for the title step (warning only).
Usage:
  python3 csj_preflight.py [--force]
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MARK = Path(tempfile.gettempdir()) / "csj_preflight_ok.json"
FONT = HERE / "fonts" / "BarlowCondensed-Black.ttf"


def run(force=False):
    if MARK.exists() and not force:
        try:
            r = json.loads(MARK.read_text())
            if r.get("pass"):
                r["cached"] = True
                return r
        except (OSError, ValueError):
            pass
    checks = {tool: shutil.which(tool) is not None for tool in ("ffmpeg", "ffprobe")}
    try:
        import numpy  # noqa: F401
        import PIL  # noqa: F401
        checks["numpy_pillow"] = True
    except ImportError:
        checks["numpy_pillow"] = False
    checks["barlow_font"] = FONT.exists()
    required = ["ffmpeg", "ffprobe", "numpy_pillow"]
    res = {"pass": all(checks[k] for k in required), "checks": checks,
           "warnings": [] if checks["barlow_font"] else ["Barlow font missing, needed for the title step"],
           "cached": False}
    if res["pass"]:
        MARK.write_text(json.dumps(res))
    return res


if __name__ == "__main__":
    r = run(force="--force" in sys.argv)
    print(json.dumps(r, indent=2))
    sys.exit(0 if r["pass"] else 1)
