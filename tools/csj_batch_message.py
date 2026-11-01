"""CS Junkie batch approval message (item 5, 29 Oct 2026). Built from the per-clip run files.

Usage:
  python3 csj_batch_message.py <out.md> <clip>_run.json [more run.json ...]

Reads only the per-clip run output (written by csj_run.py) and the files it points to.
Up to 10 clips per message (master skill section 12). One line per field per clip.
Nothing is posted here. Jord approves each clip with its own "post it <clip>" reply.
A missing piece shows as MISSING. A clip that stopped at a blocking check shows NOT READY, with no post line.
"""
import json
import sys
from pathlib import Path

MAX_CLIPS = 10


def read_json(path):
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def pick_title(run, run_path, clip):
    """Title is the top text (3 words). csj_run.py does not write it yet, so fall back to the inputs file."""
    for val in (run.get("title"), run.get("top_title"), (run.get("intake") or {}).get("title")):
        if val:
            return str(val)
    inputs = read_json(run_path.parent / f"{clip}_inputs.json")
    if inputs and inputs.get("top_title"):
        return str(inputs["top_title"])
    return None


def pick_caption(run, run_path, clip):
    """Caption pick from the run record, else the caption file the run wrote next to it."""
    if run.get("caption_pick") and run["caption_pick"].get("text"):
        return run["caption_pick"]["text"]
    cap_file = run_path.parent / f"{clip}_caption.txt"
    if cap_file.exists():
        return cap_file.read_text(encoding="utf-8").strip()
    return None


def gate_summary(run):
    gates = read_json(run.get("gates"))
    if not gates:
        return "MISSING (no gates file)"
    blocking = gates.get("blocking", {})
    passed = [n for n, r in blocking.items() if r.get("pass")]
    if gates.get("blocking_pass"):
        return f"all {len(blocking)} blocking gates pass"
    failed = [n for n in blocking if n not in passed]
    return f"FAIL at {gates.get('stopped_at') or ', '.join(failed) or '?'}"


def clip_block(run, run_path):
    clip = run.get("clip_id", "?")
    stopped = run.get("stopped_at")
    upload = run.get("upload") or {}
    timings = read_json(run.get("timings"))
    onsets = read_json(run.get("onsets"))
    title = pick_title(run, run_path, clip)
    caption = pick_caption(run, run_path, clip)

    if upload.get("url_ok"):
        link = upload["url"]
    elif upload:
        link = f"NOT UPLOADED ({upload.get('reason', 'upload failed')})"
    else:
        link = "NOT UPLOADED (no upload step ran)"

    if timings:
        kills = timings.get("kill_count")
        kill_times = timings.get("onset_s")
    elif onsets:
        kill_times = [k.get("seconds") for k in onsets.get("kills", [])]
        kills = len(kill_times)
    else:
        kills, kill_times = "MISSING", "MISSING"

    flags = list(run.get("labels", []))
    if stopped:
        flags.append(f"STOPPED at {stopped}")
    flags += [str(f) for f in run.get("flags", []) or []]

    lines = [
        f"## Clip {clip}",
        f"- Title: {title or 'MISSING'}",
        f"- Caption: {caption or 'MISSING'}",
        f"- Link: {link}",
        f"- Kills: {kills}",
        f"- Kill times (s): {kill_times}",
        f"- Gates: {gate_summary(run)}",
        f"- Flags: {'; '.join(flags) if flags else 'none'}",
    ]
    if stopped or not upload.get("url_ok"):
        lines.append("- Status: NOT READY, do not post")
    else:
        lines.append(f"- To post, reply: post it {clip}")
    return "\n".join(lines) + "\n"


def main(out_path, run_paths):
    if len(run_paths) > MAX_CLIPS:
        raise SystemExit(f"at most {MAX_CLIPS} clips per message, got {len(run_paths)}")
    text = ["# Batch approval", ""]
    for rp in run_paths:
        path = Path(rp)
        text.append(clip_block(json.loads(path.read_text(encoding="utf-8")), path))
    text.append("Anything not named in a 'post it' reply is not posted.")
    Path(out_path).write_text("\n".join(text) + "\n", encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2:])
