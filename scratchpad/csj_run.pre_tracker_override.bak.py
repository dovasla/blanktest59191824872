"""CS Junkie one-clip run, unattended. One clip at a time. No prompts, no re-export loops.

Usage:
  python3 csj_run.py <inputs.json> <candidates.json> <rows_dir> <out_dir> [--dry-run]

--dry-run (Jord, 29 Oct): runs every check and the build, but never uploads, posts or schedules. No run log line.

Order (csj-process v5, 29 Oct 2026). A failed blocking check stops the run before the approval package.
  1. Preflight, once per session (csj_preflight.py). Blocking.
  2. Player registry (csj_player_cache.py): colour must match the registry entry. Blocking if registered.
  3. Source dark check (csj_source_dark.py). Warning: adds a NOT FINAL label.
  4. Onset check (csj_onset_check.py), strict full-border rule. Blocking.
  5. Caption check (csj_caption_check.py). Needs "caption_file" in the inputs. Blocking.
  6. Build (csj_build.py). No cover step (covers out, Jord 28 Oct).
  7. Gates (csj_gates.py): probe, timing arithmetic, row edge, edge bands, slide, feed timing. Blocking.
  8. Upload (csj_asset_upload.upload_clip): final MP4 to Cloudinary and a 200 check. Runs only after gates pass.
  Intake (csj_resolve, input fields, source size and fps) runs first, before preflight.
Writes into <out_dir>: <clip>_onsets.json, <clip>_build.mp4, <clip>_timings.json, <clip>_layout.json,
<clip>_gates.json, <clip>_run.json (the approval package).
Exit 0 only when every blocking check passes. Nothing is re-exported automatically.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import csj_build  # noqa: E402
import csj_caption_check  # noqa: E402
import csj_colour_check  # noqa: E402
import csj_killer_check  # noqa: E402
import csj_rowcrop  # noqa: E402
from PIL import Image  # noqa: E402
import csj_gates  # noqa: E402
import csj_onset_check  # noqa: E402
import csj_player_cache  # noqa: E402
import csj_preflight  # noqa: E402
import csj_source_dark  # noqa: E402


def main(inputs_path, candidates_path, rows_dir, out_dir, dry_run=False):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    inputs = json.loads(Path(inputs_path).read_text())
    candidates = json.loads(Path(candidates_path).read_text())
    clip = inputs["clip_id"]
    run = {"clip_id": clip, "title": inputs.get("top_title"), "labels": [], "stopped_at": None,
           "blocking_pass": False, "upload_allowed": False, "dry_run": dry_run}
    if dry_run:
        run["labels"].append("DRY RUN: nothing uploaded, posted or scheduled")

    def finish(code):
        (out / f"{clip}_run.json").write_text(json.dumps(run, indent=2))
        # run log: one line per real run, kept in project files. Dry runs do not write to it.
        if not dry_run:
            from datetime import datetime, timezone
            log_line = {"when": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "clip_id": clip,
                        "stopped_at": run.get("stopped_at"), "blocking_pass": run.get("blocking_pass"),
                        "labels": run.get("labels", [])}
            with open("/mnt/project-files/research/run_log.jsonl", "a") as f:
                f.write(json.dumps(log_line) + "\n")
        # Batch message (Jord, 29 Oct): built from this run file at the end. Nothing is posted.
        import csj_batch_message
        csj_batch_message.main(str(out / f"{clip}_batch_message.md"), [str(out / f"{clip}_run.json")])
        print(json.dumps(run, indent=2))
        return code

    def stop(step):
        run["stopped_at"] = step
        return finish(1)

    # Item 3 (29 Oct): intake runs here. csj_intake.run_intake does resolve, killer names, caption and onsets
    # in order and stops at the first blocking fail. Then the field and source size and fps checks.
    import csj_intake
    import csj_kill_timing
    # Kill timing (Jord, 29 Oct): csj_kill_timing runs the name scan twice and compares. Its candidates feed the
    # onset step. ESTIMATED kills are labelled, never sent to Jord. A count that differs from kill_count stops here.
    kt_dir = out / f"{clip}_kill_timing"
    kt_rc = csj_kill_timing.main(inputs_path, str(kt_dir))
    kt = json.loads((kt_dir / "summary.json").read_text())
    run["kill_timing"] = {"pass": kt["pass"], "same_result_twice": kt["same_result_twice"],
                          "confirmed": kt["confirmed"], "flagged": kt["flagged"]}
    if not kt["pass"]:
        return stop("kill timing")  # a count that differs from kill_count stops the run here (docstring rule)
    scan = json.loads((kt_dir / "run1" / "onsets.json").read_text())
    scan_cands = out / f"{clip}_scan_candidates.json"
    scan_cands.write_text(json.dumps({"clip_id": clip, "kills": [
        {"kill": k["kill"], "seconds": k["candidate_s"], "status": k["status"]} for k in scan["kills"]]}, indent=2))
    run["intake_steps"] = csj_intake.run_intake(inputs_path, str(scan_cands), out, length=inputs.get("duration"))
    if not run["intake_steps"]["pass"]:
        run["intake"] = {"pass": False, "flags": run["intake_steps"]["steps"].get(run["intake_steps"]["stopped_at"], {}).get("flags", [])}
        return stop("intake")
    inputs = json.loads(Path(inputs_path).read_text())  # resolve and caption steps wrote the inputs file
    run["intake"] = intake(inputs)
    if not run["intake"]["pass"]:
        return stop("intake")
    inputs["source"] = run["intake"]["source"]

    run["preflight"] = csj_preflight.run()
    if not run["preflight"]["pass"]:
        return stop("preflight")

    run["player_registry"] = csj_player_cache.check(inputs)
    if not run["player_registry"]["pass"]:
        return stop("player_registry")

    run["source_dark"] = csj_source_dark.check(inputs)
    if run["source_dark"]["found"]:
        run["labels"].append(f"NOT FINAL: source near-black at {run['source_dark']['spans']} (passes, labelled)")

    # Onset source (Jord, 29 Oct): the kill tracker, one run per clip, cached by source checksum.
    # The old check stays as a fallback only when the tracker is not available.
    import csj_kill_tracker
    timings_path = out / f"{clip}_kill_timings.json"
    tracked = csj_kill_tracker.onsets_for_clip(inputs["source"], str(out), inputs.get("player_name", ""),
                                               int(inputs["kill_count"]))
    run["kill_timings"] = str(out / f"{Path(inputs['source']).stem}_kill_timings.json")
    onsets = tracked
    onsets_path = out / f"{clip}_onsets.json"
    onsets_path.write_text(json.dumps(onsets, indent=2))
    run["onsets"] = str(onsets_path)
    run["onset_pass"] = onsets["pass"]
    if not onsets["pass"]:
        run["flags"] = onsets["flags"]
        return stop("onset check")

    # Stacked-row check (29 Oct): csj_stack_detect counts the rows on the feed. It only warns, it never blocks.
    import csj_stack_detect
    stack_dir = out / f"{clip}_stack_detect"
    csj_stack_detect.main(inputs["source"], str(stack_dir), float(inputs.get("window_start", 3.0)),
                          float(inputs.get("window_end", 20.0)))
    stack_kills = len(json.loads((stack_dir / "stack_detect.json").read_text())["kills"])
    run["stack_check"] = {"stack_detect_kills": stack_kills, "tracker_kills": len(onsets["kills"]),
                          "agree": stack_kills == len(onsets["kills"])}
    if not run["stack_check"]["agree"]:
        run["labels"].append(f"WARN: stack detector saw {stack_kills} kills, kill tracker saw "
                             f"{len(onsets['kills'])}. Check the feed by eye before any link.")

    if not inputs.get("caption_file"):
        # no caption in the inputs: pick one from the pool (shown for approval in the batch message)
        import csj_caption_step
        pick = csj_caption_step.pick(inputs["player_name"], int(inputs["kill_count"]))
        if f"{inputs['kill_count']}K" not in pick["text"]:
            run["caption"] = {"pass": False, "flags": ["picked caption has no kill-count token"]}
            return stop("caption")
        cap_file = out / f"{clip}_caption.txt"
        cap_file.write_text(pick["text"] + "\n", encoding="utf-8")
        inputs["caption_file"] = str(cap_file)
        run["caption_pick"] = pick
    cap_path = inputs["caption_file"]
    run["caption"] = csj_caption_check.check(cap_path, inputs)
    if not run["caption"]["pass"]:
        return stop("caption")
    cap_text = Path(cap_path).read_text(encoding="utf-8")
    if f"{inputs['kill_count']}K" not in cap_text:
        run["caption"] = {"pass": False, "flags": [f"caption has no {inputs['kill_count']}K token for the input kill count"]}
        return stop("caption")

    # Killer-name check (blocking): each kill's killer must be the featured player (v39 section 9).
    run["killers"] = csj_killer_check.check(inputs)
    if not run["killers"]["pass"]:
        return stop("killer names")

    # Colour check (blocking, v39 section 8): colour 1 and 2 set, distinct, no blue for Canada or Turkey.
    if "nationality_colours" in inputs:
        run["colour"] = csj_colour_check.check(inputs)
        if not run["colour"]["pass"]:
            return stop("colour")

    # Rows must all exist before anything is built from them.
    missing_rows = [k for k in range(1, int(inputs["kill_count"]) + 1)
                    if not (Path(rows_dir) / f"raw_K{k}.png").exists()]
    if missing_rows:
        run["rows"] = {"missing": missing_rows}
        return stop("rows missing")

    # Row-one gate (Jord, 28 Oct, hard stop): row one must match donk's row before rows two to five are used.
    import csj_row1_gate
    run["row1_gate"] = csj_row1_gate.check(str(Path(rows_dir) / "raw_K1.png"), str(HERE / "final_row1.png"))
    if not run["row1_gate"]["pass"]:
        return stop("row one gate")

    # Row crop check (blocking): each raw row must have no feed noise in the 6 columns left of its border.
    row_reports = []
    for k in range(1, int(inputs["kill_count"]) + 1):
        _, rep = csj_rowcrop.crop_to_border(Image.open(Path(rows_dir) / f"raw_K{k}.png"))
        row_reports.append({"kill": k, **rep})
    run["rows"] = row_reports
    if not all(r["pass"] for r in row_reports):
        return stop("row crop")

    # Player set (Jord, 29 Oct): the banner is picked at random from the player's set. The character stays the same.
    run["player_assets"] = pick_player_assets(inputs)
    if not run["player_assets"]["pass"]:
        return stop("player assets")
    inputs = dict(inputs, banner=run["player_assets"]["banner"], figure=run["player_assets"]["character"])

    # Banner fit (Jord, 29 Oct): a banner that is not 1100x600 is fitted in the box, shape kept, before the build.
    from PIL import Image as _Img
    import csj_banner_fit
    with _Img.open(inputs["banner"]) as _b:
        if _b.size != (1100, 600):
            fitted = out / f"{clip}_banner_fitted.png"
            csj_banner_fit.fit(inputs["banner"], str(fitted))
            run["banner_fit"] = {"from": list(_b.size), "to": [1100, 600], "file": str(fitted)}
            inputs = dict(inputs, banner=str(fitted))

    timings = csj_build.build(inputs, onsets, rows_dir, out)
    run["build"] = timings["build"]
    run["build_sha256"] = timings.get("build_sha256")
    run["timings"] = str(out / f"{clip}_timings.json")
    gates = csj_gates.run(timings["build"], inputs, onsets, timings, rows_dir,
                          out / f"{clip}_layout.json", out / f"{clip}_gates.json")
    run["gates"] = str(out / f"{clip}_gates.json")
    run["blocking_pass"] = gates["blocking_pass"]
    run["upload_allowed"] = gates["blocking_pass"]
    if not gates["blocking_pass"]:
        run["stopped_at"] = gates["stopped_at"]
        return finish(1)
    if dry_run:
        run["upload"] = {"skipped": "dry run", "url_ok": None}
        return finish(0)
    # Item 4 (29 Oct): upload only after the blocking gates pass. Labelled clips upload too (NOT FINAL).
    import csj_asset_upload
    run["upload"] = csj_asset_upload.upload_clip(timings["build"], clip)
    if not run["upload"].get("url_ok"):
        run["stopped_at"] = "upload"
        return finish(1)
    return finish(0)


def pick_player_assets(inputs):
    """Item 3 (29 Oct): banner picked at random from the player's set, character kept the same.
    Sets come from players/<name>/ and research/asset_registry.json. Files with 'old' in the name are never used."""
    import random
    root = HERE.parent
    name = str(inputs.get("player_name", "")).lower()
    players = json.loads((root / "players" / "players.json").read_text())
    if name not in players:
        return {"pass": False, "flags": [f"player {name} is not in players/players.json"]}
    registry = json.loads((root / "research" / "asset_registry.json").read_text())

    def resolve_file(rel):
        for cand in (root / rel, root / (rel + ".png")):
            if cand.is_file():
                return cand
        return None

    def sets(kind):
        found = list((root / "players" / name).glob(f"{kind}*.png"))
        found += [resolve_file(a["file"]) for a in registry
                  if a.get("type") == kind and a.get("name", "").startswith(name + "-")]
        seen, out = set(), []
        for p in found:
            if p and "old" not in p.name.lower() and p.resolve() not in seen:
                seen.add(p.resolve())
                out.append(p)
        return sorted(out)

    banners, characters = sets("banner"), sets("character")
    flags = []
    if not banners:
        flags.append(f"no banner in the {name} set")
    if not characters:
        flags.append(f"no character in the {name} set")
    if flags:
        return {"pass": False, "flags": flags}
    banner = random.choice(banners)
    return {"pass": True, "flags": [], "banner": str(banner), "banner_choices": len(banners),
            "character": str(characters[0]), "character_kept_from": str(inputs.get("figure", ""))}


def intake(inputs):
    """Item 3: resolve the source and check the inputs file. Blocking. Nothing here asks Jord."""
    import csj_resolve
    flags = []
    missing = [k for k in ("player_name", "kill_count", "window_start", "window_end", "top_title",
                           "nationality_colours", "figure", "banner") if not inputs.get(k)]
    if missing:
        flags.append(f"missing inputs: {missing}")
    # kill count (Jord, 29 Oct): must come from inputs; above 5 is flagged; Jord's yes is needed before any build
    kc = int(inputs.get("kill_count") or 0)
    if kc > 5 and inputs.get("kill_count_confirmed") is not True:
        flags.append(f"kill count {kc} is above 5. Flag to Jord, then set kill_count_confirmed.")
    if inputs.get("kill_count_confirmed") is not True:
        flags.append("kill count not confirmed by Jord yet (set kill_count_confirmed after his yes)")
    # figure check (skill section 2): AWP for demOn, AK-47 for Woxic. Code cannot see the rifle, so Jord confirms.
    if inputs.get("figure_confirmed") is not True:
        flags.append("figure not confirmed (set figure_confirmed after checking the rifle by eye)")
    # row one vs donk (skill section 2): row one is checked against donk before rows two to five
    if kc > 1 and inputs.get("row1_checked_vs_donk") is not True:
        flags.append("row one not checked against donk yet (set row1_checked_vs_donk)")
    source = inputs.get("source")
    length = float(inputs.get("window_end", 0)) - float(inputs.get("window_start", 0)) if inputs.get("window_end") else None
    if not source or not Path(source).exists():
        found = csj_resolve.resolve(length=length, tol=0.1, fps=float(inputs.get("fps", 60)))
        if found:
            source = found[0]["path"]
        else:
            flags.append("source not found in any upload root (csj_resolve.py)")
    if source and Path(source).exists():
        info = csj_resolve.probe(source)
        if not info or info["w"] != 1920 or info["h"] != 1080:
            flags.append(f"source is not 1920x1080: {info}")
        if info and abs(info["fps"] - float(inputs.get("fps", 60))) > 0.05:
            flags.append(f"source fps {info['fps']} is not {inputs.get('fps')}")
    return {"pass": not flags, "flags": flags, "source": source}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="One CS Junkie clip, unattended.")
    ap.add_argument("inputs")
    ap.add_argument("candidates")
    ap.add_argument("rows_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--dry-run", action="store_true", help="run every check and the build, no upload, post or schedule")
    a = ap.parse_args()
    sys.exit(main(a.inputs, a.candidates, a.rows_dir, a.out_dir, dry_run=a.dry_run))
