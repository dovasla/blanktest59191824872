"""CS Junkie caption step (29 Oct 2026). Picks a caption when the inputs have none, and writes it to a file.

Usage:
  python3 csj_caption_step.py <inputs.json> <out_dir> [--channel youtube]

Runs the caption picker (tools/csj_caption_picker.py, preview only, nothing recorded) and writes the first pick to
<clip>_caption.txt. Sets inputs["caption_file"] so csj_caption_check.py can check it.
The pick is shown for approval in the batch message. Jord's own captions are used exactly and skip this step.
Nothing is recorded to picker state here, so a preview does not use up templates.
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def pick(player, count, channel="youtube"):
    out = subprocess.run([sys.executable, "-I", str(HERE / "csj_caption_picker.py"), "--player", player,
                          "--count", str(count), "--channel", channel],
                         capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].startswith("h"):
            return {"id": parts[0], "pool": parts[1], "text": parts[2].strip()}
    raise ValueError(f"caption picker gave no pick: {out[:200]}")


def main(inputs_path, out_dir, channel="youtube"):
    inputs = json.loads(Path(inputs_path).read_text())
    if inputs.get("caption_file"):
        print(json.dumps({"skipped": "caption_file already set", "caption_file": inputs["caption_file"]}))
        return
    n = int(inputs["kill_count"])
    p = pick(inputs["player_name"], n, channel)
    if f"{n}K" not in p["text"]:
        raise ValueError(f"pick has no literal {n}K token: {p['text']}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cap = out / f"{inputs['clip_id']}_caption.txt"
    cap.write_text(p["text"] + "\n", encoding="utf-8")
    inputs["caption_file"] = str(cap)
    Path(inputs_path).write_text(json.dumps(inputs, indent=2))
    print(json.dumps({"pick": p, "caption_file": str(cap), "status": "show this pick for approval"}, indent=2))


if __name__ == "__main__":
    main(*sys.argv[1:4])
