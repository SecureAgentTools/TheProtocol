#!/usr/bin/env python3
"""The rehearsal target: a SQLite file with the new table's columns (fake/target_sqlite.sql), for TARGET_ENGINE=sqlite.

    python3 fake/make_target.py target.db

Then --set TARGET_ENGINE=sqlite --set TARGET_PATH=target.db --set TARGET_TABLE=customers.
"""
import sqlite3
import sys
from pathlib import Path


def build(db) -> None:
    c = sqlite3.connect(db)
    try:
        c.executescript((Path(__file__).with_name("target_sqlite.sql")).read_text(encoding="utf-8"))
        c.commit()
    finally:
        c.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    build(sys.argv[1])
    print(f"{sys.argv[1]}: the table customers is ready")
