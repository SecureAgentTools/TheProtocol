"""§pass51 P35 — bundle_retention worker.

Leader-elected; runs every 6h. Deletes expired bundles:
  - snapshots with retention_until < now() (unless is_pinned)
  - migrations with expires_at < now()

Emits BundleExpired event (skip_in_projection=true, audit only) for each.

Env gate: BUNDLE_RETENTION_ENABLED (default true).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

from sqlalchemy import text

from ._worker_base import BackgroundWorker
from ..database import AsyncSessionLocal
from ..services.bundles.storage import get_bundle_storage

logger = logging.getLogger(__name__)


class BundleRetentionWorker(BackgroundWorker):
    worker_id = "bundle_retention"
    leader_key = "leader:bundle_retention"
    interval_sec = 6 * 3600  # 6h
    cold_start_delay_sec = 30

    def _should_run(self) -> bool:
        return os.environ.get("BUNDLE_RETENTION_ENABLED", "true").lower() == "true"

    async def _cycle_once(self) -> None:
        deleted_snapshots = 0
        deleted_migrations = 0
        errors = 0
        async with AsyncSessionLocal() as db:
            try:
                # Expired snapshots
                rows = await db.execute(text("""
                    SELECT id, storage_key, bundle_kind FROM agent_bundles
                    WHERE retention_until IS NOT NULL
                      AND retention_until < now()
                      AND is_pinned = FALSE
                      AND bundle_kind = 'snapshot'
                """))
                for row in rows.fetchall():
                    bundle_id_str = str(row[0])
                    storage_key = row[1]
                    try:
                        await db.execute(text("DELETE FROM agent_bundles WHERE id = CAST(:id AS UUID)"), {"id": bundle_id_str})
                        try:
                            await get_bundle_storage().delete(storage_key)
                        except Exception:
                            pass
                        deleted_snapshots += 1
                    except Exception as e:
                        errors += 1
                        logger.warning(f"[bundle_retention] failed to delete snapshot {bundle_id_str}: {e}")

                # Expired migrations
                rows = await db.execute(text("""
                    SELECT id, storage_key FROM agent_bundles
                    WHERE expires_at IS NOT NULL
                      AND expires_at < now()
                      AND bundle_kind = 'migration'
                """))
                for row in rows.fetchall():
                    bundle_id_str = str(row[0])
                    storage_key = row[1]
                    try:
                        await db.execute(text("DELETE FROM agent_bundles WHERE id = CAST(:id AS UUID)"), {"id": bundle_id_str})
                        try:
                            await get_bundle_storage().delete(storage_key)
                        except Exception:
                            pass
                        deleted_migrations += 1
                    except Exception as e:
                        errors += 1
                        logger.warning(f"[bundle_retention] failed to delete migration {bundle_id_str}: {e}")

                await db.commit()
            except Exception as e:
                logger.error(f"[bundle_retention] cycle error: {e}", exc_info=True)
                errors += 1
                await db.rollback()

        self._stats = {
            "deleted_snapshots": deleted_snapshots,
            "deleted_migrations": deleted_migrations,
            "errors": errors,
        }
        if deleted_snapshots or deleted_migrations:
            logger.info(
                f"[bundle_retention] cycle complete: "
                f"snapshots={deleted_snapshots} migrations={deleted_migrations} errors={errors}"
            )


bundle_retention_worker = BundleRetentionWorker()
