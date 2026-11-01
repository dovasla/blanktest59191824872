"""CS Junkie build (csj-process v5, Step 4). One filter graph per clip, no hand-typed filters.

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

Speed (27 Oct 2026, Jord: apply the research improvements):
  - Encode at the locked export settings from the start: H.264 crf 12, maxrate 24M, bufsize 48M (Step 5), so
    the seam gate does not force a second encode. Preset veryfast (CSJ_PRESET=medium restores the old preset).
  - Row layers are cut to their own box and only exist while they are on screen (windowed inputs), so each
    frame carries at most two small overlays instead of up to five full-canvas ones.
  - Chunked parallel encode (30 Oct, Jord: default for every clip). The clip is cut into CSJ_CHUNKS pieces of
    whole frames. Each piece is rendered by the same filter graph as the single pass, seeked to its own start
    and with every time in the graph shifted to match. The pieces run in parallel and are joined with ffmpeg
    stream copy. The audio is cut once from the source and muxed in. CSJ_CHUNKS=1 gives one piece (no split).
  Default 2 pieces (30 Oct timing on heavygod test: 1 piece 84.9 s, 2 pieces 63.1 s, 4 pieces 79.9 s).

Refuses to build unless the onset file (csj_onset_check.py) has "pass": true.
Writes <out_dir>/<clip_id>_build.mp4, <out_dir>/<clip_id>_timings.json and <out_dir>/<clip_id>_layout.json
(the slide gate input). Returns the timings.
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

SLIDE = 0.2
CUTBOX = os.environ.get("CSJ_CUTBOX", "1") == "1"  # default on (Jord, 29 Oct); set CSJ_CUTBOX=0 for the full-canvas path
FIGURE_SCALE_DEFAULT = json.loads((Path(__file__).resolve().parent / "csj_head_line.json").read_text())["figure_scale_default"]  # one size for every build (30 Oct)
PRESET = os.environ.get("CSJ_PRESET", "veryfast")  # 30 Oct: back to veryfast for picture quality (Jord); superfast gave no time saving
CHUNKS = max(1, int(os.environ.get("CSJ_CHUNKS", "2")))  # 30 Oct: parallel encode pieces. 2 was fastest on the 4-core box (4 pieces ran slower)
ENC = ["-c:v", "libx264", "-preset", PRESET, "-crf", "12", "-maxrate", "24M", "-bufsize", "48M",
       "-pix_fmt", "yuv420p", "-movflags", "+faststart"]


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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
    row, shown from its landing. Built by csj_banner, csj_figure, csj_text and csj_accents (colours are inputs).
    Each entry: the layer file, when it is on (("between", a, b) or ("gte", a), clip time), and an optional fade."""
    import csj_accents
    import csj_banner
    import csj_cache
    import csj_figure
    import csj_text
    work = Path(work)
    cfg = work / "overlay_inputs.json"
    cfg.write_text(json.dumps({
        "clip_id": inputs["clip_id"], "nationality_colours": inputs["nationality_colours"],
        "top_title": inputs.get("top_title", ""), "figure_scale": inputs.get("figure_scale", FIGURE_SCALE_DEFAULT),
        "figure_cx": inputs.get("figure_cx", 540)}))
    plan = []
    p = work / "banner_layer.png"
    if os.environ.get("CSJ_NO_BANNER"):
        # 30 Oct (Jord): no banner. The bottom section keeps the same blur as the top (bgA), so no card shows.
        Image.new("RGBA", (1080, 1920), (0, 0, 0, 0)).save(p)
    else:
        banner_key = csj_cache.key_of([csj_cache.sha(inputs["banner"]), csj_cache.sha(str(Path(__file__).with_name("csj_banner.py")))])
        if not csj_cache.get("banner", banner_key, ["banner_layer.png"], work):
            layer, _ = csj_banner.banner_layer(inputs["banner"])
            layer.save(p)
            csj_cache.put("banner", banner_key, ["banner_layer.png"], work)
    plan.append({"path": p, "enable": ("between", 0, 4), "fade": (3.5, 0.5)})
    head_y = json.loads((Path(csj_figure.__file__).parent / "csj_head_line.json").read_text())["head_line_y"]
    fig_files = [f"{inputs['clip_id']}_figure_layer.png", f"{inputs['clip_id']}_figure_report.json", f"{inputs['clip_id']}_grade.txt"]
    fig_key = csj_cache.key_of([csj_cache.sha(inputs["figure"]), head_y, inputs.get("figure_scale", 1.0),
                                inputs.get("figure_cx", 540), inputs["nationality_colours"], inputs["clip_id"],
                                csj_figure.__file__ and csj_cache.sha(csj_figure.__file__)])
    if not csj_cache.get("figure", fig_key, fig_files, work):
        csj_figure.main(str(cfg), inputs["figure"], str(work))
        csj_cache.put("figure", fig_key, fig_files, work)
    plan.append({"path": work / f"{inputs['clip_id']}_figure_layer.png", "enable": ("between", 0, planned), "fade": None})
    # 30 Oct (Jord, cache rule): title and accent layers are reused while their inputs stay the same.
    title_file = f"{inputs['clip_id']}_title_layer.png"
    title_key = csj_cache.key_of([cfg.read_text(), csj_cache.sha(csj_text.__file__)])
    if not csj_cache.get("title", title_key, [title_file], work):
        csj_text.main(str(cfg), str(work))
        csj_cache.put("title", title_key, [title_file], work)
    plan.append({"path": work / title_file, "enable": ("between", 0, planned), "fade": None})
    colours = csj_accents.colours_from(inputs)
    acc_files = [f"accents_K{k + 1}.png" for k in range(len(geo))] + [f"{inputs['clip_id']}_accents_layer.png"]
    acc_key = csj_cache.key_of([colours, [(g["x"], g["y"]) for g in geo], csj_cache.sha(csj_accents.__file__)])
    if not csj_cache.get("accents", acc_key, acc_files, work):
        for k, g in enumerate(geo):
            acc = csj_accents.draw_layer(colours, g["x"], 420 + g["y"], row_w=g["img"].width)
            acc.save(work / f"accents_K{k + 1}.png")
            if k == 0:  # row 1 is what the saved-layer colour check reads, at its real position
                acc.save(work / f"{inputs['clip_id']}_accents_layer.png")
        csj_cache.put("accents", acc_key, acc_files, work)
    for k, g in enumerate(geo):
        plan.append({"path": work / f"accents_K{k + 1}.png", "enable": ("gte", starts[k] + SLIDE), "fade": None})  # 31 Oct: settled accents start when the row lands, not 0.2 s later
    return plan


def _fade_out(st, d, off):
    """Fade-out text for a fade that runs from clip time st over d seconds, seen from a piece that starts at clip
    time off. Returns None when the fade is already over at the piece's start (nothing to draw)."""
    st_loc = st - off
    end_loc = st_loc + d
    if end_loc <= 0:
        return None
    if st_loc >= 0:
        return f"fade=t=out:st={st_loc:.6f}:d={d}:alpha=1"
    # The fade began before this piece: the alpha is already below 1 at its start. Scale it there, then fade
    # from 0 to the fade's end. The result is the same straight line as the clip-time fade.
    return f"colorchannelmixer=aa={end_loc / d:.6f},fade=t=out:st=0:d={end_loc:.6f}:alpha=1"


def _enable(spec, off):
    """Clip-time test for a static layer. The chunk's own time t plus its start offset gives clip time."""
    if spec[0] == "between":
        return f"between(t+{off:.6f},{spec[1]:.6f},{spec[2]:.6f})"
    return f"gte(t+{off:.6f},{spec[1]:.6f})"


def _chunk_bounds(total_frames, n):
    """Whole-frame cut points 0 = b0 < b1 < ... < bn = total_frames."""
    n = min(n, total_frames)
    return [round(i * total_frames / n) for i in range(n + 1)]


def _render_chunk(ctx, a, b, out_video, first):
    """Render output frames [a, b) with the same filter graph as the single pass.

    The graph works in main-clip time L. This piece starts at L = off, so the source is seeked to ws + off and
    every time in the graph is shifted by off. The first piece also holds frame 0 for one frame (tpad), as the
    single pass does. Video only: audio is muxed later from one cut of the source."""
    FPS, HOLD, planned = ctx["fps"], ctx["hold"], ctx["planned"]
    starts, kills, geo = ctx["starts"], ctx["kills"], ctx["geo"]
    off = 0.0 if first else (a - 1) / FPS  # clip time of this piece's first main frame (a - 1 is one hold back)
    span = (b - a) / FPS
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{ctx['ws'] + off:.6f}", "-i", ctx["source"]]
    n_in = 1
    parts = [
        f"[0:v]fps={FPS},split=2[v1][v2]",
        "[v1]scale=-2:1920,crop=1080:1920,split=2[bgA][bgC]",
        "[bgA]gblur=sigma=40[blur]",
        "[blur]split=2[blurA][blurT]",
        # 30 Oct (Jord): bottom band for the first 4 s comes from the TOP of the blurred frame, so no stat card shows.
        # It fades out between 3.5 and 4.0 s, then the original bottom feed shows.
        "[bgC]crop=1080:420:0:1500[origB]",
    ]
    top_fade = _fade_out(3.5, 0.5, off)  # the blurred top band fades out in clip time (30 Oct, see above)
    if top_fade:
        parts.append(f"[blurT]crop=1080:420:0:0,format=yuva420p,{top_fade}[topstrip]")
        parts.append("[origB][topstrip]overlay=0:0[botpatch]")
    else:
        parts += ["[blurT]nullsink", "[origB]null[botpatch]"]  # the band is gone: the bottom is the feed
    parts += [
        "[blurA][botpatch]overlay=0:1500[bg]",
        "[v2]crop=1080:1080:420:0[fg]",
        "[bg][fg]overlay=0:420[b0]",
    ]
    # grade the gameplay only, before rows, banner, figure, title and accents (v39 section 7)
    parts.append("[b0]eq=contrast=1.08:saturation=0.92:gamma=1.02[g0]")
    prev = "g0"
    span_end = off + span

    def overlaps(w0, w1):
        return w1 > off and w0 < span_end

    for k in range(kills):
        g, s = geo[k], starts[k]
        # sliding row: alive for exactly the 0.2 s slide. Inputs that cannot be on screen in this piece are left out.
        if overlaps(s, s + SLIDE):
            cmd += ["-framerate", str(FPS), "-itsoffset", f"{s - off:.6f}", "-loop", "1", "-t", f"{SLIDE:.6f}",
                    "-i", str(ctx["slide_png"][k])]
            xexpr = f"'{g['x']}+(1080-{g['x']})*pow(max(0,1-(t+{off:.6f}-{s:.6f})/{SLIDE}),3)'"
            parts.append(f"[{n_in}:v]format=rgba[sl{k}]")
            parts.append(f"[{prev}][sl{k}]overlay=x={xexpr}:y={420 + g['y']}:eval=frame:eof_action=pass:repeatlast=0[a{k}]")
            prev = f"a{k}"
            n_in += 1
        # settled stack k: from the landing until the next row has landed (or the end)
        t_on = s + SLIDE
        t_off = (starts[k + 1] + SLIDE) if k + 1 < kills else planned
        if overlaps(t_on, t_off):
            cmd += ["-framerate", str(FPS), "-itsoffset", f"{t_on - off:.6f}", "-loop", "1", "-t", f"{t_off - t_on:.6f}",
                    "-i", str(ctx["stack_p"][k])]
            parts.append(f"[{n_in}:v]format=rgba[st{k}]")
            sx, sy = ctx["stack_xy"][k]
            parts.append(f"[{prev}][st{k}]overlay={sx}:{420 + sy}:eof_action=pass:repeatlast=0[c{k}]")
            prev = f"c{k}"
            n_in += 1
    for layer in ctx["layers"]:
        # static layers: their own clock starts at clip time 0, so they are shifted back by off to line up
        fade = ""
        if layer["fade"]:
            fade_txt = _fade_out(layer["fade"][0], layer["fade"][1], off)
            if fade_txt is None:
                continue  # already faded out before this piece starts
            fade = "," + fade_txt
        cmd += ["-loop", "1", "-framerate", str(FPS), "-itsoffset", f"{-off:.6f}", "-t", f"{planned:.6f}",
                "-i", str(layer["path"])]
        parts.append(f"[{n_in}:v]format=rgba{fade}[ov{n_in}]")
        parts.append(f"[{prev}][ov{n_in}]overlay={layer['ox']}:{layer['oy']}:format=auto:"
                     f"enable='{_enable(layer['enable'], off)}'[p{n_in}]")
        prev = f"p{n_in}"
        n_in += 1
    if first:
        # One-frame hold at the start: frame 0 is cloned for one frame (tpad). No cover input.
        parts.append(f"[{prev}]tpad=start=1:start_mode=clone,format=yuv420p[vout]")
    else:
        parts.append(f"[{prev}]format=yuv420p[vout]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[vout]", "-an", "-t", f"{span:.6f}", "-r", str(FPS),
            "-force_key_frames", "0", *ENC, str(out_video)]
    return cmd, parts


def _run_chunks(cmds, work):
    """Run every piece at once, wait for all, and fail if one fails."""
    procs = []
    for i, cmd in enumerate(cmds):
        log = open(work / f"chunk_{i + 1}.log", "w")
        procs.append((subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT), log))
    codes = []
    for p, log in procs:
        codes.append(p.wait())
        log.close()
    if any(codes):
        raise RuntimeError(f"encode piece failed, exit codes {codes}; see {work}/chunk_*.log")


def _run_cached(cmds, pieces, work):
    """Encode each piece only when its cache entry is missing (30 Oct, cache rule). The key holds the full ffmpeg
    command (without the output file), the checksum of every input file and this script. Pieces that miss run in
    parallel, as before."""
    import csj_cache
    todo = []
    for cmd, piece in zip(cmds, pieces):
        ins = [a for a in cmd if os.path.isfile(a) and a != str(piece)]
        key = csj_cache.key_of([cmd[:-1], [csj_cache.sha(a) for a in ins], csj_cache.sha(__file__)])
        if csj_cache.get("piece", key, [piece.name], piece.parent):
            print(f"cache hit: {piece.name} reused, no encode run")
        else:
            todo.append((cmd, piece, key))
    if todo:
        _run_chunks([c for c, _, _ in todo], work)
        for _, piece, key in todo:
            csj_cache.put("piece", key, [piece.name], piece.parent)


def _join(pieces, source, ws, main_len, hold, audio, work, out_mp4):
    """Stream-copy the pieces into one video, then add the audio cut from the source."""
    lst = work / "pieces.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in pieces))
    video = work / "joined_video.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(video)], check=True)
    if not audio:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-c", "copy", "-movflags", "+faststart",
                        str(out_mp4)], check=True)
        return
    aud = work / "audio.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{ws:.6f}", "-t", f"{main_len:.6f}", "-i", source,
                    "-vn", "-af", f"asetpts=PTS-STARTPTS,adelay={hold * 1000:.4f}:all=1", "-c:a", "aac",
                    "-b:a", "192k", "-ar", "48000", str(aud)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(aud), "-map", "0:v", "-map", "1:a",
                    "-c", "copy", "-movflags", "+faststart", str(out_mp4)], check=True)


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
    # 30 Oct (Jord, rule J): the kill rows must match the last approved set before a build starts.
    rows_sums = {f"raw_K{k}.png": file_sha(Path(rows_dir) / f"raw_K{k}.png") for k in range(1, kills + 1)}
    approved_path = Path(rows_dir).parent / "approved_rows.json"
    if approved_path.exists():
        approved = json.loads(approved_path.read_text()).get("rows", {})
        changed = [n for n in rows_sums if approved.get(n) != rows_sums[n]]
        if changed:
            raise ValueError(f"kill rows differ from the approved set {changed}; build stopped, ask Jord")
        print("kill rows match the approved set")
    else:
        print("WARNING no approved row set for this clip yet; rows checksums recorded only")
    # 30 Oct (Jord, rule K): banner box comes from csj_banner_box.json; the build refuses a mismatch.
    box = json.loads((Path(__file__).resolve().parent / "csj_banner_box.json").read_text())
    import csj_banner
    if (csj_banner.BOX_W, csj_banner.BOX_H, csj_banner.BOX_X, csj_banner.BOX_Y) != (
            box["box_w"], box["box_h"], box["box_x"], box["box_y"]):
        raise ValueError("banner box in csj_banner.py does not match csj_banner_box.json; build refused")
    print(f"banner box {box['box_w']}x{box['box_h']} at x {box['box_x']}, y {box['box_y']}")
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
    import csj_accents  # 31 Oct: slide images carry the accents
    slide_png, stack_p, stack_xy = [], [], []
    for k in range(kills):
        g = geo[k]
        p = work / f"slide_{k + 1}.png"  # row k cut to its own box, with its accents on top (31 Oct: accents slide with the row)
        acc_row = csj_accents.draw_layer(csj_accents.colours_from(inputs), g["x"], 420 + g["y"], row_w=g["img"].width)
        slide_img = g["img"].convert("RGBA").copy()
        slide_img.alpha_composite(acc_row.crop((g["x"], 420 + g["y"], g["x"] + g["img"].width, 420 + g["y"] + g["img"].height)))
        slide_img.save(p)
        slide_png.append(p)
        canvas = Image.new("RGBA", (1080, 1080), (0, 0, 0, 0))
        for gg in geo[:k + 1]:
            canvas.alpha_composite(gg["img"], (gg["x"], gg["y"]))
        # 30 Oct (Jord, smaller render area): the settled stack is cut to the box it covers, so each frame blends
        # only that box, not the full 1080x1080 canvas. The box starts on an even pixel: an odd offset changes the
        # colour blend on the row edge (tested 30 Oct, output matches the full canvas except 4 frames by 1 colour level).
        box = canvas.getchannel("A").getbbox()
        ox, oy = box[0] & ~1, box[1] & ~1
        sp = work / f"stack_{k + 1}_box.png"
        canvas.crop((ox, oy, box[2], box[3])).save(sp)
        stack_p.append(sp)
        stack_xy.append((ox, oy))

    plan = overlay_plan(inputs, geo, starts, planned, FPS, work)
    # Item 2: the figure, title, accents and colour checks read the layers the build just made (saved files).
    import csj_colour_check
    colour_res = csj_colour_check.check(inputs, work, accent_origin=(geo[0]["x"], 420 + geo[0]["y"]))
    if not colour_res["pass"]:
        raise ValueError(f"colour, figure, title or accent check failed, build refused: {colour_res['flags']}")
    layers = []
    for entry in plan:
        # Cut-box overlays (29 Oct): default on, Jord approved. Each layer is cropped to its own box and placed at
        # that box's position. Where the banner and figure overlap (0 to 4 s), the blend rounds differently
        # (Y up to 15, chroma up to 54), so this is default on, not identical to the full-canvas path.
        path = entry["path"]
        img = Image.open(path).convert("RGBA")
        ox, oy, layer_path = 0, 0, path
        if CUTBOX:
            box = img.getchannel("A").getbbox()
            if box is None:
                continue  # an empty layer adds nothing to the picture
            ox, oy = box[0], box[1]
            layer_path = path.with_name(path.stem + "_box.png")
            img.crop(box).save(layer_path)
        layers.append({"path": layer_path, "ox": ox, "oy": oy, "enable": entry["enable"], "fade": entry["fade"]})

    ctx = {"fps": FPS, "hold": HOLD, "planned": planned, "ws": ws, "source": inputs["source"], "starts": starts,
           "kills": kills, "geo": geo, "slide_png": slide_png, "stack_p": stack_p, "stack_xy": stack_xy,
           "layers": layers}
    total = round(planned * FPS)
    bounds = _chunk_bounds(total, CHUNKS)
    pieces_dir = work / "pieces"
    pieces_dir.mkdir(exist_ok=True)
    cmds, pieces, first_parts = [], [], None
    for i in range(len(bounds) - 1):
        a, b = bounds[i], bounds[i + 1]
        piece = pieces_dir / f"piece_{i + 1:02d}.mp4"
        cmd, parts = _render_chunk(ctx, a, b, piece, first=(i == 0))
        if i == 0:
            first_parts = parts
        cmds.append(cmd)
        pieces.append(piece)
    t_enc = time.time()
    _run_cached(cmds, pieces, work)
    encode_s = round(time.time() - t_enc, 2)

    out_mp4 = out_dir / f"{clip}_build.mp4"
    audio = has_audio(inputs["source"])
    _join(pieces, inputs["source"], ws, planned - HOLD, HOLD, audio, work, out_mp4)
    timings_hash = hashlib.sha256(out_mp4.read_bytes()).hexdigest()

    layout = {"slide": SLIDE, "fps": FPS, "kills": [
        {"kill": k + 1, "slide_start_s": round(starts[k] + HOLD, 4), "y0": 420 + geo[k]["y"],
         "y1": 420 + geo[k]["y"] + geo[k]["img"].height - 1,
         "x_land": geo[k]["x"] + round(red_left(rows[k]) * 1.5)} for k in range(kills)]}
    (out_dir / f"{clip}_layout.json").write_text(json.dumps(layout, indent=2))
    # 30 Oct (Jord, rule J): checksum the rows and layout after each build, and keep the record with the build.
    check = {"rows": rows_sums, "layout": file_sha(out_dir / f"{clip}_layout.json")}
    (out_dir / f"{clip}_rows_check.json").write_text(json.dumps(check, indent=2))
    if approved_path.exists() and json.loads(approved_path.read_text()).get("layout") not in (None, check["layout"]):
        raise ValueError("layout differs from the approved set; build stopped, ask Jord")
    timings = {"clip_id": clip, "window_start": ws, "window_end": we, "planned_duration": planned,
               "fps": FPS, "hold_frames": 1, "kill_count": kills,
               "stack_switch_output_s": [round(s + HOLD, 4) for s in starts],
               "onset_s": [k["seconds"] for k in kill_list], "slide_s": SLIDE, "audio": audio,
               "build": str(out_mp4), "build_sha256": timings_hash,
               "encode": {"preset": PRESET, "crf": 12, "maxrate": "24M", "bufsize": "48M",
                          "chunks": len(cmds), "chunk_frames": [bounds[i + 1] - bounds[i] for i in range(len(cmds))],
                          "encode_seconds": encode_s},
               "cmd_filter": first_parts}
    (out_dir / f"{clip}_timings.json").write_text(json.dumps(timings, indent=2))
    return timings


if __name__ == "__main__":
    inputs = json.loads(Path(sys.argv[1]).read_text())
    onsets = json.loads(Path(sys.argv[2]).read_text())
    t = build(inputs, onsets, sys.argv[3], sys.argv[4])
    print(json.dumps({k: t[k] for k in ("clip_id", "kill_count", "stack_switch_output_s", "build")}, indent=2))
