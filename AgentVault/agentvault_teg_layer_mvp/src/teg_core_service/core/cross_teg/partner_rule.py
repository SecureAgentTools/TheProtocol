"""The cross-TEG partner rule (2026-10-17): this TEG takes part in a cross-TEG leg only with a CURRENT partner.

A registry that quarantines a peer, suspends, revokes or deletes its licence, or deactivates it, removes the peer from
its own TEG's partner list (its reactors call POST /api/v1/cross-teg/config/remove-partner). That list is the TEG's only
record of the decision, and nothing read it: a removed peer's TEG still prepared and committed transfers here (a commit
credits what the prepare named), and the next transfer toward it put it back (the address in the payload added any
unknown TEG as a partner). Now:

  * a leg a peer calls (prepare, commit, abort; the async legs and /accept when a peer is admitted to them) is refused
    before anything moves unless the peer that the caller's VERIFIED identity names is a current partner;
  * a transfer this TEG starts (POST /cross-teg/transfer) is refused before the sender's funds are locked unless its
    target is a current partner;
  * only the explicit add-partner path adds a partner; a leg never does (an address a caller names for one dial is used
    for that dial and stored nowhere).

Who is a peer, from the SPIFFE identity this frame's terminator verified, never from a TEG id a body claims:

  * this TEG's own frame is never one: every /service/ identity of this TEG's own trust domain (on a frame TEG its own
    services, on an operator TEG the parent frame whose SPIRE issued the operator's own identity);
  * an operator TEG's own identities (/operator/<its name>/...) are not either;
  * any other operator (/operator/<name>/..., any trust domain) is the peer <name>. A partner entry names it when its
    teg_id or registry_id, without a teg-layer-, teg- or registry- prefix and with only letters and digits kept, equals
    <name> kept the same way. The registry adds a peer TEG as teg-layer-<slug>, its reactors remove it as
    teg-<safe name>, and an operator calls itself teg-<safe name>: the three agree under this key;
  * another frame (/service/... of a foreign trust domain) is a partner when a partner entry's address is on that trust
    domain's own host (a template frame's trust domain is its public host). An entry that dials a frame at another name
    (a container alias) names no frame, so that frame's legs are refused: the identity carries no other name to match.

CROSS_TEG_PARTNER_RULE_MODE: enforce (default) | shadow (log what it would refuse, refuse nothing) | off. The mode does
not bring back the old discovery: no mode adds a partner from a leg.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, Iterable, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

MODES = ("enforce", "shadow", "off")
_DROP = re.compile(r"[^a-z0-9]")
_PREFIXES = ("teg-layer-", "teg-", "registry-")


def mode() -> str:
    raw = (os.environ.get("CROSS_TEG_PARTNER_RULE_MODE") or "enforce").strip().lower()
    if raw not in MODES:
        logger.error("[CrossTEG/partner] CROSS_TEG_PARTNER_RULE_MODE=%r is not one of %s; serving as enforce",
                     raw[:40], MODES)
        return "enforce"
    return raw


def peer_key(value: Any) -> str:
    """The peer a TEG id or registry id names: one teg-layer-, teg- or registry- prefix dropped, letters and digits kept.
    teg-layer-amsterdam, teg-amsterdam and registry-amsterdam are all amsterdam; teg-layer-sandbox-beta is sandboxbeta."""
    v = str(value or "").strip().lower()
    for prefix in _PREFIXES:
        if v.startswith(prefix):
            v = v[len(prefix):]
            break
    return _DROP.sub("", v)


def name_key(value: Any) -> str:
    """An operator name as its SVID carries it, kept the way peer_key keeps a TEG id."""
    return _DROP.sub("", str(value or "").strip().lower())


def identity(spiffe_id: Any) -> Optional[Tuple[str, str, str]]:
    """(trust domain, kind, name) of spiffe://<td>/<kind>/<name>/...; None when it is not a SPIFFE id."""
    s = str(spiffe_id or "")
    if not s.startswith("spiffe://"):
        return None
    td, _, path = s[len("spiffe://"):].partition("/")
    if not td:
        return None
    segs = path.split("/")
    kind = segs[0] if segs else ""
    name = segs[1] if len(segs) > 1 else ""
    return td.strip().lower(), kind, name


def peer_of(caller: Any, *, own_trust_domain: str, own_operator: Optional[str]) -> Optional[Dict[str, str]]:
    """None when the caller is not a peer (this TEG's own frame, this operator TEG's own identities, or a caller with no
    SPIFFE identity: the shared key, this frame's own authority, which TEG_MTLS_REQUIRED refuses before this rule);
    otherwise the peer the verified identity names: {"kind": "operator"|"frame"|"other", "trust_domain", "name"}."""
    ident = identity(caller)
    if ident is None:
        return None
    td, kind, name = ident
    own_td = (own_trust_domain or "").strip().lower()
    if kind == "service":
        if own_td and td == own_td:
            return None
        return {"kind": "frame", "trust_domain": td, "name": ""}
    if kind == "operator":
        key = name_key(name)
        if own_td and td == own_td and own_operator and key == own_operator:
            return None
        return {"kind": "operator", "trust_domain": td, "name": key}
    return {"kind": "other", "trust_domain": td, "name": ""}


def describe(peer: Dict[str, str]) -> str:
    if peer.get("kind") == "operator":
        return f"operator {peer.get('name') or '?'} of {peer.get('trust_domain')}"
    if peer.get("kind") == "frame":
        return f"frame {peer.get('trust_domain')}"
    return f"identity of {peer.get('trust_domain')}"


def _host(url: Any) -> str:
    try:
        return (urlparse(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""


def names_peer(partner: Dict[str, Any], peer: Dict[str, str]) -> bool:
    """True when this partner entry is the peer the verified identity names."""
    if peer.get("kind") == "operator":
        key = peer.get("name") or ""
        return bool(key) and key in (peer_key(partner.get("teg_id")), peer_key(partner.get("registry_id")))
    if peer.get("kind") == "frame":
        host = _host(partner.get("url"))
        return bool(host) and host == peer.get("trust_domain")
    return False


def find_partner_for_peer(partners: Iterable[Dict[str, Any]], peer: Dict[str, str]) -> Optional[Dict[str, Any]]:
    for p in partners or ():
        if isinstance(p, dict) and names_peer(p, peer):
            return p
    return None


def same_peer(partner: Dict[str, Any], teg_id: Any) -> bool:
    """True when this partner entry names the peer `teg_id` names (the entry's own id, or the same peer key)."""
    if partner.get("teg_id") == teg_id:
        return True
    key = peer_key(teg_id)
    return bool(key) and key in (peer_key(partner.get("teg_id")), peer_key(partner.get("registry_id")))


def find_partner_by_teg_id(partners: Iterable[Dict[str, Any]], teg_id: Any) -> Optional[Dict[str, Any]]:
    """The entry with this teg_id, else the first entry naming the same peer."""
    rows = [p for p in (partners or ()) if isinstance(p, dict)]
    for p in rows:
        if p.get("teg_id") == teg_id:
            return p
    for p in rows:
        if same_peer(p, teg_id):
            return p
    return None
