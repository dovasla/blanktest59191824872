"""CS Junkie caption check (29 Oct 2026). Blocking: csj_run.py stops before the approval package if it fails.

Usage:
  python3 csj_caption_check.py <caption.txt> <inputs.json>

Checks:
  1. The kill count as a literal token, e.g. "5K". Digits alone fail (gate 11, v37 section 8).
  2. The player name from the inputs appears in the caption, case ignored.
  3. At most 2 hashtags (v37 section 11, other platforms). YouTube titles have none; this checks the description.
Not checked here: the killer name against the rows. That check is still a stub (csj_candidates.py).
"""
import json
import re
import sys
from pathlib import Path


def check(caption_path, inputs):
    text = Path(caption_path).read_text(encoding="utf-8").strip()
    n = int(inputs["kill_count"])
    player = str(inputs["player_name"])
    flags = []
    if not re.search(rf"(?<![A-Za-z0-9]){n}K(?![A-Za-z0-9])", text):
        flags.append(f"no literal {n}K token in the caption")
    if player.lower() not in text.lower():
        flags.append(f"player name {player!r} not in the caption")
    tags = re.findall(r"#\w+", text)
    if len(tags) > 2:
        flags.append(f"{len(tags)} hashtags (max 2)")
    return {"pass": not flags, "flags": flags, "hashtags": len(tags), "caption": text}


if __name__ == "__main__":
    r = check(sys.argv[1], json.loads(Path(sys.argv[2]).read_text()))
    print(json.dumps(r, indent=2))
    sys.exit(0 if r["pass"] else 1)
