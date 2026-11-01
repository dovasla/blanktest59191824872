# CS Junkie build tools

Copy of the shared build tools (`csj_*.py`, `csj_*.json`, `csj_checklist.md`), kept here under version control (1 Nov 2026).

- One run: `python3 tools/csj_run.py <inputs.json> <candidates.json> <rows_dir> <out_dir>`. Add `--dry-run` to skip upload and posting.
- Run timing: `seconds_total` in `<clip>_run.json`.
- Feed cache: lives in the build folder (`<clip>_feed_cache`) and is deleted when the run ends. Nothing is reused for later clips.
- Kill onsets: 15 fps scan finds each kill, then a 60 fps second pass sets the onset (first fully visible frame minus 3).

Source of truth for the team: keep edits here and in the shared copy in sync until the shared copy is retired.
