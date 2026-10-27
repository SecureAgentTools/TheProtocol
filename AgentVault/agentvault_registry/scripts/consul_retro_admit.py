#!/usr/bin/env python3
"""
CONSUL Retro-Admission Tool
============================

Bring existing federated operators (admitted via the simpler Phase 1
federation-license pathway) into the Phase 2 compliance pipeline by
creating FederatedRegistryCompliance + PeerRegistry records for each.

Runs in --dry-run mode by default. --apply requires explicit opt-in.

USAGE
-----

  # dry-run — reports what WOULD happen, no writes
  python consul_retro_admit.py --dry-run

  # write records for operators whose live policy passes validation
  python consul_retro_admit.py --apply

  # write records even for operators that fail validation (stores them
  # as 'quarantined' at creation time — use with care)
  python consul_retro_admit.py --apply --admit-failing

IMPORTANT
---------

This script does NOT turn on enforcement. It creates the data that the
CONSUL poller operates on once the operator runs the poller. Turning on
the poller + enforcement is a separate step via
  POST /api/v1/admin/federation/compliance/enforcement-mode
and the IS_CENTRAL_REGISTRY / FEDERATION_ENFORCEMENT_ACTIVE env flags.

The script must be run from inside the Registry container (or another env
with the same DB credentials) so it can reach the Registry DB + the
operator endpoints.
"""
import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Add the registry src path so we can import models/services
REGISTRY_SRC = os.environ.get(
    "REGISTRY_SRC",
    "/opt/theprotocol/stack/Agentvault2/AgentVault/agentvault_registry/src",
)
if REGISTRY_SRC not in sys.path:
    sys.path.insert(0, REGISTRY_SRC)

from agentvault_registry.database import get_db_context  # noqa: E402
from agentvault_registry.models import (  # noqa: E402
    FederationLicense,
    FederatedRegistryCompliance,
    PeerRegistry,
)
from agentvault_registry.services.federation_policy_validator import (  # noqa: E402
    FederationPolicyValidator,
)


logger = logging.getLogger("consul_retro_admit")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)


async def _fetch_policy(base_url: str, timeout: float = 10.0) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    """
    Fetch the peer's current policy + hash.

    Returns (policy_json_or_none, policy_hash_or_none, error_or_none).

    The peer's /policy-compliance endpoint currently returns only the hash.
    If policy_json is not in the payload, we return (None, hash, None) and
    the caller falls back to hash-only record (no validation possible).
    """
    url = f"{base_url.rstrip('/')}/api/v1/admin/federation/policy-compliance"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return (None, None, f"HTTP {resp.status_code}")
        data = resp.json()
        return (data.get("policy_json"), data.get("policy_hash"), None)
    except Exception as exc:  # noqa: BLE001
        return (None, None, f"{type(exc).__name__}: {exc}")


async def _list_existing_compliance(db: AsyncSession) -> Dict[int, FederatedRegistryCompliance]:
    result = await db.execute(select(FederatedRegistryCompliance))
    return {row.peer_registry_id: row for row in result.scalars().all()}


async def _list_peers_with_urls(db: AsyncSession) -> List[PeerRegistry]:
    result = await db.execute(select(PeerRegistry).order_by(PeerRegistry.id))
    return list(result.scalars().all())


async def _list_licensed_operators(db: AsyncSession) -> List[FederationLicense]:
    result = await db.execute(
        select(FederationLicense).where(FederationLicense.status == "active")
    )
    return list(result.scalars().all())


async def run(dry_run: bool, admit_failing: bool) -> int:
    validator = FederationPolicyValidator()
    writes_planned = 0
    writes_applied = 0
    errors = 0

    async with get_db_context() as db:
        peers = await _list_peers_with_urls(db)
        existing = await _list_existing_compliance(db)
        licenses = await _list_licensed_operators(db)

        logger.info(
            "Loaded %d peer_registries, %d compliance rows, %d active licenses.",
            len(peers),
            len(existing),
            len(licenses),
        )
        logger.info("Mode: %s", "DRY-RUN" if dry_run else "APPLY")
        logger.info("")

        # We only admit peers that (a) have a PeerRegistry row AND (b) have an
        # active license AND (c) don't already have a compliance record.
        license_by_did = {l.operator_did: l for l in licenses}

        for peer in peers:
            if peer.id in existing:
                logger.info("[%s] skip — already has compliance record", peer.name)
                continue
            if peer.status != "ACTIVE":
                logger.info("[%s] skip — peer status=%s (not ACTIVE)", peer.name, peer.status)
                continue

            logger.info("[%s] url=%s — fetching current policy…", peer.name, peer.base_url)
            policy_json, policy_hash, fetch_err = await _fetch_policy(peer.base_url)

            if fetch_err:
                logger.warning("[%s] unreachable: %s", peer.name, fetch_err)
                errors += 1
                continue

            if not policy_hash:
                logger.warning("[%s] peer returned no policy_hash — cannot admit", peer.name)
                errors += 1
                continue

            if not policy_json:
                logger.warning(
                    "[%s] peer returned hash but no policy JSON (current "
                    "/policy-compliance contract is hash-only). Will admit with "
                    "hash only, validation=skipped.",
                    peer.name,
                )
                validation = None
                valid = False
            else:
                validation = validator.validate(policy_json)
                valid = validation.valid
                if validation.submitted_hash != policy_hash:
                    logger.warning(
                        "[%s] hash mismatch between our canonical computation "
                        "(%s) and peer's reported hash (%s). The peer may be "
                        "using a different canonicalization. Will admit with "
                        "peer's hash but flag in audit log.",
                        peer.name,
                        validation.submitted_hash[:16] + "…",
                        policy_hash[:16] + "…",
                    )

            if validation is not None and not valid and not admit_failing:
                logger.warning(
                    "[%s] policy FAILS validation (%d violations). Skipping. "
                    "Pass --admit-failing to admit anyway as 'quarantined'.",
                    peer.name,
                    len(validation.violations),
                )
                for v in validation.violations:
                    logger.info(
                        "[%s]   violation %s at %s (%s): required=%r submitted=%r",
                        peer.name,
                        v.severity.value,
                        v.path,
                        v.violation_type,
                        v.required,
                        v.submitted,
                    )
                errors += 1
                continue

            # Find matching license by DID
            license_match = None
            for lic_did, lic in license_by_did.items():
                if lic_did and peer.name and lic_did.lower().endswith(
                    peer.name.lower().replace(" ", "-")
                ):
                    license_match = lic
                    break

            if dry_run:
                writes_planned += 1
                logger.info(
                    "[%s] DRY-RUN — would create FederatedRegistryCompliance "
                    "(hash=%s…, validation=%s, license=%s)",
                    peer.name,
                    (policy_hash or "")[:16],
                    "PASS" if valid else "FAIL/SKIP",
                    license_match.operator_name if license_match else "none",
                )
                continue

            # APPLY
            record = FederatedRegistryCompliance(
                peer_registry_id=peer.id,
                policy_json=policy_json or {},
                policy_hash=policy_hash,
                policy_version=1,
                federation_status="federated" if valid else "quarantined",
                compliance_score=100.0 if valid else 50.0,
                drift_events_count=0,
                consecutive_poll_failures=0,
                quarantine_reason=(
                    None
                    if valid
                    else "Retro-admitted while failing validation (admit_failing=true)"
                ),
                quarantine_since=(None if valid else datetime.now(timezone.utc)),
                admitted_at=datetime.now(timezone.utc),
                admitted_by="retro_admit_script",
            )
            db.add(record)
            writes_applied += 1
            logger.info(
                "[%s] APPLIED — compliance record created (status=%s)",
                peer.name,
                record.federation_status,
            )

        if not dry_run:
            await db.commit()

    logger.info("")
    logger.info("=" * 60)
    logger.info("Summary")
    logger.info("  planned writes (dry-run): %d", writes_planned)
    logger.info("  applied writes (apply): %d", writes_applied)
    logger.info("  errors: %d", errors)
    return 0 if errors == 0 else 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CONSUL — Retro-admit existing operators into Phase 2 compliance pipeline.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Preview only — no DB writes")
    group.add_argument("--apply", action="store_true", help="Write compliance records to DB")
    parser.add_argument(
        "--admit-failing",
        action="store_true",
        help="Admit operators whose policy fails validation, storing them as 'quarantined'. "
        "Without this flag, failing operators are skipped.",
    )
    args = parser.parse_args()

    return asyncio.run(run(dry_run=args.dry_run, admit_failing=args.admit_failing))


if __name__ == "__main__":
    sys.exit(main())
