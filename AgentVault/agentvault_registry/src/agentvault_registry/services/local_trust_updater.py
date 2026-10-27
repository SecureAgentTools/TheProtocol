"""
LocalTrustUpdater — EigenTrust++ Phase 2

Updates local_trust_scores rows in response to:
  - Token transfers (bilateral positive signal)
  - Dispute rulings (bilateral positive/negative signal)
  - ZKP attestations (self-signal counter, not bilateral)

All calls are try/except guarded at the call site — a failure here
must never fail the originating operation (transfer, ruling, attestation).
"""
import uuid
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from agentvault_registry.core import ledger_names   # W4: an event's old and new names are one event

logger = logging.getLogger(__name__)


async def _upsert_local_trust(
    db: AsyncSession,
    from_did: str,
    to_did: str,
    satisfactory_delta: int = 0,
    unsatisfactory_delta: int = 0,
    volume_delta: Decimal | int = 0,
) -> None:
    """
    Upsert a local_trust_scores row for the (from_did, to_did) pair.
    Recalculates local_trust = satisfactory - unsatisfactory after update.
    """
    # Import here to avoid circular imports at module load
    from ..models import LocalTrustScore

    result = await db.execute(
        select(LocalTrustScore).where(
            LocalTrustScore.from_did == from_did,
            LocalTrustScore.to_did == to_did,
        )
    )
    row = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if row is None:
        row = LocalTrustScore(
            id=str(uuid.uuid4()),
            from_did=from_did,
            to_did=to_did,
            satisfactory=max(0, satisfactory_delta),
            unsatisfactory=max(0, unsatisfactory_delta),
            local_trust=float(satisfactory_delta - unsatisfactory_delta),
            normalized=0.0,
            tx_volume=max(Decimal(0), Decimal(str(volume_delta))),
            last_updated=now,
        )
        db.add(row)
    else:
        row.satisfactory += satisfactory_delta
        row.unsatisfactory += unsatisfactory_delta
        row.satisfactory = max(0, row.satisfactory)
        row.unsatisfactory = max(0, row.unsatisfactory)
        row.tx_volume = max(Decimal(0), Decimal(str(row.tx_volume)) + Decimal(str(volume_delta)))
        row.local_trust = float(row.satisfactory - row.unsatisfactory)
        row.last_updated = now

    await db.flush()  # flush within the caller's transaction; commit is caller's responsibility


async def on_transfer_completed(
    db: AsyncSession,
    from_did: str,
    to_did: str,
    amount: Decimal | int,
) -> None:
    """
    Called after a successful TEG transfer.
    Records a positive bilateral signal from sender to receiver.

    Must be wrapped in try/except at call site.
    """
    await _upsert_local_trust(
        db,
        from_did=from_did,
        to_did=to_did,
        satisfactory_delta=1,
        volume_delta=amount,
    )
    logger.debug(f"LocalTrust updated: transfer {from_did[:16]} → {to_did[:16]} +{amount} AVT")


async def on_dispute_resolved(
    db: AsyncSession,
    complainant_did: str,
    defendant_did: str,
    ruling: str,
) -> None:
    """
    Called after dispute_outcome is recorded.
    Dispute is a stronger signal (weight 3 for unsatisfactory).

    Must be wrapped in try/except at call site.
    """
    if ruling == "IN_FAVOR_OF_COMPLAINANT":
        # Complainant → defendant: strong negative
        await _upsert_local_trust(
            db,
            from_did=complainant_did,
            to_did=defendant_did,
            unsatisfactory_delta=3,
        )
    elif ruling == "IN_FAVOR_OF_DEFENDANT":
        # Complainant → defendant: weak positive (vindication)
        await _upsert_local_trust(
            db,
            from_did=complainant_did,
            to_did=defendant_did,
            satisfactory_delta=1,
        )
    # DISMISSED: no bilateral update — wasteful interaction, not a trust signal
    logger.debug(
        f"LocalTrust updated: dispute ruling={ruling} "
        f"complainant={complainant_did[:16]} defendant={defendant_did[:16]}"
    )


async def on_zkp_attestation(
    db: AsyncSession,
    attesting_agent_did: str,
) -> None:
    """
    Called after a successful ZKP proof verification.
    ZKP attestation is a self-signal — it affects the agent's similarity
    profile used in the EigenTrust++ similarity-activation step, but does
    not create a bilateral trust pair.

    We record it as a self-loop entry so the engine can count it during
    similarity vector construction. from_did == to_did is intentional.

    Must be wrapped in try/except at call site.
    """
    await _upsert_local_trust(
        db,
        from_did=attesting_agent_did,
        to_did=attesting_agent_did,
        satisfactory_delta=1,
    )
    logger.debug(f"LocalTrust self-signal: ZKP attestation {attesting_agent_did[:16]}")


async def backfill_from_event_store(db: AsyncSession) -> int:
    """
    One-shot backfill on first EigenTrust++ epoch initialization.
    Reads TokenTransferred events from the EventStore projection and
    builds LocalTrustScore rows for all historical pairs.

    Returns count of pairs created.
    Idempotent: skips (from_did, to_did) pairs already in the table.
    """
    from ..models import LocalTrustScore
    from ..event_emitter import get_event_emitter
    from ..es_ssl_helper import get_httpx_verify

    logger.info("Starting LocalTrust backfill from EventStore...")

    emitter = get_event_emitter()
    event_store_url = emitter.event_store_url
    api_key = emitter.internal_api_key

    # Fetch TokenTransferred events (up to 5000 — enough for our simulation corpus)
    try:
        # §SOVKIT-2 R2 (2026-09-14): the frame's store sits behind its mTLS sidecar (a SPIRE-issued server certificate, a
        # client certificate required); a bare client trusted the system roots only, failed every read and said "0 pairs".
        async with httpx.AsyncClient(verify=get_httpx_verify()) as http:
            # §VITALS 2026-09-04: the path needs its TRAILING SLASH. Without it the
            # ES vhost answers FastAPI's redirect with an absolute Location that
            # drops the scheme and port (https://…:8443 -> http://…:80, nothing
            # listening), so this backfill reported "0 pairs" for a dead
            # connection. follow_redirects stays OFF so the next such regression
            # is loud instead of looking like an empty corpus.
            # W4 (agentvault2-aa, 2026-10-25): the transfers under either name (an emitter may write
            # UnitsTransferred once phase 2 switches it)
            events = []
            for _name in ledger_names.live_names("TokensTransferred"):
                resp = await http.get(
                    f"{event_store_url}/api/v1/events/",
                    headers={"X-Internal-Key": api_key},
                    params={"event_type": _name, "limit": 5000},
                    timeout=30.0,
                    follow_redirects=False,
                )
                if resp.status_code in (301, 302, 307, 308):
                    logger.warning(
                        "EventStore backfill got %s -> %s; refusing to follow a redirect "
                        "that drops the scheme", resp.status_code, resp.headers.get("location", "?")
                    )
                    return 0
                if resp.status_code != 200:
                    logger.warning(f"EventStore backfill query returned {resp.status_code}")
                    return 0
                raw = resp.json()
                events.extend(raw if isinstance(raw, list) else raw.get("events", []))
    except Exception as e:
        logger.warning(f"EventStore backfill fetch error: {e}")
        return 0

    # Check which pairs already exist
    existing_result = await db.execute(
        select(LocalTrustScore.from_did, LocalTrustScore.to_did)
    )
    existing_pairs = set(
        (row.from_did, row.to_did) for row in existing_result
    )

    # Aggregate volume and counts per ordered pair
    pair_data: dict[tuple, dict] = {}
    for event in events:
        payload = event.get("data", {})
        from_did = payload.get("from")
        to_did = payload.get("to")
        amount_raw = payload.get("amount", 0)
        try:
            amount = int(float(str(amount_raw)))
        except Exception:
            amount = 0

        if not from_did or not to_did or from_did == to_did:
            continue
        pair = (from_did, to_did)
        if pair in existing_pairs:
            continue
        if pair not in pair_data:
            pair_data[pair] = {"satisfactory": 0, "volume": 0}
        pair_data[pair]["satisfactory"] += 1
        pair_data[pair]["volume"] += amount

    # Write new rows
    now = datetime.now(timezone.utc)
    created = 0
    for (from_did, to_did), data in pair_data.items():
        s = data["satisfactory"]
        row = LocalTrustScore(
            id=str(uuid.uuid4()),
            from_did=from_did,
            to_did=to_did,
            satisfactory=s,
            unsatisfactory=0,
            local_trust=float(s),
            normalized=0.0,
            tx_volume=data["volume"],
            last_updated=now,
        )
        db.add(row)
        created += 1

    if created:
        await db.flush()

    logger.info(f"LocalTrust backfill complete: {created} pairs created from {len(events)} events")
    return created
