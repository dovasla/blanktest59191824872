"""Locked kill onset for CS Junkie clips.

Rule (locked): onset = first fully drawn kill-row frame at 60 fps, minus 3 frames.
Pure logic. No file reads, no video, no network.

Input: a timing record (dict) with ONE of:
  "first_full_frame": int, 60 fps frame index of the first fully drawn row
  "first_full_s":     float, seconds of that same frame (the naf timing JSON
                      calls this "A_full_s")

Output: onset in seconds (float, 4 decimals), e.g. 4.1667 -> 4.1167.
"""

FPS = 60          # locked onset is always counted at 60 fps
OFFSET_FRAMES = 3  # locked: minus 3 frames


def locked_onset(record):
    """Return the locked onset in seconds for one kill's timing record."""
    if "first_full_frame" in record:
        frame = int(record["first_full_frame"])
    elif "first_full_s" in record or "A_full_s" in record:
        seconds = float(record.get("first_full_s", record.get("A_full_s")))
        frame = round(seconds * FPS)
    else:
        raise ValueError("timing record needs first_full_frame or first_full_s")

    onset_frame = frame - OFFSET_FRAMES
    if onset_frame < 0:
        raise ValueError(f"onset would be before clip start (frame {onset_frame})")
    return round(onset_frame / FPS, 4)
