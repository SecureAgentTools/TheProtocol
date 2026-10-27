"""Canonical SPIFFE → frame mapping.

Shared by:
  - TEG home-frame guard (via the /api/v1/internal/agents/home-frames endpoint)
  - federation_sync echo prevention (replaces the brittle substring match)
  - federation_card_gc defunct-source detection

The registry's `peer_registries.trust_domain` is the AUTHORITATIVE source of
home-frame information. SPIFFE strings alone are unreliable — Frame B mainframe
was originally provisioned under `agentvault.com` trust domain, then migrated
to `frame-b.theprotocol.cloud`. Cards stamped before the migration carry the
legacy stamp `spiffe://agentvault.com/ns/agentvault/sa/registry-frame-b` and
won't ever be re-stamped (`source_registry` is sticky once set in upsert).

This module:
  1. Extracts (trust_domain, registry_name) from any SPIFFE pattern observed
     in the federation today (5+ shapes including legacy).
  2. Resolves a SPIFFE → frame ("A" or "B") via peer_registries lookup with
     trust_domain as the authoritative answer; falls back to SPIFFE-domain
     pattern matching only when the peer row is missing or has NULL
     trust_domain.

Patterns observed in `agent_cards.federation_metadata.source_registry`:
  - `spiffe://agentvault.com/ns/agentvault/sa/registry-NAME`           (legacy)
  - `spiffe://agentvault.com/operator/NAME/registry`                   (current)
  - `spiffe://agentvault.com/service/registry-NAME`                    (mainframe SVID)
  - `spiffe://agentvault.com/registry-NAME-registry`                   (very legacy)
  - `spiffe://frame-b.theprotocol.cloud/operator/NAME/registry`        (Frame B current)
  - `spiffe://frame-b.theprotocol.cloud/service/registry-NAME`         (Frame B mainframe)
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

# Patterns in priority order. First match wins.
_PATTERNS = [
    # §DIDWIDEN-1 closer (2026-09-06): the Registry Card v0.3 CANONICAL SVID — spiffe://<trust domain>/registry/<name>
    # (the form the direct registry-card sync and the fan-out already build). Measured before this line existed:
    # extract_canonical() returned None for it, so canonical_equals() fell back to string equality and a presenter in
    # the canonical form failed every flare-origin check the legacy template passed.
    re.compile(r"^spiffe://([^/]+)/registry/([^/]+)$"),
    # spiffe://{td}/ns/agentvault/sa/registry-{name}
    re.compile(r"^spiffe://([^/]+)/ns/[^/]+/sa/registry-(.+)$", re.IGNORECASE),
    # spiffe://{td}/operator/{name}/registry  (or /teg, /eventstore — we only return registry name regardless)
    re.compile(r"^spiffe://([^/]+)/operator/([^/]+)/(?:registry|teg|eventstore)$", re.IGNORECASE),
    # spiffe://{td}/service/registry-{name}
    re.compile(r"^spiffe://([^/]+)/service/registry-(.+)$", re.IGNORECASE),
    # spiffe://{td}/service/teg-{name}  (TEG service SVIDs)
    re.compile(r"^spiffe://([^/]+)/service/teg-(.+)$", re.IGNORECASE),
    # spiffe://{td}/registry-{name}-registry  (very legacy)
    re.compile(r"^spiffe://([^/]+)/registry-(.+)-registry$", re.IGNORECASE),
    # spiffe://{td}/registry-{name}  (legacy short form)
    re.compile(r"^spiffe://([^/]+)/registry-(.+)$", re.IGNORECASE),
]

# Hard-known names whose home is Frame B even when the SPIFFE trust domain is
# `agentvault.com` (legacy stamps). This is the only place we hardcode names —
# kept tiny + deliberate. peer_registries lookup is preferred when it returns a
# trust_domain.
_KNOWN_FRAME_B_NAMES = frozenset({
    "frame-b",                      # mainframe stripped of "registry-" prefix
    "registry-frame-b",             # full mainframe legacy name
    "alpha-b", "beta-b", "gamma-b", "delta-b", "epsilon-b",
    "eta-b", "iota-b", "kappa-b", "theta-b", "zeta-b",
    "op-tokyo", "op-seoul", "op-sydney", "op-singapore",
})


def extract_canonical(spiffe_id: Optional[str]) -> Optional[Tuple[str, str]]:
    """Extract (trust_domain, registry_name) tuple from a SPIFFE ID.

    Both components are lowercased + trimmed. registry_name is the meaningful
    last component (the "who"); trust_domain is the SPIFFE authority (the
    "where", but unreliable for legacy stamps — use peer_registries when
    possible).

    Returns None when no pattern matches.
    """
    if not spiffe_id:
        return None
    s = spiffe_id.strip().lower()
    for pat in _PATTERNS:
        m = pat.match(s)
        if m:
            td = m.group(1).strip()
            name = m.group(2).strip()
            return (td, name)
    return None


def _normalize_name(name: str) -> str:
    """Normalize a registry name to a lookup key.

    Strips common prefixes/suffixes used inconsistently across SPIFFE patterns
    and peer_registries.name. Whitespace is converted to hyphens to harmonize
    "Sandbox Alpha" (peer name) vs "sandbox-alpha" (SPIFFE registry name).
    Result is lowercased.

    Examples:
      "registry-op-paris"       → "op-paris"
      "Op-Paris"                → "op-paris"
      "Frame-B"                 → "frame-b"
      "registry-frame-b"        → "frame-b"
      "Sandbox Alpha"           → "sandbox-alpha"
      "registry-sandbox-alpha"  → "sandbox-alpha"
    """
    n = (name or "").strip().lower()
    # Whitespace → hyphen so peer-table names match SPIFFE-style identifiers
    n = "-".join(n.split())
    if n.startswith("registry-"):
        n = n[len("registry-"):]
    return n


async def resolve_frame_via_peers(
    db: AsyncSession,
    canonical: Tuple[str, str],
    PeerRegistry,
) -> Optional[str]:
    """Resolve a (trust_domain, registry_name) tuple to "A"|"B" via peer_registries.

    Prefers `peer_registries.trust_domain` when set. Falls back to SPIFFE
    trust-domain pattern + known-Frame-B-name set when the peer row is missing
    or has NULL trust_domain.

    Returns None when the answer can't be determined (caller decides fallback).
    """
    if not canonical:
        return None
    td, name = canonical
    norm_name = _normalize_name(name)

    # 1. peer_registries lookup by name (case-insensitive, with prefix variations).
    #    Match `name` exactly OR `name` with `registry-` prefix OR `op-` prefix.
    candidates = {norm_name, f"op-{norm_name}", f"registry-{norm_name}"}
    stmt = select(PeerRegistry).where(
        func.lower(PeerRegistry.name).in_(list(candidates))
    )
    rows = (await db.execute(stmt)).scalars().all()
    for peer in rows:
        if peer.trust_domain:
            return _trust_domain_to_frame(peer.trust_domain)

    # 2. Fallback: hardcoded known Frame B names (handles legacy stamps where
    #    SPIFFE trust_domain is `agentvault.com` but the registry IS on Frame B)
    if norm_name in _KNOWN_FRAME_B_NAMES:
        return "B"

    # 3. Fallback: SPIFFE trust_domain pattern
    return _trust_domain_to_frame(td)


def resolve_frame_from_spiffe_only(spiffe_id: Optional[str]) -> Optional[str]:
    """Pure (no DB) fallback resolver — pattern + known-name only.

    Used when no DB session is available (e.g., the W4 GC worker building a
    set of live-peer canonicals can match this against card source_registry).
    Less accurate than resolve_frame_via_peers — prefer the DB version.
    """
    canonical = extract_canonical(spiffe_id)
    if not canonical:
        return None
    td, name = canonical
    norm_name = _normalize_name(name)
    if norm_name in _KNOWN_FRAME_B_NAMES:
        return "B"
    return _trust_domain_to_frame(td)


def _trust_domain_to_frame(trust_domain: Optional[str]) -> Optional[str]:
    """Map a trust_domain string to a frame label.

    §57 sweep (2026-07-30): Frame C was missing — it graduated sandbox→PROD
    during the AGORA rollout and this mapper still described the world as the
    A/B pair, so every `frame-c.theprotocol.cloud` peer resolved to None. Note
    that the DB path in `resolve_frame_via_peers` funnels through here too, so
    an authoritative `peer_registries.trust_domain` row did NOT rescue it.

    There is deliberately no `_KNOWN_FRAME_C_NAMES` counterpart: that set exists
    only to repair LEGACY stamps from Frame B's `agentvault.com`→`frame-b`
    migration, and Frame C never had one (checked live — 0 frame-c-homed peers
    carry an agentvault.com SPIFFE). Inventing the mechanism would add a second
    source of truth for a problem this frame does not have.

    Returning None for an unrecognised trust domain is correct, not a gap: the
    single-letter label is a CLUSTER concept, and a sovereign standalone frame
    has no letter. Callers must treat None as "not a cluster frame".
    """
    if not trust_domain:
        return None
    td = trust_domain.lower()
    if "frame-b" in td:
        return "B"
    if "frame-c" in td:
        return "C"
    if "agentvault.com" in td:
        return "A"
    return None


def canonical_equals(a: Optional[str], b: Optional[str]) -> bool:
    """W3 echo prevention helper — true when two SPIFFE IDs refer to the same
    canonical registry, despite syntactic differences (legacy vs current).

    Falls back to case-insensitive string equality when neither side parses.
    """
    if not a or not b:
        return False
    ca = extract_canonical(a)
    cb = extract_canonical(b)
    if ca is None and cb is None:
        return a.strip().lower() == b.strip().lower()
    if ca is None or cb is None:
        return False
    # Compare normalized names; trust_domain may differ for legacy vs current
    # SPIFFE for the same registry, so we don't require it to match.
    return _normalize_name(ca[1]) == _normalize_name(cb[1])


# ---------------------------------------------------------------------------
# WS-G — authoritative cross-frame target trust_domain resolver (refuse-on-null)
# ---------------------------------------------------------------------------
class CrossFrameResolutionError(Exception):
    """Raised when a REMOTE transfer target's home frame / trust_domain cannot be
    resolved.

    WS-G refuse-on-null contract: NEVER silently assume the local frame for an
    unresolved remote counterparty. That silent fallback (``target_trust_domain
    = local_trust_domain`` left unchanged on lookup miss) mislabeled cross-frame
    transfers as intra-frame → wrong ``target_frame`` → spurious
    CrossFrameTransferRefunded. Callers MUST surface this as a refusal
    (e.g. HTTP 409), not proceed with a guessed frame.
    """

    def __init__(self, target_registry_id: Optional[str]):
        self.target_registry_id = target_registry_id
        super().__init__(
            f"Cannot resolve home frame/trust_domain for remote target "
            f"'{target_registry_id}' — refusing cross-frame op (WS-G refuse-on-null)."
        )


def card_trust_domain(peer) -> Optional[str]:
    """Pull ``identity.trust_domain`` from a peer's signed cached registry card.

    The card is already persisted on ``peer_registries.cached_registry_card``
    (federation_sync refreshes it). Returns a lowercased trust_domain or None.
    """
    card = getattr(peer, "cached_registry_card", None)
    if isinstance(card, dict):
        ident = card.get("identity")
        if isinstance(ident, dict):
            td = ident.get("trust_domain")
            if isinstance(td, str) and td.strip():
                return td.strip().lower()
    return None


async def resolve_target_trust_domain(
    db: AsyncSession,
    *,
    target_peer,
    target_registry_id: Optional[str],
    local_registry_id: str,
    local_trust_domain: str,
) -> str:
    """Authoritative trust_domain for a cross-registry transfer target.

    Resolution order (first hit wins):
      1. ``target_peer.trust_domain``                              (authoritative column)
      2. ``target_peer.cached_registry_card.identity.trust_domain`` (signed card)
      3. BFS topology cache (``agent_locations._compute_trusted_registries``)

    Then:
      - GENUINELY-LOCAL target (no ``target_registry_id`` or == ``local_registry_id``)
        → return ``local_trust_domain`` (legitimate intra-frame, not the bug).
      - REMOTE target still unresolved → raise :class:`CrossFrameResolutionError`
        (refuse-on-null — never silently localize a remote counterparty).

    Read-only; strictly safer than the prior silent local fallback.
    """
    # 1. authoritative DB column
    if target_peer is not None and getattr(target_peer, "trust_domain", None):
        return str(target_peer.trust_domain).strip().lower()

    # 2. signed cached registry card
    if target_peer is not None:
        ctd = card_trust_domain(target_peer)
        if ctd:
            return ctd

    # genuinely-local short-circuit — no remote counterparty to place
    is_remote = bool(target_registry_id) and (
        _normalize_name(target_registry_id) != _normalize_name(local_registry_id or "")
    )
    if not is_remote:
        return local_trust_domain

    # 3. BFS topology cache (lazy import avoids a routers<->services import cycle)
    try:
        from ..routers.agent_locations import _compute_trusted_registries
        tnorm = _normalize_name(target_registry_id)
        for r in (await _compute_trusted_registries(db)) or []:
            if _normalize_name(r.get("name") or "") == tnorm:
                td = r.get("trust_domain")
                if td:
                    return str(td).strip().lower()
    except Exception:
        # fall through to refuse — a lookup error must NOT silently localize a remote target
        pass

    # 4. refuse-on-null
    raise CrossFrameResolutionError(target_registry_id)
