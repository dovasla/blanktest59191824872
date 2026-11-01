"""CS Junkie asset registry (29 Oct 2026). Uploads a banner or character image to Cloudinary and records it,
so a new one can be checked against what already exists before a new prompt is made.

Usage:
  python3 csj_asset_upload.py <file.png> <banner|character> <label>     upload and record
  python3 csj_asset_upload.py --find <sha256-or-label-part>            look up records
  python3 csj_asset_upload.py --list                                  list all records

Registry: /mnt/project-files/research/asset_registry.json (one record per upload).
A file whose sha256 is already in the registry is NOT uploaded again. The existing record is returned.
Credentials come from CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET. Values are never printed.
"""
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

REGISTRY = Path("/mnt/project-files/research/asset_registry.json")
KINDS = ("banner", "character")


def load():
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text())
    return {"records": []}


def save(reg):
    REGISTRY.write_text(json.dumps(reg, indent=2))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def creds_ready():
    return all(os.environ.get(k) for k in ("CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"))


def upload(path, kind, label, resource="image"):
    cloud = os.environ["CLOUDINARY_CLOUD_NAME"]
    key = os.environ["CLOUDINARY_API_KEY"]
    secret = os.environ["CLOUDINARY_API_SECRET"]
    public_id = f"csj/{kind}/{Path(path).stem}"
    ts = str(int(time.time()))
    params = {"public_id": public_id, "timestamp": ts}
    to_sign = "&".join(f"{k}={params[k]}" for k in sorted(params)) + secret
    signature = hashlib.sha1(to_sign.encode()).hexdigest()
    with open(path, "rb") as f:
        r = requests.post(f"https://api.cloudinary.com/v1_1/{cloud}/{resource}/upload",
                          data={**params, "api_key": key, "signature": signature},
                          files={"file": f}, timeout=120)
    r.raise_for_status()
    body = r.json()
    return body["secure_url"], body.get("public_id", public_id)


def upload_clip(path, clip_id):
    """Item 4 (29 Oct): the final MP4 goes to Cloudinary from csj_run. Returns the link and whether it answers 200.
    Only called after the blocking gates pass. Without credentials it returns a reason and uploads nothing."""
    if not creds_ready():
        return {"uploaded": False, "reason": "Cloudinary credentials not set in this session"}
    cloud = os.environ["CLOUDINARY_CLOUD_NAME"]
    key = os.environ["CLOUDINARY_API_KEY"]
    secret = os.environ["CLOUDINARY_API_SECRET"]
    public_id = f"csj/clips/{clip_id}_{sha256(path)[:8]}"
    ts = str(int(time.time()))
    params = {"public_id": public_id, "timestamp": ts}
    to_sign = "&".join(f"{k}={params[k]}" for k in sorted(params)) + secret
    signature = hashlib.sha1(to_sign.encode()).hexdigest()
    with open(path, "rb") as f:
        r = requests.post(f"https://api.cloudinary.com/v1_1/{cloud}/video/upload",
                          data={**params, "api_key": key, "signature": signature},
                          files={"file": f}, timeout=600)
    if r.status_code != 200:
        return {"uploaded": False, "reason": f"upload returned {r.status_code}"}
    url = r.json()["secure_url"]
    check = requests.get(url, timeout=60, stream=True)
    status = check.status_code
    check.close()
    return {"uploaded": True, "url": url, "public_id": public_id, "url_status": status, "url_ok": status == 200}


def add(path, kind, label):
    if kind not in KINDS:
        raise SystemExit(f"kind must be one of {KINDS}")
    digest = sha256(path)
    reg = load()
    for rec in reg["records"]:
        if rec["sha256"] == digest:
            return {"uploaded": False, "reason": "same file already in the registry", "record": rec}
    url, public_id = upload(path, kind, label)
    rec = {"kind": kind, "label": label, "file": Path(path).name, "sha256": digest, "url": url,
           "public_id": public_id, "added": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    reg["records"].append(rec)
    save(reg)
    return {"uploaded": True, "record": rec}


def find(term):
    term = term.lower()
    return [r for r in load()["records"] if term in r["sha256"] or term in r["label"].lower()
            or term in r["file"].lower()]


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    if args[0] == "--list":
        print(json.dumps(load()["records"], indent=2))
    elif args[0] == "--find":
        print(json.dumps(find(args[1]), indent=2))
    else:
        print(json.dumps(add(args[0], args[1], args[2]), indent=2))
