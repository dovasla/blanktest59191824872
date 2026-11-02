#!/usr/bin/env python3
"""Build one table from batch results.

Reads one or more batch result JSON files. Each file is a list of rows with:
  name         clip id, for example "WOXIC 697f"
  status       for example "READY", "SKIPPED", "STOPPED"
  reasons      list of open items (may be empty)
  upload_link  optional upload link

Optionally reads BATCH_PLAN.csv for each clip's map and player.

Output has one row per clip with these columns:
  clip_id, map, player, status, upload_link, open_items

If the same clip name is in more than one results file, the later file wins
and the clip keeps its first position in the table.

Usage:
  python3 batch_report.py RESULTS.json [MORE.json ...] [--plan BATCH_PLAN.csv]
                          [--out table.md | --out table.csv]

Without --out the Markdown table is printed to stdout.
"""

import argparse
import csv
import json
import sys

COLUMNS = ["clip_id", "map", "player", "status", "upload_link", "open_items"]
NOT_SET = "not set"
NO_OPEN_ITEMS = "none"
NO_REASON = "no reason recorded"
FAILED_STATUSES = {"STOPPED", "SKIPPED", "BLOCKED", "FAILED"}


def load_results(paths):
    """Return result rows in file order, one per clip name."""
    rows_by_name = {}
    order = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            raise ValueError(f"{path}: expected a list of rows")
        for item in data:
            if not isinstance(item, dict):
                raise ValueError(f"{path}: row is not an object: {item!r}")
            name = str(item.get("name", "")).strip()
            if not name:
                raise ValueError(f"{path}: row has no name: {item!r}")
            if name not in rows_by_name:
                order.append(name)
            rows_by_name[name] = item
    return [rows_by_name[name] for name in order]


def load_plan(path):
    """Return {clip_id: {"map": ..., "player": ...}} from BATCH_PLAN.csv."""
    if not path:
        return {}
    plan = {}
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            clip_id = (row.get("clip_id") or "").strip()
            if clip_id:
                plan[clip_id] = {
                    "map": (row.get("map") or "").strip(),
                    "player": (row.get("player") or "").strip(),
                }
    return plan


def build_table(results, plan):
    """Turn result rows and plan values into table rows."""
    table = []
    for item in results:
        clip_id = str(item["name"]).strip()
        plan_row = plan.get(clip_id, {})
        status = str(item.get("status") or "UNKNOWN").strip()
        reasons = [str(r).strip() for r in item.get("reasons") or [] if str(r).strip()]
        if reasons:
            open_items = "; ".join(reasons)
        elif status.upper() in FAILED_STATUSES:
            open_items = NO_REASON
        else:
            open_items = NO_OPEN_ITEMS
        table.append({
            "clip_id": clip_id,
            "map": plan_row.get("map") or NOT_SET,
            "player": plan_row.get("player") or NOT_SET,
            "status": status,
            "upload_link": str(item.get("upload_link") or "").strip(),
            "open_items": open_items,
        })
    return table


def to_markdown(table):
    """Render the table as Markdown, escaping pipe characters in cells."""
    def cell(value):
        return str(value).replace("|", "\\|")

    lines = [
        "| " + " | ".join(COLUMNS) + " |",
        "|" + "|".join("---" for _ in COLUMNS) + "|",
    ]
    for row in table:
        lines.append("| " + " | ".join(cell(row[c]) for c in COLUMNS) + " |")
    return "\n".join(lines) + "\n"


def to_csv_text(table):
    """Render the table as CSV text."""
    import io

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(table)
    return buf.getvalue()


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("results", nargs="+", help="batch result JSON files")
    parser.add_argument("--plan", help="BATCH_PLAN.csv for map and player")
    parser.add_argument("--out", help="output file (.csv or .md); default stdout Markdown")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    table = build_table(load_results(args.results), load_plan(args.plan))

    if args.out and args.out.lower().endswith(".csv"):
        text = to_csv_text(table)
    else:
        text = to_markdown(table)

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
