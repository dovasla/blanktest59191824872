"""CS Junkie overlay pass: grade the gameplay, then add the figure, title and accents (master skill v39 section 7).

Usage:
  python3 csj_overlay.py <inputs.json> <base.mp4> <layers_dir> <out.mp4>

base.mp4     the 1080x1920 build without figure, title or accents (gameplay, banner optional)
layers_dir   holds <clip>_figure_layer.png, <clip>_title_layer.png, <clip>_accents_layer.png
             (from csj_figure.py, csj_text.py, csj_accents.py). Any missing layer is skipped and listed.

Order: grade (contrast 1.08, saturation 0.92, gamma 1.02) on the gameplay only, then the layers on top.
Cost: one extra encode of the clip. Folding this into csj_build's single encode is the next step, after a
golden run on donk v48.
"""
import json
import subprocess
import sys
from pathlib import Path

GRADE = "eq=contrast=1.08:saturation=0.92:gamma=1.02"
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-maxrate", "24M", "-bufsize", "48M"]


def main(inputs_path, base, layers_dir, out_mp4):
    inputs = json.loads(Path(inputs_path).read_text())
    clip = inputs["clip_id"]
    ld = Path(layers_dir)
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", base]
    present, missing = [], []
    for name in ("figure", "title", "accents"):
        p = ld / f"{clip}_{name}_layer.png"
        if p.exists():
            cmd += ["-i", str(p)]
            present.append(name)
        else:
            missing.append(name)
    parts = [f"[0:v]{GRADE}[g]"]
    prev = "g"
    for i, _ in enumerate(present, start=1):
        parts.append(f"[{prev}][{i}:v]overlay=0:0:format=auto[o{i}]")
        prev = f"o{i}"
    parts.append(f"[{prev}]format=yuv420p[v]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "0:a?", "-c:a", "copy", *ENC, out_mp4]
    subprocess.run(cmd, check=True)
    print(json.dumps({"clip_id": clip, "out": out_mp4, "layers_used": present, "layers_missing": missing}, indent=2))


if __name__ == "__main__":
    main(*sys.argv[1:5])
