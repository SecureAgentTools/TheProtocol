"""A fake mediation system for the TRUNK recipe: rates interconnect events and appends them to the settlement table of
an SQLite file (the table is created on first use). One event in five is DISPUTED and is neither paid nor booked.

    python fake_mediation.py /data/mediation.db --partner-did did:theprotocol:... --count 5 --rate 0.12
"""
import argparse
import datetime as dt
import sqlite3


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--partner-did", required=True, help="the partner carrier's agent, paid for each event")
    ap.add_argument("--partner-code", default="CARRIER-NORD")
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--rate", type=float, default=0.12, help="per minute")
    a = ap.parse_args()
    db = sqlite3.connect(a.db)
    db.execute("CREATE TABLE IF NOT EXISTS settlement_events (event_seq INTEGER PRIMARY KEY, event_id TEXT UNIQUE, "
               "partner_code TEXT, partner_agent_did TEXT, minutes REAL, charge TEXT, status TEXT, rated_at TEXT)")
    start = (db.execute("SELECT COALESCE(MAX(event_seq), 0) FROM settlement_events").fetchone()[0]) + 1
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    with db:
        for i in range(start, start + a.count):
            minutes = 3.5 + (i % 7) * 2.25
            db.execute("INSERT INTO settlement_events (event_seq, event_id, partner_code, partner_agent_did, minutes, "
                       "charge, status, rated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (i, f"IC-{i:07d}", a.partner_code, a.partner_did, minutes, f"{minutes * a.rate:.2f}",
                        "DISPUTED" if i % 5 == 0 else "RATED", now))
            print(i, f"IC-{i:07d}", f"{minutes * a.rate:.2f}")
    db.close()


if __name__ == "__main__":
    main()
