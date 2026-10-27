"""
Reactor: settlement events → one Bayesian peer-trust observation
=================================================================
§TRUSTWIRE (2026-09-10). The registry's Beta(alpha, beta) peer-trust model
(`services/bayesian_trust.py`) had a decay half and no evidence half:
`record_interaction()` had NO CALLER anywhere in the tree, so after days of live
federation every peer row read `total_interactions=0, discount=1.0,
last_interaction_at=NULL`, and the single live behaviour of the registry's peer-trust
system was to pull healthy peers toward 0.5 for want of evidence it was never given
the chance to collect.

🔴 WHY THIS IS A REACTOR AND NOT A CALL SITE. The first fix wired the observation
into the synchronous cross-registry branch. The node it was meant to fix runs
`TEG_CROSS_FRAME_BACKEND=async`, where that branch is never reached. The second fix
wired the async settlement path. Then a real 0.01 transfer settled `200 completed`
and the peer row still did not move, because there is a THIRD path — the FX pool
swap — and it is the only one that runs BETWEEN FRAMES: every frame pair on this
network has a different currency (AVT · JDAY · BVT · ECU · ACU), so every
frame-to-frame transfer is cross-currency. Three sibling settlement paths, three
fixes, each revealing the next. Hand-wiring call sites was the defect.

All of them EMIT. That is the choke point:

    FxSwapSettled                    the FX pool swap (cross-currency, frame↔frame)
    CrossFrameTransferSettled        the async saga, at the locked → settled flip
    CrossRegistryTransferCompleted   the sync same-currency path AND each FX route hop

One settlement can announce itself through more than one of these (the sync
cross-frame path emits Completed AND Settled for the same transfer_id), and every one
of them is replicated to peers, so the same settlement arrives here several times over.
Dedup is therefore on the SETTLEMENT, not on the event: `(settlement_id, peer_id)`.

Deliberately NOT recorded here: refunds. A saga timeout or a stranded FX hop is
usually our own clock, not peer misbehaviour, and an observation of a failure that was
not the peer's is worse than no observation. The negative half of the model belongs to
the dispute rail (`routers/federation_disputes.py`), which records a lost dispute.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select

from .. import models
from ..database import get_db_context
from .leader import get_redis
from .reactor_base import EventStoreReactor

logger = logging.getLogger(__name__)

# How long a recorded settlement stays deduped. Replication lands within minutes; a week
# is a wide margin that still lets the key expire rather than growing without bound.
_DEDUP_TTL_SECONDS = int(os.environ.get("PEER_TRUST_OBSERVATION_TTL_SEC", str(7 * 24 * 3600)))

# 🔴 THE BARE `teg-layer` IDENTIFIES NOBODY. Measured 2026-09-10: frame-b, frame-c, EU and
# ASIA all run with `LOCAL_TEG_ID=teg-layer`, so four registries stamp the same string into
# `source_teg`. Only registry-a stamps something specific (`teg-layer-a`). A resolver that
# treated this as a name would map every frame onto whichever peer happened to sort first —
# the same class as the FX sidecar map that silently cross-frame mis-routed on this exact
# string. It is not a name; it is the absence of one, and it is treated as such.
_AMBIGUOUS_TEG_IDS = {"", "teg-layer", "teg", "teg-layer-"}


def _local_trust_domain() -> str:
    return (os.getenv("SPIRE_TRUST_DOMAIN", "") or "").strip().lower()


def _norm(value: Optional[str]) -> str:
    """Normalise a registry name so the shapes that mean one registry compare equal.

    Peer rows hold display case (`Registry-A`, `Frame-B`, `Sandbox Beta`) while TEG ids and SPIFFE paths hold
    lowercase, and some carriers prefix `registry-`. Hostnames are case-insensitive by RFC 4343 and these follow the
    same rule.

    §SUITES1018 / §FEDPROOF F2 (2026-10-18): ONE normalizer, the TEG partner rule's (`core/operator_names.peer_key`:
    lower case, one teg-layer-, teg- or registry- prefix dropped, letters and digits only). This used to lowercase and
    drop `registry-` only, so `Sandbox Beta` (the frame's REGISTRY_NAME) became `sandbox beta` while every sender names
    that frame's TEG `teg-layer-sandbox-beta` (`sandbox-beta`): the receiving frame never recognised its own side of an
    inbound FX settlement and filed every one as a third party's (measured on sbx-beta: settlement f68c7693, replicated
    at 12:30:04Z, dispatched at 12:30:21Z, no observation). SEC-23 refuses an operator name that collides with a peer by
    this same key, so one key cannot name two registries the network knows.
    """
    from ..core.operator_names import peer_key
    return peer_key(value)


def _peer_key_from_teg(teg_id: Optional[str]) -> Optional[str]:
    """`teg-layer-frame-b` → `frameb` · `teg-op-doha` → `opdoha` · `teg-layer` → None.

    Both prefixes are live on this network: frames and their operators are provisioned by
    different generations of the provisioner (`teg-layer-op-berlin` beside `teg-amsterdam`).
    Returns None for anything that names no particular registry — see _AMBIGUOUS_TEG_IDS (checked first: the
    normalizer alone would read the bare `teg-layer` as `layer`, a name nobody may take since SEC-21).
    """
    t = (teg_id or "").strip().lower()
    if t in _AMBIGUOUS_TEG_IDS:
        return None
    return _norm(t) or None


def observation_key(settlement_id: str, peer_id: int) -> str:
    """The claim that one settlement was counted for one peer row (the dedup key, 7 days). One writer (the reactor's
    `_claim`) and one reader (`GET /admin/federation/peer-trust?settlement_id=`, which says for which rows a given
    settlement was counted, so a test can attribute a counter's movement to its own settlement rather than to any
    traffic that moved the same counter: §SUITES1018)."""
    return f"peer_trust_obs:{os.getenv('REGISTRY_NAME', 'registry')}:{settlement_id}:{peer_id}"


_local_keys_cache: Optional[set] = None
_local_teg_named_cache: Optional[bool] = None


def _local_teg_is_nameable() -> bool:
    """Could a settlement payload name THIS registry by its TEG id?

    True on registry-a (`teg-layer-a`) and on every cloud operator (`teg-amsterdam`,
    `teg-op-doha`); False on frame-b, frame-c, EU and ASIA, which all stamp the bare `teg-layer`.
    The distinction decides whether this node may claim a side the payload did not name — see
    `_Side.is_local`.
    """
    global _local_teg_named_cache
    if _local_teg_named_cache is None:
        try:
            from ..routers.teg_integration import _get_local_teg_id
            _local_teg_named_cache = _peer_key_from_teg(_get_local_teg_id()) is not None
        except Exception:  # noqa: BLE001
            _local_teg_named_cache = False
    return _local_teg_named_cache


def _local_peer_keys() -> set:
    """The names by which THIS registry would appear in a peer's carrier.

    Memoised: the answer comes from process env, which does not change while the process runs,
    and the TEG-id branch imports a very large router module.
    """
    global _local_keys_cache
    if _local_keys_cache is not None:
        return _local_keys_cache
    keys = set()
    for env in ("REGISTRY_FEDERATION_NAME", "REGISTRY_NAME"):
        k = _norm(os.getenv(env))
        if k:
            keys.add(k)
    # The local TEG id, but only when it names something. On four of the five frames it does
    # not (see _AMBIGUOUS_TEG_IDS), which is precisely why the frame fields carry the weight.
    try:
        from ..routers.teg_integration import _get_local_teg_id
        k = _peer_key_from_teg(_get_local_teg_id())
        if k:
            keys.add(k)
    except Exception:  # noqa: BLE001 — identity is best-effort; the trust domain still binds
        pass
    _local_keys_cache = keys
    return keys


class _Side:
    """One end of a settlement, as the payload describes it."""

    __slots__ = ("frame", "key", "label")

    def __init__(self, frame: Optional[str], teg: Optional[str]) -> None:
        self.frame = (frame or "").strip().lower() or None
        self.key = _peer_key_from_teg(teg)
        self.label = self.key or self.frame or "?"

    def is_local(self, local_td: str, local_keys: set) -> bool:
        """Is THIS side of the settlement us?

        🔴 THE TRUST DOMAIN IS NOT A PER-REGISTRY IDENTITY ON THIS NETWORK. A cloud operator
        shares its parent frame's trust domain (`amsterdam` and `EU` are both
        `eu.theprotocol.cloud`) AND has no EventStore of its own — `EVENT_STORE_URL` on amsterdam
        is EU's ledger — so the operator's reactor reads its parent's events and sees them as
        local. A naive `frame == our trust domain` test therefore made amsterdam claim EU's
        settlements with ASIA as its own, and would have published a peer-interaction count for
        transfers it took no part in. Caught by reading the operator's env before rolling to it,
        not by anything that would have failed loudly afterwards.

        So: a side the payload names SPECIFICALLY is us only if it names US. A side the payload
        does NOT name may be claimed only by a node the payload could not have named — the four
        frames that stamp the bare `teg-layer`. An operator, which is always nameable, never
        claims an unnamed side.
        """
        if self.key:
            return self.key in local_keys
        if self.frame and local_td and self.frame == local_td:
            return not _local_teg_is_nameable()
        return False

    def __bool__(self) -> bool:
        return bool(self.frame or self.key)


def _sides(event_type: str, d: Dict[str, Any]) -> Tuple[Optional[str], _Side, _Side]:
    """(settlement_id, source side, destination side) for one settlement event.

    Every field name here was read off a LIVE payload, not off the emitter's signature — the
    FX emitter's keyword arguments are `sender_did`/`receiver_did` while the stored keys are
    `from`/`to`, and `CrossRegistryTransferCompleted` has a second, thinner shape that carries
    no counterparty at all.
    """
    if event_type == "FxSwapSettled":
        return (
            d.get("swap_id"),
            _Side(d.get("source_frame"), d.get("source_teg")),
            _Side(d.get("dest_frame"), d.get("dest_teg")),
        )
    if event_type == "CrossFrameTransferSettled":
        return (
            d.get("transfer_id"),
            _Side(d.get("source_frame"), None),
            _Side(d.get("target_frame"), None),
        )
    if event_type == "CrossRegistryTransferCompleted":
        return (
            d.get("transfer_id"),
            _Side(None, d.get("source_teg")),
            _Side(None, d.get("target_teg")),
        )
    return None, _Side(None, None), _Side(None, None)


async def _resolve_peer(db, side: _Side) -> Tuple[Optional[Any], str]:
    """Resolve one side of a settlement to an ACTIVE peer row. Returns (peer, how).

    Two recognisers, most specific first, and NEITHER of them guesses:

      name   — from the counterparty's TEG id. Exact and unambiguous when present.
      domain — from the trust domain, when exactly one ACTIVE peer of type `frame` carries
               it. Several rows share a domain (registry-a holds Frame-B beside four
               `discovered` operators under `frame-b.theprotocol.cloud`), and a settlement
               addressed by domain alone is a settlement with that domain's FRAME; an
               operator counterparty always carries its own TEG id and is caught above.

    ⚠ Every lookup is ordered and ACTIVE-only. The registry-card fan-out re-inserts peer
    frames under their UPPERCASE card name and those ghosts are deactivated, never deleted
    (ASIA holds `EU` beside `eu`), so an unordered `LIMIT 1` here is a lottery — §XFRAMETD.
    """
    if side.key:
        rows = (await db.execute(
            select(models.PeerRegistry)
            .where(models.PeerRegistry.status == "ACTIVE")
            .order_by(models.PeerRegistry.name, models.PeerRegistry.id)
        )).scalars().all()
        for p in rows:
            if _norm(p.name) == side.key:
                return p, "name"

    if side.frame:
        frames = (await db.execute(
            select(models.PeerRegistry)
            .where(
                models.PeerRegistry.status == "ACTIVE",
                models.PeerRegistry.peer_type == "frame",
            )
            .order_by(models.PeerRegistry.name, models.PeerRegistry.id)
        )).scalars().all()
        hits = [p for p in frames if (p.trust_domain or "").strip().lower() == side.frame]
        if len(hits) == 1:
            return hits[0], "domain"
        if len(hits) > 1:
            return None, f"domain-ambiguous({len(hits)})"

    return None, "unresolved"


async def _crossframe_counterparty(db, d: Dict[str, Any]) -> Tuple[Optional[_Side], str]:
    """The counterparty of a `CrossFrameTransferSettled`, taken from OUR OWN records.

    🔴 THIS EVENT NAMES ONLY TRUST DOMAINS, AND EVERY TRUST DOMAIN HERE IS SHARED. registry-a
    sits in `agentvault.com` beside five cloud operators; amsterdam sits in
    `eu.theprotocol.cloud` beside EU. Worse, an operator has no EventStore of its own and writes
    to its parent's, so `target_frame == our trust domain` cannot even distinguish "we settled
    this" from "the registry next door did". Inferring participation from the payload is guessing.

    Our own tables can answer it exactly and locally: the SENDER holds the `cross_frame_transfers`
    row (this is what the async settlement reactor already updates), the RECEIVER holds the
    `cross_frame_transfers_inbound` row, and a node that holds neither simply was not in it.
    """
    tid = d.get("transfer_id")
    if not tid:
        return None, "no transfer_id"
    row = await db.get(models.CrossFrameTransfer, tid)
    if row is not None and row.target_frame:
        return _Side(row.target_frame, None), "own-outbound-row"
    inbound = await db.get(models.CrossFrameTransferInbound, tid)
    if inbound is not None and inbound.source_frame:
        return _Side(inbound.source_frame, None), "own-inbound-row"
    return None, "no local row for this transfer — we were not a party to it"


class _PeerTrustObservedReactor(EventStoreReactor):
    """Shared handler. One implementation; the subclasses below only name a channel.

    The base class subscribes one reactor to one event type (`events:<type>` on the WS bus,
    one leader key, one dedup ring), so three settlement events mean three instances — but of
    ONE class, which is the whole point: the defect this replaces was three DIFFERENT
    implementations at three call sites.
    """

    # Counters, so "no observations" can be told apart from "ten it could not attribute".
    _counts: Dict[str, int]

    def __init__(self) -> None:
        super().__init__()
        self._counts = {"recorded": 0, "duplicate": 0, "third_party": 0,
                        "unresolved": 0, "dropped": 0}

    def _tally(self, outcome: str, detail: str) -> None:
        self._counts[outcome] = self._counts.get(outcome, 0) + 1
        n = self._counts[outcome]
        # A skip that says nothing is indistinguishable from a reactor that is not running
        # (§DISCMIX). Detail at DEBUG for every one; a roll-up at INFO so a quiet rail still
        # states what it withheld and why.
        logger.debug(f"[Reactor:{self.name}] peer trust {outcome}: {detail}")
        if outcome != "recorded" and n % 25 == 0:
            logger.info(
                f"[Reactor:{self.name}] peer trust totals — "
                + ", ".join(f"{k}={v}" for k, v in sorted(self._counts.items()))
                + f" (latest {outcome}: {detail})"
            )

    async def _claim(self, settlement_id: str, peer_id: int) -> str:
        """Claim this settlement for this peer exactly once.

        Returns "claimed" · "duplicate" · "unavailable" — three states, not two. ⚠ IT USED TO
        RETURN A BOOL, and the caller then said "already counted" about a Redis failure: an
        instrument reporting a cause it had not established, in the one file whose whole subject
        is not guessing. A dropped observation and a genuine duplicate are different facts.

        Keyed on the SETTLEMENT and not on the event id, because one settlement announces
        itself through more than one event type (the sync cross-frame path emits both
        Completed and Settled for the same transfer_id) and every one of those is replicated
        to peers and arrives here again with a different event id. The reactor framework's own
        dedup ring keys on event_id and cannot see either.

        ⚠ Redis unavailable ⇒ this returns False and the observation is DROPPED, deliberately.
        `total_interactions` is rendered on the peer card, so over-counting publishes a wrong
        number while under-counting merely delays a Beta update that the next settlement will
        supply. The reactor is leader-elected through the same Redis, so in practice a Redis
        outage has already stopped this handler from running at all.
        """
        r = await get_redis()
        if r is None:
            return "unavailable"
        key = observation_key(settlement_id, peer_id)
        try:
            claimed = await r.set(key, "1", ex=_DEDUP_TTL_SECONDS, nx=True)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[Reactor:{self.name}] claim failed for {settlement_id}: {e}")
            return "unavailable"
        return "claimed" if claimed else "duplicate"

    async def handle_event(self, event_data: dict) -> None:
        d = event_data or {}
        settlement_id, src, dst = _sides(self.event_type, d)
        if not settlement_id:
            self._tally("unresolved", f"{self.event_type} without a settlement id")
            return
        if not src and not dst:
            # The thin CrossRegistryTransferCompleted shape (`{to, memo, transfer_id}`) names
            # no counterparty at all. Nothing to attribute; say so rather than guess.
            self._tally("unresolved", f"{settlement_id}: payload names no counterparty")
            return

        if self.event_type == "CrossFrameTransferSettled":
            async with get_db_context() as db:
                other, how = await _crossframe_counterparty(db, d)
                if other is None:
                    self._tally("unresolved", f"{settlement_id}: {how}")
                    return
                peer, rhow = await _resolve_peer(db, other)
                if peer is None:
                    self._tally("unresolved", f"{settlement_id}: no ACTIVE peer for {other.label} ({rhow})")
                    return
                await self._record(db, peer, settlement_id, f"{how}+{rhow}")
            return

        local_td = _local_trust_domain()
        local_keys = _local_peer_keys()
        # Injected by reactor_base: present ⇒ a peer emitted this and it reached us through
        # the replicator. Absent ⇒ we emitted it, so we are a participant by construction.
        foreign_from = d.get("_foreign_frame_id")

        src_is_me = src.is_local(local_td, local_keys)
        dst_is_me = dst.is_local(local_td, local_keys)

        if src_is_me and dst_is_me:
            # Both ends inside our own trust domain (a frame and one of its operators). The
            # payload cannot say which of them is the counterparty. The same settlement's
            # CrossRegistryTransferCompleted carries specific TEG ids and resolves; this one
            # waits for it rather than picking.
            self._tally("unresolved", f"{settlement_id}: both ends read as local ({local_td})")
            return

        if src_is_me:
            other = dst
        elif dst_is_me:
            other = src
        elif foreign_from:
            # A peer emitted it and neither end is us: two other registries settling with each
            # other, overheard through replication. Not our observation to make.
            self._tally("third_party", f"{settlement_id}: {src.label} → {dst.label} (via {foreign_from})")
            return
        else:
            # WE emitted this event, so we ARE one of the two ends even though our identity
            # string is not in the payload — four of five frames stamp the bare `teg-layer`.
            # The end that resolves to one of our own peer rows is the counterparty; the other
            # end is us. This inference is available only because the event is local.
            other = None

        async with get_db_context() as db:
            if other is None:
                src_peer, src_how = await _resolve_peer(db, src)
                dst_peer, dst_how = await _resolve_peer(db, dst)
                if src_peer is not None and dst_peer is None:
                    peer, how = src_peer, f"{src_how}/local-emit"
                elif dst_peer is not None and src_peer is None:
                    peer, how = dst_peer, f"{dst_how}/local-emit"
                else:
                    self._tally(
                        "unresolved",
                        f"{settlement_id}: locally emitted but {src.label}→{dst.label} "
                        f"resolves to {'two peers' if src_peer is not None else 'none'}",
                    )
                    return
            else:
                peer, how = await _resolve_peer(db, other)
                if peer is None:
                    self._tally("unresolved", f"{settlement_id}: no ACTIVE peer for {other.label} ({how})")
                    return

            await self._record(db, peer, settlement_id, how)

    async def _record(self, db, peer, settlement_id, how: str) -> None:
        """Claim the settlement, then feed the one observation. Shared by both channels."""
        claim = await self._claim(str(settlement_id), int(peer.id))
        if claim == "duplicate":
            self._tally("duplicate", f"{settlement_id} already counted for '{peer.name}'")
            return
        if claim != "claimed":
            self._tally("dropped", f"{settlement_id} for '{peer.name}': no dedup store, so the "
                                   f"observation is DROPPED rather than risk counting it twice")
            return

        try:
            from ..services.bayesian_trust import get_bayesian_trust_service
            await get_bayesian_trust_service().record_interaction(db, peer.id, success=True)
        except Exception as e:  # noqa: BLE001 — a trust counter must never break settlement
            logger.warning(
                f"[Reactor:{self.name}] peer trust: recording {settlement_id} for "
                f"'{peer.name}' failed (non-fatal, the observation is LOST): {e}"
            )
            return

        self._counts["recorded"] = self._counts.get("recorded", 0) + 1
        logger.info(
            f"[Reactor:{self.name}] peer trust: settled observation for '{peer.name}' "
            f"(via {how}, settlement {settlement_id})"
        )


class FxSwapSettledTrustReactor(_PeerTrustObservedReactor):
    event_type = "FxSwapSettled"
    leader_key = "reactor_peer_trust_fx_swap_settled"
    name = "PeerTrust:FxSwapSettled"


class CrossFrameSettledTrustReactor(_PeerTrustObservedReactor):
    event_type = "CrossFrameTransferSettled"
    leader_key = "reactor_peer_trust_cross_frame_settled"
    name = "PeerTrust:CrossFrameTransferSettled"


class CrossRegistryCompletedTrustReactor(_PeerTrustObservedReactor):
    event_type = "CrossRegistryTransferCompleted"
    leader_key = "reactor_peer_trust_cross_registry_completed"
    name = "PeerTrust:CrossRegistryTransferCompleted"


# The three settlement events this reactor observes. The test that COUNTS settlement paths
# reads this tuple: adding a fourth settlement event is one line here, not a fourth call site.
REACTOR_CLASSES = (
    FxSwapSettledTrustReactor,
    CrossFrameSettledTrustReactor,
    CrossRegistryCompletedTrustReactor,
)

# ----------------------------------------------------------------------- module API

_instances: List[_PeerTrustObservedReactor] = []


async def start() -> None:
    global _instances
    if not _instances:
        _instances = [cls() for cls in REACTOR_CLASSES]
    for inst in _instances:
        await inst.start()


async def stop() -> None:
    global _instances
    for inst in _instances:
        await inst.stop()
    _instances = []
