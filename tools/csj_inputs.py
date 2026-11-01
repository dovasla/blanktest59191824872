"""CS Junkie inputs file (master skill v39 section 2). One file per clip. A restart reads this file, not the thread.

Usage:
  python3 csj_inputs.py <clip_id> <out.json> --player NAME --kills K1,K2,... --source PATH
        --title "3 WORDS" --c1 #RRGGBB --c2 #RRGGBB [--c3 #RRGGBB] [--nation NAME]
        [--figure PATH] [--banner PATH] [--caption-file PATH] [--length S] [--window-start S]

Fills what can be known from the file. Fields left empty are listed as "missing" and csj_run will stop on them.
window_start defaults to the first onset minus 1.0 s (the dead time, kept at 1 s per Jord, 29 Oct). Set it with
--window-start once onsets are checked. window_end = window_start + length.
--kills is the killer name for each kill, in order, as read from the feed (used by csj_killer_check).
Writes the file and prints the missing fields.
"""
import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip_id")
    ap.add_argument("out")
    ap.add_argument("--player", required=True)
    ap.add_argument("--kills", default="", help="killer name per kill, comma separated")
    ap.add_argument("--source")
    ap.add_argument("--title")
    ap.add_argument("--c1")
    ap.add_argument("--c2")
    ap.add_argument("--c3")
    ap.add_argument("--nation")
    ap.add_argument("--figure")
    ap.add_argument("--banner")
    ap.add_argument("--caption-file")
    ap.add_argument("--length", type=float, default=20.0)
    ap.add_argument("--window-start", type=float)
    ap.add_argument("--fps", type=float, default=60.0)
    a = ap.parse_args()

    killers = [k.strip() for k in a.kills.split(",") if k.strip()]
    colours = {}
    if a.c1:
        colours["colour_1"] = a.c1
    if a.c2:
        colours["colour_2"] = a.c2
    if a.c3:
        colours["colour_3"] = a.c3
    inputs = {
        "clip_id": a.clip_id,
        "player_name": a.player,
        "source": a.source,
        "fps": a.fps,
        "resolution": "1920x1080",
        "kill_count": len(killers),
        "kills": [{"killer": k} for k in killers],
        "top_title": a.title,
        "nation": a.nation,
        "nationality_colours": colours,
        "figure": a.figure,
        "banner": a.banner,
        "caption_file": a.caption_file,
    }
    if a.window_start is not None:
        inputs["window_start"] = a.window_start
        inputs["window_end"] = round(a.window_start + a.length, 4)
    Path(a.out).write_text(json.dumps(inputs, indent=2))
    missing = [k for k, v in inputs.items() if v in (None, "", [], {})]
    print(json.dumps({"written": a.out, "missing": missing}, indent=2))


if __name__ == "__main__":
    main()
