"""A fake site sensor logger for the KEYSTONE recipe: writes one test run (a concrete slab's cure strength) as a CSV,
measurement rows and a final acceptance row naming the contract milestone it proves, then the .done marker. Point
--out at the SFTP server's export folder (the sandbox drive mounts an OpenSSH container's folder), or at a plain
folder for a filedrop variant.

    python fake_logger.py /exports --contract 42 --milestone 1 --strength 41.5
"""
import argparse
import csv
import datetime as dt
import io
import pathlib

FIELDS = ["row_id", "kind", "run_id", "test", "value", "limit", "unit", "result", "contract_id", "milestone", "at"]


def rows(contract: str, milestone: int, strength: float, run: str):
    """A run's measurement rows, then its acceptance (passed) or rejection (failed) row."""
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    for i, v in enumerate((strength - 1.2, strength + 0.4, strength + 0.8)):
        yield {"row_id": f"{run}-{i}", "kind": "measurement", "run_id": run, "test": "cube_strength_28d",
               "value": round(v, 1), "limit": 35, "unit": "MPa", "result": "", "contract_id": contract,
               "milestone": milestone, "at": now}
    passed = strength >= 35
    # a passed run's last row is its acceptance (the recipe's evidence); a failed one's is a rejection (never evidence)
    yield {"row_id": f"{run}-acc", "kind": "acceptance" if passed else "rejection", "run_id": run,
           "test": "cube_strength_28d", "value": strength, "limit": 35, "unit": "MPa",
           "result": "PASS" if passed else "FAIL", "contract_id": contract, "milestone": milestone, "at": now}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--contract", required=True)
    ap.add_argument("--milestone", type=int, default=0)
    ap.add_argument("--strength", type=float, default=41.5, help="the measured 28-day strength, MPa (limit 35)")
    ap.add_argument("--run", default=dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S"))
    a = ap.parse_args()
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS)
    w.writeheader()
    for row in rows(a.contract, a.milestone, a.strength, a.run):
        w.writerow(row)
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"runs-{a.run}.csv").write_text(buf.getvalue())
    (out / f"runs-{a.run}.csv.done").write_text("")
    print(out / f"runs-{a.run}.csv")


if __name__ == "__main__":
    main()
