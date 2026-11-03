"""Regression check for the known failed clips (2 Nov 2026).

Re-runs the existing bulk dry run (tools/csj_bulk.py) on each clip that failed in the
latest bulk run, then prints PASS or FAIL for each gate. Shared code is not changed.
Nothing is uploaded, posted or scheduled (csj_bulk never uploads). Output goes to --out only.

Usage:
  python3 check_fixed_cases.py [--root /mnt/project-files] [--out DIR] [--only LABEL ...] [--timeout SEC]

Which clips run:
  The latest bulk_summary.json for each clip (build_log/bulk_*/bulk_summary.json, newest file wins).
  Clips whose latest status is SKIPPED, STOPPED or NOT RUN. Map, player and file come from
  build_log/SOURCE_REGISTRY.csv (clip_label, map, player, file).

Gates printed (from <out>/<clip>/<clip>_gates.json):
  probe, timing_arithmetic, row_edge, edge_bands (blocking), slide (reported, flags only).
  A clip with no gates file prints its bulk status and reasons instead.

Exit code: 0 when every checked clip passes all gates, 1 otherwise, 2 for a setup error.
"""
import argparse
import csv
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

GATES = ["probe", "timing_arithmetic", "row_edge", "edge_bands"]
FAILED_STATUSES = {"SKIPPED", "STOPPED", "NOT RUN"}
HERE = Path(__file__).resolve().parent


def load_registry(root):
    with open(root / "build_log" / "SOURCE_REGISTRY.csv", newline="") as f:
        return [r for r in csv.DictReader(f) if r.get("clip_label", "").strip()]


def find_row(rows, label):
    """Exact clip_label first. Else the row whose label, old_name or file holds the label's ID token."""
    for r in rows:
        if r["clip_label"].strip() == label:
            return r
    token = label.split()[-1].strip("()") if label.split() else ""
    if len(token) >= 3:
        for r in rows:
            hay = " ".join([r.get("clip_label", ""), r.get("old_name", ""), r.get("file", "")])
            if token in hay and r.get("map", "").strip() and r["map"].strip() in label:
                return r
    return None


def latest_statuses(root):
    """Newest bulk summary wins for each clip id."""
    files = sorted(glob.glob(str(root / "build_log" / "bulk_*" / "bulk_summary.json")), key=os.path.getmtime)
    latest = {}
    for p in files:
        try:
            rows = json.loads(Path(p).read_text())
        except (OSError, ValueError):
            continue
        for r in rows if isinstance(rows, list) else []:
            if isinstance(r, dict) and r.get("clip_id"):
                latest[r["clip_id"]] = r
    return latest


def cv2_ok():
    try:
        import cv2  # noqa: F401
        return True
    except ImportError:
        return False


def write_sheet(path, clip_id, file_value, map_name, player):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["clip id", "file", "map", "player"])
        w.writerow([clip_id, file_value, map_name, player])


def run_one(root, out_dir, clip_id, file_value, map_name, player, timeout):
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet = out_dir / "sheet.csv"
    write_sheet(sheet, clip_id, file_value, map_name, player)
    cmd = [sys.executable, str(root / "tools" / "csj_bulk.py"), str(sheet), str(out_dir / "bulk")]
    try:
        subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status": "TIMEOUT", "reasons": [f"no result in {timeout} s"], "gates": None}
    summ = out_dir / "bulk" / "bulk_summary.json"
    entry = {"status": "NO SUMMARY", "reasons": [], "gates": None}
    if summ.exists():
        rows = json.loads(summ.read_text())
        if rows:
            entry["status"] = rows[0].get("status", "?")
            entry["reasons"] = rows[0].get("reasons", [])
    gates_files = glob.glob(str(out_dir / "bulk" / "*" / "*_gates.json"))
    if gates_files:
        entry["gates"] = json.loads(Path(gates_files[0]).read_text())
    return entry


def gate_results(gates):
    """Return {gate: (pass_bool, note)} for the printed gates."""
    res = {}
    blocking = gates.get("blocking", {})
    for g in GATES:
        if g not in blocking:
            res[g] = (False, "not run")
        else:
            flags = blocking[g].get("flags", [])
            res[g] = (bool(blocking[g].get("pass")), "; ".join(map(str, flags))[:90])
    slide = gates.get("reported", {}).get("slide", {})
    res["slide"] = (bool(slide.get("pass")), slide.get("error", ""))
    return res


def main():
    ap = argparse.ArgumentParser(description="Re-run the dry-run gates on the known failed clips.")
    ap.add_argument("--root", default="/mnt/project-files")
    ap.add_argument("--out", default="regression_out")
    ap.add_argument("--only", nargs="*", default=None, help="clip labels to run, as in the registry")
    ap.add_argument("--timeout", type=int, default=1800, help="seconds per clip")
    a = ap.parse_args()

    root = Path(a.root)
    out = Path(a.out).resolve()
    if not (root / "tools" / "csj_bulk.py").exists():
        print(f"setup error: {root}/tools/csj_bulk.py not found")
        return 2
    if not cv2_ok():
        print("setup error: cv2 missing. Run: pip install opencv-python-headless")
        return 2

    registry = load_registry(root)
    latest = latest_statuses(root)  # clip id -> newest bulk entry
    labels = a.only if a.only else [c for c, r in latest.items() if r.get("status") in FAILED_STATUSES]
    if not labels:
        print("no failed clips found in the latest bulk summaries")
        return 0

    print(f"checking {len(labels)} clip(s) -> {out}")
    print(f"{'clip':<40} {'bulk status':<12} " + " ".join(f"{g:<12}" for g in GATES + ['slide']) + " result")
    all_pass = True
    for label in labels:
        reg = find_row(registry, label)
        if reg is None:
            print(f"{label:<40} NOT IN REGISTRY -> FAIL")
            all_pass = False
            continue
        file_value = reg.get("file") or reg.get("old_name") or ""
        map_name, player = reg.get("map", "").strip(), reg.get("player", "").strip()
        if not (file_value and map_name and player):
            print(f"{label:<40} registry row incomplete (file/map/player) -> FAIL")
            all_pass = False
            continue
        safe = "".join(ch if ch.isalnum() else "_" for ch in label)[:60]
        entry = run_one(root, out / safe, label, file_value, map_name, player, a.timeout)
        if entry["gates"] is None:
            why = "; ".join(map(str, entry["reasons"]))[:120] or "no gates file"
            print(f"{label:<40} {entry['status']:<12} no gate results: {why} -> FAIL")
            all_pass = False
            continue
        res = gate_results(entry["gates"])
        ok = all(p for p, _ in res.values())
        all_pass &= ok
        cells = " ".join(f"{('PASS' if res[g][0] else 'FAIL'):<12}" for g in GATES + ["slide"])
        print(f"{label:<40} {entry['status']:<12} {cells} {'PASS' if ok else 'FAIL'}")
        for g in GATES + ["slide"]:
            if not res[g][0] and res[g][1]:
                print(f"    {g}: {res[g][1]}")
    print("ALL PASS" if all_pass else "SOME FAILED")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
