#!/usr/bin/env python3
"""One loader and checker for the CS Junkie streamline tools.

It reads three files from the project folder:
  players/players.json              player names, nationality, character files
  tools/csj_character_md5.json      approved character PNGs and their md5
  build_log/SOURCE_REGISTRY_v2.csv  one row per clip: map, player, source file, md5, size

It only reads. It never writes, moves, uploads or posts anything.

Command line:
  python3 tools/streamline/config.py              # check the project folder
  python3 tools/streamline/config.py --root DIR   # check another folder
  python3 tools/streamline/config.py --no-media   # skip the md5 of the clip files (faster)

From code:
  import sys
  sys.path.insert(0, "tools/streamline")
  from config import load_config

  cfg = load_config()              # raises ConfigError if any check fails
  cfg.player("demon")              # -> "demon" (the players.json key)
  cfg.ingame_name("demon")         # -> "dem0n"
  cfg.nationality("donk")          # -> "Russia"
  cfg.clip("6a2d6739")             # -> one registry row (full id, or a prefix that matches one row)
  cfg.clips                        # all registry rows (dicts)

Project folder: --root, else the CSJ_ROOT environment variable, else /mnt/project-files.
Exit code: 0 when there are no FAIL lines, 1 when there is at least one.
"""

import argparse
import csv
import hashlib
import json
import os
import re
import sys

DEFAULT_ROOT = "/mnt/project-files"
PLAYERS_PATH = "players/players.json"
MD5_PATH = "tools/csj_character_md5.json"
REGISTRY_PATH = "build_log/SOURCE_REGISTRY_v2.csv"

KNOWN_MAPS = {"Ancient", "Dust 2", "Inferno", "Mirage", "Nuke", "Cache", "Anubis", "Overpass", "Train"}
REQUIRED_COLUMNS = [
    "clip_id", "map", "player", "nationality",
    "source_file", "source_md5", "source_bytes", "build_status",
]
CLIP_ID_RE = re.compile(r"[0-9a-f]{24}")
MD5_RE = re.compile(r"[0-9a-f]{32}")


class ConfigError(Exception):
    """Raised by load_config when a check fails. .problems holds every FAIL line."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


class Config:
    """Loaded and checked project data."""

    def __init__(self, root, players, md5s, clips):
        self.root = root
        self.players = players  # players.json key -> entry dict
        self.md5s = md5s        # name -> {"file": path, "md5": hex}
        self.clips = clips      # registry rows as dicts, clip_id lower case

    def player(self, name):
        """Return the players.json key for a key or in-game name. Raises KeyError if unknown."""
        key = _find_player(self.players, name)
        if key is None:
            raise KeyError(f"unknown player: {name}")
        return key

    def ingame_name(self, name):
        """Exact in-game spelling, e.g. 'dem0n', 'NAF'."""
        key = self.player(name)
        return self.players[key].get("ingame_name") or key

    def nationality(self, name):
        """Nation without the note, e.g. 'Russia'. None when players.json has no nation."""
        return clean_nation(self.players[self.player(name)].get("nationality"))

    def clip(self, clip_id):
        """Return one registry row. A full id always wins. A prefix must match exactly one row."""
        q = (clip_id or "").strip().lower()
        for row in self.clips:
            if row["clip_id"] == q:
                return row
        hits = [row for row in self.clips if row["clip_id"].startswith(q)] if q else []
        if len(hits) == 1:
            return hits[0]
        if not hits:
            raise KeyError(f"no clip id starts with {q!r}")
        raise KeyError(f"{q!r} matches {len(hits)} clips, use the full id")

    def path(self, rel):
        """Full path for a path that the data files give relative to the project folder."""
        return os.path.join(self.root, rel)


class Report:
    """Result of check(). config is None only when the project folder itself is missing."""

    def __init__(self, root, config, problems, warnings):
        self.root = root
        self.config = config
        self.problems = problems  # FAIL lines
        self.warnings = warnings  # WARN lines


def clean_nation(text):
    """'Russia (Jord, 1 Nov 2026)' -> 'Russia'. Blank or 'unknown...' -> None."""
    if not text:
        return None
    base = str(text).split(" (")[0].strip()
    if not base or base.lower().startswith("unknown"):
        return None
    return base


def _find_player(players, name):
    """Match on players.json keys first, then in-game names. Also tries 0 and o swapped."""
    q = (name or "").strip().lower()
    index = {}
    for key in players:
        index.setdefault(key.lower(), key)
    for key, entry in players.items():
        ingame = str((entry or {}).get("ingame_name") or "").lower()
        if ingame:
            index.setdefault(ingame, key)
    for cand in (q, q.replace("0", "o"), q.replace("o", "0")):
        if cand in index:
            return index[cand]
    return None


def _reject_dupes(pairs):
    seen = {}
    dupes = set()
    for key, value in pairs:
        if key in seen:
            dupes.add(key)
        seen[key] = value
    if dupes:
        raise ValueError("duplicate keys: " + ", ".join(sorted(dupes)))
    return seen


def _load_json(path, label, problems):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f, object_pairs_hook=_reject_dupes)
    except FileNotFoundError:
        problems.append(f"{label}: file not found: {path}")
    except (OSError, ValueError) as e:
        problems.append(f"{label}: could not read as JSON ({e})")
    return None


def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def check(root=None, verify_media=True):
    """Run every check and return a Report. Never raises for bad data, only for bad arguments."""
    root = root or os.environ.get("CSJ_ROOT") or DEFAULT_ROOT
    problems, warnings = [], []
    if not os.path.isdir(root):
        problems.append(f"project folder not found: {root}")
        return Report(root, None, problems, warnings)

    # 1. players.json
    players = {}
    raw_players = _load_json(os.path.join(root, PLAYERS_PATH), "players.json", problems)
    players_loaded = isinstance(raw_players, dict)
    if players_loaded:
        for key, entry in raw_players.items():
            if not isinstance(entry, dict):
                problems.append(f"players.json: {key} is not an object")
                continue
            if not str(entry.get("ingame_name") or "").strip():
                problems.append(f"players.json: {key} has no ingame_name")
            if clean_nation(entry.get("nationality")) is None:
                warnings.append(f"players.json: {key} has no nationality (treated as no nation)")
            char = entry.get("character_file")
            if char and not os.path.isfile(os.path.join(root, char)):
                warnings.append(f"players.json: {key} character_file not found: {char}")
            players[key] = entry
    elif raw_players is not None:
        problems.append("players.json: top level must be an object")

    # 2. md5 list of approved character files
    md5s = {}
    raw_md5 = _load_json(os.path.join(root, MD5_PATH), "md5 list", problems)
    if isinstance(raw_md5, dict):
        for name, entry in raw_md5.items():
            rel = (entry or {}).get("file") or ""
            want = str((entry or {}).get("md5") or "").lower()
            if not MD5_RE.fullmatch(want):
                problems.append(f"md5 list: {name} has no valid md5")
                continue
            if not rel or not os.path.isfile(os.path.join(root, rel)):
                problems.append(f"md5 list: {name} file not found: {rel}")
                continue
            got = _md5(os.path.join(root, rel))
            if got != want:
                problems.append(f"md5 list: {name} md5 differs for {rel} (disk {got}, list {want})")
            md5s[name] = {"file": rel, "md5": want}
            if name not in players:
                warnings.append(f"md5 list: {name} is not a key in players.json")

    # 3. registry, one row per clip
    clips = []
    reg_path = os.path.join(root, REGISTRY_PATH)
    rows = []
    try:
        with open(reg_path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            missing = [c for c in REQUIRED_COLUMNS if c not in header]
            if missing:
                problems.append("registry: missing columns: " + ", ".join(missing))
            rows = list(reader)
    except FileNotFoundError:
        problems.append(f"registry: file not found: {reg_path}")
    except OSError as e:
        problems.append(f"registry: could not read {reg_path} ({e})")

    seen = set()
    for n, row in enumerate(rows, start=2):  # line 1 is the header
        raw_id = (row.get("clip_id") or "").strip().lower()
        if not CLIP_ID_RE.fullmatch(raw_id):
            problems.append(f"registry line {n}: clip_id is not 24 hex characters: {row.get('clip_id')!r}")
            continue
        if raw_id in seen:
            problems.append(f"registry line {n}: duplicate clip_id {raw_id}")
        seen.add(raw_id)
        label = f"registry {raw_id[:8]}"

        mp = (row.get("map") or "").strip()
        if mp not in KNOWN_MAPS:
            problems.append(f"{label}: unknown map {mp!r}")

        player_text = (row.get("player") or "").strip()
        key = _find_player(players, player_text)
        if key is None:
            if players_loaded:  # if players.json itself failed, its FAIL line already says so
                problems.append(f"{label}: player {player_text!r} is not in players.json")
        else:
            want = clean_nation(players[key].get("nationality"))
            got = clean_nation(row.get("nationality"))
            if got and want and got.lower() != want.lower():
                warnings.append(f"{label}: nationality {got!r} differs from players.json {want!r}")

        src = (row.get("source_file") or "").strip()
        src_path = os.path.join(root, src) if src else ""
        if not src or not os.path.isfile(src_path):
            problems.append(f"{label}: source file not found: {src!r}")
        else:
            size_disk = os.path.getsize(src_path)
            try:
                size_reg = int((row.get("source_bytes") or "").strip())
            except ValueError:
                size_reg = None
                problems.append(f"{label}: source_bytes is not a number")
            if size_reg is not None and size_disk != size_reg:
                problems.append(
                    f"{label}: size differs for {src} (disk {size_disk}, registry {size_reg}). "
                    "Keep the current copy and flag it."
                )
            if verify_media:
                want_md5 = (row.get("source_md5") or "").strip().lower()
                if not MD5_RE.fullmatch(want_md5):
                    problems.append(f"{label}: source_md5 is not a valid md5")
                elif _md5(src_path) != want_md5:
                    problems.append(
                        f"{label}: md5 differs for {src}. Keep the current copy and flag it."
                    )

        clip = dict(row)
        clip["clip_id"] = raw_id
        clips.append(clip)

    config = Config(root, players, md5s, clips)
    return Report(root, config, problems, warnings)


def load_config(root=None, verify_media=True):
    """Return a Config. Raises ConfigError with every FAIL line if any check fails."""
    report = check(root=root, verify_media=verify_media)
    if report.problems or report.config is None:
        raise ConfigError(report.problems)
    return report.config


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check the CS Junkie config files. Read only.")
    ap.add_argument("--root", help="project folder (default: CSJ_ROOT or /mnt/project-files)")
    ap.add_argument("--no-media", action="store_true", help="skip the md5 of the clip files")
    args = ap.parse_args(argv)

    report = check(root=args.root, verify_media=not args.no_media)
    for line in report.problems:
        print("FAIL", line)
    for line in report.warnings:
        print("WARN", line)
    cfg = report.config
    counts = (
        f"players {len(cfg.players) if cfg else 0} | md5 list {len(cfg.md5s) if cfg else 0} | "
        f"clips {len(cfg.clips) if cfg else 0}"
    )
    print(f"{counts} | FAIL {len(report.problems)} | WARN {len(report.warnings)}")
    return 1 if report.problems or cfg is None else 0


if __name__ == "__main__":
    sys.exit(main())
