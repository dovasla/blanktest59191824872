"""Small file cache for build steps (30 Oct, Jord: reduce build time and usage).

A step's output is reused only when its key matches exactly. The key holds the checksums of the input
files and the settings that change the output. Cache folder: CSJ_CACHE_DIR or /home/user/.csj_cache.
"""
import hashlib
import json
import os
import shutil
from pathlib import Path

CACHE = Path(os.environ.get("CSJ_CACHE_DIR", "/home/user/.csj_cache"))


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def key_of(parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:32]


def get(step, key, files, dest_dir):
    """Copy cached files into dest_dir. Returns True on a hit."""
    d = CACHE / step / key
    if not (d / "_done").exists():
        return False
    for name in files:
        src = d / name
        if not src.exists():
            return False
        shutil.copy(src, Path(dest_dir) / name)
    return True


def put(step, key, files, src_dir):
    d = CACHE / step / key
    d.mkdir(parents=True, exist_ok=True)
    for name in files:
        shutil.copy(Path(src_dir) / name, d / name)
    (d / "_done").write_text("ok")
