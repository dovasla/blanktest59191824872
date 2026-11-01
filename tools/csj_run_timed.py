"""One CS Junkie build, every stage, with a timing log for that build.

Usage:
  python3 tools/csj_run_timed.py <inputs.json> <candidates.json> <rows_dir> <out_dir> [--dry-run]

This runs csj_run.main unchanged (same stages, same checks, same encode preset). It also writes
<out_dir>/<clip_id>_timing_log.json with:
  - the start, end and total wall time of the run
  - the exit code and where the run stopped (from csj_run's own run file)
  - for each stage function: how many times it ran, its total seconds and when it first started

How the stage timing works: every top-level function in the csj_* modules is wrapped. Only the
outermost wrapped call on each thread is counted, so a stage that calls other stage code is timed once.
Parallel work in worker threads is counted on each thread, so its seconds can add up to more than the
wall time. The log says so.

Per clip only. Nothing in the log is reused for a later clip (Jord, 1 Nov 2026).
"""
import functools
import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# Modules whose top-level functions are timed. csj_run imports most of these lazily inside main,
# so they are imported here first. Importing them has no build side effects.
STAGE_MODULES = [
    "csj_run", "csj_build", "csj_intake", "csj_resolve", "csj_kill_timing", "csj_kill_tracker",
    "csj_name_scan", "csj_stack_detect", "csj_cache", "csj_caption_step", "csj_caption_check",
    "csj_banner_fit", "csj_banner", "csj_accents", "csj_text", "csj_gates", "csj_onset_check",
    "csj_preflight", "csj_player_cache", "csj_source_dark", "csj_asset_upload", "csj_batch_message",
    "csj_colour_check", "csj_killer_check", "csj_rowcrop", "csj_row_crop",
]


NOT_TIMED = {("csj_run", "main")}


class StageTimer:
    """Collects wall time per stage function. Thread-safe; nested calls on a thread are not counted twice."""

    def __init__(self):
        self._local = threading.local()
        self._lock = threading.Lock()
        self.stages = {}
        self.t0 = time.perf_counter()

    def wrap(self, name, fn):
        timer = self

        @functools.wraps(fn)
        def inner(*args, **kwargs):
            depth = getattr(timer._local, "depth", 0)
            if depth:  # called from another timed stage on this thread: the outer call already counts it
                return fn(*args, **kwargs)
            timer._local.depth = 1
            start = time.perf_counter()
            ok = True
            try:
                return fn(*args, **kwargs)
            except BaseException:
                ok = False
                raise
            finally:
                elapsed = time.perf_counter() - start
                timer._local.depth = 0
                timer._record(name, start - timer.t0, elapsed, ok)

        return inner

    def _record(self, name, offset, elapsed, ok):
        with self._lock:
            s = self.stages.setdefault(name, {"calls": 0, "total_seconds": 0.0,
                                              "first_start_seconds": round(offset, 3), "failed_calls": 0})
            s["calls"] += 1
            s["total_seconds"] = round(s["total_seconds"] + elapsed, 3)
            s["first_start_seconds"] = min(s["first_start_seconds"], round(offset, 3))
            if not ok:
                s["failed_calls"] += 1

    def wrap_modules(self, modules):
        for mod in modules:
            for attr, obj in list(vars(mod).items()):
                if attr.startswith("_") or not callable(obj) or not hasattr(obj, "__code__"):
                    continue
                if getattr(obj, "__module__", None) != mod.__name__:
                    continue  # imported helper, timed in its own module
                if (mod.__name__, attr) in NOT_TIMED:
                    continue  # the run itself: wrapping it would hide every stage inside it
                setattr(mod, attr, self.wrap(f"{mod.__name__}.{attr}", obj))


def write_log(out_dir, clip_id, started, finished, timer, exit_code, dry_run, run_file):
    total = round(finished - started, 3)
    run = {}
    try:
        run = json.loads(Path(run_file).read_text())
    except (OSError, ValueError):
        pass
    stages = sorted(timer.stages.items(), key=lambda kv: kv[1]["first_start_seconds"])
    log = {
        "clip_id": clip_id,
        "dry_run": dry_run,
        "started_utc": datetime.fromtimestamp(started, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "total_seconds": total,
        "exit_code": exit_code,
        "stopped_at": run.get("stopped_at"),
        "blocking_pass": run.get("blocking_pass"),
        "stage_seconds_note": "Parallel worker threads are counted on each thread, so stage seconds can add up to more than total_seconds.",
        "stages": [{"name": name, **data} for name, data in stages],
    }
    path = Path(out_dir) / f"{clip_id}_timing_log.json"
    path.write_text(json.dumps(log, indent=2))
    return path


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(description="One CS Junkie clip, every stage, with a timing log.")
    ap.add_argument("inputs")
    ap.add_argument("candidates")
    ap.add_argument("rows_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--dry-run", action="store_true",
                    help="run every check and the build, no upload, post or schedule")
    a = ap.parse_args(argv)

    import importlib
    mods = [importlib.import_module(name) for name in STAGE_MODULES]
    timer = StageTimer()
    timer.wrap_modules(mods)
    csj_run = importlib.import_module("csj_run")

    clip_id = json.loads(Path(a.inputs).read_text())["clip_id"]
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    exit_code = 1
    try:
        exit_code = csj_run.main(a.inputs, a.candidates, a.rows_dir, a.out_dir, dry_run=a.dry_run)
        return exit_code
    finally:
        finished = time.time()
        # csj_run writes <clip>_run.json itself; the timing log is written even when a stage raises.
        log_path = write_log(out_dir, clip_id, started, finished, timer, exit_code, a.dry_run,
                             out_dir / f"{clip_id}_run.json")
        print(f"timing log: {log_path}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
