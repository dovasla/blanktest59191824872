"""Saved character lookup (Jord, 29 Oct). Never fails silently.

Order: players/<name>/character.* on disk, then players/players.json entry, then research/asset_registry.json.
Raises LookupError when nothing is found. Test: python3 csj_character_lookup.py <name> (exits 1 if missing).
"""
import json
import sys
from pathlib import Path

ROOT = Path("/mnt/project-files")


def find_saved_character(player_name):
    name = player_name.strip().lower()
    if not name:
        raise LookupError("player name is empty")
    for ext in ("png", "jpg", "jpeg", "webp"):
        p = ROOT / "players" / name / f"character.{ext}"
        if p.exists() and p.stat().st_size > 0:
            return {"player": name, "file": str(p), "source": "players folder"}
    reg = ROOT / "players" / "players.json"
    if reg.exists():
        entry = json.loads(reg.read_text()).get(name)
        if entry and entry.get("character_url"):
            return {"player": name, "file": None, "url": entry["character_url"], "source": "players.json"}
    asset = ROOT / "research" / "asset_registry.json"
    if asset.exists():
        for row in json.loads(asset.read_text()):
            if str(row.get("name", "")).lower() == f"{name}-character" and row.get("url"):
                return {"player": name, "file": None, "url": row["url"], "source": "asset_registry.json"}
    raise LookupError(f"no saved character for '{player_name}' in players/, players.json or asset_registry.json")


if __name__ == "__main__":
    try:
        print(json.dumps(find_saved_character(sys.argv[1])))
    except LookupError as exc:
        print(f"LOOKUP FAILED: {exc}")
        sys.exit(1)
