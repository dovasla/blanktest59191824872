# CS Junkie clip checklist (one page, csj-process v4)

Run this in order for every clip. The checker does the same steps:

    python3 tools/csj_checker.py <clip_folder> [--export FILE] [--timings FILE] [--json OUT]

Exit 0 means every step is PASS. Anything else is not complete. Jord's sign-offs go in `<clip_id>_signoff.json`.

| # | Step | Checker | Who | Pass when |
|---|------|---------|-----|-----------|
| 0 | Preflight: ffmpeg, ffprobe, Barlow Condensed Black | Auto | Thread | Tools on PATH, Barlow installed |
| 0 | Preflight: edit path, Cloudinary secret (27 chars), Buffer and Metricool reads, session not linked to a computer | Not automated | Thread | Done once per session, noted in the thread |
| 1 | Inputs file: source 1920x1080, fps from ffprobe, kill count, player, colour, window | Auto | Thread | Keys present, source matches, window rules hold |
| 1 | Kill count is not 5 | Manual | Jord | `kill_count_approved: true` |
| 2 | Onsets: every kill clean, count matches, window = first onset - 2.0 s, last onset + 4.0 s (capped) | Auto | Thread | `pass: true`, counts match |
| 2 | Approval contact sheet (name and count) | File plus manual | Jord | Sheet exists, `kill_list_approved: true` |
| 4 | Raw rows: one per kill, row-edge gate | Auto | Thread | `csj_row_edge_gate` passes each row |
| 5 | Build: stack switches = kill count, fps and onsets match | Auto | Thread | Timings agree with inputs and onsets |
| 6 | Look-check: frames at stack changes, 20 s sheet, row count, borders, names | Manual | Jord | `look_check_ok: true` |
| 7 | Gate 1: 1080x1920, 30 or source fps, duration, AAC, bitrate, size under 100 MB | Auto | Thread | `csj_gates` probe passes |
| 7 | Gate 3: stack switches on the onset arithmetic, within 1/60 s | Auto | Thread | All switches pass |
| 7 | Gate 4: no near-black bands top or bottom | Auto | Thread | `csj_bar_gate` passes |
| 7 | Gate 2b (seam): reported only | Reported | Jord | Open item. Number shown, never blocks |
| 8 | Upload: Cloudinary mp4 URL, HEAD returns 200 | Auto | Thread | `<clip>_upload.json` with the mp4 URL at 200. Only after gates PASS. No cover (Jord, 30 Oct) |
| 9 | Caption: one line, kill count and player match, at most 2 hashtags | Auto | Thread | Caption file clean |
| 9 | Caption killer name matches the rows | Manual | Jord | `caption_name_checked: true` |
| 10 | Approval: one reply from Jord covering clip and caption | Manual | Jord | `clip_approved`, `caption_approved`, `approval_message_id`, `approval_by: "Jord"` |
| 11 | Schedule: YouTube, Instagram, TikTok scheduled or sent. Facebook manual | Auto | Thread | `<clip>_schedule.json`. Written only after step 10 PASS |
| 12 | Delivery message and project memory saved | Manual | Thread | `delivery_message_sent`, `memory_saved` |

## Rules that stop a clip

- A failed gate stops the clip. Report the numbers, then ask Jord before any re-export.
- No upload before gates pass. No schedule before approval.
- Nothing is posted or scheduled without Jord's explicit approval of the clip and caption, in the thread.
- A kill count other than 5 needs Jord's go. Above 5 is flagged for him.

## Open items the checker does not settle

- Caption hashtag limit: the checker uses 2 (Jord's 21 Oct caption note). Process Step 9 allows 4 to 5. Confirm with Jord and change `CAPTION_MAX_HASHTAGS` in `csj_checker.py`.
- Gate 2b seam: reported only until Jord decides its definition.
- Name check: replaced by the approval contact sheet (step 2).
- Preflight service checks (steps 0.3 to 0.7): run by hand.

## Kill onset measurement (border template match, 22 Oct)

Tool: `tools/csj_border_match.py`. Reads the feed crop only (1620, 40, 300, 280 source px) at source fps. No full frames.

1. Pick one reference frame per kill where its full red border is drawn. Confirm by eye on a contact sheet (one sheet per kill, about 36 frames).
2. Set the row box (x0, y0, x1, y1) on that frame and build the template from its outline pixels.
3. Score every frame in a window of about 0.6 s around the first visible frame. Score = share of template pixels still red, 1 px tolerance. Flash frames score 0.
4. Onset = first frame with score at or above 0.90 that stays there 4 frames. This is the complete-border frame. The first frame with any red is kept as a second reading, not the onset.
5. Report the onset with the frame number, the score curve, and the frame cost.

Measured on P5 (6a172a774943beb8d2cdf236.mp4, 60 fps, 22 Oct):
- Snappi: complete border frame 488, 8.133 s. First red frame 486, 8.100 s. Ref frame 489.
- sjuush: complete border frame 526, 8.767 s. First red frame 522, 8.700 s. Ref frame 530.
- Cost: 2 reference frames checked by eye, 72 crop frames scored. Zero full frames.

The fixed values in the P5 thread (Snappi 8.05 s, sjuush 8.68 s) were set by hand, not measured. They sit about 5 frames (0.08 s) before the measured complete-border onsets. The onsets file clips/p5_alex_5K/p5_onsets.json (8.27 s, 9.93 s) disagrees with both and has no recorded method.

Still to measure for P5: cairne, r1nkle, xKacpersky. For P6: all five kills.

## Kill row slide (default for every clip, Jord 22 Oct 17:04)

Build: `tools/csj_build_slide.py` (P6 build script; the slide default is in it).
- Every kill row slides in from the right edge, moving left. Length 0.2 s, ease-out cubic (x = 1080 times (1 - p) cubed).
- The slide ends on the full-register frame. The onset time is unchanged.
- The slide starts at onset minus 0.2 s. Rows stay in the stack after they land.
- Kill rows only. No cover is built (Jord, 30 Oct).
- Row PNGs are cut from the settled frame with the most red on the top and bottom border lines.

## Kill detection default (Jord, 30 Oct 2026, "set this method to default")
- Default method for every clip: read the kill-feed bars by eye, then measure with code.
  1. Scan the feed at 60 fps, including partly hidden bars.
  2. Read each bar's killer name. Keep only bars where the named player is a killer (a bar like "NAF + JT" counts).
  3. Check the kept count against Jord's total. A mismatch stops the clip and gets reported. Do not change the total.
  4. Mark each kill at the first frame where its name is fully drawn, minus 3 frames. Label ESTIMATED.
  5. Save a contact sheet of the bars at their marks, with the name box outlined.
- Reference run: NAF clip, upload 5f504b0f (30 Oct). 4 kills matched Jord's total: 4.07 s, 8.67 s, 12.28 s, 16.32 s.
- Code scripts still on the old red-border method (csj_kill_tracker.py) are not the default until they are updated.
