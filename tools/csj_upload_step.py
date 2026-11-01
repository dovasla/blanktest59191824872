"""CS Junkie upload step (29 Oct 2026). One function a run script can call: upload a finished NOT FINAL MP4 to
Cloudinary, then check that the link answers 200.

Use from a run script:
  from csj_upload_step import upload_step
  result = upload_step("/path/to/clip.mp4", "68790a62")

Returns a dict with "uploaded". When uploaded, it also has "url", "public_id", "url_status" and "url_ok".
If the file is missing, the credentials are not set, or the upload fails, it returns "uploaded": False and a reason.
It does not raise for those cases.

Credentials come from CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET. Values are never printed.
The Google service-account key is never used here.
"""
import hashlib
import os
import time
from pathlib import Path

import requests

CRED_KEYS = ("CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sign(params, secret):
    to_sign = "&".join(f"{k}={params[k]}" for k in sorted(params)) + secret
    return hashlib.sha1(to_sign.encode()).hexdigest()


def check_url(url):
    """Returns (status, ok). A network error counts as not ok."""
    try:
        r = requests.get(url, timeout=60, stream=True)
        status = r.status_code
        r.close()
    except requests.RequestException:
        return None, False
    return status, status == 200


def upload_step(path, clip_id):
    path = Path(path)
    if not path.is_file():
        return {"uploaded": False, "reason": f"file not found: {path.name}"}
    if path.suffix.lower() != ".mp4":
        return {"uploaded": False, "reason": "file is not an MP4"}
    missing = [k for k in CRED_KEYS if not os.environ.get(k)]
    if missing:
        return {"uploaded": False, "reason": "Cloudinary credentials not set in this session"}

    cloud = os.environ["CLOUDINARY_CLOUD_NAME"]
    key = os.environ["CLOUDINARY_API_KEY"]
    secret = os.environ["CLOUDINARY_API_SECRET"]
    public_id = f"csj/clips/{clip_id}_{sha256(path)[:8]}"
    params = {"public_id": public_id, "timestamp": str(int(time.time()))}
    try:
        with open(path, "rb") as f:
            r = requests.post(f"https://api.cloudinary.com/v1_1/{cloud}/video/upload",
                              data={**params, "api_key": key, "signature": sign(params, secret)},
                              files={"file": f}, timeout=600)
    except requests.RequestException as e:
        return {"uploaded": False, "reason": f"upload failed: {type(e).__name__}"}
    if r.status_code != 200:
        return {"uploaded": False, "reason": f"upload returned {r.status_code}"}

    url = r.json()["secure_url"]
    status, ok = check_url(url)
    return {"uploaded": True, "url": url, "public_id": public_id, "url_status": status, "url_ok": ok}
