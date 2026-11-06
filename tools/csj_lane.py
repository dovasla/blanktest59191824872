"""csj_lane.py - read-only auto lane report (F0 + F1).

Reads each built clip's *_run.json and *_gates.json under final_builds\\rowN\\,
decides "ready" or "review", and writes a CSV and a Markdown report.
It changes no registry row, no clip file and no status. Safe to run any time.

F0 rule: the character file used by the clip must exist and its md5 must match
the approved md5 for that exact file path in csj_character_md5.json.
A clip that fails F0 is never "ready".

A clip is "ready" only when all of these hold:
  - run.stopped_at is empty
  - run.blocking_pass is true
  - run.not_final is false (NOT FINAL can never be ready)
  - no NEEDS_EYE_CHECK item in the gates file or the run labels
  - the character file passes F0

Usage:
  python csj_lane.py --project-root "C:\\Users\\Jordan\\Desktop\\CS JUNKIE" \
      [--final-builds PATH] [--md5 PATH] [--out-dir PATH]

Default out dir: <project-root>\\review_lane\\<YYYY-MM-DD>\\ (new folder).
"""

import argparse
import csv
import datetime
import glob
import hashlib
import json
import os
import re
import sys

MARK = "CS JUNKIE"


def md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rel_from_recorded(recorded, project_root):
    """Turn a recorded path (may be a Windows path under the project) into a local path.

    Returns (local_path, relative_path_under_project). relative uses forward slashes.
    """
    norm = recorded.replace("\\", "/")
    low = norm.lower()
    key = MARK.lower() + "/"
    idx = low.find(key)
    if idx >= 0:
        rel = norm[idx + len(key):]
    else:
        rel = norm.lstrip("/")
    local = os.path.join(project_root, *rel.split("/"))
    return local, rel


def load_md5_table(path):
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    by_file = {}
    for player, entry in data.items():
        by_file[entry["file"].replace("\\", "/")] = (player, entry["md5"].lower())
    return data, by_file


def check_character(recorded, project_root, by_file):
    """F0. Returns (ok, reason, player, md5)."""
    if not recorded:
        return False, "no character file recorded in run file", "", ""
    local, rel = rel_from_recorded(recorded, project_root)
    if rel not in by_file:
        return False, "character file not on the approved list: " + rel, "", ""
    player, want = by_file[rel]
    if not os.path.isfile(local):
        return False, "approved character file missing on disk: " + rel, player, ""
    got = md5_of(local)
    if got != want:
        return False, "character md5 does not match approved (%s vs %s): %s" % (got[:8], want[:8], rel), player, got
    return True, "approved character " + rel, player, got


def eye_items(run, gates):
    items = []
    for n in (gates or {}).get("needs_eye_check", []) or []:
        items.append("NEEDS_EYE_CHECK %s: %s" % (n.get("step"), n.get("reason")))
    for lab in (run or {}).get("labels", []) or []:
        if "NEEDS_EYE_CHECK" in lab:
            items.append(lab)
    return items


def decide(clip_id, run, gates, char_ok, char_reason):
    reasons = []
    if run.get("stopped_at"):
        reasons.append("stopped at " + str(run.get("stopped_at")))
    if not run.get("blocking_pass"):
        reasons.append("blocking gate failed")
    if run.get("not_final"):
        reasons.append("NOT FINAL")
    reasons += eye_items(run, gates)
    if not char_ok:
        reasons.append("F0 character: " + char_reason)
    status = "ready" if not reasons else "review"
    return status, reasons


def warnings_of(gates):
    out = []
    for k, v in ((gates or {}).get("warnings") or {}).items():
        if isinstance(v, dict) and v.get("pass") is False:
            out.append(k)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", required=True)
    ap.add_argument("--final-builds", default=None)
    ap.add_argument("--md5", default=None)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    root = args.project_root
    fb = args.final_builds or os.path.join(root, "final_builds")
    md5_path = args.md5 or os.path.join(root, "tools", "csj_character_md5.json")
    today = datetime.date.today().isoformat()
    out_dir = args.out_dir or os.path.join(root, "review_lane", today)
    os.makedirs(out_dir, exist_ok=True)

    _, by_file = load_md5_table(md5_path)

    rows = []
    for run_path in sorted(glob.glob(os.path.join(fb, "row*", "*_run.json"))):
        clip_id = os.path.basename(run_path)[: -len("_run.json")]
        gates_path = run_path[: -len("_run.json")] + "_gates.json"
        with open(run_path, encoding="utf-8-sig") as f:
            run = json.load(f)
        gates = {}
        if os.path.isfile(gates_path):
            with open(gates_path, encoding="utf-8-sig") as f:
                gates = json.load(f)
        recorded = (run.get("player_assets") or {}).get("character") or ""
        char_ok, char_reason, player, got = check_character(recorded, root, by_file)
        status, reasons = decide(clip_id, run, gates, char_ok, char_reason)
        rows.append({
            "clip_id": clip_id,
            "row": os.path.basename(os.path.dirname(run_path)),
            "player": player,
            "status": status,
            "reasons": "; ".join(reasons),
            "warnings_logged": ", ".join(warnings_of(gates)),
            "character_file": recorded,
            "character_md5": got,
            "run_file": run_path,
        })

    csv_path = os.path.join(out_dir, "lane_report.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["clip_id"])
        w.writeheader()
        for r in rows:
            w.writerow(r)

    ready = [r for r in rows if r["status"] == "ready"]
    review = [r for r in rows if r["status"] != "ready"]
    md_path = os.path.join(out_dir, "lane_report.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Auto lane report %s\n\n" % today)
        f.write("Read only. Nothing was changed.\n\n")
        f.write("Ready: %d. Needs review: %d.\n\n" % (len(ready), len(review)))
        f.write("## Ready\n\n")
        for r in ready:
            f.write("- %s (%s, %s)\n" % (r["clip_id"], r["row"], r["player"] or "player unknown"))
        f.write("\n## Needs review\n\n")
        for r in review:
            f.write("- %s (%s): %s\n" % (r["clip_id"], r["row"], r["reasons"]))
        f.write("\n## Warnings logged only (not blocking)\n\n")
        for r in rows:
            if r["warnings_logged"]:
                f.write("- %s: %s\n" % (r["clip_id"], r["warnings_logged"]))

    print("ready=%d review=%d" % (len(ready), len(review)))
    print(csv_path)
    print(md_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
