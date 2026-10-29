"""CS Junkie banner fit: fit a banner in the 1100x600 box at its own shape, then place it on the clip.

Usage:
  python3 csj_banner_fit.py fit <banner.png> <fitted.png>
  python3 csj_banner_fit.py place <base.mp4> <fitted.png> <out.mp4>

fit    Scales the banner to fit inside the 1100x600 box. Keeps its shape: no stretch, no crop.
       Leftover space stays transparent and the banner sits centred in the box.
       Fades all four edges with a soft smoothstep ramp (140 px, or a quarter of the short side if smaller).
       Writes a 1100x600 RGBA PNG.
place  Overlays the fitted PNG on a 1080x1920 base at the box position (x -10, y 1180).
       Visible 0 to 4.0 s. Fades out 3.5 to 4.0 s. Audio is copied from the base.

Spec (master skill v39, banner section): box 1100x600, x -10, y 1180, soft fades, visible 0 to 4 s.
"""
import subprocess
import sys

import numpy as np
from PIL import Image

BOX_W, BOX_H = 1100, 600
BOX_X, BOX_Y = -10, 1180
RAMP_MAX = 140
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-maxrate", "24M", "-bufsize", "48M"]


def fit(src, dst):
    im = Image.open(src).convert("RGBA")
    scale = min(BOX_W / im.width, BOX_H / im.height)
    w = max(1, round(im.width * scale))
    h = max(1, round(im.height * scale))
    im = im.resize((w, h), Image.LANCZOS)

    ramp = max(1, min(RAMP_MAX, min(w, h) // 4))
    ys = np.arange(h)[:, None]
    xs = np.arange(w)[None, :]
    edge = np.minimum(np.minimum(xs, w - 1 - xs), np.minimum(ys, h - 1 - ys)).astype(float)
    t = np.clip((edge + 0.5) / ramp, 0, 1)
    t = t * t * (3 - 2 * t)

    arr = np.array(im)
    arr[:, :, 3] = (arr[:, :, 3] * t).astype(np.uint8)
    fitted = Image.fromarray(arr, "RGBA")

    box = Image.new("RGBA", (BOX_W, BOX_H), (0, 0, 0, 0))
    box.paste(fitted, ((BOX_W - w) // 2, (BOX_H - h) // 2), fitted)
    box.save(dst)
    print(f"fit: source {Image.open(src).size} -> {w}x{h} inside {BOX_W}x{BOX_H}, edge ramp {ramp} px -> {dst}")


def base_seconds(base):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", base],
        capture_output=True, text=True, check=True,
    )
    return float(r.stdout.strip())


def place(base, fitted, out):
    dur = base_seconds(base)
    fc = (
        "[1:v]format=rgba,fade=t=out:st=3.5:d=0.5:alpha=1[ban];"
        f"[0:v][ban]overlay={BOX_X}:{BOX_Y}:enable='lt(t,4)'[v]"
    )
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-i", base,
        "-loop", "1", "-r", "60", "-i", fitted,
        "-filter_complex", fc,
        "-map", "[v]", "-map", "0:a?",
        *ENC, "-c:a", "copy", "-t", f"{dur:.3f}", out,
    ]
    subprocess.run(cmd, check=True)
    print(f"place: banner at x {BOX_X}, y {BOX_Y}, visible 0 to 4 s -> {out}")


def main(argv):
    if len(argv) == 4 and argv[1] == "fit":
        fit(argv[2], argv[3])
    elif len(argv) == 5 and argv[1] == "place":
        place(argv[2], argv[3], argv[4])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
