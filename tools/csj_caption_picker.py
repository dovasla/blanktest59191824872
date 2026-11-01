#!/usr/bin/env python3
"""Pick caption templates at random, with no repeats per channel until the pool runs out.

Personalised lines come first. A line with a "needs" list (country, adj, team, enemy_country) is used only
when every fact it needs is known. Facts come from tools/clip_lookup/<clip>.json, one research file per clip,
and only high-confidence facts count. When no personalised line fits, the picker uses the generic
pool (lines without "needs"). Generic lines are never personalised.

Usage:
  python3 -I csj_caption_picker.py --player XANTARES --count 5 --clip 68769a_clip4 --n 3
  python3 -I csj_caption_picker.py --player alex --count 5 --channel youtube --record

Without --record nothing is saved, so a preview does not use up templates.
With --record the picked ids are saved under the channel name (generic) and "personal:<channel>" (personalised)
in caption_picker_state.json.
"""
import argparse
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
POOL_PATH = os.path.join(HERE, "caption_pool.json")
STATE_PATH = os.path.join(HERE, "caption_picker_state.json")
CLIP_DIR = os.path.join(HERE, "clip_lookup")
DEFAULT_HASHTAGS = "#cs2 #csgo"
# Lines that claim headshot counts or kill types (headshot, heads, one-tap, dink, no-scope, wallbang) are never picked.
# Crosshair and tap lines are allowed. Captions must not claim anything the clip does not show.
EXCLUDE_RE = re.compile(r"\b(heads|headshots?|one-tap|dinks?|no-?scopes?|wallbangs?)\b", re.IGNORECASE)


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def normalise_count(raw):
    digits = re.sub(r"[kK]$", "", raw.strip())
    if not digits.isdigit():
        sys.exit(f"count must be a number like 5 or 5K, got: {raw!r}")
    return digits


def facts_for(clip):
    """Facts for personalised lines, read from this clip's research file. Only high-confidence facts count."""
    if not clip:
        return {}
    path = os.path.join(CLIP_DIR, f"{clip}.json")
    data = load_json(path, None)
    if data is None:
        sys.exit(f"no research file for clip {clip!r}: expected {path}")
    facts = {}
    feat = data["featured"]
    if feat.get("country_confidence") == "high":
        facts["country"] = feat["country"]
        facts["adj"] = feat["country_adjective"]
    if feat.get("team_confidence") == "high" and feat.get("team"):
        facts["team"] = feat["team"]
    if feat.get("weapon_confidence") == "high" and feat.get("weapon"):
        facts["weapon"] = feat["weapon"]
    enemy = data["enemy"]
    if enemy.get("country_confidence") == "high" and enemy.get("country"):
        facts["enemy_country"] = enemy["country"]
    return facts


def pick(templates, used_ids, n, rng):
    """Return (chosen_templates, new_used_ids). Starts a new cycle when fewer than n remain."""
    available = [t for t in templates if t["id"] not in used_ids]
    if len(available) < n:
        available = list(templates)
        used_ids = set()
    chosen = rng.sample(available, n)
    return chosen, used_ids | {t["id"] for t in chosen}


def render(template, count, player, hashtags, facts):
    values = {"count": count, "player": player, "COUNT": count, "PLAYER": player.upper()}
    for key, value in facts.items():
        values[key] = value
        values[key.upper()] = value.upper()
    text = template["text"].format(**values)
    if "\n" in text or "—" in text:
        sys.exit(f"template {template['id']} breaks the one-line or no-em-dash rule")
    return f"{text} {hashtags}".strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--player", required=True, help="player name as read from the clip")
    parser.add_argument("--count", required=True, help="kill count, e.g. 5 or 5K")
    parser.add_argument("--clip", help="research file name in tools/clip_lookup, e.g. 68769a_clip4")
    parser.add_argument("--channel", default="preview", help="channel name used for the no-repeat memory")
    parser.add_argument("--n", type=int, default=1, help="how many distinct picks to return")
    parser.add_argument("--hashtags", default=DEFAULT_HASHTAGS)
    parser.add_argument("--record", action="store_true", help="save the picks so they are not reused on this channel")
    args = parser.parse_args()

    templates = load_json(POOL_PATH, {"templates": []})["templates"]
    templates = [t for t in templates if not EXCLUDE_RE.search(t["text"])]
    generic = [t for t in templates if "needs" not in t]

    facts = facts_for(args.clip)
    personal = [t for t in templates if "needs" in t and all(k in facts for k in t["needs"])]

    if args.n < 1 or args.n > len(generic) + len(personal):
        sys.exit(f"--n must be between 1 and {len(generic) + len(personal)}")

    count = normalise_count(args.count)
    state = load_json(STATE_PATH, {})
    personal_key = f"personal:{args.channel}"
    used_personal = set(state.get(personal_key, []))
    used_generic = set(state.get(args.channel, []))

    rng = random.SystemRandom()
    n_personal = min(args.n, len(personal))
    chosen_personal, new_personal = pick(personal, used_personal, n_personal, rng) if n_personal else ([], used_personal)
    n_generic = args.n - n_personal
    chosen_generic, new_generic = pick(generic, used_generic, n_generic, rng) if n_generic else ([], used_generic)

    for t in chosen_personal:
        print(f"{t['id']}\tpersonal\t{render(t, count, args.player, args.hashtags, facts)}")
    for t in chosen_generic:
        print(f"{t['id']}\tgeneric\t{render(t, count, args.player, args.hashtags, {})}")
    if not facts:
        print("# no high-confidence facts for this clip, generic pool only", file=sys.stderr)

    if args.record:
        if chosen_personal:
            state[personal_key] = sorted(new_personal)
        if chosen_generic:
            state[args.channel] = sorted(new_generic)
        save_json(STATE_PATH, state)
        print(
            f"# recorded on channel '{args.channel}': {len(generic) - len(new_generic)} generic and "
            f"{len(personal) - len(new_personal)} personal templates left in this cycle",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
