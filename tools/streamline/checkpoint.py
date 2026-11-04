#!/usr/bin/env python3
"""Stage checkpoints for the clip streamline.

Each stage saves a record of what went in (checksums of its input files plus
its params) and what came out (checksums of its output files). A rerun skips
the stage when the inputs and params match and every output is still intact.
Otherwise the stage runs again.

Rules:
- A stage with no saved record always runs.
- The record is removed before the stage starts, so a crash never leaves a
  false "done" behind.
- A changed input, changed params, changed output list, missing output or
  edited output all make the stage run again.

Python use:

    from checkpoint import Checkpoint
    cp = Checkpoint("/path/to/state")
    res = cp.run(
        "build_clip",
        inputs=["/path/source.mp4"],
        outputs=["/path/out/clip.mp4"],
        params={"map": "Nuke", "fps": 60},
        fn=lambda: do_the_build(),   # return a JSON-friendly value or None
    )
    # res = {"ran": bool, "reason": str, "result": ...}

Command line use:

    # Ask whether a stage can be skipped. Exit 0 = skip, 2 = must run, 1 = error.
    python3 checkpoint.py check --state-dir DIR --stage build_clip \
        --input /path/source.mp4 --output /path/out/clip.mp4 \
        --params-json '{"map":"Nuke","fps":60}'

    # Show all saved stages.
    python3 checkpoint.py status --state-dir DIR

    # Forget one stage so it runs again.
    python3 checkpoint.py reset --state-dir DIR --stage build_clip

The state folder can also come from the STREAMLINE_STATE_DIR environment
variable. Only the standard library is used.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

CHUNK = 1024 * 1024
RECORD_VERSION = 1
STAGE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")

EXIT_SKIP = 0
EXIT_RUN = 2
EXIT_ERROR = 1


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def hash_path(path):
    """Return a checksum record for a file or folder, or None if missing.

    A folder hashes every file under it, by relative path and content.
    """
    p = Path(path)
    if p.is_file():
        return {"type": "file", "sha256": _sha256_file(p)}
    if p.is_dir():
        h = hashlib.sha256()
        for f in sorted(x for x in p.rglob("*") if x.is_file()):
            rel = f.relative_to(p).as_posix()
            h.update(rel.encode("utf-8") + b"\0")
            h.update(_sha256_file(f).encode("ascii") + b"\n")
        return {"type": "dir", "sha256": h.hexdigest()}
    return None


def _fingerprint(obj):
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Checkpoint:
    """Saves and checks stage records in one state folder."""

    def __init__(self, state_dir):
        self.state_dir = Path(state_dir)

    # ----- paths and records -------------------------------------------------

    def _record_path(self, stage):
        if not STAGE_RE.match(stage or ""):
            raise ValueError(
                f"bad stage name {stage!r}: use letters, digits, '_', '.', '-' only"
            )
        return self.state_dir / f"{stage}.json"

    def load(self, stage):
        """Return the saved record for a stage, or None."""
        path = self._record_path(stage)
        if not path.is_file():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                record = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None  # a damaged record counts as no record
        if record.get("record_version") != RECORD_VERSION:
            return None
        return record

    def _write(self, stage, record):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        path = self._record_path(stage)
        fd, tmp = tempfile.mkstemp(dir=str(self.state_dir), prefix=".tmp_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2, sort_keys=True, default=str)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    # ----- decisions ---------------------------------------------------------

    def _input_hashes(self, inputs):
        out = {}
        for p in inputs:
            info = hash_path(p)
            if info is None:
                raise FileNotFoundError(f"input missing: {p}")
            out[str(p)] = info
        return out

    def _key(self, input_hashes, params, outputs):
        return _fingerprint({
            "inputs": input_hashes,
            "params": params or {},
            "outputs": sorted(str(o) for o in outputs),
        })

    def check(self, stage, inputs=(), params=None, outputs=()):
        """Say whether the stage can be skipped. Runs nothing.

        Returns (can_skip, reason).
        """
        input_hashes = self._input_hashes(inputs)
        record = self.load(stage)
        if record is None:
            return False, "no saved record"
        if record.get("key") != self._key(input_hashes, params, outputs):
            return False, "inputs, params or outputs changed"
        for out in record.get("outputs", []):
            info = hash_path(out["path"])
            if info is None:
                return False, f"output missing: {out['path']}"
            if info != out["info"]:
                return False, f"output changed: {out['path']}"
        return True, "inputs and outputs unchanged"

    def run(self, stage, fn, inputs=(), params=None, outputs=(), force=False):
        """Run fn unless the stage is up to date. Returns a dict:

        {"ran": bool, "reason": str, "result": <value fn returned, or the saved one>}
        """
        if force:
            can_skip, reason = False, "forced"
        else:
            can_skip, reason = self.check(stage, inputs, params, outputs)

        if can_skip:
            record = self.load(stage)
            return {"ran": False, "reason": reason, "result": record.get("result")}

        input_hashes = self._input_hashes(inputs)
        key = self._key(input_hashes, params, outputs)

        # Remove the old record first, so a crash leaves no false "done".
        path = self._record_path(stage)
        if path.exists():
            path.unlink()

        result = fn()

        out_records = []
        for out in outputs:
            info = hash_path(out)
            if info is None:
                raise FileNotFoundError(f"stage {stage!r} did not create output: {out}")
            out_records.append({"path": str(out), "info": info})

        record = {
            "record_version": RECORD_VERSION,
            "stage": stage,
            "key": key,
            "params": params or {},
            "inputs": input_hashes,
            "outputs": out_records,
            "result": result,
            "saved_at": _now_iso(),
        }
        self._write(stage, record)
        return {"ran": True, "reason": reason, "result": result}

    # ----- housekeeping ------------------------------------------------------

    def stages(self):
        """Names of all saved stages."""
        if not self.state_dir.is_dir():
            return []
        names = []
        for p in sorted(self.state_dir.glob("*.json")):
            if p.name.startswith(".tmp_"):
                continue
            names.append(p.stem)
        return names

    def reset(self, stage):
        """Forget a stage so it runs again. Returns True if a record was removed."""
        path = self._record_path(stage)
        if path.exists():
            path.unlink()
            return True
        return False


def _now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----- command line -----------------------------------------------------------

def _state_dir(args):
    d = args.state_dir or os.environ.get("STREAMLINE_STATE_DIR")
    if not d:
        raise SystemExit("error: give --state-dir or set STREAMLINE_STATE_DIR")
    return d


def _params(args):
    if args.params_json and args.params_file:
        raise SystemExit("error: use only one of --params-json or --params-file")
    if args.params_file:
        with open(args.params_file, "r", encoding="utf-8") as f:
            return json.load(f)
    if args.params_json:
        return json.loads(args.params_json)
    return {}


def _cmd_check(args):
    cp = Checkpoint(_state_dir(args))
    can_skip, reason = cp.check(args.stage, args.input, _params(args), args.output)
    print(json.dumps({"stage": args.stage, "skip": can_skip, "reason": reason}, indent=2))
    return EXIT_SKIP if can_skip else EXIT_RUN


def _cmd_status(args):
    cp = Checkpoint(_state_dir(args))
    rows = []
    for name in cp.stages():
        rec = cp.load(name)
        rows.append({
            "stage": name,
            "saved_at": rec.get("saved_at") if rec else None,
            "outputs": [o["path"] for o in rec.get("outputs", [])] if rec else [],
            "valid_record": rec is not None,
        })
    print(json.dumps(rows, indent=2))
    return EXIT_SKIP


def _cmd_reset(args):
    cp = Checkpoint(_state_dir(args))
    removed = cp.reset(args.stage)
    print(json.dumps({"stage": args.stage, "removed": removed}, indent=2))
    return EXIT_SKIP


def build_parser():
    p = argparse.ArgumentParser(description="Stage checkpoints for the clip streamline.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--state-dir", help="folder for stage records (or STREAMLINE_STATE_DIR)")
        sp.add_argument("--stage", required=True)

    c = sub.add_parser("check", help="say whether a stage can be skipped; runs nothing")
    common(c)
    c.add_argument("--input", action="append", default=[], help="input file or folder (repeat)")
    c.add_argument("--output", action="append", default=[], help="output file or folder (repeat)")
    c.add_argument("--params-json", help="params as a JSON object")
    c.add_argument("--params-file", help="params as a JSON file")
    c.set_defaults(func=_cmd_check)

    s = sub.add_parser("status", help="list saved stages")
    s.add_argument("--state-dir")
    s.set_defaults(func=_cmd_status)

    r = sub.add_parser("reset", help="forget one stage so it runs again")
    common(r)
    r.set_defaults(func=_cmd_reset)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
