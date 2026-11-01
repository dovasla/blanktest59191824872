"""CS Junkie Buffer scheduling step. Builds the Buffer post for each channel from a run file.

Usage:
  python3 csj_schedule.py <clip>_run.json [--dry-run] [--due "2026-10-30 18:00"] [--tracker PATH]

What it does:
  1. Reads the run file. Refuses unless blocking_pass is true and the upload link returned 200.
  2. Reads the caption (caption_pick text, or <clip>_caption.txt next to the run file).
  3. Counts scheduled posts in the Buffer tracker. Refuses if the count is 10 or more (Buffer Free limit per channel).
  4. Sets dueAt to 18:00 UK time (GMT or BST, handled by zoneinfo), the next one in the future, unless --due is given.
  5. Builds one payload per channel (YouTube, Instagram, TikTok).

It never calls the Buffer API and never schedules anything.
  --dry-run   prints the payloads and the queue check. Writes nothing.
  (default)   writes <clip>_buffer_payload.json next to the run file. A thread then sends it with Buffer create_post.
Exit 0 when the payloads are built. Exit 1 on any refusal.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

UK = ZoneInfo("Europe/London")
QUEUE_LIMIT = 10
POST_HOUR = 18
DEFAULT_TRACKER = Path("/tmp/claude/memory/team/silo/buffer-queue-tracker.md")

# Channel IDs from the buffer-queue-tracker memory (org: My Organization).
CHANNELS = {
    "youtube": "6ad6ae89778b240e2f618d88",    # CS JUNKIE
    "instagram": "6ad6ae65778b240e2f618cc8",  # warmsummershine
    "tiktok": "67e98e9153d152b9daa069d1",     # ostrichpeek
}


def parse_release(text):
    """Release time (UTC) from a tracker bullet, e.g. '28 Oct 2026 20:00 UTC'. None if not found."""
    m = re.search(r"(\d{1,2} [A-Za-z]{3} \d{4} \d{2}:\d{2}) UTC", text)
    if not m:
        return None
    return datetime.strptime(m.group(1), "%d %b %Y %H:%M").replace(tzinfo=ZoneInfo("UTC"))


def count_scheduled(tracker_path, now_utc):
    """Return (still queued, already out) from the 'Scheduled posts' section.
    A bullet whose release time has passed counts as released. A bullet with no readable time stays queued (fail closed)."""
    lines = Path(tracker_path).read_text(encoding="utf-8").splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("**Scheduled posts")), None)
    if start is None:
        raise SystemExit("tracker has no 'Scheduled posts' section; refusing")
    queued, out = [], []
    for line in lines[start + 1:]:
        if line.startswith("**"):
            break
        if not line.startswith("- "):
            continue
        text = line[2:].strip()
        due = parse_release(text)
        if due is not None and due <= now_utc:
            out.append(text)
        else:
            queued.append(text)
    return queued, out


def next_post_time(now_utc, due_arg):
    if due_arg:
        naive = datetime.strptime(due_arg, "%Y-%m-%d %H:%M")
        return naive.replace(tzinfo=UK)
    local = now_utc.astimezone(UK)
    day = local.replace(hour=POST_HOUR, minute=0, second=0, microsecond=0)
    if day <= local:
        day += timedelta(days=1)
    return day


def read_caption(run_path, run):
    pick = run.get("caption_pick") or {}
    if pick.get("text"):
        return pick["text"].strip()
    side = run_path.parent / f"{run['clip_id']}_caption.txt"
    if side.exists():
        return side.read_text(encoding="utf-8").strip()
    return None


def build_payloads(run, caption, video_url, due):
    no_tags = re.sub(r"\s*#\w+", "", caption).strip()
    title = no_tags[:100]
    due_iso = due.isoformat()
    video = [{"video": {"url": video_url}}]
    base = {"schedulingType": "automatic", "mode": "customScheduled", "dueAt": due_iso, "assets": video}
    return {
        "youtube": {**base, "channelId": CHANNELS["youtube"], "text": caption,
                    "metadata": {"youtube": {"title": title, "categoryId": "20", "privacy": "public"}}},
        "instagram": {**base, "channelId": CHANNELS["instagram"], "text": caption,
                      "metadata": {"instagram": {"type": "reel", "shouldShareToFeed": True}}},
        "tiktok": {**base, "channelId": CHANNELS["tiktok"], "text": caption,
                   "metadata": {"tiktok": {"title": title}}},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_file")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--due", help='UK time, "YYYY-MM-DD HH:MM". Default: next 18:00 UK.')
    ap.add_argument("--tracker", default=str(DEFAULT_TRACKER))
    args = ap.parse_args()

    run_path = Path(args.run_file)
    run = json.loads(run_path.read_text(encoding="utf-8"))
    fail = []

    if not run.get("blocking_pass"):
        fail.append("run file: blocking_pass is not true")
    upload = run.get("upload") or {}
    if not (upload.get("url_ok") and upload.get("url")):
        fail.append("run file: no upload link that returned 200")
    caption = read_caption(run_path, run)
    if not caption:
        fail.append("no caption found (caption_pick or <clip>_caption.txt)")

    now = datetime.now(UK)
    posts, out_posts = count_scheduled(args.tracker, now.astimezone(ZoneInfo("UTC")))
    if len(posts) >= QUEUE_LIMIT:
        fail.append(f"queue full: {len(posts)} of {QUEUE_LIMIT} scheduled posts per channel")
    due = next_post_time(now, args.due)
    if due <= now:
        fail.append(f"dueAt {due.isoformat()} is not in the future")

    print(f"clip: {run.get('clip_id')}  title: {run.get('title')}")
    print(f"queue: {len(posts)} still scheduled of {QUEUE_LIMIT} per channel, {QUEUE_LIMIT - len(posts)} free")
    for t in out_posts:
        print("already out (counted as released): " + t[:70])
    if run.get("labels"):
        print("labels (kept on the post, not blocking): " + "; ".join(run["labels"]))
    if fail:
        for f in fail:
            print("REFUSED: " + f)
        return 1

    payloads = build_payloads(run, caption, upload["url"], due)
    print(f"dueAt: {due.isoformat()} (18:00 UK)")
    if args.dry_run:
        print("DRY RUN. Nothing sent or written.")
        print(json.dumps(payloads, indent=2))
        return 0

    out = run_path.parent / f"{run.get('clip_id')}_buffer_payload.json"
    out.write_text(json.dumps(payloads, indent=2), encoding="utf-8")
    print(f"payloads written: {out} (nothing sent to Buffer)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
