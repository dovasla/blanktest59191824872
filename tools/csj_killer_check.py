"""CS Junkie killer-name check (29 Oct 2026). Blocking: csj_run.py stops before the build if it fails.

Usage:
  python3 csj_killer_check.py <inputs.json>

Reads inputs["kills"]: one entry per kill row, in kill order, with the killer name as read from the feed at
intake (the killer slot, with or without "+"). Own kill rule (v39 section 9): the featured player's name
must be in the killer slot.
Checks:
  1. inputs["kills"] has one entry per kill (count matches kill_count).
  2. Each killer name equals the featured player_name (case ignored, "+" ignored, spaces trimmed).
  3. The kill count is 5 or less. More than 5 is flagged for Jord, not blocked here.
Not done in code: reading the names from the feed pixels. The killer name is entered at intake, then checked here.
"""
import json
import sys
from pathlib import Path


def norm(name):
    return str(name).replace("+", "").strip().lower()


def check(inputs):
    flags, warn = [], []
    n = int(inputs["kill_count"])
    player = norm(inputs["player_name"])
    kills = inputs.get("kills")
    if not kills:
        flags.append("no kills list in inputs. Add one killer name per kill from the feed.")
    else:
        if len(kills) != n:
            flags.append(f"kills list has {len(kills)} entries, kill_count is {n}")
        for i, k in enumerate(kills, start=1):
            killer = norm(k.get("killer", ""))
            if killer != player:
                flags.append(f"kill {i}: killer {k.get('killer')!r} is not the featured player {inputs['player_name']!r}")
    if n > 5:
        warn.append(f"kill_count {n} is above 5. Flag to Jord before building.")
    return {"pass": not flags, "flags": flags, "warnings": warn}


if __name__ == "__main__":
    res = check(json.loads(Path(sys.argv[1]).read_text()))
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["pass"] else 1)
