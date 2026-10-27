"""The three card extensions only a card's HOME registry may state (§TWOAGENT #10, 2026-09-23).

The reputation bond (§REPBOND), the enforcement state (§ENFPROP) and the listing state (§LISTPROP) are each derived from
this registry's own rows at the moment a card is served (`inject_extension` in their modules), and a MIRROR keeps the copy
its home served: that copy is how the fact crosses frames. What had no rule was the NATIVE card, in both directions:

  * its stored card_data is owner content (the create and update routes, the pull-sync of the agent's own well-known
    card, a CI/CD restore, an import), and nothing kept a home extension out of it, so an owner could write a bond block
    this registry never granted;
  * the card reads served stored card_data and derived nothing, so the federated Directory, which indexes exactly the
    single-card read, recorded every native card as unbonded and unenforced whatever this registry held.

Two halves, one list of URIs:

  strip_home_extensions(card_data)             every owner-content write path, before it persists
  derive_for_read / derive_for_read_batch      every read that serves a native card's card_data: the same three calls the
                                               card-export and the federation export make, in the same order, so every
                                               read of a native card states the same thing

A mirror is never touched by either half.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from . import enforcement_propagation as _ep
from . import listing_propagation as _lp
from . import reputation_bond as _rb

logger = logging.getLogger(__name__)

HOME_EXTENSION_URIS = frozenset({
    _rb.BOND_EXTENSION_URI,
    _ep.ENFORCEMENT_EXTENSION_URI,
    _lp.LISTING_EXTENSION_URI,
})


def is_native(card_data: Any) -> bool:
    """A card is native unless it names the registry it was mirrored from (the same signal every native filter reads)."""
    if not isinstance(card_data, dict):
        return False
    fm = card_data.get("federation_metadata")
    return not (isinstance(fm, dict) and fm.get("source_registry"))


def strip_home_extensions(card_data: Any) -> Any:
    """Owner content never carries a home extension: drop the three from the top-level `extensions`.

    Returns a NEW dict when something was dropped and the same object otherwise, so an unaffected card is persisted
    byte for byte as it came. Every other extension (the payment extension, the owner's own) is kept in order."""
    if not isinstance(card_data, dict):
        return card_data
    exts = card_data.get("extensions")
    if not isinstance(exts, list):
        return card_data
    kept = [e for e in exts if not (isinstance(e, dict) and e.get("uri") in HOME_EXTENSION_URIS)]
    if len(kept) == len(exts):
        return card_data
    return {**card_data, "extensions": kept}


def _derived(card_data: Dict[str, Any], did: Optional[str], bond: Optional[Dict[str, Any]],
             enforcement: Optional[Dict[str, Any]], listing: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out = dict(strip_home_extensions(card_data))
    if not did:
        return out                      # no agent to state anything about: the owner's copies are dropped, nothing added
    out = _rb.inject_extension(out, bond)
    out = _ep.inject_extension(out, enforcement)
    out = _lp.inject_extension(out, listing)
    return out


async def derive_for_read(db: AsyncSession, card_data: Any, did: Optional[str]) -> Any:
    """The single-card read of a NATIVE card: stored card_data with the three stated from this registry's rows.

    A mirror (or anything that is not a dict) comes back untouched. If a state cannot be read the card is served with
    the owner's copies dropped and nothing added, and the failure is logged: a read never states a bond this registry
    did not vouch for, and never fails a card over a garnish."""
    if not is_native(card_data):
        return card_data
    if not did:
        return _derived(card_data, None, None, None, None)
    try:
        bond = await _rb.card_state(db, did)
        enforcement = await _ep.card_state(db, did)
        listing = await _lp.card_state(db, did)
    except Exception as e:  # noqa: BLE001
        logger.warning("[HOMEEXT] %s: the home extensions could not be read (%s); served without them", did, e)
        return _derived(card_data, None, None, None, None)
    return _derived(card_data, did, bond, enforcement, listing)


async def derive_for_read_batch(db: AsyncSession, items: List[Dict[str, Any]], dids: Sequence[Optional[str]]) -> None:
    """The list twin, parallel to the flare batch: `items[i]["card_data"]` is replaced for every native card, with one
    query per extension for the whole page. `dids[i]` is the agent DID of `items[i]` (None for a card without one)."""
    if not items or len(items) != len(dids):
        return
    idxs = [i for i, it in enumerate(items) if is_native(it.get("card_data"))]
    if not idxs:
        return
    wanted = sorted({dids[i] for i in idxs if dids[i]})
    bonds: Dict[str, Dict[str, Any]] = {}
    enfs: Dict[str, Dict[str, Any]] = {}
    lsts: Dict[str, Dict[str, Any]] = {}
    failed = False
    if wanted:
        try:
            bonds = await _rb.card_states(db, wanted)
            enfs = await _ep.card_states(db, wanted)
            lsts = await _lp.card_states(db, wanted)
        except Exception as e:  # noqa: BLE001
            failed = True
            logger.warning("[HOMEEXT] a page of %d native cards: the home extensions could not be read (%s); served without them",
                           len(wanted), e)
    for i in idxs:
        did = None if failed else dids[i]
        items[i]["card_data"] = _derived(items[i]["card_data"], did, bonds.get(did or ""), enfs.get(did or ""),
                                         lsts.get(did or ""))


__all__ = ["HOME_EXTENSION_URIS", "is_native", "strip_home_extensions", "derive_for_read", "derive_for_read_batch"]
