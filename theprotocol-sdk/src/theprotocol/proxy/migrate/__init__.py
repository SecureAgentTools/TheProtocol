"""tp-proxy migrate (V0664, M3): move a system's data from system A to system B with a kit (migration.yaml, proxy.yaml,
README.md, sample/), dry-run it on scratch targets, load it exactly once, reconcile both sides, roll it back, and certify
it on the ledger. The contract is sessionlogs2026/DESIGN_2026-11-14_MIGRATION_TEMPLATES.md, sections A to C."""
from .schema import (KIT_CAPS, MANIFEST_SCHEMA, REPORT_SCHEMA_ID, SCHEMA_ID, Kit, KitError, canonical, content_hash,
                     load_kit)

__all__ = ["KIT_CAPS", "MANIFEST_SCHEMA", "REPORT_SCHEMA_ID", "SCHEMA_ID", "Kit", "KitError", "canonical",
           "content_hash", "load_kit"]
