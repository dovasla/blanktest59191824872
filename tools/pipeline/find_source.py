"""Find a clip's source video from its clip id prefix or full id.

Searches the project folder and its uploads folder (not recursive, so build
outputs in subfolders are never matched). A query matches a file when the
file's name, without its extension, starts with the query. Zero matches and
more than one match both raise SourceLookupError.

Command line:
    python3 -m tools.pipeline.find_source 6a7
"""

import os
import re
import sys

DEFAULT_ROOTS = (
    "/mnt/project-files",
    "/mnt/project-files/uploads/hearth",
)

VIDEO_EXTENSIONS = (".mp4", ".mov", ".webm")
MIN_QUERY_LENGTH = 3
_HEX_RE = re.compile(r"^[0-9a-f]+$")


class SourceLookupError(Exception):
    """Raised when a query is invalid, matches no file, or matches several."""


def _is_source_candidate(name):
    stem, ext = os.path.splitext(name)
    if ext == "":
        # Upload files are stored by id with no extension.
        return bool(stem)
    return ext.lower() in VIDEO_EXTENSIONS


def _stem(name):
    return os.path.splitext(name)[0]


def find_source(query, roots=DEFAULT_ROOTS):
    """Return the one source file path that matches the clip id query.

    Raises SourceLookupError if the query is malformed, no file matches,
    or more than one file matches.
    """
    if not isinstance(query, str):
        raise SourceLookupError("clip id must be text")
    clean = query.strip().lower()
    if len(clean) < MIN_QUERY_LENGTH:
        raise SourceLookupError(
            f"clip id {query!r} is too short; use at least {MIN_QUERY_LENGTH} characters"
        )
    if not _HEX_RE.match(clean):
        raise SourceLookupError(f"clip id {query!r} must use only hex characters (0-9, a-f)")

    matches = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            full = os.path.join(root, name)
            if not os.path.isfile(full) or not _is_source_candidate(name):
                continue
            if _stem(name).lower().startswith(clean):
                matches.append(full)

    if not matches:
        raise SourceLookupError(f"no source file found for clip id {query!r} in {list(roots)}")
    if len(matches) > 1:
        listed = "\n  ".join(matches)
        raise SourceLookupError(
            f"{len(matches)} source files match clip id {query!r}; use a longer id:\n  {listed}"
        )
    return matches[0]


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python3 -m tools.pipeline.find_source <clip_id>", file=sys.stderr)
        return 2
    try:
        print(find_source(args[0]))
    except SourceLookupError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
