"""Checks the 30 fps feed scan against the source-rate scan. Synthetic clip, no build.

Run: python3 -m unittest tools/test_csj_scan_rate.py -v
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import csj_feedcache as F  # noqa: E402


class ScanRateTests(unittest.TestCase):
    def test_30fps_scan_matches_every_other_source_frame(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "synthetic_60fps.mp4"
            # 4 s of changing colour at 60 fps, 1920x1080, so the red count moves frame to frame.
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                            "testsrc2=size=1920x1080:rate=60:duration=4", "-pix_fmt", "yuv420p", str(src)],
                           check=True)
            full = F.red_counts(str(src))
            scan = F.scan_red_counts(str(src), 30)
            self.assertEqual(len(full), 240)
            self.assertEqual(len(scan), 120)
            # 30 fps frame i is source frame 2i, so every third 30 fps frame is source frame 6j (10 fps).
            np.testing.assert_array_equal(scan[::3], full[::6])
            np.testing.assert_array_equal(scan, full[::2])


if __name__ == "__main__":
    unittest.main()
