"""
Migration Bridge — One-time alembic_version stamp for squashed migration.

Handles the transition from the old 56-migration chain (3 heads) to the
single squashed migration (0001_squash). Safe to run on every boot:

  - Fresh DB (no alembic_version table) → no-op, alembic upgrade handles it
  - Old DB (3 heads in alembic_version) → re-stamps to 0001_squash
  - Already migrated (0001_squash present) → no-op

Usage (in compose command):
  python -m agentvault_registry.migration_bridge && alembic upgrade head && ...
"""

import logging
import os
import sys

from sqlalchemy import create_engine, text

from agentvault_registry.core.dsn import sync_engine_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("migration_bridge")

SQUASH_REV = "0001_squash"


def run():
    db_url = os.environ.get("DATABASE_URL_SYNC", os.environ.get("DATABASE_URL", ""))
    if not db_url:
        logger.warning("migration_bridge: no DATABASE_URL found, skipping")
        return

    # The sync engine names its driver (psycopg2): a plain postgresql:// is psycopg 3 on SQLAlchemy 2.1, and
    # +asyncpg (DATABASE_URL) is not a sync driver at all (§DEPS sqla-driver-pin).
    db_url = sync_engine_url(db_url)

    engine = create_engine(db_url)
    with engine.connect() as conn:
        # Check if alembic_version table exists
        has_table = conn.execute(text(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.tables "
            "  WHERE table_schema = 'public' AND table_name = 'alembic_version'"
            ")"
        )).scalar()

        if not has_table:
            logger.info("migration_bridge: fresh DB, no alembic_version table")
            return

        rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()

        if not rows:
            logger.info("migration_bridge: empty alembic_version, fresh DB")
            return

        current_revs = [r[0] for r in rows]

        if current_revs == [SQUASH_REV]:
            logger.info("migration_bridge: already at %s", SQUASH_REV)
            return

        # §pass42 (2026-05-18) — Post-squash safety net. The bridge's INTENT
        # is to transition the OLD multi-head pre-squash chain (3 heads in
        # alembic_version) to the single-row squash. Any single-row state
        # that isn't 0001_squash is therefore POST-squash (alembic has
        # moved past 0001 normally — e.g. we're at 0063_agent_signing_keys).
        # Re-stamping THAT back to 0001_squash forces alembic to re-run all
        # 62 post-squash migrations on every restart. Several of those
        # (0055 flare_tier orphan scrub, 0056 variant orphan scrub) are
        # destructive UPDATE statements with no idempotency gate — they
        # wipe sovereign agents' flare_tier='sovereign' + variant data on
        # every container restart.
        #
        # Rule: only re-stamp the OLD multi-head state. Single-head with
        # an unknown revision is the normal post-squash case — leave it
        # alone so alembic can track it natively.
        if len(current_revs) == 1:
            logger.info(
                "migration_bridge: single-head at %s — already past squash, skipping bridge",
                current_revs[0],
            )
            return

        # Multi-head OLD revision IDs found — re-stamp to squash
        logger.info("migration_bridge: found old multi-head revisions %s, re-stamping to %s", current_revs, SQUASH_REV)
        conn.execute(text("DELETE FROM alembic_version"))
        conn.execute(text("INSERT INTO alembic_version (version_num) VALUES (:rev)"), {"rev": SQUASH_REV})
        conn.commit()
        logger.info("migration_bridge: stamped to %s", SQUASH_REV)

    engine.dispose()


if __name__ == "__main__":
    run()
