"""V0657 (b), session-code 2026-11-06: an agent's ORGANIZATION travels with its card (orgs v2, items 1 to 3; the discovery
at room seq 1475, the Commander's answer at seq 1482).

Nothing about an organization left its registry: a peer could not tell which organization an agent belongs to, and the
only org-like field on a card was A2A's `provider.name`, free text any card's author types (any card can name any
organization). The organization is a fact of the agent's HOME registry, so it travels the way the bond, the
enforcement state and the listing state already travel (services/home_extensions.py):

  1. DERIVED at serve time as a top-level card extension, never persisted into card_data: at the federation feed, the
     well-known card and every read of a native card. A mirror keeps the copy its home served;
  2. every change TOUCHES the agent's native card (assign, move, unassign, the organization renamed, its logo changed,
     its listing turned on or off, it deleted, the agent's "show my org"), so a peer's incremental pull re-fetches it
     and the mark appears, changes or goes within two pull cycles;
  3. PRIVACY FIRST (item 2): it is stated only while the organization is listed (its setting `public_listing`, off by
     default) AND the agent shows it (`agents.show_org`, on by default). Otherwise the card carries no block at all,
     on its home's reads and on every peer, so no private affiliation is published;
  4. the logo is the one the home registry hosts (item 3), at an address under the home's own console origin; a
     `logo_url` on another host is never stated.

What travels: the organization's id, slug, name, logo address and its home (name, the console a person opens). Never
its members, settings, treasury or anything else.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Sequence

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

ORG_EXTENSION_URI = "https://theprotocol.cloud/extensions/v1/org"


def registry_display_name() -> str:
    try:
        from agentvault_registry.services.reputation_bond import registry_display_name as _rdn
        return _rdn()
    except Exception:  # noqa: BLE001
        return "registry"


def _origin() -> Optional[str]:
    """The browser-openable origin of this registry's console (its /api/ answers there too)."""
    try:
        from agentvault_registry.core.public_url import public_ui_origin
        return public_ui_origin()
    except Exception:  # noqa: BLE001
        return None


def _console() -> Optional[str]:
    try:
        from agentvault_registry.core.public_url import public_ui_url_static
        return public_ui_url_static()
    except Exception:  # noqa: BLE001
        return None


def logo_path(org_id: str, sha256: Optional[str]) -> Optional[str]:
    """Where this registry serves an organization's hosted logo (relative to its own origin), versioned by its bytes so
    a new upload is a new address (the old one is cached hard). None when it has no hosted logo."""
    if not org_id or not sha256:
        return None
    return f"/api/v1/organizations/{org_id}/logo?v={sha256[:12]}"


def home_block() -> Dict[str, Any]:
    """This registry as an organization's home: its name, its origin (where its hosted logos are) and its console."""
    return {"name": registry_display_name(), "origin": _origin(), "console": _console()}


def state_for(org_id: str, slug: str, name: str, sha256: Optional[str],
              home: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    home = home or home_block()
    path = logo_path(org_id, sha256)
    origin = home.get("origin")
    return {
        "id": str(org_id), "slug": slug, "name": name,
        # absolute, under the home's own origin: a peer's console loads it from the agent's home, never a third party
        "logo": (origin + path) if (path and origin) else None,
        "home": home,
        "page": (f"{home['console']}/#/firms?org={slug}" if home.get("console") and slug else None),
    }


def extension_entry(state: Dict[str, Any]) -> Dict[str, Any]:
    """The card-carried block."""
    return {
        "uri": ORG_EXTENSION_URI,
        "required": False,
        "description": "The agent's organization, stated by its home registry",
        "params": {"version": 1, **{k: state.get(k) for k in ("id", "slug", "name", "logo", "home", "page")}},
    }


def inject_extension(card: Dict[str, Any], state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Derive-time: strip any stale org block, add the current one when there is a mark to state. A card whose agent is
    in no listed organization (or hides it) exports with NO block, so an unlisted organization leaves no trace, and the
    mark's disappearance is the removal. Never persisted into card_data."""
    if not isinstance(card, dict):
        return card
    exts = [e for e in (card.get("extensions") or [])
            if not (isinstance(e, dict) and e.get("uri") == ORG_EXTENSION_URI)]
    if state:
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
    """The org block's params as the card carries them (a mirror's is its home's statement), or None."""
    for ext in (_as_dict(card_data).get("extensions") or []):
        if isinstance(ext, dict) and ext.get("uri") == ORG_EXTENSION_URI:
            p = ext.get("params") or {}
            return p if isinstance(p, dict) else None
    return None


# ── the home's own truth ────────────────────────────────────────────────────────────────────────────────────────────
_STATE_SQL = (
    "SELECT a.did, o.id, o.slug, o.name, l.sha256 FROM agents a "
    "JOIN organizations o ON o.id = a.organization_id "
    "LEFT JOIN organization_logos l ON l.organization_id = o.id "
    "WHERE a.did = ANY(:dids) AND o.is_active = TRUE AND a.show_org = TRUE "
    "AND ((o.settings->'public_listing')::text = 'true')"
)


async def card_states(db: AsyncSession, dids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """Batch: the organization mark to state for each DID, keyed by DID; only the agents whose organization is listed
    and who show it (the others carry no block). The same predicate as org_policy.listed_public, in SQL."""
    ids = [d for d in dids if d]
    if not ids:
        return {}
    rows = (await db.execute(text(_STATE_SQL), {"dids": ids})).fetchall()
    if not rows:
        return {}
    home = home_block()
    return {r[0]: state_for(r[1], r[2], r[3], r[4], home) for r in rows}


async def card_state(db: AsyncSession, did: str) -> Optional[Dict[str, Any]]:
    if not did:
        return None
    return (await card_states(db, [did])).get(did)


async def mark_for_did(db: AsyncSession, did: str) -> Optional[Dict[str, Any]]:
    """The organization mark of any agent this registry knows: a native agent's from the rows (the same rule its card
    follows), else the mark its newest active mirror carries (its home's statement), else None."""
    if not did:
        return None
    native = (await db.execute(text("SELECT 1 FROM agents WHERE did = :d"), {"d": did})).first()
    if native is not None:
        return await card_state(db, did)
    row = (await db.execute(text(
        "SELECT card_data FROM agent_cards WHERE agent_did = :d AND is_active = TRUE ORDER BY updated_at DESC LIMIT 1"),
        {"d": did})).first()
    return extension_from_card(row[0]) if row is not None else None


# V0658 (t): the chat list reads the block of every room on its page in one statement (a room's entry in the sidebar
# wears the logo the thread's header shows); the header asks the same statement for its one room. An expanding IN, not
# Postgres' ANY: the header reads it on every room, and the route tests read real SQLite rows (tests/_sqlite_db.py),
# where ANY is no function. The logo is named only for an active organization: GET /organizations/{id}/logo serves
# only an active one's, so a block naming another would cost a failed image per load.
ROOM_ORGS_SQL = (
    "SELECT o.id, o.slug, o.name, l.sha256, o.settings FROM organizations o "
    "LEFT JOIN organization_logos l ON l.organization_id = o.id AND o.is_active = TRUE WHERE o.id IN :ids"
)
ROOM_ORGS_STMT = text(ROOM_ORGS_SQL).bindparams(bindparam("ids", expanding=True))


def _room_block(row: Sequence[Any]) -> Dict[str, Any]:
    settings = row[4]
    if isinstance(settings, (str, bytes)):
        try:
            settings = json.loads(settings)
        except (ValueError, TypeError):
            settings = None
    from .org_policy import listed_public
    return {"id": str(row[0]), "slug": row[1], "name": row[2], "logo": logo_path(str(row[0]), row[3]),
            "listed": listed_public(settings)}


async def room_orgs(db: AsyncSession, org_ids: Sequence[Optional[str]]) -> Dict[str, Dict[str, Any]]:
    """Batch: room_org's block for each organization, keyed by its id, in one statement for a page of rooms. An id this
    registry does not hold answers nothing."""
    ids = list(dict.fromkeys(str(o) for o in org_ids if o))
    if not ids:
        return {}
    rows = (await db.execute(ROOM_ORGS_STMT, {"ids": ids})).fetchall()
    return {str(r[0]): _room_block(r) for r in rows}


async def room_org(db: AsyncSession, org_id: str) -> Optional[Dict[str, Any]]:
    """An organization as its own room shows it to its members (item 5): id, slug, name, the hosted logo (a path on this
    registry, None while the organization is not active), and whether it is listed. Shown whatever the listing: the
    room is the organization's own space."""
    if not org_id:
        return None
    return (await room_orgs(db, [org_id])).get(str(org_id))


# ── the card must MOVE when the mark moves ──────────────────────────────────────────────────────────────────────────
_NATIVE = "(card_data#>>'{federation_metadata,source_registry}') IS NULL"


async def touch_agent_cards_no_commit(db: AsyncSession, dids: Sequence[str]) -> int:
    """On the CALLER's transaction: move the native cards of these agents, so every peer's incremental pull re-fetches
    them (the §ENFPROP rule). Returns the rows moved. Never raises: a stale mirror is a delay, never a failed change."""
    ids = [d for d in dids if d]
    if not ids:
        return 0
    try:
        res = await db.execute(text(
            "UPDATE agent_cards SET updated_at = NOW() WHERE agent_did = ANY(:dids) AND is_active = TRUE AND " + _NATIVE),
            {"dids": ids})
        return int(res.rowcount or 0)
    except Exception as e:  # noqa: BLE001
        logger.error("[ORGMARK] card touch failed for %d agent(s): %s", len(ids), e)
        return 0


async def touch_org_cards_no_commit(db: AsyncSession, org_id: str) -> int:
    """On the CALLER's transaction: move the native cards of every agent of this organization (a rename, a new logo,
    the listing turned on or off). Never raises."""
    if not org_id:
        return 0
    try:
        res = await db.execute(text(
            "UPDATE agent_cards SET updated_at = NOW() WHERE is_active = TRUE AND " + _NATIVE + " "
            "AND agent_did IN (SELECT did FROM agents WHERE organization_id = :o)"), {"o": str(org_id)})
        n = int(res.rowcount or 0)
        logger.info("[ORGMARK] organization %s: %d native card(s) touched for the peers", org_id, n)
        return n
    except Exception as e:  # noqa: BLE001
        logger.error("[ORGMARK] card touch failed for organization %s: %s", org_id, e)
        return 0


__all__ = [
    "ORG_EXTENSION_URI", "registry_display_name", "logo_path", "home_block", "state_for", "extension_entry",
    "inject_extension", "extension_from_card", "card_states", "card_state", "mark_for_did", "ROOM_ORGS_SQL",
    "ROOM_ORGS_STMT", "room_orgs", "room_org", "touch_agent_cards_no_commit", "touch_org_cards_no_commit",
]
