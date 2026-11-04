#!/usr/bin/env python3
"""CS Junkie kill timing regression check (4 Nov 2026, coordinator note from Jord's thread).

DRY RUN ONLY. Reads six tracked clips and runs the build's kill timing path on each one.
It never uploads, posts, schedules, or edits players/ or any shared file.

Each run recomputes every clip from scratch in a new work folder (no cache), so a change in the
code shows up. Results are saved in build_log/regression/:
  baseline.json        the "before" snapshot (saved with --save-baseline, or the first run)
  runs/<stamp>.json    the "after" snapshot of each run
  latest.json          the most recent run

A kill is reported when:
  - the kill count changes from the baseline, or
  - a kill's onset moves by more than 1 frame at 60 fps.

Usage:
  python3 tools/csj_regression.py --save-baseline    # record the "before" on the current code
  python3 tools/csj_regression.py                    # run again, compare to the baseline
  python3 tools/csj_regression.py --only 692c        # one clip, prefix match on clip id

Exit codes: 0 = no change, 1 = a kill moved or the count changed, 2 = the check could not run.
"""
import argparse
import csv
import hashlib
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = Path("/mnt/project-files")
DEFAULT_REGISTRY = PROJECT / "build_log" / "SOURCE_REGISTRY_v2.csv"
DEFAULT_OUT = PROJECT / "build_log" / "regression"
PLAYERS_DIR = PROJECT / "players"

# The six tracked clips (full clip ids, from the registry).
TRACKED = [
    "692c88fbb1732272d9181897",  # dem0n Nuke
    "69174464081f2160f2db74bc",  # donk Nuke
    "68e153a8328e24afe4367ad5",  # Martinez Nuke
    "697f7d6c24f1e7d4371318fc",  # WOXIC Mirage
    "6a7883b922f3bf53872c93f3",  # Martinez Ancient
    "6ace55f013f8f825955e38de",  # naf Inferno
]
FPS = 60
MOVE_LIMIT_FRAMES = 1


def md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def players_fingerprint():
    """Name, size and mtime of every file under players/. Used to prove this check did not change them."""
    out = []
    for root, _dirs, files in os.walk(PLAYERS_DIR):
        for f in sorted(files):
            p = Path(root) / f
            st = p.stat()
            out.append([str(p.relative_to(PLAYERS_DIR)), st.st_size, int(st.st_mtime)])
    return hashlib.md5(json.dumps(out).encode()).hexdigest()


def load_registry(path):
    with open(path, newline="") as fh:
        rows = {r["clip_id"]: r for r in csv.DictReader(fh)}
    missing = [c for c in TRACKED if c not in rows]
    if missing:
        raise SystemExit(f"STOP: registry has no row for {missing}")
    return rows


def kill_count_for(row):
    """Only Jord's count is used. A blank or non-Jord count stops the check for that clip."""
    if row.get("kill_count_source") != "jord" or not row.get("kill_count"):
        return None
    return int(row["kill_count"])


def run_clip(tools_dir, row, work_dir):
    """Runs the build's onset path (csj_killcount_chain.resolve), the same call csj_intake uses."""
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    import csj_killcount_chain  # noqa: E402

    src = str(PROJECT / row["source_file"])
    player = row["player"]
    expected = kill_count_for(row)
    res = csj_killcount_chain.resolve(src, str(work_dir), player, expected)
    if res is None:
        return {"status": "STOP", "note": f"no name template for player '{player}'", "kills": []}
    kills = [{"kill": k["kill"], "seconds": round(float(k["seconds"]), 4),
              "frame_60fps": int(round(float(k["seconds"]) * FPS)), "status": k.get("status")}
             for k in res["kills"]]
    return {"status": "PASS" if res.get("pass") else "STOP", "note": "; ".join(res.get("flags") or []),
            "kills": kills}


def compare(before, after):
    """Returns a list of change lines. Empty list = no change."""
    changes = []
    for clip in after["clips"].values():
        cid = clip["clip_id"]
        label = clip["label"]
        old = before.get("clips", {}).get(cid)
        if old is None:
            changes.append(f"{label} ({cid[:8]}): not in baseline, cannot compare")
            continue
        if clip["status"] != old["status"] and clip["status"] != "PASS":
            changes.append(f"{label}: status {old['status']} -> {clip['status']}")
        if len(clip["kills"]) != len(old["kills"]):
            changes.append(f"{label}: COUNT CHANGED {len(old['kills'])} -> {len(clip['kills'])} kills")
            continue
        for a, b in zip(old["kills"], clip["kills"]):
            moved = abs(b["frame_60fps"] - a["frame_60fps"])
            if moved > MOVE_LIMIT_FRAMES:
                changes.append(f"{label}: kill {b['kill']} moved {moved} frames "
                               f"({a['seconds']} s -> {b['seconds']} s)")
    return changes


def main():
    ap = argparse.ArgumentParser(description="Dry-run kill timing regression for the six tracked clips.")
    ap.add_argument("--tools", default=str(HERE), help="folder with csj_killcount_chain.py (default: this folder)")
    ap.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="folder for baseline, runs and latest results")
    ap.add_argument("--save-baseline", action="store_true", help="save this run as the 'before' snapshot")
    ap.add_argument("--only", default="", help="clip id prefix, run one tracked clip only")
    args = ap.parse_args()

    tools_dir = Path(args.tools)
    out_dir = Path(args.out)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    work_root = out_dir / "work" / stamp
    work_root.mkdir(parents=True, exist_ok=True)
    (out_dir / "runs").mkdir(parents=True, exist_ok=True)

    rows = load_registry(args.registry)
    ids = [c for c in TRACKED if c.startswith(args.only)] if args.only else TRACKED
    if not ids:
        print(f"STOP: no tracked clip starts with '{args.only}'")
        return 2

    players_before = players_fingerprint()
    result = {"stamp": stamp, "fps": FPS, "clips": {}}
    stopped = []

    for cid in ids:
        row = rows[cid]
        label = row["clip_label"]
        src = PROJECT / row["source_file"]
        entry = {"clip_id": cid, "label": label, "player": row["player"], "source_file": row["source_file"],
                 "kill_count_expected": kill_count_for(row), "md5_matches_registry": None}
        if not src.exists():
            entry.update(status="STOP", note="source file missing, not touched", kills=[])
            result["clips"][cid] = entry
            stopped.append(f"{label}: source missing")
            continue
        entry["md5_matches_registry"] = md5_of(src) == row["source_md5"]
        if entry["kill_count_expected"] is None:
            entry.update(status="STOP", note="no Jord kill count in registry", kills=[])
            result["clips"][cid] = entry
            stopped.append(f"{label}: no Jord kill count")
            continue
        print(f"running {label} ({cid[:8]}) ...", flush=True)
        try:
            run = run_clip(tools_dir, row, work_root / cid)
            entry.update(run)
        except Exception as exc:  # one clip failing does not hide the others
            entry.update(status="STOP", note=f"{type(exc).__name__}: {exc}", kills=[],
                         trace=traceback.format_exc(limit=3))
        if entry["status"] != "PASS":
            stopped.append(f"{label}: {entry['status']} {entry['note']}")
        result["clips"][cid] = entry

    players_after = players_fingerprint()
    result["players_unchanged"] = players_before == players_after

    run_file = out_dir / "runs" / f"{stamp}.json"
    run_file.write_text(json.dumps(result, indent=2))
    (out_dir / "latest.json").write_text(json.dumps(result, indent=2))

    baseline_file = out_dir / "baseline.json"
    changes = []
    if args.save_baseline or not baseline_file.exists():
        # A stopped clip is saved too, with its STOP status, so later runs still compare it.
        baseline_file.write_text(json.dumps(result, indent=2))
        print(f"BASELINE saved: {baseline_file}")
    else:
        before = json.loads(baseline_file.read_text())
        changes = compare(before, result)

    print(f"Run saved: {run_file}")
    for cid in ids:
        c = result["clips"][cid]
        times = ", ".join(f"{k['seconds']}" for k in c["kills"])
        print(f"  {c['label']}: {c['status']}, {len(c['kills'])} kills (expected {c['kill_count_expected']}), "
              f"md5 match {c['md5_matches_registry']}: [{times}]")
    if not result["players_unchanged"]:
        print("WARNING: players/ changed during the check")
    if stopped:
        print("STOPPED CLIPS:")
        for s in stopped:
            print(f"  {s}")
    if changes:
        print("CHANGES (kill moved more than 1 frame, or count changed):")
        for c in changes:
            print(f"  {c}")
    else:
        print("Saved as baseline. Nothing to compare yet." if args.save_baseline
              else "No kill moved more than 1 frame and no count changed.")

    if stopped:
        return 2
    return 1 if changes else 0


if __name__ == "__main__":
    sys.exit(main())
