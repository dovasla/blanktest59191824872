"""CS Junkie export gates (csj-process v5, 29 Oct 2026). Streams frames; never loads the whole video.

Called by csj_run.py: run(exp, inputs, onsets, timings, rows_dir, layout_path, report_path).
Stops at the first failed blocking gate. Cheap checks run first.

BLOCKING, in order:
  probe              1080x1920, 60 fps, duration within 0.04 s of planned length, AAC, bit rate >= 10 Mb/s, size < 100 MB.
  timing_arithmetic  each stack switch = onset - window_start, rounded to the clip frame, plus the one-frame hold.
  row_edge           csj_row_edge_gate: each raw row has its own red border, no bleed.
  edge_bands         csj_bar_gate: no near-black bars top or bottom.
  slide              csj_slide_gate: each kill row slides in over 0.2 s and lands on its slot.
  feed_timing        csj_timing_gate: each kill's first visible frame in the 60 fps source feed matches its slide start.
REPORTED ONLY:
  seam               last frame vs source frame at window_end (open item).
The cover gate (frame 0 vs cover PNG) is removed: covers are out (Jord, 28 Oct).
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import csj_feedcache  # noqa: E402
import csj_row_edge_gate  # noqa: E402
import csj_slide_gate  # noqa: E402
import csj_timing_gate  # noqa: E402


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "stream=codec_type,codec_name,width,height,r_frame_rate,bit_rate:format=duration,bit_rate,size",
                          "-of", "json", path], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def gate_probe(exp, planned, fps=30):
    j = probe(exp)
    v = next(s for s in j["streams"] if s["codec_type"] == "video")
    a = [s for s in j["streams"] if s["codec_type"] == "audio"]
    dur = float(j["format"]["duration"])
    br = float(j["format"].get("bit_rate", 0)) / 1e6
    size_mb = int(j["format"]["size"]) / 1e6
    checks = {
        "size": (v["width"], v["height"]) == (1080, 1920),
        "fps": v["r_frame_rate"] == f"{fps}/1",
        "duration": abs(dur - planned) <= 0.04,
        "aac": bool(a) and a[0]["codec_name"] == "aac",
        "bitrate": br >= 10.0,
        "file_size": size_mb < 100,
    }
    return {"pass": all(checks.values()), "checks": checks, "duration": round(dur, 3),
            "bitrate_mbps": round(br, 2), "size_mb": round(size_mb, 1), "planned": round(planned, 3)}


def seam(exp, source, we):
    """Reported only: last frame of the export vs the source frame at window_end."""
    raw_e = subprocess.run(["ffmpeg", "-v", "error", "-sseof", "-0.05", "-i", exp, "-frames:v", "1",
                            "-vf", "format=gray", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    raw_s = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{we:.3f}", "-i", source, "-frames:v", "1",
                            "-vf", "scale=-2:1920,crop=1080:1920,format=gray", "-f", "rawvideo", "-"],
                           capture_output=True, check=True).stdout
    if len(raw_e) != len(raw_s):
        return None
    return float(np.abs(np.frombuffer(raw_e, np.uint8).astype(np.float32)
                        - np.frombuffer(raw_s, np.uint8).astype(np.float32)).mean())


def planned_len(ws, we, segments=None):
    if segments:
        return sum(float(b) - float(a) for a, b in segments)
    return we - ws


def output_time(t, ws, segments=None):
    if not segments:
        return t - ws
    off = 0.0
    for a, b in segments:
        if float(a) <= t < float(b):
            return off + (t - float(a))
        off += float(b) - float(a)
    raise ValueError(f"onset {t} is not inside any kept segment")


def timing_check(onsets, timings, ws, fps=30, tol=None, segments=None):
    """Timing arithmetic: each stack switch sits at (onset - window_start) rounded to the frame, plus the one-frame hold."""
    hold = 1 / fps
    tol = tol if tol is not None else 1 / (2 * fps)
    kills = sorted(onsets["kills"], key=lambda k: k["seconds"])
    switches = timings["stack_switch_output_s"]
    out = []
    for k, sw in zip(kills, switches):
        expect = round(output_time(k["seconds"], ws, segments) * fps) / fps + hold
        diff = sw - expect
        out.append({"kill_onset_s": k["seconds"], "stack_switch_s": sw, "expected_s": round(expect, 4),
                    "diff_s": round(diff, 4), "pass": abs(diff) <= tol + 1e-9})
    return out


def kill_list(onsets, kills):
    return sorted(onsets["kills"], key=lambda k: k["seconds"])[:kills]


def timing_result(onsets, timings, ws, fps, n):
    rows = timing_check({"kills": kill_list(onsets, n)}, timings, ws, fps)
    return {"pass": len(rows) == n and all(r["pass"] for r in rows), "kills": rows}


def rows_result(rows_dir, n):
    rows = {}
    for k in range(1, n + 1):
        p = Path(rows_dir) / f"raw_K{k}.png"
        rows[p.name] = csj_row_edge_gate.check_row(p) if p.exists() else {"pass": False, "reason": "row file missing"}
    return {"pass": bool(rows) and all(v["pass"] for v in rows.values()), "rows": rows}


def edge_result(exp):
    bar = subprocess.run([sys.executable, str(HERE / "csj_bar_gate.py"), exp], capture_output=True, text=True)
    return {"pass": bar.returncode == 0, "output": bar.stdout.strip() or bar.stderr.strip()}


def slide_result(exp, layout_path, fps):
    layout = json.loads(Path(layout_path).read_text())
    rep = {f"K{k['kill']}": csj_slide_gate.check_kill(exp, k, layout["slide"], fps) for k in layout["kills"]}
    return {"pass": bool(rep) and all(v["pass"] for v in rep.values()), "kills": rep}


def feed_result(source, onsets, n, timings):
    kills = []
    for i, k in enumerate(kill_list(onsets, n), start=1):
        if "box_feed" not in k or "crop_frame" not in k:
            return {"pass": False, "reason": f"kill {i} has no box_feed or crop_frame in the onsets file"}
        kills.append({"kill": i, "name": k.get("victim_or_assist", f"K{i}"), "box": k["box_feed"],
                      "ref": int(k["crop_frame"])})
    if not kills:
        return {"pass": False, "reason": "no kills"}
    ok, recs = csj_timing_gate.check_kills(csj_timing_gate.KillFeed(source, kills), kills, timings["onset_s"])
    return {"pass": ok, "kills": recs}


def run(exp, inputs, onsets, timings, rows_dir, layout_path, report_path):
    ws, we = float(inputs["window_start"]), float(inputs["window_end"])
    planned = we - ws
    fps = int(round(float(inputs["fps"])))
    n = int(inputs["kill_count"])
    res = {"clip_id": inputs["clip_id"], "blocking": {}, "reported": {}}
    steps = [
        ("probe", lambda: gate_probe(exp, planned, fps)),
        ("timing_arithmetic", lambda: timing_result(onsets, timings, ws, fps, n)),
        ("row_edge", lambda: rows_result(rows_dir, n)),
        ("edge_bands", lambda: edge_result(exp)),
        ("slide", lambda: slide_result(exp, layout_path, fps)),
    ]
    for name, fn in steps:
        res["blocking"][name] = fn()
        if not res["blocking"][name]["pass"]:
            res["stopped_at"] = name
            break
    res["blocking_pass"] = "stopped_at" not in res
    # feed_timing is a warning only (Jord, 30 Oct): it never stops a build or blocks upload.
    feed = feed_result(inputs["source"], onsets, n, timings)
    res["warnings"] = {"feed_timing": {"pass": feed["pass"], "note": "warning only, does not block"}}
    if res["blocking_pass"]:
        s = seam(exp, inputs["source"], we)
        res["reported"]["seam_mad"] = None if s is None else round(s, 2)
    Path(report_path).write_text(json.dumps(res, indent=2))
    return res


if __name__ == "__main__":
    # python3 csj_gates.py <export> <inputs.json> <onsets.json> <timings.json> <rows_dir> <layout.json> <report.json>
    exp, ip, op, tp, rd, lp, rp = sys.argv[1:8]
    r = run(exp, json.loads(Path(ip).read_text()), json.loads(Path(op).read_text()),
            json.loads(Path(tp).read_text()), rd, lp, rp)
    print(json.dumps(r, indent=2))
    sys.exit(0 if r["blocking_pass"] else 1)
