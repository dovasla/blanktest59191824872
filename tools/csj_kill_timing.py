"""CS Junkie kill timing, one command (29 Oct 2026). Dry run only: writes timings, never uploads or posts.

Usage:
  python3 csj_kill_timing.py <inputs.json> <out_dir>

Runs csj_name_scan.py twice into out_dir/run1 and out_dir/run2, then compares the two runs.
Prints both runs side by side and writes out_dir/summary.json.
Exit 0 only when both runs agree and every kill is confirmed (no flags).
Flags for unconfirmed kills go to research/kill_timing_flags.jsonl, from csj_name_scan.py.
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run_once(inputs, out):
    subprocess.run([sys.executable, str(HERE / "csj_name_scan.py"), inputs, str(out)],
                   capture_output=True, check=False)
    return json.loads((out / "onsets.json").read_text())


def main(inputs, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    r1 = run_once(inputs, out / "run1")
    r2 = run_once(inputs, out / "run2")

    def onsets(r):
        return [(k["kill"], k["candidate_s"], k.get("seconds")) for k in r["kills"]]

    same = onsets(r1) == onsets(r2)
    confirmed = [k for k in r1["kills"] if k["status"] == "pass"]
    flagged = [k for k in r1["kills"] if k["status"] != "pass"]
    summary = {"same_result_twice": same, "run1": onsets(r1), "run2": onsets(r2),
               "confirmed": len(confirmed), "flagged": [k["candidate_s"] for k in flagged],
               "flags": r1["flags"], "frame_reads_per_run": r1["frame_reads_total"],
               "pass": same and not r1["flags"]}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print("kill | candidate | run1 onset | run2 onset")
    for (k, c, s1), (_, _, s2) in zip(onsets(r1), onsets(r2)):
        print(f"{k} | {c} | {s1} | {s2}")
    print(f"same result twice: {same}")
    print(f"confirmed: {len(confirmed)}, flagged: {summary['flagged']}")
    print(f"frame reads per run: {r1['frame_reads_total']}")
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
