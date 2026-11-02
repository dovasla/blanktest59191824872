import os
import tempfile
import unittest
from unittest import mock

import storage_guard as sg

GIB = 1024 ** 3


def fake_usage(free_gb):
    return lambda path: int(free_gb * GIB)


class StorageGuardTests(unittest.TestCase):
    def test_above_limit_passes(self):
        ok, free_gb = sg.check_free_space("/x", 5, fake_usage(10))
        self.assertTrue(ok)
        self.assertAlmostEqual(free_gb, 10)

    def test_below_limit_fails(self):
        ok, _ = sg.check_free_space("/x", 5, fake_usage(4.5))
        self.assertFalse(ok)

    def test_exactly_at_limit_passes(self):
        ok, _ = sg.check_free_space("/x", 5, fake_usage(5))
        self.assertTrue(ok)

    def test_guard_raises_when_low(self):
        with self.assertRaises(sg.BatchStopped) as cm:
            sg.guard_batch("/x", 5, fake_usage(1))
        self.assertIn("Batch stopped", str(cm.exception))

    def test_guard_returns_free_gb_when_ok(self):
        self.assertAlmostEqual(sg.guard_batch("/x", 5, fake_usage(8)), 8)

    def test_guard_never_deletes(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "keep.txt")
            with open(f, "w") as fh:
                fh.write("data")
            with mock.patch.object(os, "remove", side_effect=AssertionError("delete called")), \
                    mock.patch.object(os, "unlink", side_effect=AssertionError("delete called")):
                with self.assertRaises(sg.BatchStopped):
                    sg.guard_batch(d, 5, fake_usage(0))
            self.assertTrue(os.path.exists(f))

    def test_real_disk_read_works(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertGreaterEqual(sg.free_bytes(d), 0)
            self.assertGreater(sg.guard_batch(d, 0), -1)

    def test_cli_returns_2_when_low(self):
        with mock.patch.object(sg, "free_bytes", return_value=GIB):
            self.assertEqual(sg.main(["--path", "/x", "--min-free-gb", "5"]), 2)

    def test_cli_returns_0_when_ok(self):
        with mock.patch.object(sg, "free_bytes", return_value=20 * GIB):
            self.assertEqual(sg.main(["--path", "/x", "--min-free-gb", "5"]), 0)

    def test_cli_returns_2_on_os_error(self):
        with mock.patch.object(sg, "free_bytes", side_effect=OSError("gone")):
            self.assertEqual(sg.main(["--path", "/nope"]), 2)


if __name__ == "__main__":
    unittest.main()
