#!/usr/bin/env python3
"""CS Junkie clip checker (csj-process v4, Steps 0 to 12).

Walks one clip folder through every step in research/csj-process.md and reports PASS, FAIL,
MISSING or MANUAL for each. Exit 0 only when every step is PASS. Nothing is posted or scheduled here.

Usage:
  python3 tools/csj_checker.py <clip_folder> [--clip-id ID] [--export FILE] [--timings FILE]
                               [--rows DIR] [--json OUT]

File names follow <clip_id>_<kind>. Flags override a name. Relative flag paths are read from the folder.

Gates are reused, not copied: csj_gates (probe, frame 0, timing arithmetic), csj_bar_gate (edge bands)
and csj_row_edge_gate (raw rows). No threshold here is looser than the gate tools.

Status:
  PASS     automated check passed, or a manual step has Jord's sign-off in <clip_id>_signoff.json
  FAIL     an automated check ran and failed
  MISSING  a file the step needs is not there
  MANUAL   a person must look and sign off (keys in <clip_id>_signoff.json). Not automated.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from PIL import Image  # noqa: E402

import csj_gates  # noqa: E402
import csj_row_edge_gate  # noqa: E402

REQUIRED_INPUT_KEYS = ["clip_id", "source", "fps", "width", "height", "duration", "kill_count",
                       "player_name", "player_colour", "window_start", "window_end"]
MAX_UPLOAD_MB = 100
# Jord's caption note (memory, 21 Oct): one line, at most two hashtags. Process Step 9 allows
# #cs2 #csgo plus 2 to 3 more. Confirm with Jord; change this constant to match his answer.
CAPTION_MAX_HASHTAGS = 2
CHANNELS_REQUIRED = ("youtube", "instagram", "tiktok")


class Step:
    def __init__(self, num, title):
        self.num, self.title = num, title
        self.fails, self.missing, self.notes, self.manual = [], [], [], []
        self.status = None

    def finish(self, signoff):
        pending = [k for k in self.manual if not signoff.get(k)]
        if self.fails:
            self.status = "FAIL"
        elif self.missing:
            self.status = "MISSING"
        elif pending:
            self.status = "MANUAL"
            self.notes.append("awaiting sign-off: " + ", ".join(pending))
        else:
            self.status = "PASS"
        return self

    def to_dict(self):
        return {"step": self.num, "title": self.title, "status": self.status, "fails": self.fails,
                "missing": self.missing, "notes": self.notes}


def fraction(text):
    if not text or text in ("0/0", "0"):
        return 0.0
    if "/" in text:
        n, d = text.split("/")
        return float(n) / float(d)
    return float(text)


def probe_source(path):
    j = csj_gates.probe(str(path))
    v = next(s for s in j["streams"] if s["codec_type"] == "video")
    return {"width": v["width"], "height": v["height"], "fps": fraction(v["r_frame_rate"]),
            "duration": float(j["format"]["duration"])}


def read_json(S, step, key, label):
    """Load a JSON file from the clip folder. Records MISSING or FAIL on the step and returns None."""
    path = S["P"][key]
    if not path.exists():
        step.missing.append(f"{path.name} ({label})")
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as e:
        step.fails.append(f"{path.name} does not parse: {e}")
        return None


def need(step, path, label):
    if not path.exists():
        step.missing.append(f"{path.name} ({label})")
        return False
    return True


def head_status(url):
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, None
    except Exception as e:  # network or HTTP error: report, never retry
        return None, str(e)


# ---- steps -----------------------------------------------------------------------------------

def step0_preflight(S):
    s = Step(0, "Preflight: tools and font (automated part)")
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            s.fails.append(f"{tool} not on PATH")
    has_barlow = False
    if not has_barlow:
        try:
            fc = subprocess.run(["fc-list"], capture_output=True, text=True).stdout.lower()
            has_barlow = "barlow condensed" in fc
        except FileNotFoundError:
            pass
    if not has_barlow:
        s.fails.append("Barlow Condensed Black not installed (Step 0.1: install it, or build from "
                       "@fontsource/barlow-condensed 5.3.0)")
    s.notes.append("not automated (Step 0.3 to 0.7): edit path test, Cloudinary secret length, "
                   "Buffer and Metricool reads, session not linked to a computer")
    return s.finish(S["signoff"])


def step1_inputs(S):
    s = Step(1, "Inputs and kill count")
    inp = read_json(S, s, "inputs", "inputs JSON")
    if inp is None:
        return s.finish(S["signoff"])
    S["inp"] = inp
    for k in REQUIRED_INPUT_KEYS:
        if k not in inp:
            s.fails.append(f"inputs missing key '{k}'")
    if s.fails:
        return s.finish(S["signoff"])
    if inp["player_colour"] not in ("yellow", "blue"):
        s.fails.append(f"player_colour '{inp['player_colour']}' is not yellow or blue")
    if float(inp["window_end"]) <= float(inp["window_start"]):
        s.fails.append("window_end is not after window_start")
    src = Path(inp["source"])
    if not src.exists():
        s.missing.append(f"source reel not on disk: {src}")
    else:
        info = probe_source(src)
        if (info["width"], info["height"]) != (1920, 1080):
            s.fails.append(f"source is {info['width']}x{info['height']}, must be 1920x1080")
        if abs(info["fps"] - float(inp["fps"])) > 0.01:
            s.fails.append(f"inputs fps {inp['fps']} does not match source {info['fps']:.3f}")
        if float(inp["window_end"]) > info["duration"] + 0.01:
            s.fails.append("window_end is past the source end")
        s.notes.append(f"source {info['width']}x{info['height']} {info['fps']:.3f} fps {info['duration']:.2f} s")
    k = int(inp["kill_count"])
    s.notes.append(f"kill count {k}, player {inp['player_name']} ({inp['player_colour']})")
    if k != 5:
        s.manual.append("kill_count_approved")
        s.notes.append(f"kill count {k} is not 5: Jord's go is needed before a build (Step 1)")
    return s.finish(S["signoff"])


def step2_onsets(S):
    s = Step(2, "Kill onsets and approval contact sheet")
    on = read_json(S, s, "onsets", "onsets JSON from csj_onset_check")
    inp = S.get("inp")
    if on is not None:
        if on.get("pass") is not True:
            s.fails.append("onset check did not pass: " + "; ".join(on.get("flags", ["no flags recorded"])))
        kills = on.get("kills", [])
        expect = int(inp["kill_count"]) if inp else len(kills)
        if len(kills) != expect:
            s.fails.append(f"{len(kills)} onsets, kill count is {expect}")
        bad = [k.get("kill") for k in kills if k.get("status") != "pass" or k.get("seconds") is None]
        if bad:
            s.fails.append(f"kills without a clean onset: {bad}")
        if inp and kills and not bad:
            secs = sorted(k["seconds"] for k in kills)
            ws_want = secs[0] - 2.0
            we_want = min(secs[-1] + 4.0, float(inp["duration"]))
            if abs(float(inp["window_start"]) - ws_want) > 0.04:
                s.fails.append(f"window_start {inp['window_start']} is not first onset - 2.0 ({ws_want:.3f})")
            if abs(float(inp["window_end"]) - we_want) > 0.04:
                s.fails.append(f"window_end {inp['window_end']} is not last onset + 4.0 or the source end ({we_want:.3f})")
        s.notes.append("name check: not run in the script; the contact sheet is the name check (Step 4a)")
    need(s, S["P"]["contact"], "approval contact sheet, Step 4a")
    s.manual.append("kill_list_approved")
    return s.finish(S["signoff"])


def step4_rows(S):
    s = Step(4, "Raw rows and row-edge gate")
    rows = S["P"]["rows"]
    inp = S.get("inp")
    if not rows.is_dir():
        s.missing.append(f"rows folder ({rows.name})")
        return s.finish(S["signoff"])
    if not inp:
        s.missing.append("kill count (needs the inputs JSON)")
        return s.finish(S["signoff"])
    n = int(inp["kill_count"])
    for k in range(1, n + 1):
        p = rows / f"raw_K{k}.png"
        if not need(s, p, f"raw row {k}"):
            continue
        res = csj_row_edge_gate.check_row(p)
        if not res["pass"]:
            s.fails.append(f"{p.name}: " + "; ".join(res.get("flags") or [res.get("reason", "failed")]))
    return s.finish(S["signoff"])


def step5_build(S):
    s = Step(5, "Build and timings consistency")
    ok_export = need(s, S["P"]["export"], "build MP4")
    t = read_json(S, s, "timings", "build timings JSON")
    inp = S.get("inp")
    if t is not None:
        n = len(t.get("stack_switch_output_s", []))
        if inp and n != int(inp["kill_count"]):
            s.fails.append(f"{n} stack switches, kill count is {inp['kill_count']}")
        if inp and int(t.get("fps", 0)) != int(round(float(inp["fps"]))):
            s.fails.append(f"timings fps {t.get('fps')} does not match inputs {inp['fps']}")
        if t.get("hold_frames") != 1:
            s.fails.append(f"hold_frames is {t.get('hold_frames')}, spec is 1")
        on = S.get("onsets")
        if on and on.get("kills"):
            want = sorted(k["seconds"] for k in on["kills"])
            got = t.get("onset_s", [])
            if len(want) != len(got) or any(abs(a - b) > 1e-3 for a, b in zip(want, got)):
                s.fails.append("timings onset_s does not match the onsets file")
        s.notes.append(f"stack switches (s): {t.get('stack_switch_output_s')}")
    return s.finish(S["signoff"])


def step6_look(S):
    s = Step(6, "Look-check (manual)")
    s.manual += ["look_check_ok"]
    s.notes.append("frames before and after each stack change, 20 s contact sheet, row count, full red borders, "
                   "names legible")
    return s.finish(S["signoff"])


def step7_gates(S):
    s = Step(7, "Export gates (blocking)")
    if not need(s, S["P"]["export"], "build MP4"):
        return s.finish(S["signoff"])
    export = S["P"]["export"]
    t = S.get("t")
    inp = S.get("inp")
    if inp:
        ws, we, fps = float(inp["window_start"]), float(inp["window_end"]), int(round(float(inp["fps"])))
    elif t:
        ws, we, fps = float(t["window_start"]), float(t["window_end"]), int(t["fps"])
        s.notes.append("inputs JSON missing: window and fps read from the timings file")
    else:
        s.missing.append("window and fps (needs the inputs or timings JSON)")
        return s.finish(S["signoff"])
    segments = (inp or {}).get("segments")
    planned = csj_gates.planned_len(ws, we, segments)

    probe = csj_gates.gate_probe(str(export), planned, fps)
    if not probe["pass"]:
        bad = [k for k, v in probe["checks"].items() if not v]
        s.fails.append(f"gate 1 probe fails: {bad} (duration {probe['duration']}, planned {probe['planned']})")
    s.notes.append(f"gate 1: {probe['size_mb']} MB, {probe['bitrate_mbps']} Mb/s, {probe['duration']} s")

    bar = subprocess.run([sys.executable, str(HERE / "csj_bar_gate.py"), str(export)],
                         capture_output=True, text=True)
    if bar.returncode != 0:
        s.fails.append(f"gate 4 edge bands: {bar.stdout.strip() or bar.stderr.strip()}")
    s.notes.append(f"gate 4: {bar.stdout.strip() or 'no output'}")

    on = S.get("onsets")
    if t is None:
        s.missing.append("timings JSON (gate 3 needs it)")
    elif on is None:
        s.missing.append("onsets JSON (gate 3 needs it)")
    elif not on.get("kills"):
        s.fails.append("gate 3 timing: onsets file has no kills, so the switches cannot be checked")
    else:
        rows = csj_gates.timing_check(on, t, ws, fps, segments=segments)
        bad = [r for r in rows if not r["pass"]]
        if bad:
            s.fails.append(f"gate 3 timing: {len(bad)} switch(es) off the onset arithmetic: {bad}")
        s.notes.append(f"gate 3 timing: {len(rows) - len(bad)}/{len(rows)} switches exact")

    if inp and Path(inp["source"]).exists():
        sm = csj_gates.seam(str(export), inp["source"], we)
        s.notes.append("gate 2b seam (reported only, open item): " + ("not comparable" if sm is None else f"{sm:.2f}"))
    return s.finish(S["signoff"])


def step8_upload(S):
    s = Step(8, "Upload (Cloudinary, HEAD check)")
    st7 = S["results"][7].status
    if st7 == "FAIL":
        s.fails.append("upload recorded while gates FAIL (Step 6: no upload until gates pass)")
    if need(s, S["P"]["upload"], "upload record with mp4_url"):
        rec = read_json(S, s, "upload", "upload record")
        if rec:
            for key in ("mp4_url",):
                url = rec.get(key)
                if not url:
                    s.fails.append(f"upload record has no {key}")
                    continue
                code, err = head_status(url)
                if code != 200:
                    s.fails.append(f"{key} HEAD returned {code or 'error'} {err or ''}".strip())
                else:
                    s.notes.append(f"{key} HEAD 200")
            if S["P"]["export"].exists() and S["P"]["export"].stat().st_size > MAX_UPLOAD_MB * 1e6:
                s.fails.append(f"export is over {MAX_UPLOAD_MB} MB")
    return s.finish(S["signoff"])


def step9_caption(S):
    s = Step(9, "Caption and hashtags")
    if read_json_text(S, s):
        text = S["caption_text"]
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if len(lines) != 1:
            s.fails.append(f"caption has {len(lines)} lines, must be one")
        tags = re.findall(r"#\w+", text)
        if len(tags) > CAPTION_MAX_HASHTAGS:
            s.fails.append(f"caption has {len(tags)} hashtags, limit is {CAPTION_MAX_HASHTAGS}")
        inp = S.get("inp")
        if inp:
            if not re.search(rf"\b{int(inp['kill_count'])}K\b", text, re.I):
                s.fails.append(f"caption does not show the {inp['kill_count']}K count")
            if inp["player_name"].lower() not in text.lower():
                s.fails.append(f"caption does not name {inp['player_name']}")
        s.notes.append(f"caption: {text.strip()}")
    s.manual += ["caption_approved", "caption_name_checked"]
    s.notes.append("caption name must match the killer on each row (Step 9); checked by eye")
    return s.finish(S["signoff"])


def read_json_text(S, s):
    path = S["P"]["caption"]
    if not need(s, path, "caption text"):
        return False
    S["caption_text"] = path.read_text()
    return True


def step10_approval(S):
    s = Step(10, "Approval in the project thread (Jord)")
    sg = S["signoff"]
    if sg.get("clip_approved") and S["results"][7].status != "PASS":
        s.fails.append("clip recorded as approved while the export gates are not PASS")
    if sg.get("approval_message_id") and sg.get("approval_by") != "Jord":
        s.fails.append(f"approval_by is '{sg.get('approval_by')}', must be Jord")
    s.manual += ["clip_approved", "caption_approved", "approval_message_id"]
    s.notes.append("approval is one reply from Jord to clip and caption together; record his message id")
    return s.finish(sg)


def step11_schedule(S):
    s = Step(11, "Scheduling (only after approval)")
    if S["results"][10].status != "PASS" and S["P"]["schedule"].exists():
        s.fails.append("schedule record exists before approval PASS (Step 10)")
    if need(s, S["P"]["schedule"], "schedule record"):
        rec = read_json(S, s, "schedule", "schedule record")
        if rec:
            posts = {p.get("channel"): p for p in rec.get("posts", [])}
            for ch in CHANNELS_REQUIRED:
                st = posts.get(ch, {}).get("status")
                if st not in ("scheduled", "sent"):
                    s.fails.append(f"{ch}: status '{st}' (need scheduled or sent)")
                else:
                    s.notes.append(f"{ch}: {st} for {posts[ch].get('due_at_london', '?')} London")
            fb = posts.get("facebook", {}).get("status")
            s.notes.append(f"facebook: {fb or 'not listed'} (manual batch by Jord, Step 10)")
    return s.finish(S["signoff"])


def step12_delivery(S):
    s = Step(12, "Delivery and project memory (manual)")
    s.manual += ["delivery_message_sent", "memory_saved"]
    return s.finish(S["signoff"])


# ---- run -------------------------------------------------------------------------------------

def load_optional(path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check one CS Junkie clip folder against csj-process v4.")
    ap.add_argument("folder")
    ap.add_argument("--clip-id")
    ap.add_argument("--export")
    ap.add_argument("--timings")
    ap.add_argument("--rows")
    ap.add_argument("--json", help="write the full result here")
    a = ap.parse_args(argv)

    folder = Path(a.folder).resolve()
    clip = a.clip_id or folder.name

    def pick(override, default_name):
        if override:
            p = Path(override)
            return p if p.is_absolute() else folder / p
        return folder / default_name

    rows = pick(a.rows, "") if a.rows else next((folder / d for d in ("rows", "raw_rows") if (folder / d).is_dir()),
                                                  folder / "rows")
    P = {
        "inputs": folder / f"{clip}_inputs.json",
        "onsets": folder / f"{clip}_onsets.json",
        "contact": folder / f"{clip}_contact_sheet.png",
        "rows": rows,
        "export": pick(a.export, f"{clip}_build.mp4"),
        "timings": pick(a.timings, f"{clip}_timings.json"),
        "signoff": folder / f"{clip}_signoff.json",
        "caption": folder / f"{clip}_caption.txt",
        "upload": folder / f"{clip}_upload.json",
        "schedule": folder / f"{clip}_schedule.json",
    }
    S = {"P": P, "signoff": load_optional(P["signoff"]) or {}, "results": {}}
    S["inp"] = load_optional(P["inputs"])
    S["onsets"] = load_optional(P["onsets"])
    S["t"] = load_optional(P["timings"])

    order = [step0_preflight, step1_inputs, step2_onsets, step4_rows, step5_build,
             step6_look, step7_gates, step8_upload, step9_caption, step10_approval, step11_schedule,
             step12_delivery]
    results = []
    for fn in order:
        st = fn(S)
        S["results"][st.num] = st
        results.append(st)

    print(f"clip {clip}  folder {folder}")
    for st in results:
        print(f"{st.num:>2}  {st.status:<8} {st.title}")
        for f in st.fails:
            print(f"        FAIL     {f}")
        for m in st.missing:
            print(f"        MISSING  {m}")
        for n in st.notes:
            print(f"        note     {n}")
    passed = sum(1 for st in results if st.status == "PASS")
    done = passed == len(results)
    print(f"\nRESULT: {passed}/{len(results)} steps PASS. "
          f"{'Clip complete.' if done else 'Clip NOT complete. Exit 1.'}")

    if a.json:
        Path(a.json).write_text(json.dumps({"clip_id": clip, "pass": done,
                                            "steps": [st.to_dict() for st in results]}, indent=2))
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
