#!/usr/bin/env python3
"""A stand-in for the old system: a SQLite database with the sample's table, so the real run (load, reconcile,
rollback) can be tried with no old system at all.

    python3 fake/make_legacy.py sample/products.jsonl legacy.db

The table is named after the sample file (products) and has its columns; every value is the sample's own (invented).
"""
import json
import sqlite3
import sys
from pathlib import Path


def build(sample, db) -> int:
    sample, db = Path(sample), Path(db)
    rows = [json.loads(line) for line in sample.read_text(encoding="utf-8").splitlines() if line.strip()]
    cols = list(dict.fromkeys(k for r in rows for k in r))
    table = sample.name.split(".")[0]
    q = lambda n: '"' + n.replace('"', '""') + '"'  # noqa: E731
    c = sqlite3.connect(db)
    try:
        c.execute(f"DROP TABLE IF EXISTS {q(table)}")
        c.execute(f"CREATE TABLE {q(table)} ({', '.join(q(x) + (' INTEGER PRIMARY KEY' if x == 'id' else '') for x in cols)})")
        c.executemany(f"INSERT INTO {q(table)} VALUES ({', '.join('?' for _ in cols)})",
                      [[r.get(x) for x in cols] for r in rows])
        c.commit()
    finally:
        c.close()
    return len(rows)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    print(f"{build(sys.argv[1], sys.argv[2])} rows written to {sys.argv[2]}")
