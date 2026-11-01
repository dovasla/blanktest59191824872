"""CS Junkie intake (29 Oct 2026). One call runs the four intake steps in order and stops at the first blocking fail.

Usage:
  python3 csj_intake.py <inputs.json> <candidates.json> <out_dir> [--length S] [--channel youtube]

Steps:
  1. resolve: if inputs["source"] is not on disk, find the source reel (csj_resolve.py). Uses the newest match.
     Asks Jord only when nothing matches.
  2. killers: csj_killer_check.py. Each kill must be the featured player (own kill rule).
  3. caption: if no caption_file is set, csj_caption_step.py picks one. Then csj_caption_check.py:
     literal NK token, player name, at most 2 hashtags.
  4. onsets: csj_onset_check.py on the candidates. Onset = first visible frame minus 3 frames (locked rule).
     The candidate count must match kill_count before any decode runs.

Writes <out_dir>/<clip_id>_onsets.json and updates the inputs file (source, caption_file).
Output is one JSON result on stdout. Exit 0 when every step passes, 1 when a step stops the intake.
Does not touch the row crop, the build, or csj_build.py / csj_run.py.
"""
import argparse
import contextlib
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import csj_caption_check  # noqa: E402
import csj_caption_step  # noqa: E402
import csj_killer_check  # noqa: E402
import csj_onset_check  # noqa: E402
import csj_resolve  # noqa: E402


def load(path):
    return json.loads(Path(path).read_text())


def step_resolve(inputs_path, length=None):
    inputs = load(inputs_path)
    src = inputs.get("source")
    if src and Path(src).is_file():
        return {"pass": True, "source": src, "note": "source already on disk"}
    found = csj_resolve.resolve(length=length or inputs.get("duration"), fps=float(inputs["fps"]))
    if not found:
        return {"pass": False, "flags": [f"no 1920x1080 {inputs['fps']} fps source found in the upload folders. Ask Jord for the reel."]}
    inputs["source"] = found[0]["path"]
    Path(inputs_path).write_text(json.dumps(inputs, indent=2))
    out = {"pass": True, "source": found[0]["path"], "matches": len(found)}
    if len(found) > 1:
        out["warnings"] = [f"{len(found)} matches, newest used. Check it is the right reel."]
    return out


def step_killers(inputs_path):
    res = csj_killer_check.check(load(inputs_path))
    return {"pass": res["pass"], "flags": res["flags"], "warnings": res["warnings"]}


def step_caption(inputs_path, out_dir, channel):
    inputs = load(inputs_path)
    picked_now = False
    if not inputs.get("caption_file"):
        with contextlib.redirect_stdout(io.StringIO()):
            csj_caption_step.main(str(inputs_path), str(out_dir), channel)
        inputs = load(inputs_path)
        picked_now = True
    cap = inputs.get("caption_file")
    if not cap or not Path(cap).is_file():
        return {"pass": False, "flags": ["caption file missing"]}
    res = csj_caption_check.check(cap, inputs)
    return {"pass": res["pass"], "flags": res["flags"], "caption": res["caption"], "picked_now": picked_now}


def step_onsets(inputs_path, candidates_path, out_dir):
    """Onset step (Jord, 29 Oct): the kill tracker is the onset source. One run per clip, cached by checksum."""
    import csj_kill_tracker
    inputs = load(inputs_path)
    try:
        tracked = csj_kill_tracker.onsets_for_clip(inputs["source"], str(out_dir), inputs.get("player_name", ""),
                                                   int(inputs["kill_count"]))
    except Exception as exc:  # the step reports, it does not crash the run
        return {"pass": False, "flags": [f"kill tracker failed: {exc}"]}
    out = Path(out_dir) / f"{inputs['clip_id']}_onsets.json"
    out.write_text(json.dumps(tracked, indent=2))
    return {"pass": tracked["pass"], "flags": tracked["flags"],
            "onsets": [k["seconds"] for k in tracked["kills"]], "file": str(out)}


def _old_step_onsets(inputs_path, candidates_path, out_dir):
    inputs = load(inputs_path)
    cands = load(candidates_path)
    n_cands = len(cands.get("kills", []))
    if n_cands != int(inputs["kill_count"]):
        return {"pass": False, "flags": [f"{n_cands} onset candidates, kill_count is {inputs['kill_count']}"]}
    if "window_end" not in inputs:
        return {"pass": False, "flags": ["window_end missing. Set window_start in csj_inputs.py first."]}
    res = csj_onset_check.check(inputs, cands)
    out = Path(out_dir) / f"{inputs['clip_id']}_onsets.json"
    out.write_text(json.dumps(res, indent=2))
    return {"pass": res["pass"], "flags": res["flags"],
            "onsets": [k.get("seconds") for k in res["kills"]], "file": str(out)}


def run_intake(inputs_path, candidates_path, out_dir, length=None, channel="youtube"):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plan = [
        ("resolve", lambda: step_resolve(inputs_path, length)),
        ("killers", lambda: step_killers(inputs_path)),
        ("caption", lambda: step_caption(inputs_path, out_dir, channel)),
        ("onsets", lambda: step_onsets(inputs_path, candidates_path, out_dir)),
    ]
    steps, stopped = {}, None
    for name, fn in plan:
        try:
            steps[name] = fn()
        except Exception as e:  # reported as a blocking fail, never hidden
            steps[name] = {"pass": False, "flags": [f"{type(e).__name__}: {e}"]}
        if not steps[name]["pass"]:
            stopped = name
            break
    return {"clip_id": load(inputs_path).get("clip_id"), "pass": stopped is None,
            "stopped_at": stopped, "steps": steps}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs")
    ap.add_argument("candidates")
    ap.add_argument("out_dir")
    ap.add_argument("--length", type=float)
    ap.add_argument("--channel", default="youtube")
    a = ap.parse_args()
    res = run_intake(a.inputs, a.candidates, a.out_dir, a.length, a.channel)
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["pass"] else 1)
