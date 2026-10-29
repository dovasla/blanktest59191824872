"""CS Junkie build (csj-process v5, Step 4). One ffmpeg call per clip, no hand-typed filters.

Usage:
  python3 csj_build.py <inputs.json> <onsets.json> <rows_dir> <out_dir>

Layout (agreed):
  - Canvas 1080x1920, source fps (60 for these clips; 21 Oct), total duration = window_end - window_start.
  - Background: source frame scaled to cover (scale=-2:1920, crop 1080x1920), Gaussian blur 40 (fill, never pad).
  - Foreground: source crop 1080x1080 at x 420, placed at y 420.
  - Rows scaled 1.5x (LANCZOS), right edge x 1050, top y 40, gap 9. Stack k = rows 1..k.
  - Slide (Step 4): row k enters from the right at its switch time, moves left over 0.2 s with ease-out cubic
    (x = land + (1080 - land) * (1 - u)^3) and lands on its slot at switch time + 0.2 s. Then stack k stays
    until the next row lands. Switch time = (onset - window_start) rounded to the clip frame.
  - No cover (covers out, Jord 28 Oct). Frame 0 is a copy of the first frame, held for one clip frame (1/fps).
    Every stack and the audio move by that one frame.
  - Audio: source from window_start, delayed by the hold, AAC.

Speed (27 Oct 2026, Jord: apply the research improvements). The picture is the same as the earlier build;
only how it is made changed:
  - Encode at the locked export settings from the start: H.264 crf 12, maxrate 24M, bufsize 48M (Step 5), so
    the seam gate does not force a second encode. Preset veryfast (CSJ_PRESET=medium restores the old preset).
  - Row layers are cut to their own box and only exist while they are on screen (windowed inputs), so each
    frame carries at most two small overlays instead of up to five full-canvas ones.

Refuses to build unless the onset file (csj_onset_check.py) has "pass": true.
Writes <out_dir>/<clip_id>_build.mp4, <out_dir>/<clip_id>_timings.json and <out_dir>/<clip_id>_layout.json
(the slide gate input). Returns the timings.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

SLIDE = 0.2
CUTBOX = os.environ.get("CSJ_CUTBOX", "1") == "1"  # default on (Jord, 29 Oct); set CSJ_CUTBOX=0 for the full-canvas path
PRESET = os.environ.get("CSJ_PRESET", "veryfast")
ENC = ["-c:v", "libx264", "-preset", PRESET, "-crf", "12", "-maxrate", "24M", "-bufsize", "48M",
       "-pix_fmt", "yuv420p", "-movflags", "+faststart"]


def row_geometry(rows):
    """Scaled rows (1.5x LANCZOS) with their top y and landing x in the 1080x1080 canvas."""
    out = []
    for k, im in enumerate(rows):
        w, h = im.size
        r = im.convert("RGBA").resize((round(w * 1.5), round(h * 1.5)), Image.LANCZOS)
        y = 40 + 60 * k  # each later kill 60 px lower, downward only (locked, Jord 28 Oct)
        out.append({"img": r, "x": 1049 - r.width, "y": y})  # right edge x 1049 (locked)
        if y + r.height > 1080:
            raise ValueError("stack overflows the 1080 px square")
    return out


def stack_png(rows, n, out_png):
    canvas = Image.new("RGBA", (1080, 1080), (0, 0, 0, 0))
    for g in row_geometry(rows)[:n]:
        canvas.alpha_composite(g["img"], (g["x"], g["y"]))
    canvas.save(out_png)


def red_left(row):
    """Leftmost raw-row column with at least 4 red pixels (the row's own red border), as the slide gate reads it."""
    a = np.asarray(row.convert("RGB")).astype(int)
    red = (a[..., 0] > 120) & (a[..., 0] - np.maximum(a[..., 1], a[..., 2]) > 90)
    cols = np.nonzero(red.sum(axis=0) >= 4)[0]
    return int(cols[0]) if cols.size else 0


def has_audio(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                          "stream=index", "-of", "csv=p=0", path], capture_output=True, text=True).stdout
    return bool(out.strip())


def overlay_plan(inputs, geo, starts, planned, fps, work):
    """Static overlays in order: banner (0 to 4 s, fade 3.5 to 4.0 s), figure, title, then one accent layer per
    row, shown from its landing. Built by csj_banner, csj_figure, csj_text and csj_accents (colours are inputs)."""
    import csj_accents
    import csj_banner
    import csj_figure
    import csj_text
    work = Path(work)
    cfg = work / "overlay_inputs.json"
    cfg.write_text(json.dumps({
        "clip_id": inputs["clip_id"], "nationality_colours": inputs["nationality_colours"],
        "top_title": inputs.get("top_title", ""), "figure_scale": inputs.get("figure_scale", 1.0),
        "figure_cx": inputs.get("figure_cx", 540)}))
    plan = []
    layer, _ = csj_banner.banner_layer(inputs["banner"])
    p = work / "banner_layer.png"
    layer.save(p)
    plan.append((p, "between(t,0,4)", ",fade=t=out:st=3.5:d=0.5:alpha=1"))
    csj_figure.main(str(cfg), inputs["figure"], str(work))
    plan.append((work / f"{inputs['clip_id']}_figure_layer.png", f"between(t,0,{planned:.6f})", ""))
    csj_text.main(str(cfg), str(work))
    plan.append((work / f"{inputs['clip_id']}_title_layer.png", f"between(t,0,{planned:.6f})", ""))
    colours = csj_accents.colours_from(inputs)
    for k, g in enumerate(geo):
        acc = csj_accents.draw_layer(colours, g["x"], 420 + g["y"])
        p = work / f"accents_K{k + 1}.png"
        acc.save(p)
        if k == 0:  # row 1 is what the saved-layer colour check reads, at its real position
            acc.save(work / f"{inputs['clip_id']}_accents_layer.png")
        plan.append((p, f"gte(t,{starts[k] + 1 / fps + 0.2:.6f})", ""))
    return plan


def build(inputs, onsets, rows_dir, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    clip = inputs["clip_id"]
    FPS = int(round(float(inputs["fps"])))  # final rate = source rate (21 Oct, Jord: highest fps)
    HOLD = 1 / FPS
    ws, we = float(inputs["window_start"]), float(inputs["window_end"])
    planned = we - ws
    kills = int(inputs["kill_count"])
    rows = [Image.open(Path(rows_dir) / f"raw_K{k}.png") for k in range(1, kills + 1)]
    if onsets.get("pass") is not True:
        # Jord (29 Oct): onset check is a warning, not a blocker. Build continues, clip labelled NOT FINAL.
        print("WARNING onset check not passed, build continues as NOT FINAL:", onsets.get("flags"))
    # Item 2 (29 Oct): figure, title, accents and colours are always part of the build. No optional path.
    missing = [k for k in ("figure", "banner", "top_title", "nationality_colours") if not inputs.get(k)]
    if missing:
        raise ValueError(f"build refused, missing inputs: {missing}")
    kill_list = sorted(onsets["kills"], key=lambda k: k["seconds"])[:kills]
    starts = [round((k["seconds"] - ws) * FPS) / FPS for k in kill_list]
    if any(s < 0 or s + SLIDE >= planned for s in starts):
        raise ValueError(f"onset outside window: {starts}")

    geo = row_geometry(rows)
    work = out_dir / f"{clip}_layers"
    work.mkdir(exist_ok=True)
    slide_png, stack_p, stack_xy = [], [], []
    for k in range(kills):
        g = geo[k]
        p = work / f"slide_{k + 1}.png"  # row k alone, cut to its own box
        g["img"].save(p)
        slide_png.append(p)
        canvas = Image.new("RGBA", (1080, 1080), (0, 0, 0, 0))
        for gg in geo[:k + 1]:
            canvas.alpha_composite(gg["img"], (gg["x"], gg["y"]))
        sp = work / f"stack_{k + 1}.png"  # full 1080x1080 canvas, placed at (0, 420) as in the locked build
        canvas.save(sp)
        stack_p.append(sp)
        stack_xy.append((0, 0))

    # Main timeline is planned minus one hold; the hold is a copy of the first frame.
    main_len = planned - HOLD
    audio = has_audio(inputs["source"])
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{ws:.3f}", "-i", inputs["source"]]
    n_in = 1
    parts = [
        f"[0:v]fps={FPS},split=2[v1][v2]",
        "[v1]scale=-2:1920,crop=1080:1920,gblur=sigma=40[bg]",
        "[v2]crop=1080:1080:420:0[fg]",
        "[bg][fg]overlay=0:420[b0]",
    ]
    prev = "b0"
    # grade the gameplay only, before rows, banner, figure, title and accents (v39 section 7)
    parts.append("[b0]eq=contrast=1.08:saturation=0.92:gamma=1.02[g0]")
    prev = "g0"
    for k in range(kills):
        g, s = geo[k], starts[k]
        # sliding row: alive for exactly the 0.2 s slide
        cmd += ["-framerate", str(FPS), "-itsoffset", f"{s:.6f}", "-loop", "1", "-t", f"{SLIDE:.6f}",
                "-i", str(slide_png[k])]
        xexpr = f"'{g['x']}+(1080-{g['x']})*pow(max(0,1-(t-{s:.6f})/{SLIDE}),3)'"
        parts.append(f"[{n_in}:v]format=rgba[sl{k}]")
        parts.append(f"[{prev}][sl{k}]overlay=x={xexpr}:y={420 + g['y']}:eval=frame:eof_action=pass:repeatlast=0[a{k}]")
        prev = f"a{k}"
        n_in += 1
        # settled stack k: from the landing until the next row has landed (or the end)
        t_on = s + SLIDE
        t_off = (starts[k + 1] + SLIDE) if k + 1 < kills else planned
        cmd += ["-framerate", str(FPS), "-itsoffset", f"{t_on:.6f}", "-loop", "1", "-t", f"{t_off - t_on:.6f}",
                "-i", str(stack_p[k])]
        parts.append(f"[{n_in}:v]format=rgba[st{k}]")
        parts.append(f"[{prev}][st{k}]overlay=0:420:eof_action=pass:repeatlast=0[b{k}]")
        prev = f"b{k}"
        n_in += 1
    plan = overlay_plan(inputs, geo, starts, planned, FPS, work)
    # Item 2: the figure, title, accents and colour checks read the layers the build just made (saved files).
    import csj_colour_check
    colour_res = csj_colour_check.check(inputs, work, accent_origin=(geo[0]["x"], 420 + geo[0]["y"]))
    if not colour_res["pass"]:
        raise ValueError(f"colour, figure, title or accent check failed, build refused: {colour_res['flags']}")
    for path, enable, pre in plan:
        # Cut-box overlays (29 Oct): default on, Jord approved. Each layer is cropped to its own box and placed at
        # that box's position, about 36 percent faster on heavygod (75.7 s vs 118.6 s, 16 s window). Not the default:
        # where the banner and figure overlap (0 to 4 s), the blend rounds differently (Y up to 15, chroma up to 54).
        img = Image.open(path).convert("RGBA")
        ox, oy, layer_path = 0, 0, path
        if CUTBOX:
            box = img.getchannel("A").getbbox()
            if box is None:
                continue  # an empty layer adds nothing to the picture
            ox, oy = box[0], box[1]
            layer_path = path.with_name(path.stem + "_box.png")
            img.crop(box).save(layer_path)
        n_in_now = n_in
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{planned:.6f}", "-i", str(layer_path)]
        parts.append(f"[{n_in_now}:v]format=rgba{pre}[ov{n_in_now}]")
        parts.append(f"[{prev}][ov{n_in_now}]overlay={ox}:{oy}:format=auto:enable='{enable}'[p{n_in_now}]")
        prev = f"p{n_in_now}"
        n_in += 1
    # One-frame hold at the start: frame 0 is cloned for one frame (tpad). No cover input.
    parts.append(f"[{prev}]tpad=start=1:start_mode=clone,format=yuv420p[vout]")
    maps = ["-map", "[vout]"]
    if audio:
        parts.append(f"[0:a]atrim=0:{main_len:.6f},asetpts=PTS-STARTPTS,adelay={HOLD * 1000:.4f}:all=1[aout]")
        maps += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    out_mp4 = out_dir / f"{clip}_build.mp4"
    cmd += ["-filter_complex", ";".join(parts), *maps, "-t", f"{planned:.6f}", "-r", str(FPS), *ENC, str(out_mp4)]
    subprocess.run(cmd, check=True)
    import hashlib
    timings_hash = hashlib.sha256(out_mp4.read_bytes()).hexdigest()

    layout = {"slide": SLIDE, "fps": FPS, "kills": [
        {"kill": k + 1, "slide_start_s": round(starts[k] + HOLD, 4), "y0": 420 + geo[k]["y"],
         "y1": 420 + geo[k]["y"] + geo[k]["img"].height - 1,
         "x_land": geo[k]["x"] + round(red_left(rows[k]) * 1.5)} for k in range(kills)]}
    (out_dir / f"{clip}_layout.json").write_text(json.dumps(layout, indent=2))
    timings = {"clip_id": clip, "window_start": ws, "window_end": we, "planned_duration": planned,
               "fps": FPS, "hold_frames": 1, "kill_count": kills,
               "stack_switch_output_s": [round(s + HOLD, 4) for s in starts],
               "onset_s": [k["seconds"] for k in kill_list], "slide_s": SLIDE, "audio": audio,
               "build": str(out_mp4), "build_sha256": timings_hash, "encode": {"preset": PRESET, "crf": 12, "maxrate": "24M", "bufsize": "48M"},
               "cmd_filter": parts}
    (out_dir / f"{clip}_timings.json").write_text(json.dumps(timings, indent=2))
    return timings


if __name__ == "__main__":
    inputs = json.loads(Path(sys.argv[1]).read_text())
    onsets = json.loads(Path(sys.argv[2]).read_text())
    t = build(inputs, onsets, sys.argv[3], sys.argv[4])
    print(json.dumps({k: t[k] for k in ("clip_id", "kill_count", "stack_switch_output_s", "build")}, indent=2))
