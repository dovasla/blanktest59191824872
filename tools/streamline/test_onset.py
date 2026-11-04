"""Tests for onset.py using the naf Inferno numbers (build_log/naf_timing_2nov/naf_inferno_6ace_timing.json).

Run: python3 -I test_onset.py   (from this folder, or with the folder on sys.path)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from onset import locked_onset  # noqa: E402

# (A_full_s, expected onset_s from the record)
NAF_INFERNO = [
    (4.1667, 4.1167),   # kill 1
    (8.1667, 8.1167),   # kill 2
    (12.8333, 12.7833),  # kill 3
    (16.15, 16.1),      # kill 4
]


def test_naf_inferno_seconds():
    for a_full, expected in NAF_INFERNO:
        got = locked_onset({"A_full_s": a_full})
        assert abs(got - expected) < 0.0001, (a_full, got, expected)


def test_naf_inferno_frames():
    # 4.1667 s is frame 250 at 60 fps; minus 3 = 247 = 4.1167 s
    assert locked_onset({"first_full_frame": 250}) == 4.1167
    assert locked_onset({"first_full_frame": 490}) == 8.1167  # 8.1667 s = frame 490
    assert locked_onset({"first_full_s": 16.15}) == 16.1


def test_rejects_missing_keys():
    try:
        locked_onset({"kill": 1})
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_rejects_before_clip_start():
    try:
        locked_onset({"first_full_frame": 2})
    except ValueError:
        return
    raise AssertionError("expected ValueError")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("ALL PASS")
