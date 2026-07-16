#!/usr/bin/env python3
"""CLI helper: count master partitions per (database, host) from showClusterStatus.json.

Reuses parsers.parse_sdb_json_table so the numbers match what the app sees,
lets you cross-check the app's view against the raw-TSV awk one-liner.

Usage:
    python partition_audit.py <report-dir> [database_filter]
    python partition_audit.py <report-dir> --json

<report-dir> is an extracted sdb-report bundle root (the directory containing
per-node subdirs such as 100.127.180.12-LEAF/). Every node may have a copy of
showClusterStatus.json with the same cluster-wide view; this tool uses the
single richest file (most Master rows) so counts are not multiplied by node
count.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from parsers import parse_sdb_json_table

CLUSTER_STATUS_FILE = "showClusterStatus.json"
# Read every row: the default per-collector cap (MAX_RESOURCE_POOLS_ROWS=2000)
# would truncate large clusters and undercount master partitions. A large cap
# still works with the oversized-file streaming path.
ALL_ROWS_CAP = 10_000_000


def _find_key(row: dict, *candidates: str) -> str | None:
    lower_map = {k.lower(): k for k in row.keys()}
    for cand in candidates:
        actual = lower_map.get(cand.lower())
        if actual is not None:
            return actual
    return None


def _count_masters_in_rows(rows: list, db_filter: str | None = None) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    if not rows:
        return counts
    for row in rows:
        if not isinstance(row, dict):
            continue
        db_key = _find_key(row, "Database", "DB_NAME", "Db")
        host_key = _find_key(row, "Host")
        role_key = _find_key(row, "Role")
        if not (db_key and host_key and role_key):
            continue
        role = str(row[role_key] or "").strip().lower()
        if role != "master":
            continue
        db = str(row[db_key] or "").strip()
        host = str(row[host_key] or "").strip()
        if not db or not host:
            continue
        if db_filter and db.lower() != db_filter.lower():
            continue
        counts[(db, host)] = counts.get((db, host), 0) + 1
    return counts


def collect_master_partitions(root: str, db_filter: str | None = None) -> dict[tuple[str, str], int]:
    """Aggregate Master partition rows per (database, host).

    Uses the single showClusterStatus.json with the most Master rows so
    duplicated cluster-wide files under each leaf do not N× inflate counts.
    """
    best: dict[tuple[str, str], int] = {}
    best_total = -1
    for dirpath, _dirnames, filenames in os.walk(root):
        if CLUSTER_STATUS_FILE not in filenames:
            continue
        rows = parse_sdb_json_table(dirpath, CLUSTER_STATUS_FILE, row_cap=ALL_ROWS_CAP)
        counts = _count_masters_in_rows(rows, db_filter)
        total = sum(counts.values())
        if total > best_total:
            best = counts
            best_total = total
    return best


def _format_text(counts: dict[tuple[str, str], int]) -> str:
    lines = []
    total = 0
    for (db, host), n in sorted(counts.items()):
        lines.append(f"Database: {db}  Host: {host}  Master partitions: {n}")
        total += n
    lines.append(f"Total master partitions: {total}")
    return "\n".join(lines)


def _format_json(counts: dict[tuple[str, str], int]) -> str:
    payload = [
        {"database": db, "host": host, "master_partitions": n}
        for (db, host), n in sorted(counts.items())
    ]
    return json.dumps(payload, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Count master partitions per (database, host) from showClusterStatus.json.",
    )
    parser.add_argument("report_dir", help="extracted sdb-report bundle root")
    parser.add_argument("database", nargs="?", default=None, help="optional database filter")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.report_dir):
        print(f"error: {args.report_dir!r} is not a directory", file=sys.stderr)
        return 2

    counts = collect_master_partitions(args.report_dir, args.database)
    if not counts:
        where = f" for database {args.database!r}" if args.database else ""
        print(
            f"No master partition rows found in any {CLUSTER_STATUS_FILE} under "
            f"{args.report_dir}{where}.",
            file=sys.stderr,
        )
        return 0

    print(_format_json(counts) if args.json else _format_text(counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
