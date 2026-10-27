"""
TEG Migration Bridge — stamps existing DBs to squashed migration.
Same pattern as registry migration_bridge.py.
"""

import logging
import os

from sqlalchemy import create_engine, text

from .core.db_url import sync_engine_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("teg_migration_bridge")

SQUASH_REV = "0001_teg_squash"


def run():
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        logger.warning("teg_migration_bridge: no DATABASE_URL found, skipping")
        return

    # The sync engine names its driver (psycopg2): a plain postgresql:// is psycopg 3 on SQLAlchemy 2.1, which
    # the TEG does not install, and +asyncpg is not a sync driver at all (§DEPS sqla-driver-pin).
    db_url = sync_engine_url(db_url)

    engine = create_engine(db_url)
    with engine.connect() as conn:
        has_table = conn.execute(text(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.tables "
            "  WHERE table_schema = 'public' AND table_name = 'alembic_version'"
            ")"
        )).scalar()

        if not has_table:
            logger.info("teg_migration_bridge: fresh DB, no alembic_version table")
            return

        rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()

        if not rows:
            logger.info("teg_migration_bridge: empty alembic_version, fresh DB")
            return

        current_revs = [r[0] for r in rows]

        if current_revs == [SQUASH_REV]:
            logger.info("teg_migration_bridge: already at %s", SQUASH_REV)
            return

        logger.info("teg_migration_bridge: found old revisions %s, re-stamping to %s", current_revs, SQUASH_REV)
        conn.execute(text("DELETE FROM alembic_version"))
        conn.execute(text("INSERT INTO alembic_version (version_num) VALUES (:rev)"), {"rev": SQUASH_REV})
        conn.commit()
        logger.info("teg_migration_bridge: stamped to %s", SQUASH_REV)

    engine.dispose()


if __name__ == "__main__":
    run()
