"""§LISTPROP — an agent's LISTING state travels with its card (the §ENFPROP shape, one step further).

MEASURED 2026-09-08 (on the live EU/ASIA cluster): unlisting an agent never reaches a peer's mirror.
The mechanism is the ABSENCE of a signal, and absence does not propagate — `crud_peer_registry`'s two
export selectors both filter `unlisted.is_(False)` (§DISCREFINE: "an unlisted agent never leaves this
registry"), so the moment an agent is unlisted its card simply STOPS being exported. A peer that
already holds the mirror is told nothing and keeps showing it, forever; a pull cannot remove.

The fix is §ENFPROP's, with one simplification and one hardening:

  1. SIMPLER than §ENFPROP: enforcement lives on the `agents` row, so §ENFPROP had to batch-load state
     and TOUCH the card to move its clock. Listing lives on the CARD ROW itself (`agent_cards.unlisted`),
     and `AgentCard.updated_at` carries `onupdate=func.now()` — so the flip moves the peer's cursor by
     construction. No touch rail, no batch state load on the fan-out: the loop already holds the row.
  2. The unlisted card is exported as a TOMBSTONE — an envelope carrying the DID and this extension and
     nothing else. Never the name, the description, the skills, the pricing or the URL: §DISCREFINE's
     posture is that an unlisted agent does not leave this registry, and a tombstone keeps that promise
     while still saying the ONE word a stale mirror needs to hear.
  3. On receive, the tombstone sets the MIRROR's `unlisted` column — never a native card, never an
     INSERT. The discover CTE already reads that column (`agent_cards.py`, the §DISCREFINE filter), so
     the page, the facets AND the tag counts all follow with no query change and no per-row jsonb scan
     on the hottest public rail.

🔴 THE TOMBSTONE IS DELIBERATELY SAFE FOR A PEER THAT DOES NOT SPEAK §LISTPROP. All four quadrants were
reasoned before it shipped, because a federation is never one version:
  · new peer, holds the mirror   → applies `unlisted=True` (below, before any timestamp gate). Correct.
  · new peer, no mirror          → "skipped". No hidden row is ever inserted. Correct.
  · OLD peer, holds the mirror   → `updated_at` is EPOCH and the body carries none of the fields that
                                   trip `has_new_fields`, so its upsert returns "skipped" and nothing
                                   changes. Stale, exactly as today — never a REGRESSION.
  · OLD peer, no mirror          → it may create a row from the envelope; `is_active=False` keeps that
                                   row out of discovery (the CTE filters `is_active`), and the body
                                   carries no name or content to leak.

What travels is one boolean and a coarse `since`. Never the reason, never the content.

🔴 §DARKSYNC (2026-09-22, his words "figure out why dark agents dont synch. fix it properly"): UNLISTED MEANS "NOT IN
DISCOVERY", NOT "NEVER LEAVES HOME". The tombstone made a discovery flag a federation gate: a card BORN unlisted (every
service account's agent since §FRAMELIC: canaries, clerks, listing funders, market makers) was never mirrored by any peer,
so everything that places an agent through the card mesh failed for it (a venue resolving a clerk's home: every operator
clerk's passport order 502'd). Measured on the sandbox: 19 of sbx-alpha's 21 unlisted natives absent on sbx-beta, 50 of
50 listed ones present. Now a puller that sends `listing_carry=true` receives the FULL card of an unlisted agent with this
block and the envelope's `unlisted: true` (which survives the v0.3 projection that strips extensions), stores the mirror
with its `unlisted` column set, and every discovery surface on both sides filters that column. A puller that does not ask
keeps receiving the tombstone, so a peer that does not speak §DARKSYNC can never create a LISTED mirror of a dark agent.

🔴 AND THE ONE THAT ONLY THE LIVE PROOF COULD FIND (2026-09-09). `FEDERATION_INGEST_FAIL_CLOSED=true`
is set on both frames; that gate asks whether an incoming card validates as an `AgentCard`, and a
tombstone deliberately is not one. Every tombstone EU exported was quarantined on arrival, silently,
while the export side logged success — 19 green unit tests, a green build gate and a green roll, and
the mirror never moved. The receive handling therefore sits ABOVE that gate, exempt because it
stores nothing: one boolean on a row we already hold, never card_data, never a native card, never an
insert. A capability is not shipped until it has been driven end to end on the real thing.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.core import network_profile as _np

logger = logging.getLogger(__name__)

LISTING_EXTENSION_URI = "https://theprotocol.cloud/extensions/v1/listing"
MODES = ("off", "shadow", "enforce")

#: The name an unlisted card wears on the wire. It is a placeholder, not the agent's name —
#: nothing downstream should ever render it, and a peer that does render it is showing a row
#: it should not have created.
TOMBSTONE_NAME = "(unlisted)"

#: A tombstone is stamped at the epoch ON PURPOSE — see the quadrant table above. The receiver
#: that speaks §LISTPROP reads the extension BEFORE any timestamp comparison, so the stamp costs
#: it nothing; the receiver that does not, deterministically declines to act on it.
TOMBSTONE_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

try:  # the counter is optional (tests import the module without a registry)
    from prometheus_client import Counter as _Counter
    LISTING_EVENTS = _Counter(
        "registry_listing_propagation_total",
        "§LISTPROP events per action and mode (exported / applied / relisted / refused_insert / shadow)",
        ["action", "mode"],
    )
except Exception:  # noqa: BLE001
    LISTING_EVENTS = None


# ── the knob ────────────────────────────────────────────────────────────────

def propagation_mode() -> str:
    """`LISTING_PROPAGATION_MODE`: env → network profile → "enforce". An unknown value falls to
    "shadow" (observe, never act), never silently to enforce.

    The default is ENFORCE and not, as §ENFPROP shipped, shadow — because the capability IS the
    propagation, and because it was measured inert on the day it shipped: 0 unlisted native cards
    and 0 unlisted mirrors on both live frames, so nothing changes until somebody unlists something.
    `off` restores the pre-§LISTPROP behaviour exactly (the export filter goes back to excluding
    unlisted cards), which is the rollback.
    """
    v = (_np.knob("LISTING_PROPAGATION_MODE", "enforce") or "enforce").strip().lower()
    return v if v in MODES else "shadow"


def registry_display_name() -> str:
    try:
        from agentvault_registry.services.reputation_bond import registry_display_name as _rdn
        return _rdn()
    except Exception:  # noqa: BLE001
        return "registry"


def count(action: str, mode: Optional[str] = None) -> None:
    if LISTING_EVENTS is not None:
        try:
            LISTING_EVENTS.labels(action=action, mode=mode or propagation_mode()).inc()
        except Exception:  # noqa: BLE001
            pass


# ── pure helpers ─────────────────────────────────────────────────────────────

def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _as_dict(card_data: Any) -> Dict[str, Any]:
    if isinstance(card_data, dict):
        return card_data
    if isinstance(card_data, (str, bytes)):
        try:
            v = json.loads(card_data)
            return v if isinstance(v, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def extension_entry(state: Dict[str, Any]) -> Dict[str, Any]:
    """The card-carried block. `state` = {"unlisted", "since", "registry"}."""
    return {
        "uri": LISTING_EXTENSION_URI,
        "required": False,
        "description": "Listing state stamped by the agent's home registry",
        "params": {
            "version": 1,
            "unlisted": bool(state.get("unlisted")),
            "since": state.get("since"),
            "registry": state.get("registry") or registry_display_name(),
        },
    }


def inject_extension(card: Dict[str, Any], state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Derive-time: strip any stale listing extension, add the current one ONLY when unlisted.

    A listed card therefore exports with NO block — which keeps every listed card byte-identical to
    what it was before §LISTPROP (no federation-wide re-write on the first sync after the roll) and
    makes a re-list detectable as the disappearance of the block. Never persisted into card_data.
    """
    if not isinstance(card, dict):
        return card
    exts = [e for e in (card.get("extensions") or [])
            if not (isinstance(e, dict) and e.get("uri") == LISTING_EXTENSION_URI)]
    if state and bool(state.get("unlisted")):
        exts.append(extension_entry(state))
    if exts:
        card["extensions"] = exts
    elif "extensions" in card:
        card["extensions"] = []
    return card


def extension_from_card(card_data: Any) -> Optional[Dict[str, Any]]:
    for ext in (_as_dict(card_data).get("extensions") or []):
        if isinstance(ext, dict) and ext.get("uri") == LISTING_EXTENSION_URI:
            p = ext.get("params") or {}
            return p if isinstance(p, dict) else None
    return None


def unlisted_from_card(card_data: Any) -> Optional[bool]:
    """TRUE when the home says unlisted, None when the card carries no listing block at all.

    ⚠ THE THIRD STATE IS REAL AND IT IS DELIBERATELY COLLAPSED BY THE CALLER, NOT HERE. None means
    two different things — "a §LISTPROP home says this card is listed" (no block, by design above)
    and "the home does not speak §LISTPROP" — and this function cannot tell them apart. The receive
    path may safely treat both as LISTED, but only because nothing else in the product ever sets
    `unlisted` on a MIRROR row: the column's only other writer is `crud.agent_card.create_agent_card`,
    which writes native cards. Collapse it anywhere that is not true and it becomes a bug.
    """
    p = extension_from_card(card_data)
    if p is None:
        return None
    return bool(p.get("unlisted"))


def is_legacy_tombstone(agent_card: Dict[str, Any]) -> bool:
    """§DARKSYNC: TRUE for the content-free §LISTPROP tombstone, FALSE for a full card whose home says unlisted.
    The tombstone keeps its old handling (flip the column on a mirror we hold, never insert); a full card is imported
    as an unlisted mirror. Shape, not a flag: the tombstone wears TOMBSTONE_NAME, is inactive, and its card_data holds
    nothing but the DID, the listing block and (relayed) the origin attribution."""
    if not isinstance(agent_card, dict):
        return False
    cd = _as_dict(agent_card.get("card_data"))
    return (agent_card.get("name") == TOMBSTONE_NAME and not bool(agent_card.get("is_active"))
            and set(cd.keys()) <= {"did", "extensions", "federation_metadata"})


# ── the export side ──────────────────────────────────────────────────────────

def tombstone_card_data(did: Optional[str], state: Dict[str, Any],
                        source_registry: Optional[str] = None) -> Dict[str, Any]:
    """The whole body of an unlisted card's export: the DID, the listing block, and the origin
    attribution the echo-prevention needs. Nothing else — see the module docstring."""
    body: Dict[str, Any] = {"extensions": [extension_entry(state)]}
    if did:
        body["did"] = did
    fed: Dict[str, Any] = {}
    if source_registry:
        # a RELAYED tombstone keeps naming its origin, so the mesh's echo-prevention still works
        # and a downstream peer applies it against the right home.
        fed["source_registry"] = source_registry
    if fed:
        body["federation_metadata"] = fed
    return body


def tombstone_state(since: Optional[datetime] = None, *, registry: Optional[str] = None) -> Dict[str, Any]:
    return {"unlisted": True, "since": _iso(since), "registry": registry or registry_display_name()}


def home_name(card_data: Any) -> Optional[str]:
    """The display name of the registry a card was born on, as the card itself carries it
    (`federation_metadata.origin_registry_name`, stamped once by the first export and never
    overwritten by a relay), or None when the card does not say."""
    fed = _as_dict(card_data).get("federation_metadata")
    name = fed.get("origin_registry_name") if isinstance(fed, dict) else None
    return name.strip() if isinstance(name, str) and name.strip() else None


def export_state(card_data: Any, since: Optional[datetime], *, relayed: bool) -> Dict[str, Any]:
    """The listing block's state for an unlisted card leaving through the fan-out.

    §ECHO-2 (2026-09-28, measured on the sandbox pair): the block says "stamped by the agent's home registry",
    but the fan-out stamped the EXPORTING registry's name on every unlisted card, relayed ones included. Two
    relays of the same mirror therefore disagreed on `registry`, the receiver's idempotency gate (which ignores
    only `since`) saw a change on every hop, each write re-stamped `updated_at` and made the copy "newer" for
    the next hop, and the mirror circled the mesh for good. Measured: the ten unlisted mirrors of four torn-down
    test frames rewritten on every 30 s tick on both frames; of the fields the gate compares, this name was the
    only one that differed.
    A relayed card now names its HOME, which every relay reads off the same card, so their copies agree and the
    gate settles. A native card names this registry, as before; a relayed card that does not say where it was
    born falls back to this registry's name (the old behaviour, so it is never worse than before).
    """
    return tombstone_state(since, registry=home_name(card_data) if relayed else None)


# ── the home's own truth, for the well-known export ──────────────────────────

async def card_states(db: AsyncSession, dids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """Batch: the listing state of this registry's NATIVE card for each DID, keyed by DID. Only the
    unlisted ones are returned (a listed card has no block to carry); per DID the newest active native
    card decides, as it always did for the single read (§TWOAGENT #10: the list reads need the batch)."""
    ids = [d for d in dids if d]
    if not ids:
        return {}
    res = await db.execute(text(
        "SELECT DISTINCT ON (agent_did) agent_did, unlisted, updated_at FROM agent_cards "
        "WHERE agent_did = ANY(:dids) AND is_active = TRUE "
        "AND (card_data#>>'{federation_metadata,source_registry}') IS NULL "
        "ORDER BY agent_did, updated_at DESC"
    ), {"dids": ids})
    return {r[0]: tombstone_state(r[2]) for r in res.fetchall() if bool(r[1])}


async def card_state(db: AsyncSession, did: str) -> Optional[Dict[str, Any]]:
    """The listing state of this registry's NATIVE card for `did`, or None when it is listed
    (or when there is no native card here). Only an unlisted card has a block to carry."""
    if not did:
        return None
    return (await card_states(db, [did])).get(did)


async def touch_native_card_no_commit(db: AsyncSession, did: str) -> int:
    """Kept for symmetry with §ENFPROP and for any future rail that flips the column WITHOUT
    updating the card row itself. The product's only flip today is `PUT /agent-cards/{id}/listing`,
    which writes `unlisted` ON the card row, so `AgentCard.updated_at`'s `onupdate` already moves
    the peer's cursor — `tests/test_listing_propagation.py` pins that, so this stays unused rather
    than becoming a second, redundant clock."""
    try:
        res = await db.execute(text(
            "UPDATE agent_cards SET updated_at = NOW() WHERE agent_did = :did AND is_active = TRUE "
            "AND (card_data#>>'{federation_metadata,source_registry}') IS NULL"
        ), {"did": did})
        return int(res.rowcount or 0)
    except Exception as e:  # noqa: BLE001 — a stale mirror is a delay, never a failure of the unlist
        logger.error("[LISTPROP] card touch failed for %s: %s", did, e)
        return 0


__all__ = [
    "LISTING_EXTENSION_URI", "MODES", "TOMBSTONE_NAME", "TOMBSTONE_EPOCH",
    "propagation_mode", "registry_display_name", "count",
    "extension_entry", "inject_extension", "extension_from_card", "unlisted_from_card", "is_legacy_tombstone",
    "tombstone_card_data", "tombstone_state", "home_name", "export_state",
    "card_state", "card_states", "touch_native_card_no_commit",
]
