"""V0666 (order gwo_e086b25f868da7ec9fce9fd2): governed code names ONE governing registry.

The code-change rail (services/code_changes) is written per registry: "the frame's members vote". Every registry runs the same image, so a second
registry given the checker key would hold its own ballots over the same code base. One code base has one authority: EU.

  CODE_CHANGES_GOVERNING_REGISTRY   the name of the registry that governs code. It is compared with THIS registry's own name as its signed card
                                    states it (services/registry_card_builder.federation_name: identity.registry_name), never a container label.

  this registry is the governing one   everything as before.
  unset, or another registry           the rail is READ-ONLY: propose, review, the ballot, the go and the veto, the acceptance record, the
                                       merge record and every vote or tally of a code_change proposal refuse with 403 and one sentence:
                                       "Code changes are governed on <name>; open them there", with that registry's console link when its
                                       network manifest (FRESH_NETWORK_JSON) names one. Reads answer as before.

The refusal sits in the STORE the production routes use (services/code_changes.DbStore.check_governing, called first by every flow step and again by
every write of the store), so any route, MCP tool or background step that writes through the rail inherits it, and a registry that is not the governing
one writes no code_changes row, no review, no bounty order and no governance proposal of the type.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional, Tuple

ENV = "CODE_CHANGES_GOVERNING_REGISTRY"
# The name the sentence uses when nothing is set (the doctrine's authority). It names a place to go; it never makes a registry the governing one.
DEFAULT_NAME = "EU"


def governing_name() -> Optional[str]:
    v = (os.environ.get(ENV) or "").strip()
    return v or None


def own_name() -> str:
    from .registry_card_builder import federation_name
    return (federation_name() or "").strip()


def is_governing() -> bool:
    g = governing_name()
    return bool(g) and g.casefold() == own_name().casefold()


_PEER_LINKS: Dict[str, Tuple[float, Optional[str]]] = {}      # name -> (read at, the console its peer row's cached card publishes); five minutes
_PEER_LINK_TTL = 300.0


async def warm_peer_link(db: Any, name: str) -> Optional[str]:
    """The console link the governing registry's CARD publishes (identity.public_url in its peer row's cached registry card, pulled by federation_sync), remembered for
    five minutes. A registry with no peer row for it, no cached card, or no database in hand answers None and the manifest below is the fallback."""
    key = name.strip().lower()
    hit = _PEER_LINKS.get(key)
    if hit and time.time() - hit[0] < _PEER_LINK_TTL:
        return hit[1]
    link: Optional[str] = None
    if db is not None:
        try:
            from sqlalchemy import func, select
            from ..models import PeerRegistry
            row = (await db.execute(select(PeerRegistry.cached_registry_card).where(func.lower(PeerRegistry.name) == key).limit(1))).scalar_one_or_none()
            ident = (row or {}).get("identity") if isinstance(row, dict) else None
            url = str((ident or {}).get("public_url") or "").strip()
            link = url if url.startswith(("https://", "http://")) else None
        except Exception:  # noqa: BLE001 — the link is a courtesy: a read that fails leaves the manifest to answer
            link = None
    _PEER_LINKS[key] = (time.time(), link)
    return link


def console_link(name: str) -> Optional[str]:
    """The console of the registry `name`: its own card's public_url as this registry last read it (warm_peer_link), else the frame of that name in this network's manifest
    (FRESH_NETWORK_JSON). None when neither says one."""
    hit = _PEER_LINKS.get(name.strip().lower())
    if hit and hit[1] and time.time() - hit[0] < _PEER_LINK_TTL:
        return hit[1]
    raw = (os.environ.get("FRESH_NETWORK_JSON") or "").strip()
    if not raw:
        return None
    try:
        frames = json.loads(raw)
    except ValueError:
        return None
    for f in frames if isinstance(frames, list) else []:
        if isinstance(f, dict) and str(f.get("name") or "").strip().lower() == name.strip().lower():
            link = str(f.get("console") or "").strip()
            return link or None
    return None


def authority() -> Dict[str, Any]:
    """What the console and a refusal say: who governs, whether this registry does, the sentence and the link."""
    g = governing_name()
    me = is_governing()
    shown = g or DEFAULT_NAME
    link = None if me else console_link(shown)
    sentence = None if me else f"Code changes are governed on {shown}; open them there" + (f": {link}" if link else ".")
    return {"governing": g, "self": me, "name": shown, "console": link, "sentence": sentence, "own_name": own_name()}


def sentence() -> str:
    return authority()["sentence"] or ""


def refusal():
    """The one refusal every write path answers (403, code_change_not_governed_here)."""
    from .code_changes import CodeChangeRefusal
    return CodeChangeRefusal(403, "code_change_not_governed_here", sentence())


def require_governing() -> None:
    if not is_governing():
        raise refusal()


async def require_governing_async(db: Any = None) -> None:
    """The same, after reading the governing registry's card for the link the sentence carries."""
    if not is_governing():
        await warm_peer_link(db, governing_name() or DEFAULT_NAME)
        raise refusal()
