"""§pass51 P35 — bundle_storage_gc worker.

Leader-elected; runs every 1h. Reconciles bundle-storage volume against the
agent_bundles table:

  - Files on disk with no DB row → move to _orphans/<bundle_id>.tpb_<rescued_at>
  - _orphans/ files older than 7d → hard delete

Per PLAN §19.2. Mitigates the "DB rollback after disk write succeeded" gap.

Env gate: BUNDLE_STORAGE_GC_ENABLED (default true).
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict

from sqlalchemy import text

from ._worker_base import BackgroundWorker
from ..database import AsyncSessionLocal

logger = logging.getLogger(__name__)

ORPHAN_RETENTION_DAYS = 7


class BundleStorageGcWorker(BackgroundWorker):
    worker_id = "bundle_storage_gc"
    leader_key = "leader:bundle_storage_gc"
    interval_sec = 3600  # 1h
    cold_start_delay_sec = 45

    def _should_run(self) -> bool:
        return os.environ.get("BUNDLE_STORAGE_GC_ENABLED", "true").lower() == "true"

    def _root(self) -> Path:
        return Path(os.environ.get("BUNDLE_STORAGE_DIR", "/app/bundle-storage"))

    async def _cycle_once(self) -> None:
        orphans_moved = 0
        orphans_purged = 0
        errors = 0

        root = self._root()
        orphans_dir = root / "_orphans"
        orphans_dir.mkdir(parents=True, exist_ok=True)

        # 1. Build set of valid storage_keys
        async with AsyncSessionLocal() as db:
            try:
                rows = await db.execute(text("SELECT storage_key FROM agent_bundles"))
                valid_keys = {r[0] for r in rows.fetchall() if r[0]}
            except Exception as e:
                logger.error(f"[bundle_storage_gc] failed to load valid keys: {e}")
                self._stats = {"orphans_moved": 0, "orphans_purged": 0, "errors": 1}
                return

        # 2. Walk disk; any .tpb without a matching valid key is an orphan
        for p in root.rglob("*.tpb"):
            try:
                if p.parent.name == "_orphans" or "_orphans" in p.parts:
                    continue
                rel = str(p.relative_to(root))
                if rel in valid_keys:
                    continue
                # Move to _orphans (7d quarantine before delete)
                bundle_id = p.stem  # filename without .tpb
                rescued_at = int(time.time())
                target = orphans_dir / f"{bundle_id}.tpb_{rescued_at}"
                p.rename(target)
                orphans_moved += 1
                logger.info(f"[bundle_storage_gc] moved orphan: {rel} → _orphans/")
            except Exception as e:
                errors += 1
                logger.warning(f"[bundle_storage_gc] failed to quarantine {p}: {e}")

        # 3. Purge _orphans files older than 7d
        cutoff = time.time() - (ORPHAN_RETENTION_DAYS * 86400)
        for p in orphans_dir.iterdir():
            try:
                if not p.is_file():
                    continue
                if p.stat().st_mtime < cutoff:
                    p.unlink()
                    orphans_purged += 1
            except Exception as e:
                errors += 1
                logger.warning(f"[bundle_storage_gc] failed to purge {p}: {e}")

        self._stats = {
            "orphans_moved": orphans_moved,
            "orphans_purged": orphans_purged,
            "errors": errors,
        }
        if orphans_moved or orphans_purged:
            logger.info(
                f"[bundle_storage_gc] cycle complete: "
                f"moved={orphans_moved} purged={orphans_purged} errors={errors}"
            )


bundle_storage_gc_worker = BundleStorageGcWorker()
