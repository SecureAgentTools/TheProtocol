#!/usr/bin/env python3
"""A stand-in for the old system's export folder: the sample's orders split into a few CSV files, as a system that
exports once a month would leave them.

    python3 fake/make_export.py sample/orders.csv export --files 3

Every value is the sample's own (invented).
"""
import argparse
import csv
import io
from pathlib import Path


def split(sample, folder, files: int = 3) -> int:
    rows = list(csv.DictReader(io.StringIO(Path(sample).read_text(encoding="utf-8"))))
    if not rows:
        return 0
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    per = -(-len(rows) // files)
    for n in range(files):
        part = rows[n * per:(n + 1) * per]
        if not part:
            break
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(part)
        (out / f"orders-export-{n + 1:02d}.csv").write_text(buf.getvalue(), encoding="utf-8")
    return len(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sample")
    ap.add_argument("folder")
    ap.add_argument("--files", type=int, default=3)
    a = ap.parse_args()
    print(f"{split(a.sample, a.folder, a.files)} rows written to {a.folder}")
