"""
EventStore Balance Sync — keeps `agents.liquid_balance` honest against the TEG
=============================================================================
`agents.liquid_balance` is a CACHE of a number the TEG owns. Every console, agent
list and admin view reads the cache; only the TEG knows the truth. This module is
what closes the gap, by re-reading the TEG whenever a balance moves.

§FRAMELIC (2026-09-07, findings row 164) — IT SUBSCRIBED TO ONE EVENT TYPE AND
BALANCES MOVE UNDER SEVERAL.
--------------------------------------------------------------------------------
It listened to `TokensTransferred` alone. That event is emitted by the REGISTRY for
a plain transfer, and it is not emitted at all for several movements that are just
as real. Measured on the EU/ASIA pair:

    ConverterHub (EU)     registry 1000.000000   TEG 750    — a 250 reputation bond
                          recorded as `ReputationBondDeposited` + `LedgerBalanceChanged`
    dust-proof sender     registry  100.000000   TEG  90    — a cross-frame debit
                          recorded as `LedgerBalanceChanged{kind:transfer}` + `FxSwapSettled`
    dust-proof receiver   registry    0.000000   TEG   9.949005
                          recorded ONLY as `LedgerBalanceChanged` — the receiving frame
                          never sees a `TokensTransferred` at all, by construction

Δ stayed 0.0 throughout, correctly: the LEDGER had every movement. It was the cache
that was wrong, so nothing that watches money noticed — and the reactor's own health
was perfect while it did nothing, because the handler read `from`/`to` off an event
type that never arrives for these movements, and the sync helper swallowed everything
it could not do (`except Exception: pass`, no counter, no log). Sixteen dispatches,
zero errors, zero updates.

`LedgerBalanceChanged` is the event the supply invariant itself is built on — every
balance movement produces one, which is exactly why Δ works — and it names each party
in `entries[].agent_did`. So the fix is to subscribe to THAT, and to keep the
`TokensTransferred` subscription as well: the sync is a re-read, so a doubled trigger
costs one HTTP call and nothing else, while dropping a subscription could lose a
movement nobody has thought of yet.

The re-read is deliberate. Applying `delta_liquid` from the event would drift on any
missed or replayed event; asking the TEG for the current number is self-correcting.
"""
from __future__ import annotations

import logging
import os
from decimal import Decimal
from typing import Iterable, Optional

import aiohttp
from sqlalchemy import select

from .. import models
from ..database import get_db_context
from ..es_ssl_helper import get_es_ssl_context
from .reactor_base import EventStoreReactor
from ..core.path_segment import seg  # §MCPTEST30 V0523: a caller's value is one path segment, encoded

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# A silent handler is why this went unnoticed for the life of two frames.
# Every outcome is counted, and every failure says which half failed.
# ----------------------------------------------------------------------
try:
    from prometheus_client import Counter as _Counter

    BALANCE_SYNC_TOTAL = _Counter(
        "registry_balance_sync_total",
        "agents.liquid_balance re-reads from the TEG, by outcome",
        labelnames=["registry", "outcome"],  # updated|unchanged|teg_error|db_error|not_found
    )
    _METRICS = True
except Exception:  # pragma: no cover - prometheus optional
    BALANCE_SYNC_TOTAL = None  # type: ignore[assignment]
    _METRICS = False


def _count(outcome: str) -> None:
    if _METRICS and BALANCE_SYNC_TOTAL is not None:
        try:
            BALANCE_SYNC_TOTAL.labels(
                registry=os.getenv("REGISTRY_NAME", "unknown"), outcome=outcome
            ).inc()
        except Exception:
            pass


# System accounts hold real balances but have no `agents` row, so syncing them is a
# guaranteed miss. ⚠ the live DIDs are `did:theprotocol:teg_system_treasury` and
# `did:theprotocol:teg_system_fx_reserve` — the old guard tested `teg:system:`, which
# matches NEITHER, so every treasury leg spent an HTTP call to find nothing.
_SYSTEM_MARKERS = ("teg:system:", "teg_system_", ":system:")


def _is_system(did: str) -> bool:
    d = (did or "").lower()
    return any(m in d for m in _SYSTEM_MARKERS)


async def _sync_agent_from_teg(agent_did: str) -> None:
    """Re-read one agent's balance from the TEG and update the cache if it moved."""
    if not agent_did or _is_system(agent_did):
        return

    teg_url = os.getenv("TEG_API_BASE_URL", "http://teg-layer:8080")
    teg_key = os.getenv("TEG_ADMIN_API_KEY", "")

    # §BALTLS 2026-09-10 — THE TEG IS BEHIND AN mTLS SIDECAR ON EVERY FRAME THAT HAS ONE, AND
    # THIS CALL BROUGHT NO IDENTITY TO IT. A bare `aiohttp.ClientSession()` uses the system CA
    # store and presents no client certificate, so on `https://<frame>-nginx-teg:8443` every
    # single re-read died at the handshake — `CERTIFICATE_VERIFY_FAILED` — and the handler
    # above did exactly what it was written to do: counted `teg_error`, logged, and left the
    # cache stale. Measured 2026-09-10: 562 failures per hour on EACH of registry-a, frame-b
    # and frame-c; 0 on EU and ASIA, whose TEG is plain http on the frame's own network. So the
    # §FRAMELIC row-164 fix — subscribe to the event every movement produces — has been landing
    # its re-reads into a closed door on precisely the three frames that have the most agents.
    #
    # `get_es_ssl_context()` is the SHARED context this fleet already uses for internal mTLS
    # (the same one `get_httpx_verify()` hands a dozen routers, `teg_integration_mtls` included):
    # it trusts the SPIRE bundle AND the public roots, presents `/certs/svid.0.pem` as the client
    # cert, and REBUILDS ITSELF when cert-writer rotates the SVID. Hand-rolling a second one here
    # would be the money-helper-with-its-own-transport shape all over again
    # ([[feedback_handrolled_transport_bypasses_shared_client_hardening]]).
    #
    # ADDITIVE BY CONSTRUCTION: the `ssl=` argument is attached only for an https TEG URL, so the
    # plain-http frames keep byte-identical behaviour. Proven both ways on all five live
    # registries before this was written — registry-a/frame-b/frame-c went
    # CERTIFICATE_VERIFY_FAILED -> 200, EU/ASIA stayed 200 -> 200.
    req_kwargs = {
        "headers": {"Authorization": f"Bearer {teg_key}"},
        "timeout": aiohttp.ClientTimeout(total=5),
    }
    if teg_url.lower().startswith("https://"):
        ssl_ctx = get_es_ssl_context()
        if ssl_ctx is not None:
            req_kwargs["ssl"] = ssl_ctx

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{teg_url}/api/v1/agent/{seg(agent_did)}/teg-status",
                **req_kwargs,
            ) as resp:
                if resp.status != 200:
                    # An agent this frame does not hold is a 404 and not a fault;
                    # anything else is, and it must be visible.
                    _count("not_found" if resp.status == 404 else "teg_error")
                    if resp.status != 404:
                        logger.warning(
                            "[BalanceSync] TEG %s for %s — cache left stale",
                            resp.status, agent_did[-12:],
                        )
                    return
                bal_data = await resp.json()
                # §BALTLS 2026-09-10 — "THE TEG HAS NO ACCOUNT FOR THIS AGENT" IS A 200, NOT A
                # 404. `GET /agent/{id}/teg-status` answers 200 with `teg_initialized: false`
                # and NO `balance` key at all when the profile is missing, so `.get("balance", 0)`
                # turned "I do not know this agent" into "this agent holds nothing" and would
                # write that zero straight over the cache — the `.get()`-on-a-missing-key class,
                # deciding a write instead of a branch.
                #
                # Inert today and deliberately fixed anyway: censused 2026-09-10 across all five
                # live frames, 3,613 registry rows have no TEG profile and EVERY ONE of them
                # already caches 0, so the bad write has never had anything to destroy. It is one
                # deleted profile or one renamed DID away from having plenty, and this path only
                # started executing on the three mTLS frames with the transport fix above.
                if not bal_data.get("teg_initialized", True) or bal_data.get("balance") is None:
                    _count("not_found")
                    return
                teg_balance = Decimal(str(bal_data["balance"]))
    except Exception as exc:  # noqa: BLE001 — counted and named, never swallowed
        _count("teg_error")
        logger.warning("[BalanceSync] TEG read failed for %s: %s", agent_did[-12:], exc)
        return

    try:
        async with get_db_context() as db:
            result = await db.execute(
                select(models.Agent).where(models.Agent.did == agent_did)
            )
            agent = result.scalar_one_or_none()
            if agent is None:
                _count("not_found")
                return
            if agent.liquid_balance == teg_balance:
                _count("unchanged")
                return
            old = agent.liquid_balance
            agent.liquid_balance = teg_balance
            await db.commit()
            _count("updated")
            logger.info("[BalanceSync] %s: %s → %s", agent_did[-12:], old, teg_balance)
    except Exception as exc:  # noqa: BLE001
        _count("db_error")
        logger.warning("[BalanceSync] DB update failed for %s: %s", agent_did[-12:], exc)


async def _sync_all(dids: Iterable[str]) -> None:
    seen = set()
    for did in dids:
        if did and did not in seen:
            seen.add(did)
            await _sync_agent_from_teg(did)


class BalanceSyncReactor(EventStoreReactor):
    """The registry's own transfer event. Kept — see the module docstring."""

    event_type = "TokensTransferred"
    leader_key = "es_balance_sync"  # preserved from pre-migration to keep the same Redis lock
    name = "BalanceSync"

    async def handle_event(self, event_data: dict) -> None:
        await _sync_all((event_data.get("from", ""), event_data.get("to", "")))


class LedgerBalanceSyncReactor(EventStoreReactor):
    """§FRAMELIC row 164 — the event EVERY balance movement produces.

    This is the same event the supply auditor classifies to prove Δ=0, so a movement
    that is invisible here is a movement that is invisible to the invariant — which
    makes it the right subscription for a cache that must not drift.
    """

    event_type = "LedgerBalanceChanged"
    leader_key = "es_ledger_balance_sync"
    name = "LedgerBalanceSync"

    async def handle_event(self, event_data: dict) -> None:
        entries = event_data.get("entries") or []
        if not isinstance(entries, list):
            return
        await _sync_all(
            str(e.get("agent_did", "")) for e in entries if isinstance(e, dict)
        )


# ----------------------------------------------------------------------- module API

_instance: Optional[BalanceSyncReactor] = None
_ledger_instance: Optional[LedgerBalanceSyncReactor] = None


async def start() -> None:
    global _instance, _ledger_instance
    if _instance is None:
        _instance = BalanceSyncReactor()
    await _instance.start()
    if _ledger_instance is None:
        _ledger_instance = LedgerBalanceSyncReactor()
    await _ledger_instance.start()


async def stop() -> None:
    global _instance, _ledger_instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
    if _ledger_instance is not None:
        await _ledger_instance.stop()
        _ledger_instance = None
