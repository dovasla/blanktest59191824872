"""CS Junkie player filter (21 Oct). Finds a player's kill rows in the feed by matching the killer name.

Usage:
  python3 csj_players.py template <source> <t_seconds> <x0> <y0> <x1> <y1> <out.npy>
      Cut the player's killer-name template from one legible row (blue text mask, source pixels). Once per player.
  python3 csj_players.py scan <source> <template.npy> <out.json> [--fps 10] [--thr 0.6]
      Scan the whole clip at --fps and count the player's rows as they appear. Writes kill starts.

Blue text mask: the killer name of the featured player is blue in the feed (team colour, memory: 'blue' for alex).
Matching is an overlap score on the binary mask, 2*|T and P| / (|T| + |P|), over all positions in the feed crop.
"""
import json
import subprocess
import sys

import numpy as np

FEED = (1620, 40, 300, 280)  # x, y, w, h, source pixels (feed crop)
# Killer names sit on the right of the feed box. Search only that part of the crop (feed crop coordinates).
CROP_X0, CROP_X1, CROP_Y0, CROP_Y1 = 60, 300, 10, 130


def blue_mask(frames):
    r, g, b = frames[..., 0], frames[..., 1], frames[..., 2]
    return (b > 140) & (b - r > 60) & (b - g > 30)


def decode(source, fps, t0=None, dur=None):
    x, y, w, h = FEED
    cmd = ["ffmpeg", "-v", "error"]
    if t0 is not None:
        cmd += ["-ss", f"{t0:.3f}"]
    cmd += ["-i", source]
    if dur is not None:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-vf", f"fps={fps},crop={w}:{h}:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)


def make_template(source, t, box, out):
    x0, y0, x1, y1 = box  # feed crop coordinates
    fr = decode(source, 60, t0=t, dur=1 / 60)[0]
    m = blue_mask(fr.astype(np.int16))[y0:y1, x0:x1]
    np.save(out, m.astype(np.float32))
    return {"template": out, "shape": list(m.shape), "px": int(m.sum())}


def score_map(mask, tpl):
    """Overlap score 2|T and P| / (|T| + |P|) at every offset, by FFT correlation (fast on the whole feed crop).
    The window sums come from an integral image."""
    H, W = mask.shape
    th, tw = tpl.shape
    P = mask.astype(np.float64)
    fh, fw = H + th, W + tw
    inter = np.fft.irfft2(np.fft.rfft2(P, (fh, fw)) * np.conj(np.fft.rfft2(tpl.astype(np.float64), (fh, fw))), (fh, fw))
    inter = inter[:H - th + 1, :W - tw + 1]
    ii = np.pad(P, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    win = ii[th:, tw:] - ii[:-th, tw:] - ii[th:, :-tw] + ii[:-th, :-tw]
    win = win[:H - th + 1, :W - tw + 1]
    return 2 * inter / np.maximum(tpl.sum() + win, 1e-6)


def peaks(score, thr, nms=14):
    """Local maxima at or above thr, at least nms px apart (feed rows are about 30 px apart)."""
    out = []
    H, W = score.shape
    cand = np.argwhere(score >= thr)
    order = sorted(cand.tolist(), key=lambda p: -score[p[0], p[1]])
    for y, x in order:
        if all(abs(y - py) >= nms or abs(x - px) >= 60 for py, px, _ in out):
            out.append((y, x, float(score[y, x])))
    return out


def scan(source, tpl_path, fps=10, thr=0.8, hold=3, track_thr=0.55, gap=5):
    """Track each row of the player's name through the clip (21 Oct).
    A row is a track: a peak >= track_thr assigned to the nearest existing track (<= 40 px down, <= 60 px across),
    so a row that slides within the stack keeps its identity. A track closes after `gap` frames unseen.
    A kill is a track that reaches the confirm score `thr` and lasts at least `hold` frames.
    The kill time is the track's first frame."""
    tpls = [np.load(q) for q in tpl_path.split(",")]  # one template per name layout ("alex" alone, "alex + x")
    frames = decode(source, fps)
    tracks = []  # dicts: y, x, first, last, peak, n
    done = []
    for i, fr in enumerate(frames):
        m = blue_mask(fr.astype(np.int16))[CROP_Y0:CROP_Y1, CROP_X0:CROP_X1]
        pk = []
        for t in tpls:  # templates can differ in height; merge their peaks instead of their maps
            for y, x, v in peaks(score_map(m, t), track_thr):
                same = [j for j, (py, px, pv) in enumerate(pk) if abs(py - y) < 14 and abs(px - x) < 60]
                if not same:
                    pk.append((y, x, v))
                elif v > pk[same[0]][2]:
                    pk[same[0]] = (y, x, v)
        free = list(pk)
        for tr in tracks:
            best, bd = None, None
            for pki in free:
                y, x, v = pki
                d = abs(y + CROP_Y0 - tr["y"]) + abs(x + CROP_X0 - tr["x"])
                if abs(y + CROP_Y0 - tr["y"]) <= 40 and abs(x + CROP_X0 - tr["x"]) <= 60 and (bd is None or d < bd):
                    best, bd = pki, d
            if best is not None:
                y, x, v = best
                free.remove(best)
                tr.update(y=y + CROP_Y0, x=x + CROP_X0, last=i, peak=max(tr["peak"], v), n=tr["n"] + 1)
        for y, x, v in free:
            tracks.append({"y": y + CROP_Y0, "x": x + CROP_X0, "first": i, "last": i, "peak": v, "n": 1})
        still = []
        for tr in tracks:
            (done.append(tr) if i - tr["last"] > gap else still.append(tr))
        tracks = still
    done += tracks
    kills = []
    for tr in sorted(done, key=lambda t: t["first"]):
        if tr["peak"] >= thr and tr["n"] >= hold:
            t = round(tr["first"] / fps, 2)
            if not kills or t - kills[-1] > 0.3:
                kills.append(t)
    return {"fps": fps, "thr": thr, "hold": hold, "track_thr": track_thr, "frames": len(frames),
            "tracks": [{"first_s": round(t["first"] / fps, 2), "last_s": round(t["last"] / fps, 2), "peak": round(t["peak"], 2), "n": t["n"], "y": t["y"], "x": t["x"]} for t in sorted(done, key=lambda t: t["first"])],
            "kill_starts": kills}


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "template":
        src, t, x0, y0, x1, y1, out = sys.argv[2:9]
        print(json.dumps(make_template(src, float(t), [int(x0), int(y0), int(x1), int(y1)], out)))
    elif cmd == "scan":
        src, tpl, out = sys.argv[2:5]
        fps = float(sys.argv[sys.argv.index("--fps") + 1]) if "--fps" in sys.argv else 10
        thr = float(sys.argv[sys.argv.index("--thr") + 1]) if "--thr" in sys.argv else 0.8
        res = scan(src, tpl, fps, thr)
        json.dump(res, open(out, "w"), indent=1)
        print(json.dumps({"kill_starts": res["kill_starts"], "tracks": res["tracks"]}, indent=1))
