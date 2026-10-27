"""§pass51 Block 2 — Bundle file storage abstraction.

Per PLAN §19. Defines BundleStorage Protocol + LocalBundleStorage that
writes .tpb files to a host-volume-mounted path. Future S3 backend implements
the same Protocol; switching is a config change.

Layout:
    <root>/
      snapshots/<bundle_id[0:2]>/<bundle_id>.tpb
      templates/<bundle_id[0:2]>/<bundle_id>.tpb
      migrations/<bundle_id>.tpb
      _orphans/<bundle_id>.tpb_<rescued_at>
"""
from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


class BundleStorage(Protocol):
    """Async-friendly bundle blob storage interface."""

    async def write(self, bundle_id: str, kind: str, data: bytes) -> str: ...
    async def read(self, storage_key: str) -> bytes: ...
    async def delete(self, storage_key: str) -> None: ...
    async def size(self, storage_key: str) -> int: ...
    async def list_all_keys(self) -> list[str]: ...
    async def total_bytes(self) -> int: ...


class LocalBundleStorage:
    """File-backed storage. Atomic-write via tempfile + rename.

    bundle_id sharding (first 2 chars) prevents single-dir blowup on
    ext4/xfs. Migrations are unsharded (small volume, 7d retention).
    """

    def __init__(self, root: str):
        self.root = Path(root)
        for sub in ("snapshots", "templates", "migrations", "_orphans"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    def _path_for(self, bundle_id: str, kind: str) -> Path:
        if kind == "migration":
            return self.root / "migrations" / f"{bundle_id}.tpb"
        shard = bundle_id[:2].lower()
        bucket = "templates" if kind == "template" else "snapshots"
        d = self.root / bucket / shard
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{bundle_id}.tpb"

    async def write(self, bundle_id: str, kind: str, data: bytes) -> str:
        """Write atomically. Returns storage_key (relative path inside root)."""
        target = self._path_for(bundle_id, kind)
        tmp = target.with_suffix(".tpb.tmp")
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, target)
        key = str(target.relative_to(self.root))
        logger.info(f"[bundles.storage] wrote {key} ({len(data)} bytes)")
        return key

    async def read(self, storage_key: str) -> bytes:
        path = self.root / storage_key
        with open(path, "rb") as f:
            return f.read()

    async def delete(self, storage_key: str) -> None:
        path = self.root / storage_key
        if path.exists():
            path.unlink()
            logger.info(f"[bundles.storage] deleted {storage_key}")

    async def size(self, storage_key: str) -> int:
        return (self.root / storage_key).stat().st_size

    async def list_all_keys(self) -> list[str]:
        keys = []
        for p in self.root.rglob("*.tpb"):
            keys.append(str(p.relative_to(self.root)))
        return keys

    async def total_bytes(self) -> int:
        total = 0
        for p in self.root.rglob("*.tpb"):
            try:
                total += p.stat().st_size
            except OSError:
                pass
        return total


# ── Default factory based on env ────────────────────────────────────────────

_singleton: BundleStorage | None = None


def get_bundle_storage() -> BundleStorage:
    """Returns the configured bundle storage backend.

    v1: only LocalBundleStorage exists. Env BUNDLE_STORAGE_DIR overrides
    default `/app/bundle-storage`. Future: BUNDLE_STORAGE_BACKEND=s3 ...
    """
    global _singleton
    if _singleton is None:
        root = os.environ.get("BUNDLE_STORAGE_DIR", "/app/bundle-storage")
        _singleton = LocalBundleStorage(root)
        logger.info(f"[bundles.storage] LocalBundleStorage rooted at {root}")
    return _singleton
