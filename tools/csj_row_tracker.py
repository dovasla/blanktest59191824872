"""CS Junkie row tracker (30 Oct 2026). Dry run only: reads one clip, writes JSON. Never uploads or posts.

Usage: python3 csj_row_tracker.py <source.mp4> <out.json> <killer_name> [--cache-dir DIR]

1. Decodes the widened scan area (x 1540, y 40, 380 x 280) once at 30 fps. Saves per-frame red-border boxes
   to <cache-dir>/<sha256 of source>.json. Later runs read that cache only.
2. Tracks each red-bordered row as one object: new object when a border appears, followed by overlap, up to
   40 px of shift per frame, kept alive for 3 missed frames.
3. Reads killer and victim text from the object's first fully-in frame and 3 more frames, keeps the best match.
4. A kill counts when the killer text matches the killer name and the victim text is new.
5. Onset = first frame the object appears, minus 3 frames (30 fps frames, so 0.1 s).
"""
import argparse, difflib, hashlib, json, subprocess
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps

X, Y, W, H = 1540, 40, 380, 280
FPS = 30
MIN_BORDER = 60  # narrow feed rows (test clip 5f504b0f) have shorter borders; standard rows are 120+ px
SHIFT = 40
MISS_MAX = 3


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def decode(src):
    cmd = ['ffmpeg', '-v', 'error', '-i', src, '-vf', f'fps={FPS},crop={W}:{H}:{X}:{Y}',
           '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    out = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.uint8).reshape(-1, H, W, 3)


def boxes_of(frame):
    r, g, b = frame[..., 0].astype(int), frame[..., 1].astype(int), frame[..., 2].astype(int)
    m = (r > 150) & (g < 90) & (b < 90)
    lines = [y for y in range(H) if m[y].sum() >= MIN_BORDER]
    out = []
    for k, y in enumerate(lines):
        if k and lines[k - 1] == y - 1:
            continue
        xs = np.where(m[y])[0]
        out.append({'top': int(y), 'left': int(xs.min()), 'right': int(xs.max())})
    return out


def build_cache(src, cache_dir):
    digest = sha256(src)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f'{digest}_rows_{FPS}fps_mb{MIN_BORDER}.json'
    if path.exists():
        return json.loads(path.read_text()), path, digest
    frames = decode(src)
    per_frame = [boxes_of(f) for f in frames]
    path.write_text(json.dumps({'source_sha256': digest, 'fps': FPS, 'frames': per_frame}))
    return {'source_sha256': digest, 'fps': FPS, 'frames': per_frame}, path, digest


def track(per_frame):
    objs = []
    done = []
    for i, boxes in enumerate(per_frame):
        used = set()
        for o in objs:
            best = None
            for j, b in enumerate(boxes):
                if j in used:
                    continue
                if abs(b['top'] - o['top']) <= SHIFT and abs(b['right'] - o['right']) <= 2 or (o.get('sliding') and abs(b['top'] - o['top']) <= SHIFT and abs(b['right'] - o['right']) <= 300):
                    d = abs(b['top'] - o['top'])
                    if best is None or d < best[0]:
                        best = (d, j)
            if best is not None:
                j = best[1]
                used.add(j)
                o['top'] = boxes[j]['top']
                o['right'] = boxes[j]['right']
                o['last'] = i
                o['frames'].append(i)
                o['miss'] = 0
            else:
                o['miss'] += 1
        for j, b in enumerate(boxes):
            if j not in used:
                objs.append({'top': b['top'], 'right': b['right'], 'first': i, 'last': i,
                             'frames': [i], 'miss': 0})
        still = []
        for o in objs:
            if o['miss'] > MISS_MAX:
                done.append(o)
            else:
                still.append(o)
        objs = still
    return done + objs


def read_text(frames_rgb, i, top, left, right, part):
    """Read one name from a row. Crops sit inside the row's own red border, binarised and upscaled."""
    row = Image.fromarray(frames_rgb[i].astype(np.uint8)).convert('L')
    if part == 'killer':
        x0, x1 = left + 4, min(left + 80, right)
    else:
        x0, x1 = max(left, right - 120), right
    c = row.crop((x0, top + 2, x1, top + 28))
    c = c.resize((c.width * 4, c.height * 4), Image.LANCZOS)
    bw = c.point(lambda p: 255 if p > 140 else 0)
    bw = ImageOps.invert(bw)
    bw = ImageOps.expand(bw, border=20, fill=255)
    tmp = '/tmp/claude-0/csj_row_ocr.png'
    Path(tmp).parent.mkdir(parents=True, exist_ok=True)
    bw.save(tmp)
    res = subprocess.run(['tesseract', tmp, '-', '--psm', '7'], capture_output=True, text=True).stdout
    return res.strip().lower().replace(' ', '')


def row_edges(frame_rgb, top):
    r, g, b = frame_rgb[top, :, 0].astype(int), frame_rgb[top, :, 1].astype(int), frame_rgb[top, :, 2].astype(int)
    xs = np.where((r > 150) & (g < 90) & (b < 90))[0]
    return (int(xs.min()), int(xs.max())) if len(xs) else (0, 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('source')
    ap.add_argument('out')
    ap.add_argument('killer')
    ap.add_argument('--cache-dir', default='/mnt/project-files/tools/cache')
    a = ap.parse_args()
    cache, cache_path, digest = build_cache(a.source, Path(a.cache_dir))
    per_frame = cache['frames']
    rows = sorted(track(per_frame), key=lambda o: o['first'])
    frames_rgb = decode(a.source)
    kills = []
    seen = []
    for o in rows:
        if len(o['frames']) < 6:
            continue
        full = o['frames'][min(6, len(o['frames']) - 1)]
        sample = [o['frames'][min(k, len(o['frames']) - 1)] for k in (6, 9, 12)]
        best_k, best_v = '', ''
        for fi in sample:
            b = per_frame[fi]
            cand = [x for x in b if abs(x['top'] - o['top']) <= SHIFT]
            if not cand:
                continue
            x = cand[0]
            k = read_text(frames_rgb, fi, x['top'], x['left'] if 'left' in x else x['right'] - 300, x['right'], 'killer')
            v = read_text(frames_rgb, fi, x['top'], x['right'] - 300, x['right'], 'victim')
            if difflib.SequenceMatcher(None, k, a.killer.lower()).ratio() > difflib.SequenceMatcher(None, best_k, a.killer.lower()).ratio():
                best_k = k
            if len(v) > len(best_v):
                best_v = v
        if a.killer != '*' and difflib.SequenceMatcher(None, best_k, a.killer.lower()).ratio() < 0.7:
            continue
        if len(best_k) < 3 or len(best_v) < 3:
            continue
        if any(difflib.SequenceMatcher(None, best_v, pv).ratio() >= 0.5 for pv in seen):
            continue
        seen.append(best_v)
        onset = max(0, o['first'] - 3)
        kills.append({'killer': best_k, 'victim': best_v, 'first_frame': o['first'],
                      'onset_frame': onset, 'onset_s': round(onset / FPS, 3),
                      'fully_in_frame': full})
    Path(a.out).write_text(json.dumps({'source_sha256': digest, 'cache': str(cache_path), 'count': len(kills),
                                       'kills': kills}, indent=1))
    print('count', len(kills))
    for k in kills:
        print(k['onset_s'], k['killer'], '->', k['victim'])


if __name__ == '__main__':
    main()
