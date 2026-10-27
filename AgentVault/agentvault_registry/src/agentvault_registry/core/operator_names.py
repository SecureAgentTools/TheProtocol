"""§SLUGCONVERGE (2026-09-02) — the ONE rule for a renamed operator's two faces.

On 2026-06-15 the Lane-B rename (PRODUCTION_DOCS/06_OPERATIONS/Operator_Rename.md) moved four frame-B operators'
FEDERATION IDENTITY from the city names to the US names — the name each signs its registry card with, its public
URL, its TEG id, its peer rows and every mirrored card on every node — and, by design, KEPT their containers, stack
directories and SPIFFE ids under the old city names ("no data move; only IDENTITY changes"). So each of the four has
two faces: an IDENTITY (op-losangeles) and an INFRA LABEL (cloud-op-op-singapore: the container, the directory, the
SPIFFE id, the Prometheus scrape job, the MCP bridge name).

The identity is the name. The label is where it runs. Any surface that lists peers shows the IDENTITY; a label that
leaks into a peer list (a `discovered` ghost named after the container, measured on all 16 nodes 2026-09-02, kept
alive by the card fan-out) is collapsed onto its identity, never shown beside it.

This module touches no row. It is applied where the peer list is built (`/api/v1/stack-health`) and shared by the
status rail. Do NOT add a second map on another surface, and do NOT invert this one (the status page did, for an
hour, on the assumption that the container name was the current name — it is the old one).
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

# infra label (container / directory / SPIFFE / scrape job) → federation identity (the name)
INFRA_LABEL_TO_IDENTITY: Dict[str, str] = {
    "op-singapore": "op-losangeles",
    "op-sydney": "op-chicago",
    "op-seoul": "op-houston",
    "op-tokyo": "op-newyork",
}
IDENTITY_TO_INFRA_LABEL: Dict[str, str] = {v: k for k, v in INFRA_LABEL_TO_IDENTITY.items()}


# SEC-21 (2026-10-17): the names no operator may take, refused where an operator gets its name (the application, its
# approval, its activation, the self-service provisioning). Each is a name the event store or this code treats as
# something other than one operator's name:
#   origin            the event store's name for this frame's own services (es_auth.is_origin: auth_context["operator"]
#                     == "origin"; a caller named so is refused there since fix/es-sec3 59e7548)
#   unknown           the label the event store gives a proposal with no named operator, and the name this registry's
#                     suspend, reinstate and teardown use for an application with none (teg-unknown)
#   commander         the label the event store gives a veto with no named actor
#   local registry    a name this registry's topology writeback treats as itself (topology_self_names)
#   peer:<domain>     the event store's label for a peer frame's services
#   layer, layer-*    an operator's TEG id is teg-<name>: teg-layer is the frames' own TEG id and teg-layer-<x> is read
#                     as registry <x> (reactor_peer_trust_observed._peer_key_from_teg)
#   registry-*        peer names and TEG ids are read without a leading registry- (reactor_peer_trust_observed._norm,
#                     the teg-layer-<registry> derivations), so registry-eu reads as eu
#   the infra labels  op-singapore, op-sydney, op-seoul, op-tokyo: identity_slug maps them onto other operators, and the
#                     registry-card fan-out never creates a peer row under one
# A name is compared as typed (case and surrounding spaces ignored) and in the forms the code derives from it: the
# provisioner's slug (cloud_provisioner._safe_name: SPIFFE path, TEG id, pull username, DID) and the licence-matching
# slug (federation_auth._norm_slug).
RESERVED_OPERATOR_WORDS: Dict[str, str] = {
    "origin": "a name the network uses for a frame's own services",
    "unknown": "a name the network uses where an operator's name is missing",
    "commander": "a name the network records for a frame's own actions",
    "local registry": "a name a registry uses for itself",
}


def reserved_operator_name(name: Optional[str]) -> Optional[str]:
    """Why `name` may not name an operator, or None when it may (SEC-21). The reason is a short phrase for the
    refusal's message."""
    from .federation_auth import _norm_slug
    from ..services.cloud_provisioner import _safe_name

    raw = (name or "").strip().lower()
    safe = _safe_name(name or "")
    slug = _norm_slug(name or "")
    for form in (raw, safe, slug):
        if form in RESERVED_OPERATOR_WORDS:
            return RESERVED_OPERATOR_WORDS[form]
    if raw.startswith("peer:"):
        return "a name the network uses for a peer frame's services"
    for form in (raw, safe):
        if form in INFRA_LABEL_TO_IDENTITY:
            return "a container label the network maps to another operator"
        if form.startswith("registry-"):
            return "the network reads such a name without its leading 'registry-'"
    if safe == "layer" or safe.startswith("layer-"):
        return "its TEG id would take the form of a frame's TEG id"
    return None


# SEC-23 (2026-10-18): nor may a name be one the network would confuse with a peer this registry already knows. A TEG's
# partner rule (agentvault2-5b's ledgergate3 TEG, core/cross_teg/partner_rule.peer_key) matches an operator's
# certificate name against a partner entry's TEG id or registry id with one prefix dropped and only letters and digits
# kept: an operator of EU named asia, teg-asia or a-sia would match the partner entry of the frame ASIA, and a
# remove-partner for the operator (its quarantine) would drop the frame's entry with it.
_PEER_KEY_PREFIXES = ("teg-layer-", "teg-", "registry-")


def peer_key(value: Optional[str]) -> str:
    """The key the TEG partner rule compares a peer by: lower case, one teg-layer-, teg- or registry- prefix dropped,
    letters and digits only (teg-layer-amsterdam, registry-amsterdam and Ams-terdam are all amsterdam)."""
    v = (value or "").strip().lower()
    for prefix in _PEER_KEY_PREFIXES:
        if v.startswith(prefix):
            v = v[len(prefix):]
            break
    return re.sub(r"[^a-z0-9]", "", v)


def _domain_label(trust_domain: Optional[str]) -> str:
    return (trust_domain or "").strip().lower().split(".", 1)[0]


async def colliding_peer_name(db, name: Optional[str]) -> Optional[str]:
    """Why `name` would be confused with a peer this registry already knows, or None (SEC-23). Compared by peer_key
    against this frame's own registry id, TEG id and trust domain, and against every peer_registries row's name and
    trust domain, whatever its status (a deactivated peer can be reactivated). A cloud operator's row under the same
    safe name does not count: it is this operator's own row (a provisioning tried again) or an exact duplicate, which
    the activation's and the self-provisioning's duplicate-name checks refuse."""
    from sqlalchemy import select

    from .. import models
    from ..services.cloud_provisioner import _safe_name

    key = peer_key(name)
    if not key:
        return None
    own = [_domain_label(os.getenv("SPIRE_TRUST_DOMAIN"))]
    try:
        from ..routers.teg_integration import _get_local_registry_id, _get_local_teg_id
        own += [_get_local_registry_id(), _get_local_teg_id()]
    except Exception:  # noqa: BLE001  the trust domain and the peer rows still decide
        pass
    if key in {peer_key(v) for v in own if v}:
        return "this frame's own name"
    safe = _safe_name(name or "")
    rows = (await db.execute(select(models.PeerRegistry.name, models.PeerRegistry.trust_domain,
                                    models.PeerRegistry.peer_type))).all()
    for row_name, trust_domain, peer_type in rows:
        if str(peer_type or "") == "cloud_operator" and _safe_name(row_name or "") == safe:
            continue
        if key == peer_key(row_name) or (trust_domain and key == peer_key(_domain_label(trust_domain))):
            return f"the registry '{row_name}' this registry already knows"
    return None


def identity_slug(name: Optional[str]) -> str:
    """The name a peer is known by in the federation. Non-label names pass through (whitespace trimmed)."""
    n = (name or "").strip()
    return INFRA_LABEL_TO_IDENTITY.get(n.lower(), n)


def infra_label(identity: Optional[str]) -> Optional[str]:
    """The container an identity runs in (`cloud-op-<label>`), or None when name and label coincide."""
    lab = IDENTITY_TO_INFRA_LABEL.get((identity or "").strip().lower())
    return f"cloud-op-{lab}" if lab else None


def scrape_job(identity: Optional[str]) -> str:
    """The Prometheus job that scrapes an identity: jobs are named after the container (monitoring/prometheus.yml)."""
    n = (identity or "").strip().lower()
    return IDENTITY_TO_INFRA_LABEL.get(n, n)


def fanout_peer_name_allowed(peer_name: Optional[str], card: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """§FEDSYNCTRUTH — may the registry-card fan-out CREATE a peer row under `peer_name`?

    The fan-out copies every ACTIVE row's cached card to every direct peer, and a receiver used to INSERT any
    name it did not know as a `discovered` peer. That is how one ghost (`op-singapore`, a container label
    carrying losangeles's card) lived on all 16 nodes and came back after every sweep. A NEW peer row is
    allowed only under a name the peer itself answers to:
      - not a bare infra label (`identity_slug(name) == name`), and
      - equal to the card's own `identity.registry_name` when the card carries one.
    Existing rows are never touched by this rule (an INACTIVE ghost stays INACTIVE; an ACTIVE row keeps
    receiving card updates through the caller's existing guard). Returns (allowed, reason).
    """
    name = (peer_name or "").strip()
    if not name:
        return False, "empty_name"
    if identity_slug(name).lower() != name.lower():
        return False, "infra_label"
    ident = card.get("identity") if isinstance(card, dict) else None
    signed = (ident.get("registry_name") if isinstance(ident, dict) else None) or ""
    if signed and str(signed).strip().lower() != name.lower():
        return False, "card_name_mismatch"
    return True, "ok"


def collapse_to_identity(services: Iterable[Dict[str, Any]], *, drop: Iterable[str] = (),
                         name_key: str = "name", label_key: str = "infra_label") -> List[Dict[str, Any]]:
    """Name every peer by its identity, ONCE, and stamp the container label where one exists.

    - an entry under a bare label (the ghost) is renamed to the identity when it is the only face present
      (its probe URL still answers: the label hostname is an nginx alias of the same container);
    - both faces present → the entry already under the identity keeps the seat, whichever arrived first;
    - `drop` = names that are this node itself (a renamed operator sees its own label in topology);
    - order = first occurrence; idempotent.
    """
    drop_l = {(d or "").strip().lower() for d in drop}
    out: List[Dict[str, Any]] = []
    index: Dict[str, int] = {}          # identity (lower) → seat in `out`
    seat_is_label: Dict[str, bool] = {}  # whether that seat holds a renamed label face
    for svc in services:
        raw = str(svc.get(name_key) or "")
        ident = identity_slug(raw)
        if ident.lower() in drop_l:
            continue
        renamed = ident != raw.strip()
        entry = dict(svc, **{name_key: ident}) if renamed else svc
        lab = infra_label(ident)
        if lab and not entry.get(label_key):
            entry = dict(entry, **{label_key: lab})
        k = ident.lower()
        if k in index:
            if not renamed and seat_is_label[k]:
                out[index[k]] = entry
                seat_is_label[k] = False
            continue
        index[k] = len(out)
        seat_is_label[k] = renamed
        out.append(entry)
    return out


def is_own_fanout_entry(peer_name: Optional[str], card: Optional[Dict[str, Any]], *,
                        own_registry_name: Optional[str], own_spiffe: Optional[str],
                        trust_domain: Optional[str], own_federation_name: Optional[str] = None) -> Tuple[bool, str]:
    """§ONESHOT (2026-09-12) — is this fan-out entry THIS node's own card coming back?

    The parent's registry-card fan-out relays every card it holds, the receiver's own included, and a
    receiver that does not recognise itself INSERTs a `discovered` row under its own name and dials
    itself every cycle (401, parked 33 minutes — runbook §8.5 made deactivating it a hand step). The
    old check compared the relayed card's `identity.spiffe_id` with the LIVE SVID and fell back to the
    canonical `spiffe://<td>/registry/<REGISTRY_NAME>` only when the live one was empty; a fresh cloud
    operator's live SVID is its cert-writer's (`…/operator/<slug>/svid-writer`), so the fallback never
    ran and the row landed on every operator the §ONESHOT proof stood up. Recognise ourselves by ANY of:
    the fan-out name equals REGISTRY_NAME or its `cloud-op-` slug; the card's spiffe_id equals the live
    SVID OR the canonical form; the card's identity.registry_name equals our slug.
    """
    name = (peer_name or "").strip().lower()
    own = (own_registry_name or "").strip().lower()
    slug = own[len("cloud-op-"):] if own.startswith("cloud-op-") else own
    ident = card.get("identity") if isinstance(card, dict) and isinstance(card.get("identity"), dict) else {}
    card_spiffe = (ident.get("spiffe_id") or "").strip().lower()
    card_name = (ident.get("registry_name") or "").strip().lower()
    # the card's spiffe names the registry by its federation name since V0560 (REGISTRY_FEDERATION_NAME, else
    # REGISTRY_NAME) and by REGISTRY_NAME before it: any of those forms is ours. The federation name is passed in, not
    # derived from the label: a renamed operator's (op-singapore's container is op-losangeles) is not its label's slug.
    fed = (own_federation_name or "").strip().lower()
    td_l = (trust_domain or "").strip().lower()
    canonical = {f"spiffe://{td_l}/registry/{n}" for n in (own, slug, fed) if td_l and n}
    live = (own_spiffe or "").strip().lower()
    if name and name in {n for n in (own, slug, fed) if n}:
        return True, f"fan-out name {peer_name!r} is our own registry name"
    if card_spiffe and (card_spiffe == live or card_spiffe in canonical):
        return True, f"card.identity.spiffe_id {card_spiffe} is our own"
    if card_name and card_name in {n for n in (slug, fed) if n}:
        return True, f"card.identity.registry_name {card_name!r} is our own slug"
    return False, ""


def topology_self_names(env: Dict[str, str], local_name: Optional[str]) -> set:
    """§ONESHOT (2026-09-12) — every name and host the topology writeback must treat as ITSELF.

    The boot-time BFS (main.py, the topology writeback) inserts every registry the parent lists as a
    `discovered` row unless it is in this set. A fresh cloud operator is listed by its parent under its
    SLUG (`juiceop`) with its public host (`juiceop.op.theprotocol.cloud`); the set held REGISTRY_NAME
    (`cloud-op-juiceop`) and the hosts of REGISTRY_PUBLIC_URL / BASE_URL / FEDERATION_BASE_URL, none of
    which an operator carries — PUBLIC_URL is the one it has. So every operator inserted itself at every
    boot, and the URL self-heal reactor re-activated the row whenever a hand deactivated it (measured on
    the §ONESHOT proof pair, four times). Now: the slug, the display name, and PUBLIC_URL's host are self too.
    """
    from urllib.parse import urlparse

    def host(u: str) -> str:
        try:
            p = urlparse(u if u.startswith("http") else f"https://{u}")
            return (p.hostname or u).lower()
        except Exception:  # noqa: BLE001
            return u.lower()

    names = {(env.get("REGISTRY_DISPLAY_NAME") or "").strip().lower(), (env.get("REGISTRY_NAME") or "").strip().lower(),
             (local_name or "").strip().lower(), "local registry", (env.get("BILATERAL_PEER_NAME") or "").strip().lower()}
    rn = (env.get("REGISTRY_NAME") or "").strip().lower()
    if rn.startswith("cloud-op-"):
        names.add(rn[len("cloud-op-"):])
    for var in ("REGISTRY_PUBLIC_URL", "BASE_URL", "FEDERATION_BASE_URL", "PUBLIC_URL", "MAINFRAME_PUBLIC_URL_SELF"):
        hint = (env.get(var) or "").strip()
        if hint and var != "MAINFRAME_PUBLIC_URL_SELF":
            names.add(host(hint))
    names.discard("")
    return names

