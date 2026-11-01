"""CS Junkie per-player registry (29 Oct 2026). One JSON file per player in tools/player_cache/.

Holds facts about the player only: name, team colour, and the files made for that player
(figure and banner, empty until those steps exist in the build). Never holds a clip's own values.
Blocking check: if the player is registered, the clip's colour must match the registry.

Usage:
  python3 csj_player_cache.py register <inputs.json>   add or update the player from this clip
  python3 csj_player_cache.py show <player name>
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

DIR = Path(__file__).resolve().parent / "player_cache"


def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def path_for(name):
    return DIR / f"{slug(name)}.json"


def check(inputs):
    name = str(inputs["player_name"])
    p = path_for(name)
    if not p.exists():
        # locked (skill section 3): unknown player stops and asks Jord, unless Jord confirmed the new player
        if inputs.get("player_new_confirmed") is True:
            return {"pass": True, "registered": False, "flags": [], "note": f"{name} is new, Jord confirmed"}
        return {"pass": False, "registered": False, "flags": [f"{name} is not in the registry. Ask Jord to confirm the new player (set player_new_confirmed)."]}
    entry = json.loads(p.read_text())
    flags = []
    if inputs.get("player_colour") != entry.get("colour"):
        flags.append(f"clip colour {inputs.get('player_colour')!r} does not match registry colour "
                     f"{entry.get('colour')!r} for {name}")
    return {"pass": not flags, "registered": True, "flags": flags}


def register(inputs):
    name = str(inputs["player_name"])
    DIR.mkdir(parents=True, exist_ok=True)
    p = path_for(name)
    entry = json.loads(p.read_text()) if p.exists() else {}
    entry.update({"name": name, "colour": inputs["player_colour"], "updated": date.today().isoformat()})
    entry.setdefault("figure", None)
    entry.setdefault("banner", None)
    p.write_text(json.dumps(entry, indent=2))
    return entry


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "register":
        print(json.dumps(register(json.loads(open(sys.argv[2]).read())), indent=2))
    elif cmd == "show":
        p = path_for(sys.argv[2])
        print(p.read_text() if p.exists() else f"{sys.argv[2]} is not registered")
