"""Free-space guard for batches.

Reads free space on a path and stops a batch when it is below a set limit.
It only reads disk stats. It never deletes or moves anything.
"""

import argparse
import shutil
import sys

DEFAULT_PATH = "/mnt/project-files"
DEFAULT_MIN_FREE_GB = 5.0
GIB = 1024 ** 3


class BatchStopped(Exception):
    """Raised when free space is below the limit."""


def free_bytes(path):
    """Return free bytes on the filesystem that holds path."""
    return shutil.disk_usage(path).free


def check_free_space(path=DEFAULT_PATH, min_free_gb=DEFAULT_MIN_FREE_GB, usage=None):
    """Return (ok, free_gb). ok is False when free space is below min_free_gb."""
    usage = usage or free_bytes
    free_gb = usage(path) / GIB
    return free_gb >= min_free_gb, free_gb


def guard_batch(path=DEFAULT_PATH, min_free_gb=DEFAULT_MIN_FREE_GB, usage=None):
    """Raise BatchStopped when free space is below the limit. Otherwise return free GB."""
    ok, free_gb = check_free_space(path, min_free_gb, usage)
    if not ok:
        raise BatchStopped(
            f"Batch stopped: {free_gb:.2f} GB free on {path}, limit is {min_free_gb:.2f} GB."
        )
    return free_gb


def main(argv=None):
    parser = argparse.ArgumentParser(description="Stop a batch when free space is low.")
    parser.add_argument("--path", default=DEFAULT_PATH)
    parser.add_argument("--min-free-gb", type=float, default=DEFAULT_MIN_FREE_GB)
    args = parser.parse_args(argv)
    try:
        free_gb = guard_batch(args.path, args.min_free_gb)
    except BatchStopped as exc:
        print(exc, file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Batch stopped: cannot read free space on {args.path}: {exc}", file=sys.stderr)
        return 2
    print(f"OK: {free_gb:.2f} GB free on {args.path}, limit {args.min_free_gb:.2f} GB.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
