"""A fake student-record system for the LYCEUM recipe: writes the awarded credentials as a CSV export, one row per
award (a pseudonymous holder id, never a name), with one REVOKED row the recipe leaves out.

    python fake_sis.py /data/sis-out --count 5
"""
import argparse
import csv
import datetime as dt
import io
import os
import pathlib

FIELDS = ["award_id", "holder_pseudonym", "credential", "eqf_level", "ects", "awarded_on", "status"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--run", default=dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S"))
    a = ap.parse_args()
    today = dt.date.today().isoformat()
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS)
    w.writeheader()
    for i in range(a.count):
        w.writerow({"award_id": f"AW-{a.run}-{i:03d}", "holder_pseudonym": f"stu-{(7919 * (i + 3)) % 100000:05d}",
                    "credential": ["BSc Data Engineering", "Certificate in Applied Statistics"][i % 2],
                    "eqf_level": 6 if i % 2 == 0 else 5, "ects": 180 if i % 2 == 0 else 30, "awarded_on": today,
                    "status": "REVOKED" if i == a.count - 1 else "AWARDED"})
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / f".credentials-{a.run}.csv.part"
    tmp.write_text(buf.getvalue())
    os.replace(tmp, out / f"credentials-{a.run}.csv")
    print(out / f"credentials-{a.run}.csv")


if __name__ == "__main__":
    main()
