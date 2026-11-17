"""V0665 the contributor track: the one-time backfill of the unlock records from the governed-code tables that already exist.

A script, never run at boot. It walks every developer the tables name (proposers, reviewers, voters, season winners) through services/contributor_track
(the one writer of cosmetic_unlocks) and writes what their history earned; a record that exists is left alone, so running it twice writes nothing the second time.
Every condition reads the governed-code tables, so the backfill finds what the rows already prove and stamps each unlock with the time of its event.

  python -m scripts.contributor_track_backfill            # or: cd /app && PYTHONPATH=/app/src python scripts/contributor_track_backfill.py
  python scripts/contributor_track_backfill.py --dry-run  # prints what it would write, writes nothing
"""
from __future__ import annotations

import asyncio
import sys


async def main(dry_run: bool) -> int:
    from agentvault_registry.database import AsyncSessionLocal
    from agentvault_registry.services.contributor_track import DbTrackStore, Tracker

    async with AsyncSessionLocal() as db:
        store = DbTrackStore(db)
        if dry_run:
            class _Dry:
                def __getattr__(self, n):
                    return getattr(store, n)

                async def insert(self, rows):          # nothing is written
                    return None
            rows = await Tracker(_Dry()).backfill()
        else:
            rows = await Tracker(store).backfill()
            await db.commit()
    for r in rows:
        print(f"{'would write' if dry_run else 'wrote'} developer {r['developer_id']} {r['kind']} {r['item_key']} ({r['source']})")
    print(f"{len(rows)} unlock record(s) {'to write' if dry_run else 'written'}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--dry-run" in sys.argv[1:])))
