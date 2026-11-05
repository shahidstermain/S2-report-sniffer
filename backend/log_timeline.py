"""Build and page the complete tracelog timeline without loading it into memory."""
from collections import defaultdict
from contextlib import closing
import json
import sqlite3

from parsers import _parse_timestamp


def json_lines(path, *, legacy=False):
    if path.is_file():
        with path.open(encoding="utf-8") as source:
            for line in source:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    if legacy:
                        continue
                    raise
                if isinstance(row, dict):
                    yield row


def _populate(db, rows):
    db.execute("""CREATE TABLE entries (
        timestamp TEXT, sort_time TEXT, hostname TEXT COLLATE NOCASE,
        role TEXT COLLATE NOCASE, node_port TEXT, severity TEXT COLLATE NOCASE,
        message TEXT, source TEXT
    )""")

    def values():
        for row in rows:
            raw = str(row.get("timestamp") or "")
            instant = _parse_timestamp(raw)
            yield (raw, instant.isoformat(timespec="microseconds") if instant else "",
                   str(row.get("hostname") or ""), str(row.get("role") or ""),
                   str(row.get("node_port") or ""), str(row.get("severity") or ""),
                   str(row.get("message") or ""), str(row.get("source") or ""))

    db.executemany("INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?, ?, ?)", values())
    db.execute("CREATE INDEX chronology ON entries(sort_time DESC)")
    db.execute("CREATE INDEX node_time ON entries(hostname, role, node_port, sort_time DESC)")
    db.execute("""CREATE TABLE counts AS SELECT hostname, role, node_port, severity,
                  COUNT(*) AS n FROM entries GROUP BY hostname, role, node_port, severity""")


def build_timeline(path, rows):
    with closing(sqlite3.connect(path)) as db, db:
        _populate(db, rows)
        return db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]


def read_timeline(path, legacy_path, search, severities, node, page, page_size,
                  *, exact=False, role=None, port=None):
    # Old installations only have a bounded JSONL sample. Never open a missing
    # SQLite file in create mode or leave an empty file masking that sample.
    indexed = path.is_file()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro" if indexed else ":memory:",
                                 uri=indexed)) as db:
        if not indexed:
            _populate(db, json_lines(legacy_path, legacy=True))
        db.row_factory = sqlite3.Row
        conditions, args = [], []
        if node:
            conditions.append("hostname = ?" if exact else "instr(lower(hostname), lower(?)) = 1")
            args.append(node)
        for column, value in (("role", role), ("node_port", port)):
            if value is not None:
                conditions.append(f"{column} = ?")
                args.append(value)
        if severities:
            conditions.append("severity IN (" + ",".join("?" for _ in severities) + ")")
            args.extend(severities)
        if search:
            conditions.append("instr(lower(timestamp || ' ' || message || ' ' || hostname), lower(?)) > 0")
            args.append(search)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        total = db.execute("SELECT COUNT(*) FROM entries" + where, args).fetchone()[0]
        rows = db.execute(
            "SELECT timestamp, hostname, role, node_port, severity, message, source FROM entries"
            + where + " ORDER BY sort_time DESC, rowid LIMIT ? OFFSET ?",
            [*args, page_size, (page - 1) * page_size],
        )
        nodes, counts = {}, defaultdict(int)
        for row in db.execute("SELECT * FROM counts ORDER BY hostname, role, node_port"):
            hostname, role_name, node_port, severity, n = row
            nodes[(hostname, role_name, node_port)] = {
                "hostname": hostname, "role": role_name, "port": node_port,
            }
            counts[severity] += n
        return {
            "logs": [dict(row) for row in rows], "total": total,
            "log_nodes": list(nodes.values()), "timeline_indexed": indexed,
            "timeline_severity_counts": dict(counts),
        }
