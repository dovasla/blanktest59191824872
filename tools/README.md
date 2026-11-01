# CS Junkie build tools

Run one clip, every stage, with a timing log:

    python3 tools/csj_run_timed.py <inputs.json> <candidates.json> <rows_dir> <out_dir> [--dry-run]

Writes into `<out_dir>`: the run file `<clip_id>_run.json`, and `<clip_id>_timing_log.json` with total time and per-stage time for that build.

`--dry-run` runs every check and the build but never uploads, posts or schedules.

Tests (no build, no upload):

    python3 -m unittest tools/test_csj_run_timed.py -v

Notes:
- The tools are copied from the project files folder (`tools/` there). Archive, backup, cache and media files are not copied.
- `csj_run.py` is the same run without the timing log. Its stages and encode preset are unchanged.
- Kill timings are per clip only. Nothing from one clip's timings is reused for another.
- Some tools still write to `/mnt/project-files/` (run log, asset registry, kill-timing flags). They need that mount.
