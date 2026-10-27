"""§ENFPROP — an agent's ENFORCEMENT state travels with its CARD (the bond pattern, R55's enforcement half).

MEASURED 2026-09-05 (§BATCH4 item 8, on the sandbox pair): a suspension never reached a mirror. Structural,
not a bug in one place — the card is untouched by a suspension, the federation feed exports `WHERE is_active`
(so a deleted agent's card, deactivated, is never exported again), the peer upsert never applies `is_active`,
and a pull cannot remove. The peer's discover hid the probe only through the bond gate.

The fix is the shape §REPBOND already proved for the bond:
  1. the state is DERIVED onto the card as an A2A extension at the two export points (the federation feed and
     the well-known card) — never persisted into card_data, so the home's row stays the only truth;
  2. every state change TOUCHES the agent's native card, so a peer's INCREMENTAL pull re-fetches it;
  3. ONE predicate, on the agents row for local truth and on the card's extension for a mirror, applied at
     the SAME six sites as the bond behind `ENFORCEMENT_PROPAGATION_MODE` (off | shadow | enforce);
  4. a deletion (status `revoked`, card deactivated) is exported as a TOMBSTONE for a window, and the peer
     upsert applies `is_active=False` to a mirror it already holds (never to a native card, never an insert).

What travels is the STATUS and a coarse `since`, never the free-text reason (that is the home's business).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence, Tuple

from fastapi import HTTPException, status as http_status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.core import network_profile as _np

logger = logging.getLogger(__name__)

ENFORCEMENT_EXTENSION_URI = "https://theprotocol.cloud/extensions/v1/enforcement"
MODES = ("off", "shadow", "enforce")
ENFORCED = ("suspended", "revoked")
GATE_SITES = ("discovery", "listing", "pricing", "guild_bid", "contract_accept", "a2a_payee")
TOMBSTONE_WINDOW_DAYS = 30

try:  # the counter is optional (tests import the module without a registry)
    from prometheus_client import Counter as _Counter
    GATE_DECISIONS = _Counter(
        "registry_enforcement_propagation_gate_total",
        "§ENFPROP gate decisions per site (allow / refuse / unknown / skipped) and mode",
        ["site", "mode", "decision"],
    )
    TOMBSTONES_APPLIED = _Counter(
        "registry_federation_tombstones_applied_total",
        "§ENFPROP mirrors deactivated because the home exported the card as a tombstone",
    )
except Exception:  # noqa: BLE001
    GATE_DECISIONS = None
    TOMBSTONES_APPLIED = None


# ── the knob ────────────────────────────────────────────────────────────────

def propagation_mode() -> str:
    """`ENFORCEMENT_PROPAGATION_MODE`: env → network profile → "shadow". An unknown value falls to
    shadow (count + log, never refuse), never to enforce."""
    v = (_np.knob("ENFORCEMENT_PROPAGATION_MODE", "shadow") or "shadow").strip().lower()
    return v if v in MODES else "shadow"


def registry_display_name() -> str:
    try:
        from agentvault_registry.services.reputation_bond import registry_display_name as _rdn
        return _rdn()
    except Exception:  # noqa: BLE001
        return "registry"


# ── pure helpers ─────────────────────────────────────────────────────────────

def is_enforced_status(status: Optional[str]) -> bool:
    return (status or "").strip().lower() in ENFORCED


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def extension_entry(state: Dict[str, Any]) -> Dict[str, Any]:
    """The card-carried block. `state` = {"status", "since", "registry"} (see `card_states`)."""
    return {
        "uri": ENFORCEMENT_EXTENSION_URI,
        "required": False,
        "description": "Enforcement state stamped by the agent's home registry",
        "params": {
            "version": 1,
            "status": state.get("status"),
            "since": state.get("since"),
            "registry": state.get("registry") or registry_display_name(),
        },
    }


def inject_extension(card: Dict[str, Any], state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Derive-time: strip any stale enforcement extension, add the current one when ENFORCED.
    A reinstated agent therefore exports a card WITHOUT the block, and the touch that follows the
    reinstatement makes every peer re-pull that clean card. Never persisted into card_data."""
    if not isinstance(card, dict):
        return card
    exts = [e for e in (card.get("extensions") or [])
            if not (isinstance(e, dict) and e.get("uri") == ENFORCEMENT_EXTENSION_URI)]
    if state and is_enforced_status(state.get("status")):
        exts.append(extension_entry(state))
    if exts:
        card["extensions"] = exts
    elif "extensions" in card:
        card["extensions"] = []
    return card


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


def extension_from_card(card_data: Any) -> Optional[Dict[str, Any]]:
    for ext in (_as_dict(card_data).get("extensions") or []):
        if isinstance(ext, dict) and ext.get("uri") == ENFORCEMENT_EXTENSION_URI:
            p = ext.get("params") or {}
            return p if isinstance(p, dict) else None
    return None


# ── the ONE predicate, in SQL (both truths) ──────────────────────────────────

_EXT_PATH = "'$.extensions[*] ? (@.uri == \"" + ENFORCEMENT_EXTENSION_URI + "\")'"


def sql_is_enforced(agent_alias: str = "a", card_alias: str = "s") -> str:
    """`agent_alias` = the agents row (local truth), `card_alias` = the card row whose card_data may
    carry the home's extension (a mirror). TRUE when the agent is suspended or revoked either way."""
    ext = "jsonb_path_query_first(" + card_alias + ".card_data::jsonb, " + _EXT_PATH + ")"
    return (
        "(COALESCE(" + agent_alias + ".status, '') IN ('suspended','revoked')"
        " OR COALESCE(" + ext + "->'params'->>'status', '') IN ('suspended','revoked'))"
    )


def sql_card_is_enforced(card_alias: str = "c") -> str:
    """Population-level predicate for a CTE that has ONLY the card row."""
    ext = "jsonb_path_query_first(" + card_alias + ".card_data::jsonb, " + _EXT_PATH + ")"
    return (
        "(EXISTS (SELECT 1 FROM agents ab WHERE ab.did = " + card_alias + ".agent_did"
        " AND ab.status IN ('suspended','revoked'))"
        " OR COALESCE(" + ext + "->'params'->>'status', '') IN ('suspended','revoked'))"
    )


# ── loading ──────────────────────────────────────────────────────────────────

async def card_states(db: AsyncSession, dids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """Batch, for the export: the local agents rows' status for these DIDs. Only ENFORCED ones are
    returned (the rest need no block). `since` = the row's updated_at (the last status change moves it)."""
    ids = [d for d in dids if d]
    if not ids:
        return {}
    # `agents` carries no updated_at; the native card's updated_at IS the moment of the last flip
    # (every flip touches the card — that is the whole mechanism), so it is the honest `since`.
    res = await db.execute(text(
        "SELECT a.did, a.status, MAX(c.updated_at) FROM agents a "
        "LEFT JOIN agent_cards c ON c.agent_did = a.did "
        "AND (c.card_data#>>'{federation_metadata,source_registry}') IS NULL "
        "WHERE a.did = ANY(:dids) AND a.status IN ('suspended','revoked') GROUP BY a.did, a.status"
    ), {"dids": ids})
    reg = registry_display_name()
    return {r[0]: {"status": r[1], "since": _iso(r[2]), "registry": reg} for r in res.fetchall()}


async def card_state(db: AsyncSession, did: str) -> Optional[Dict[str, Any]]:
    return (await card_states(db, [did])).get(did)


async def is_enforced_did(db: AsyncSession, did: str) -> Optional[bool]:
    """Local row first (the truth), else the newest active card's extension (a mirror), else None
    (a DID this registry cannot see — the third state, never collapsed into False)."""
    res = await db.execute(text("SELECT status FROM agents WHERE did = :did LIMIT 1"), {"did": did})
    row = res.fetchone()
    if row is not None:
        return is_enforced_status(row[0])
    res = await db.execute(text(
        "SELECT card_data FROM agent_cards WHERE agent_did = :did AND is_active = TRUE ORDER BY updated_at DESC LIMIT 1"
    ), {"did": did})
    row = res.fetchone()
    if row is None:
        return None
    p = extension_from_card(row[0]) or {}
    return is_enforced_status(p.get("status"))


async def enforcement_block(db: AsyncSession, did: str) -> Dict[str, Any]:
    """For `/agents/{did}/reputation`: what this registry knows, and from where."""
    res = await db.execute(text("SELECT status FROM agents WHERE did = :did LIMIT 1"), {"did": did})
    row = res.fetchone()
    if row is not None:
        st = (row[0] or "active").lower()
        since = (await card_state(db, did) or {}).get("since") if is_enforced_status(st) else None
        return {"status": st, "is_enforced": is_enforced_status(st), "since": since,
                "registry": registry_display_name(), "source": "registry", "mode": propagation_mode()}
    res = await db.execute(text(
        "SELECT card_data FROM agent_cards WHERE agent_did = :did ORDER BY is_active DESC, updated_at DESC LIMIT 1"
    ), {"did": did})
    row = res.fetchone()
    p = (extension_from_card(row[0]) if row is not None else None) or {}
    st = (p.get("status") or "active").lower()
    return {"status": st, "is_enforced": is_enforced_status(st), "since": p.get("since"),
            "registry": p.get("registry"), "source": "card", "mode": propagation_mode()}


# ── the card must MOVE when the status moves ────────────────────────────────

async def touch_native_card_no_commit(db: AsyncSession, did: str) -> int:
    """Same rule as `reputation_bond.touch_native_card`, but on the CALLER's transaction: the
    coordinated suspend/reinstate rails mutate the agent in-session and the route commits — the touch
    must land in that same commit, never before it. Returns the rows moved (0 = no native card here)."""
    try:
        res = await db.execute(text(
            "UPDATE agent_cards SET updated_at = NOW() WHERE agent_did = :did AND is_active = TRUE "
            "AND (card_data#>>'{federation_metadata,source_registry}') IS NULL"
        ), {"did": did})
        n = int(res.rowcount or 0)
        logger.info("[ENFPROP] %s: %d native card(s) touched for the peers", did, n)
        return n
    except Exception as e:  # noqa: BLE001 — a stale mirror is a delay; the enforcement itself already happened
        logger.error("[ENFPROP] card touch failed for %s: %s", did, e)
        return 0


# ── the gate ─────────────────────────────────────────────────────────────────

def _count(site: str, mode: str, decision: str) -> None:
    if GATE_DECISIONS is not None:
        try:
            GATE_DECISIONS.labels(site=site, mode=mode, decision=decision).inc()
        except Exception:  # noqa: BLE001
            pass


def _refusal(did: str, site: str, block: Dict[str, Any]) -> str:
    st = block.get("status") or "enforced"
    home = block.get("registry") or "its home registry"
    since = f" since {block['since']}" if block.get("since") else ""
    return (f"Agent {did} is {st} by {home}{since}; {site} is refused while the enforcement stands "
            f"(ENFORCEMENT_PROPAGATION_MODE=enforce).")


async def decide(db: AsyncSession, did: str, *, site: str,
                 mode: Optional[str] = None) -> Tuple[Dict[str, Any], Optional[str]]:
    """The enforcement gate's decision at one site, and the sentence it refuses with under enforce
    (None when it lets the DID through, or only counts it in shadow). No counter and no log: `gate`
    applies this, and a preview (the buy door's quote, the public showcase: D6-831/832) asks it
    without adding a decision to the gate's counters."""
    if site not in GATE_SITES:
        raise ValueError(f"unknown gate site {site!r}")
    m = mode or propagation_mode()
    if m == "off":
        return {"site": site, "mode": m, "decision": "skipped", "enforced": None}, None
    enforced = await is_enforced_did(db, did)
    decision = "allow" if not enforced else "refuse"
    if enforced is None:
        decision = "unknown"
    if decision in ("allow", "unknown"):
        return {"site": site, "mode": m, "decision": decision, "enforced": enforced}, None
    out = {"site": site, "mode": m, "decision": decision, "enforced": True}
    if m != "enforce":
        return out, None
    return out, _refusal(did, site, await enforcement_block(db, did))


async def gate(db: AsyncSession, did: str, *, site: str, mode: Optional[str] = None) -> Dict[str, Any]:
    """Apply the enforcement gate at one site. off → nothing; shadow → count + log; enforce → refuse
    a suspended/revoked agent with the sentence. A DID this registry cannot see is ALLOWED here (the
    bond gate already refuses unknown providers under enforce; this gate speaks only to what it knows).
    The decision and its sentence are `decide`'s, so a preview and the gate cannot disagree."""
    out, why = await decide(db, did, site=site, mode=mode)
    if out["decision"] == "skipped":
        return out
    _count(site, out["mode"], out["decision"])
    if out["decision"] in ("allow", "unknown"):
        return out
    if why:
        raise HTTPException(http_status.HTTP_403_FORBIDDEN, detail=why)
    logger.info("[ENFPROP shadow] %s would be refused at %s (enforced)", did, site)
    return out


__all__ = [
    "ENFORCEMENT_EXTENSION_URI", "MODES", "ENFORCED", "GATE_SITES", "TOMBSTONE_WINDOW_DAYS",
    "propagation_mode", "is_enforced_status", "extension_entry", "inject_extension", "extension_from_card",
    "sql_is_enforced", "sql_card_is_enforced", "card_states", "card_state", "is_enforced_did",
    "enforcement_block", "touch_native_card_no_commit", "decide", "gate",
]
