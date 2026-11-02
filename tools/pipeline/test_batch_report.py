import csv
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout

import batch_report as br


def write_json(directory, name, data):
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    return path


def write_csv(directory, name, rows):
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["clip_id", "map", "player"])
        writer.writerows(rows)
    return path


class LoadResultsTests(unittest.TestCase):
    def test_reads_rows_in_file_order(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_json(d, "a.json", [{"name": "A 1"}, {"name": "B 2"}])
            rows = br.load_results([p])
            self.assertEqual([r["name"] for r in rows], ["A 1", "B 2"])

    def test_later_file_wins_and_keeps_first_position(self):
        with tempfile.TemporaryDirectory() as d:
            first = write_json(d, "a.json", [{"name": "A 1", "status": "SKIPPED"},
                                             {"name": "B 2", "status": "SKIPPED"}])
            second = write_json(d, "b.json", [{"name": "A 1", "status": "READY"}])
            rows = br.load_results([first, second])
            self.assertEqual([r["name"] for r in rows], ["A 1", "B 2"])
            self.assertEqual(rows[0]["status"], "READY")

    def test_rejects_non_list(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_json(d, "a.json", {"name": "A 1"})
            with self.assertRaises(ValueError):
                br.load_results([p])

    def test_rejects_row_without_name(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_json(d, "a.json", [{"status": "READY"}])
            with self.assertRaises(ValueError):
                br.load_results([p])

    def test_rejects_row_that_is_not_an_object(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_json(d, "a.json", ["WOXIC 697f"])
            with self.assertRaises(ValueError):
                br.load_results([p])


class LoadPlanTests(unittest.TestCase):
    def test_reads_map_and_player(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_csv(d, "plan.csv", [["WOXIC 697f", "Mirage", "woxic"]])
            plan = br.load_plan(p)
            self.assertEqual(plan["WOXIC 697f"], {"map": "Mirage", "player": "woxic"})

    def test_no_plan_gives_empty_dict(self):
        self.assertEqual(br.load_plan(None), {})


class BuildTableTests(unittest.TestCase):
    def test_open_items_are_joined(self):
        results = [{"name": "X 1", "status": "SKIPPED",
                    "reasons": ["missing column value: file", "missing column value: map"]}]
        table = br.build_table(results, {})
        self.assertEqual(table[0]["open_items"],
                         "missing column value: file; missing column value: map")

    def test_no_reasons_means_none(self):
        table = br.build_table([{"name": "X 1", "status": "DRY RUN DONE", "reasons": []}], {})
        self.assertEqual(table[0]["open_items"], "none")

    def test_map_and_player_come_from_plan(self):
        plan = {"X 1": {"map": "Mirage", "player": "woxic"}}
        table = br.build_table([{"name": "X 1", "status": "READY"}], plan)
        self.assertEqual(table[0]["map"], "Mirage")
        self.assertEqual(table[0]["player"], "woxic")

    def test_missing_map_and_player_are_not_guessed(self):
        table = br.build_table([{"name": "Martinez 6a78", "status": "SKIPPED"}], {})
        self.assertEqual(table[0]["map"], "not set")
        self.assertEqual(table[0]["player"], "not set")

    def test_blank_plan_values_show_not_set(self):
        plan = {"X 1": {"map": "", "player": ""}}
        table = br.build_table([{"name": "X 1", "status": "READY"}], plan)
        self.assertEqual(table[0]["map"], "not set")
        self.assertEqual(table[0]["player"], "not set")

    def test_upload_link_passes_through_and_defaults_blank(self):
        results = [{"name": "A 1", "status": "READY", "upload_link": "https://x/y.mp4"},
                   {"name": "B 2", "status": "READY"}]
        table = br.build_table(results, {})
        self.assertEqual(table[0]["upload_link"], "https://x/y.mp4")
        self.assertEqual(table[1]["upload_link"], "")

    def test_stopped_row_without_reason_says_so(self):
        table = br.build_table([{"name": "X 1", "status": "STOPPED", "reasons": []}], {})
        self.assertEqual(table[0]["open_items"], "no reason recorded")

    def test_missing_status_is_unknown(self):
        table = br.build_table([{"name": "A 1"}], {})
        self.assertEqual(table[0]["status"], "UNKNOWN")


class RenderTests(unittest.TestCase):
    def test_markdown_has_header_and_escapes_pipes(self):
        table = [{"clip_id": "A 1", "map": "Mirage", "player": "woxic", "status": "SKIPPED",
                  "upload_link": "", "open_items": "a | b"}]
        text = br.to_markdown(table)
        lines = text.strip().split("\n")
        self.assertEqual(lines[0], "| " + " | ".join(br.COLUMNS) + " |")
        self.assertEqual(lines[1], "|---|---|---|---|---|---|")
        self.assertIn("a \\| b", lines[2])

    def test_csv_has_header_and_one_line_per_clip(self):
        table = br.build_table([{"name": "A 1", "status": "READY"},
                                {"name": "B 2", "status": "SKIPPED"}], {})
        lines = br.to_csv_text(table).strip().split("\n")
        self.assertEqual(lines[0], ",".join(br.COLUMNS))
        self.assertEqual(len(lines), 3)


class MainTests(unittest.TestCase):
    def test_main_writes_csv_file(self):
        with tempfile.TemporaryDirectory() as d:
            res = write_json(d, "r.json", [{"name": "WOXIC 697f", "status": "DRY RUN DONE",
                                            "reasons": []}])
            plan = write_csv(d, "plan.csv", [["WOXIC 697f", "Mirage", "woxic"]])
            out = os.path.join(d, "table.csv")
            self.assertEqual(br.main([res, "--plan", plan, "--out", out]), 0)
            with open(out, encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(rows[0]["clip_id"], "WOXIC 697f")
            self.assertEqual(rows[0]["map"], "Mirage")
            self.assertEqual(rows[0]["open_items"], "none")

    def test_main_prints_markdown_to_stdout(self):
        with tempfile.TemporaryDirectory() as d:
            res = write_json(d, "r.json", [{"name": "A 1", "status": "READY"}])
            buf = io.StringIO()
            with redirect_stdout(buf):
                br.main([res])
            self.assertIn("| A 1 | not set | not set | READY |", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
