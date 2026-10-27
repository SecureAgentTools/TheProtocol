"""§RESIDUES C1 (2026-09-13) — a peer FRAME is grouped as a frame, never as an operator.

Measured on the flagship's public status page after V0356: "ASIA" sat under the `operator` heading on EU's
page (and "EU" under ASIA's), because stack-health stamped every discovered peer `"group": "operator"`.
One rule, shared by stack-health and the status page: the peer row's `peer_type` decides.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def peer_group(item: Optional[Dict[str, Any]]) -> str:
    """`frame` for a peer frame (peer_type == "frame"), `operator` for everything else (operators, discovered)."""
    t = str(((item or {}).get("peer_type") or (item or {}).get("type") or "")).strip().lower()
    return "frame" if t == "frame" else "operator"


PEER_GROUPS = ("operator", "frame")


def is_peer_group(group: Optional[str]) -> bool:
    """A peer's tile (an operator's or a frame's) as opposed to this frame's own spine."""
    return str(group or "").strip().lower() in PEER_GROUPS


def tier_for_group(group: Optional[str]) -> str:
    """stack-health's tier: a peer of either kind is `federation`; everything else is the frame's own `spine`.
    (V0357 grouped a peer frame as `frame` and the tier rule still asked `== "operator"`, so the peer frame
    moved INTO the spine and the roll's spine gate read 4 of 3: the group and the tier are one rule now.)"""
    return "federation" if is_peer_group(group) else "spine"


# ---------------------------------------------------------------------------------------------------------------
# E11 (2026-09-13, his word "E11 approved"): three more halves of the same rule, measured on the flagship after the
# V0359 roll. The trusted-registries rail carried an UNTYPED twin per frame ("ASIA" beside the peer row "asia", "eu"
# beside "EU": the fan-out's card-name ghost, kept forever by a cache that never regresses), stack-health named the
# twin first and so grouped the peer FRAME `operator`; and a peer frame's TEG and Event Store tiles read `sandbox`
# because the 2026-09-07 standup wrote `"group": "sandbox"` into FRESH_NETWORK_JSON and the page honoured the label
# over the entry's `"role": "frame"`. One identity per registry, the role over the label, a known group over a label.
# ---------------------------------------------------------------------------------------------------------------
from urllib.parse import urlparse as _urlparse

FRAME_ROW_GROUP = "frame"
OPERATOR_ROW_GROUP = "operator"
_GROUP_RANK = {"core": 0, "frame": 1, "operator": 1}


def identity_key(item: Optional[Dict[str, Any]]) -> str:
    """What makes two trusted-registry entries the SAME registry: the public HOST (the port dropped: the ghost carried
    the bare card URL, the peer row the :8443 federation address), else the trust domain, else the lowercased name.
    ⚠ Not the trust domain first: an OPERATOR carries its PARENT's trust domain (amsterdam: eu.theprotocol.cloud), and
    a domain-first key folded every operator into its frame (the test wrote the hazard down and then caught it)."""
    it = item or {}
    for k in ("public_url", "url"):
        u = str(it.get(k) or "").strip().lower()
        if u:
            host = _urlparse(u if "://" in u else "http://" + u).hostname or u
            return "host:" + host
    td = str(it.get("trust_domain") or "").strip().lower()
    if td:
        return "td:" + td
    return "name:" + str(it.get("name") or "").strip().lower()


def _typed(item: Dict[str, Any]) -> bool:
    return bool(str(item.get("peer_type") or item.get("type") or "").strip())


def collapse_twins(regs: list) -> list:
    """One entry per registry identity: an untyped twin of a typed entry is dropped, and of several typed entries the
    first is kept. Entries that are alone under their identity pass through whatever they carry (an untyped lone
    entry is still an entry: the rule removes twins, never peers). Order is preserved."""
    groups: Dict[str, list] = {}
    for it in regs or []:
        if isinstance(it, dict):
            groups.setdefault(identity_key(it), []).append(it)
    out: list = []
    for it in regs or []:
        if not isinstance(it, dict):
            continue
        sibs = groups[identity_key(it)]
        typed = [s for s in sibs if _typed(s)]
        keep = typed[0] if typed else sibs[0]
        if it is keep:
            out.append(it)
    return out


def fresh_entry_groups(entry: Optional[Dict[str, Any]]) -> tuple:
    """(the group of a FRESH_NETWORK_JSON entry's own rows, the group of its operators' rows). The entry's ROLE
    decides for a frame (its own rows `frame`, its operators `operator`) whatever tier label the standup wrote; an
    entry that declares no role keeps a declared group for both (a control the tests hold), and no declaration at
    all is a frame."""
    e = entry or {}
    role = str(e.get("role") or "").strip().lower()
    declared = str(e.get("group") or "").strip().lower()
    if role == "frame":
        return FRAME_ROW_GROUP, OPERATOR_ROW_GROUP
    if declared:
        return declared, declared
    return FRAME_ROW_GROUP, OPERATOR_ROW_GROUP


def group_rank(group: Optional[str]) -> int:
    """For a dedupe between two rows of one job: a known group (core, frame, operator) beats a label (sandbox, peer,
    none). Lower is better."""
    return _GROUP_RANK.get(str(group or "").strip().lower(), 2)


# ---------------------------------------------------------------------------------------------------------------
# §FRAMETWIN (2026-09-29): which of two peer-FRAME rows of one trust domain survives is decided, never drawn. The
# topology reconcile in main.py (`_run_topology_bfs`, pass 2) keeps the FIRST ACTIVE frame row it meets per trust
# domain and parks the rest as `duplicate_frame`; it met them in unordered SELECT order. Measured: on all six production
# nodes a frame's 443 card-name twin sat beside the row the invitation or provisioner wrote, and the 2026-09-07 reconcile
# kept the right row on four and the 443 twin on shenzhen and hochiminh (EU's card feed answers 401 there), so their EU
# corridor carried nothing for three weeks until the rows were swapped by hand (2026-09-28). A parked row stays parked
# (the revival prober leaves a reasoned row alone), so an order that chose wrong once chose for good.
# ---------------------------------------------------------------------------------------------------------------
from urllib.parse import urlparse as _urlparse_ft


def _dial_address(url: Any) -> str:
    """scheme://host[:port]/path, lowercased scheme and host, the default port dropped, no trailing slash."""
    u = str(url or "").strip()
    if not u:
        return ""
    try:
        p = _urlparse_ft(u if "://" in u else "https://" + u)
        scheme, host, port = (p.scheme or "https").lower(), (p.hostname or "").lower(), p.port
    except ValueError:
        return u.rstrip("/").lower()
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        host = f"{host}:{port}"
    return f"{scheme}://{host}{(p.path or '').rstrip('/')}"


def frame_row_keep_rank(row: Any) -> tuple:
    """Sort key for peer rows; of several frame rows of one trust domain, the reconcile keeps the one that sorts first:
      1. the row that dials the address the frame's own signed card declares (`identity.federation_base_url`),
      2. then a row that has synced, the most recent sync first,
      3. then the oldest row (the one somebody wrote before a discovery path added its twin).
    Reads attributes only (an ORM row or anything shaped like one) and never raises on a missing or junk card."""
    card = getattr(row, "cached_registry_card", None)
    ident = card.get("identity") if isinstance(card, dict) else None
    lane = _dial_address(ident.get("federation_base_url")) if isinstance(ident, dict) else ""
    on_lane = bool(lane) and _dial_address(getattr(row, "base_url", None)) == lane
    synced = getattr(row, "last_synced_at", None)
    try:
        synced_ts = float(synced.timestamp()) if synced is not None else None
    except (AttributeError, TypeError, ValueError, OverflowError):
        synced_ts = None
    try:
        row_id = int(getattr(row, "id", None) or 0)
    except (TypeError, ValueError):
        row_id = 0
    return (0 if on_lane else 1, 0 if synced_ts is not None else 1, -(synced_ts or 0.0), row_id)
