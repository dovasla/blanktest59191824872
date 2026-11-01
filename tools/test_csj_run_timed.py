"""Tests for the timing wrapper. No build, no upload: fake modules only.

Run: python3 -m unittest tools/test_csj_run_timed.py -v
"""
import json
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import csj_run_timed as T  # noqa: E402


def fake_module(name, funcs):
    mod = types.ModuleType(name)
    for fname, fn in funcs.items():
        fn.__module__ = name
        setattr(mod, fname, fn)
    return mod


class StageTimerTests(unittest.TestCase):
    def test_nested_calls_counted_once(self):
        timer = T.StageTimer()

        def inner():
            time.sleep(0.02)

        def outer():
            inner()
            time.sleep(0.02)

        mod = fake_module("fake_nested", {"outer": outer, "inner": inner})
        timer.wrap_modules([mod])
        mod.outer()
        self.assertEqual(set(timer.stages), {"fake_nested.outer"})
        self.assertEqual(timer.stages["fake_nested.outer"]["calls"], 1)
        self.assertGreaterEqual(timer.stages["fake_nested.outer"]["total_seconds"], 0.035)

    def test_repeated_calls_aggregate(self):
        timer = T.StageTimer()

        def step():
            return 1

        mod = fake_module("fake_loop", {"step": step})
        timer.wrap_modules([mod])
        for _ in range(5):
            mod.step()
        self.assertEqual(timer.stages["fake_loop.step"]["calls"], 5)

    def test_failed_call_recorded_and_reraised(self):
        timer = T.StageTimer()

        def boom():
            raise ValueError("stage failed")

        mod = fake_module("fake_fail", {"boom": boom})
        timer.wrap_modules([mod])
        with self.assertRaises(ValueError):
            mod.boom()
        self.assertEqual(timer.stages["fake_fail.boom"]["failed_calls"], 1)

    def test_imported_helpers_and_private_names_not_wrapped(self):
        timer = T.StageTimer()

        def helper():
            return 1

        def _private():
            return 2

        other = fake_module("some_other_module", {"helper": helper})
        mod = fake_module("fake_mod", {"_private": _private})
        mod.imported = other.helper  # __module__ is some_other_module, so it stays unwrapped
        timer.wrap_modules([mod])
        self.assertIs(mod.imported, other.helper)
        self.assertIs(mod._private, _private)

    def test_run_main_is_not_wrapped(self):
        timer = T.StageTimer()

        def main(*a, **k):
            return 0

        mod = fake_module("csj_run", {"main": main})
        timer.wrap_modules([mod])
        self.assertIs(mod.main, main)


class WriteLogTests(unittest.TestCase):
    def test_log_written_with_stage_rows(self):
        timer = T.StageTimer()
        timer._record("csj_build.encode", 0.5, 2.0, True)
        timer._record("csj_gates.check", 3.0, 0.25, False)
        with tempfile.TemporaryDirectory() as d:
            run_file = Path(d) / "CLIP-1_run.json"
            run_file.write_text(json.dumps({"stopped_at": "gates", "blocking_pass": False}))
            started = time.time()
            path = T.write_log(d, "CLIP-1", started, started + 5.0, timer, 1, False, run_file)
            log = json.loads(path.read_text())
        self.assertEqual(path.name, "CLIP-1_timing_log.json")
        self.assertEqual(log["total_seconds"], 5.0)
        self.assertEqual(log["exit_code"], 1)
        self.assertEqual(log["stopped_at"], "gates")
        self.assertEqual([s["name"] for s in log["stages"]], ["csj_build.encode", "csj_gates.check"])
        self.assertEqual(log["stages"][1]["failed_calls"], 1)


if __name__ == "__main__":
    unittest.main()
