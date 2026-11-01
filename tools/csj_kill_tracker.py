"""CS Junkie kill feed tracker (29 Oct 2026). Dry run only: reads a video, writes JSON. Never uploads or posts.

Usage:
  python3 csj_kill_tracker.py <source.mp4> <out.json> [--victims "Aleksib,makazze,..."] [--killer heavygod]
          [--expected "Aleksib:4.17,makazze:11.8,..."]

What it does:
  1. Decodes the kill feed crop (x 1564, y 40, 356 x 200) at 15 fps (30 Oct). Onset is still counted in frames at the source rate.
  2. Finds each feed row by its red border (top and bottom lines, left and right edges).
  3. Reads the victim slot (saturated text on the right of the row) as a small bit mask.
     The mask is the row's identity. A row that shifts down keeps its mask, so it is never counted twice.
  4. A row counts as a new kill once the same name has matched in 6 frames. The kill stays counted
     until the end of the clip, so a row that shifts or leaves and comes back is never counted again.
  5. Fully visible = first frame the name text reaches 95% of its settled brightness.
     onset = that frame minus 3 frames, in seconds.
  Known limit: text brightness can read a row as visible a few frames before its plate looks solid.

Victim names are not read by OCR (no OCR engine here). Pass them in order with --victims.
Kills without a name are written as "victim_<n>".
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

FPS = 15
CROP = (1564, 40, 356, 200)  # x, y, w, h: smallest crop that keeps every kill and time (30 Oct, Woxic 4K and NAF)
ONSET_FRAMES = 3
MATCH_MIN = 0.85             # name patch correlation needed to call two rows the same victim
TEXT_DIST = 70               # colour distance from the plate that counts as text
CONTRAST_MIN = 12            # a patch with no text has almost no grey contrast
MIN_ROW_WIDTH = 120          # real rows are wide; thin false boxes are dropped
CONFIRM_HITS = 6             # frames a name must match before it counts as a kill
FULL_SHARE = 0.95            # share of settled text brightness that means fully visible


def decode(src):
    x, y, w, h = CROP
    cmd = ["ffmpeg", "-v", "error", "-i", src, "-vf", f"fps={FPS},crop={w}:{h}:{x}:{y}",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.run(cmd, capture_output=True, check=True)
    return np.frombuffer(proc.stdout, dtype=np.uint8).reshape(-1, h, w, 3)


def red_mask(f):
    r = f[..., 0].astype(int)
    g = f[..., 1].astype(int)
    b = f[..., 2].astype(int)
    return (r > 130) & (r - g > 70) & (r - b > 70)


def bands(counts, min_count):
    """Group consecutive y values with enough red pixels into [start, end] bands."""
    out = []
    for y, c in enumerate(counts):
        if c < min_count:
            continue
        if out and y - out[-1][1] <= 1:
            out[-1][1] = y
        else:
            out.append([y, y])
    return out


def find_rows(f):
    """Return rows as dicts: top, bottom, left, right."""
    red = red_mask(f)
    bs = bands(red.sum(axis=1), 40)
    rows = []
    i = 0
    while i + 1 < len(bs):
        top, bot = bs[i], bs[i + 1]
        height = bot[0] - top[1]
        if not 26 <= height <= 34:
            i += 1
            continue
        box = red[top[0]:bot[1] + 1]
        xs = np.where(box.sum(axis=0) >= 0.6 * box.shape[0])[0]
        if len(xs) < 2:
            i += 1
            continue
        left, right = int(xs.min()), int(xs.max())
        rows.append({"top": top[0], "bottom": bot[1], "left": left, "right": right})
        i += 2
    return rows


def victim_patch(f, row):
    """Grey 24 x 58 patch of the victim name area (right side of the row).
    Grey level only: a translucent plate over sand or sky shifts brightness, not shape."""
    y0 = row["top"] + 3
    x1 = row["right"] - 3
    patch = f[y0:y0 + 24, x1 - 58:x1].astype(float).mean(axis=2)
    return patch if patch.shape == (24, 58) else None


def text_peak(f, row):
    """Brightness of the brightest text pixels in the name area. Rises as the row fades in."""
    y0 = row["top"] + 6
    x1 = row["right"] - 6
    lum = f[y0:y0 + 16, x1 - 34:x1].astype(float).mean(axis=2)
    return float(np.percentile(lum, 95))


def same_victim(a, b):
    """Normalised correlation of the two name patches, allowing 1 px of shift."""
    core = a[1:23, 1:57]
    x = core - core.mean()
    best = -1.0
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            other = b[1 + dy:23 + dy, 1 + dx:57 + dx]
            y = other - other.mean()
            d = np.sqrt((x * x).sum() * (y * y).sum())
            if d > 0:
                best = max(best, float((x * y).sum() / d))
    return best >= MATCH_MIN


def killer_is_featured(f, row):
    """Killer check (29 Oct). The killer name sits on the left of the row. The featured player's
    name is drawn in the team's text colour (yellow in the clips tested). Another player's killer name
    in a different colour (blue in the clips tested) is rejected. This is a colour check, not a name read:
    there is no OCR here, so two players with the same colour would both pass."""
    y0 = row["top"] + 6
    x0 = row["left"] + 8
    area = f[y0:y0 + 16, x0:x0 + 64].astype(int)
    R, G, B = area[..., 0], area[..., 1], area[..., 2]
    yellow = ((R > 150) & (G > 120) & (B < 120)).sum()
    blue = ((B > 180) & (R < 170) & (B - R > 40)).sum()
    return yellow > blue and yellow >= 20


def run(src):
    """Track every feed row through the clip. Returns confirmed entries.

    A row becomes a kill once it has matched the same name patch in CONFIRM_HITS frames.
    Its onset is the first frame that reaches FULL_SHARE of its settled text contrast,
    which is the first fully visible frame.
    """
    frames = decode(src)
    tracks = []
    for n, f in enumerate(frames):
        for row in find_rows(f):
            if row["right"] - row["left"] < MIN_ROW_WIDTH:
                continue
            patch = victim_patch(f, row)
            if patch is None or patch.std() < CONTRAST_MIN:
                continue
            hit = next((t for t in tracks if same_victim(t["ref"], patch)), None)
            if hit is None:
                hit = {"ref": patch, "hits": [], "boxes": {}, "killer_ok": killer_is_featured(f, row)}
                tracks.append(hit)
            hit["ref"] = patch  # follow the row as its plate background changes
            hit["hits"].append((n, text_peak(f, row), row["top"]))
            hit["boxes"][n] = (row["left"], row["top"], row["right"], row["bottom"])  # bar box in feed crop (30 Oct)
    confirmed = [t for t in tracks if len(t["hits"]) >= CONFIRM_HITS]
    confirmed.sort(key=lambda t: t["hits"][0][0])
    return drop_slot_repeats(confirmed)


def drop_slot_repeats(tracks):
    """Slot rule (29 Oct). A kill row keeps its slot (its top y, +-3 px) until the clip ends.
    A later track that starts in a slot still held by an earlier kill is the same row with a changed
    victim name, not a new kill. Only the first track per slot counts."""
    kept = []
    for t in tracks:
        first_n, last_n = t["hits"][0][0], t["hits"][-1][0]
        slot = int(t["hits"][0][2])  # slot from first sighting (30 Oct): a row that shifts up is not a new kill slot
        clash = False
        for k in kept:
            k_slot = k["slot"]
            k_first, k_last = k["hits"][0][0], k["hits"][-1][0]
            overlaps = first_n <= k_last + 30 and k_first <= last_n
            if overlaps and abs(slot - k_slot) <= 3:
                clash = True
                break
        if not clash:
            t["slot"] = slot
            kept.append(t)
    return kept


def onset_frame_of(track):
    """First frame where the name reaches FULL_SHARE of its settled brightness.
    Settled brightness is the median over the 10 to 24 frames after the row first shows."""
    first = track["hits"][0][0]
    settled_vals = [v for n, v, _ in track["hits"] if first + 10 <= n <= first + 24]
    settled = float(np.median(settled_vals)) if settled_vals else max(v for _, v, _ in track["hits"])
    for n, v, _ in track["hits"]:
        if v >= FULL_SHARE * settled:
            return n
    return first


def build_kills(tracks, victims, killer):
    kills = []
    for k, t in enumerate(tracks, start=1):
        full = onset_frame_of(t)
        onset = max(full - ONSET_FRAMES, 0)
        kills.append({
            "kill": k,
            "victim": victims[k - 1] if k - 1 < len(victims) else f"victim_{k}",
            "killer": killer,
            "first_seen_s": round(t["hits"][0][0] / FPS, 4),
            "first_full_s": round(full / FPS, 4),
            "onset_frame": onset,
            "onset_s": round(onset / FPS, 4),
            # Feed timing gate fields (30 Oct, defaults): bar box in the feed crop, and the source frame
            # where the row is fully drawn (60 fps frame = 15 fps frame x 4). The frame is an estimate.
            "box_feed": list(t["boxes"].get(full, [0, 0, 0, 0])),
            "crop_frame": int(full * (60 // FPS)),
        })
    return kills


def apply_helper(tracks, expected):
    """Helper (Jord, 29 Oct). Main count comes from the row tracker. Only when it is above the expected
    kill count do we warn and drop rows whose killer colour is not the featured player's."""
    if expected is None or len(tracks) <= expected:
        return tracks, False
    print(f"WARNING too many kills detected: {len(tracks)} found, {expected} expected. Running killer helper.")
    kept = [t for t in tracks if t.get("killer_ok")]
    return kept, True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("out")
    ap.add_argument("--victims", default="")
    ap.add_argument("--killer", default="heavygod")
    ap.add_argument("--expected", default="")
    ap.add_argument("--expected-count", type=int, default=None)
    args = ap.parse_args()

    victims = [v.strip() for v in args.victims.split(",") if v.strip()]
    tracks, fired = apply_helper(run(args.source), args.expected_count)
    kills = build_kills(tracks, victims, args.killer)
    result = {"source": args.source, "fps": FPS, "onset_rule": "first fully visible frame minus 3",
              "count": len(kills), "helper_fired": fired, "kills": kills}

    if args.expected:
        checks = []
        for item in args.expected.split(","):
            name, sec = item.rsplit(":", 1)
            hit = next((k for k in kills if k["victim"] == name.strip()), None)
            got = hit["onset_s"] if hit else None
            checks.append({"victim": name.strip(), "expected_s": float(sec), "got_s": got,
                           "pass": got is not None and abs(got - float(sec)) <= 0.1})
        result["checks"] = checks
        result["pass"] = all(c["pass"] for c in checks) and len(kills) == len(checks)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if result.get("pass", True) else 1


def source_sha256(src):
    import hashlib
    h = hashlib.sha256()
    with open(src, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def onsets_for_clip(src, out_dir, killer, expected_count=None):
    """Build-facing entry point (29 Oct). One tracker run per clip. The result is cached in
    <out_dir>/<clip>_kill_timings.json, keyed by the source checksum, so a re-run on the same source is free.
    Returns the dict the build reads: {"kills": [{"seconds": ...}], "pass": bool, "flags": [...]}.
    Timing tolerance: 0.1 to 0.2 s (Jord, 29 Oct)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    sha = source_sha256(src)
    cache = out / f"{Path(src).stem}_kill_timings.json"
    if cache.exists():
        cached = json.loads(cache.read_text())
        if cached.get("source_sha256") == sha and cached.get("killer") == killer:
            return cached["onsets"]
    tracks, fired = apply_helper(run(src), expected_count)
    kills = build_kills(tracks, [], killer)
    flags = []
    if expected_count is not None and len(kills) != expected_count:
        flags.append(f"tracker found {len(kills)} kills, expected {expected_count}")
    onsets = {"pass": not flags, "flags": flags, "helper_fired": fired,
              "kills": [{"kill": k["kill"], "seconds": k["onset_s"], "victim": k["victim"],
                         "first_seen_s": k["first_seen_s"], "box_feed": k["box_feed"],
                         "crop_frame": k["crop_frame"]} for k in kills]}
    cache.write_text(json.dumps({"source": src, "source_sha256": sha, "killer": killer,
                                 "tolerance_s": [0.1, 0.2], "onsets": onsets}, indent=2))
    return onsets


if __name__ == "__main__":
    sys.exit(main())
