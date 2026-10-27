"""CROSS-FRAME CONTRACTS (2026-07-26) — one home, a signed replica, a command rail, a reconciler.

The contract spine already settles across frames: when `counterparty_home_registry` is set,
release stages `treasury→client` and drives the client's own cross-registry transfer, so the
provider is paid on their own ledger in their own currency exactly once. What did NOT cross was
the contract *object* — a provider on frame B could not see or act on an agreement living on
frame A.

THE RULE THIS MODULE EXISTS TO PROTECT:

    The escrow can only be in one place, so the authority can only be in one place.
    Everything else is a view of it.

§V0162b paid for the alternative once: two paths that could each settle a grievance paid it
twice. A symmetric peer-to-peer contract state machine is that same bug racing over escrowed
funds across a network boundary. So:

  * the frame holding `ctrref:{cid}:hold` owns every transition and every money move;
  * the peer gets a REPLICA carrying this frame's Ed25519 signature over a content digest, so it
    can prove it is current — or prove it is stale — without trusting the transport;
  * writes on the peer are relayed COMMANDS back to home, never local transitions;
  * and because cross-frame event fanout is best-effort by design, a digest reconciler is the
    guarantee while the event is only the optimisation.

Reuse, not reinvention: the signing keys, the `verify_with_jwk` verifier and the home-JWKS fetch
with rotation-retry are the same ones the AGORA passport DevCard envelope has used in production
since 2026-06-16.
"""
from __future__ import annotations

import hashlib
import json
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.config import settings

logger = logging.getLogger(__name__)

# §COVERAGE 2026-07-26 — a peer that cannot be resolved means replication silently STOPS, and an
# absence of replication is indistinguishable from "nothing to replicate". That is exactly how the
# case-sensitivity bug hid: WARNING-level log line, no counter, no metric, hours of dead
# mainframe-to-mainframe replication that no dashboard could show. Make the silence countable.
try:
    from prometheus_client import Counter as _XFCounter

    XFRAME_PEER_UNRESOLVED = _XFCounter(
        "xframe_peer_unresolved_total",
        "counterparty_home_registry values that resolved to no known peer (replication is "
        "silently not happening for these)",
        ["reason"],
    )
except Exception:  # pragma: no cover - metrics are optional, never load-bearing
    XFRAME_PEER_UNRESOLVED = None

# §XFRAMETD 2026-09-10 — the counter was unlabelled, so a breach could say HOW MANY and never
# WHICH KIND, and the two kinds want opposite actions: `unmatched` is a peer we have no row for
# (add the peer, or the value is junk), `ambiguous_trust_domain` is a peer we have SEVERAL rows
# for (a data defect on THIS node — nothing to add, something to clean). Both sum identically
# under the existing `sum(increase(...))` alert, so widening the series breaks no query.
# The label set is CLOSED on purpose: the unresolved VALUE is caller-supplied and would be
# unbounded cardinality, so it stays in the log line where it is already printed.
_XFRAME_UNRESOLVED_REASONS = ("unmatched", "ambiguous_trust_domain")


def _count_unresolved(reason: str) -> None:
    """Count one unresolvable value. Never raises — a metric must not break resolution."""
    if XFRAME_PEER_UNRESOLVED is None:
        return
    try:
        XFRAME_PEER_UNRESOLVED.labels(
            reason=reason if reason in _XFRAME_UNRESOLVED_REASONS else "unmatched").inc()
    except Exception:
        pass


def service_svid_trust_domain(value: Optional[str]) -> Optional[str]:
    """`spiffe://<trust domain>/service/<anything>` -> the trust domain, lowercased. Else None.

    DELIBERATELY NARROW, and each exclusion is load-bearing:

      * `/operator/<slug>/registry` is an OPERATOR's SVID. Its trust domain is its PARENT
        FRAME's, so answering by trust domain would name a different peer than the caller.
        The slug branch in `resolve_peer_name` already resolves those correctly, which is why
        this one runs after it and refuses the shape outright.
      * the legacy `/ns/<ns>/sa/registry-<name>` presenter template names Frame A's trust
        domain whoever presents it (doctrine, §DIDWIDEN-1), so it is not evidence of who
        called and must never reach a trust-domain lookup.

    A `/service/` path is the frame's own workload identity in its own trust domain, which is
    the one case where the trust domain IS the answer.
    """
    if not value:
        return None
    v = value.strip()
    if not v.lower().startswith("spiffe://"):
        return None
    td, sep, path = v[len("spiffe://"):].partition("/")
    if not sep or not td or not path.lower().startswith("service/"):
        return None
    return td.lower()

# Terminal states never need reconciling — nothing can change them at home.
# §DOCSFIX D6-461: a contract (v2) ends completed, cancelled or expired; without the first and last of those every
# completed or expired replica was re-checked against its home forever (the older names stay)
TERMINAL = ("settled", "cancelled", "failed", "completed", "expired")

# The exact fields that constitute "the agreement as home sees it". Anything outside this set is
# presentation and must NOT enter the digest, or every cosmetic change would mark peers stale.
DIGEST_FIELDS = (
    "cid", "home_registry", "status", "seq",
    "client_did", "provider_did", "currency", "total_amount", "title",
)

# §TWOAGENT (2026-09-23) — the MILESTONE half of what a replica learns. The signed core above is contract-level, so the
# provider's frame heard a release only when it changed the contract's STATUS: the final one (as `contract.completed`),
# never a middle one, and never as `contract.milestone_released` (measured on production V0432, `ctr_046d2b3a…`: the
# provider's owner on ASIA got offered, agreed, payment.received and completed). The home now carries the released
# milestones in the payload under a SECOND signature over the core plus that list. The core's digest and signature
# are unchanged, so a frame on an older image verifies exactly as before and ignores the key; a list whose own
# signature does not verify is dropped before anything stores or reads it.
EXT_FIELD = "released_milestones"


def self_federation_name() -> str:
    """THE identifier peers know this registry by — the same string the registry card publishes
    as `registry_name` and peers store as `peer_registries.name`.

    Not `REGISTRY_NAME`: on cloud-ops that is the Docker container name (`cloud-op-op-tokyo`)
    while the canonical federation name is `op-tokyo`. The card builder carries a scar about
    this — mismatched names made fanout receivers store duplicate peer rows under the Docker
    name. A replica stamped with the wrong name is unverifiable, because the peer resolves the
    home's JWKS by exactly this string.
    """
    import os
    return os.environ.get("REGISTRY_FEDERATION_NAME") or str(getattr(settings, "REGISTRY_NAME", ""))


async def resolve_peer_name(db: AsyncSession, value: Optional[str]) -> Optional[str]:
    """Normalise whatever `counterparty_home_registry` happens to hold into a peer NAME.

    MATCHING IS CASE-INSENSITIVE on every lookup. Peer rows store display-cased names
    (`Frame-B`, `Frame-C`, `Registry-A`) while SPIFFE ids and URLs carry them lowercased
    (`.../service/registry-frame-b`), so an exact `=` silently resolved to None and BOTH
    mainframes' cross-frame contract replication was dead — no error, just nothing replicating.
    Hostnames are case-insensitive by RFC 4343; peer names here follow the same rule.

    Live data on frame-c holds three shapes for the same idea:

        https://op-doha.op.theprotocol.cloud
        https://op-telaviv.op.theprotocol.cloud:8443
        spiffe://frame-c.theprotocol.cloud/operator/op-doha/registry

    None of them is the `peer_registries.name` that peer routing and JWKS lookup require. A
    mirror addressed with the raw value would be ignored by every peer, silently, forever — the
    exact failure the registry-card builder already carries a scar about. So resolve through the
    peer table (name → base_url → spiffe_id → host-prefix), and return None rather than guess.
    """
    if not value:
        return None
    v = value.strip()

    # §XFRAMETD 2026-09-10 — EVERY LOOKUP HERE IS ORDERED, ACTIVE FIRST. A `LIMIT 1` with no
    # `ORDER BY` is a lottery (doctrine), and this table is FULL of deliberate duplicates: the
    # registry-card fan-out re-inserts a peer frame under its UPPERCASE card name, and those
    # ghosts are DEACTIVATED, never deleted (§SLUGCONVERGE). EU holds `ASIA` beside `asia` and
    # ASIA holds `EU` beside `eu`, so `LOWER(name) = LOWER('asia')` matches TWO rows and the
    # planner picked between them. Measured: the ghost won.
    #
    # It did not matter while frame-to-frame resolution was dead in both directions; the moment
    # the branch at the bottom of this function starts answering, it does — `contracts-for-peer`
    # compares a contract's resolved home against the resolved CALLER, so one side answering
    # `ASIA` and the other `asia` filters out every contract while looking like a clean empty
    # list. An ACTIVE row beats a deactivated ghost; ties break by name so the answer is at
    # least stable.
    _ACTIVE_FIRST = ("ORDER BY CASE WHEN UPPER(COALESCE(status, '')) = 'ACTIVE' "
                     "THEN 0 ELSE 1 END, name")

    row = (await db.execute(text(
        "SELECT name FROM peer_registries WHERE LOWER(name) = LOWER(:v) "
        + _ACTIVE_FIRST + " LIMIT 1"), {"v": v})).first()
    if row:
        return row[0]

    # base_url match, tolerant of a trailing slash and an explicit port.
    # Normalised in PYTHON on purpose: SQLAlchemy's text() reads `:443` inside a SQL literal as
    # a bind parameter named "443" and raises. Colons and text() do not mix.
    def _forms(u: str) -> set:
        u = u.rstrip("/").lower()   # hostnames are case-insensitive (RFC 4343)
        out = {u}
        for port in (":443", ":8443", ":8000", ":8100", ":8101"):
            if u.endswith(port):
                out.add(u[: -len(port)])
        return out

    cands = _forms(v)
    rows = (await db.execute(text(
        "SELECT name, base_url FROM peer_registries WHERE base_url IS NOT NULL "
        + _ACTIVE_FIRST))).all()
    for name, base in rows:
        if _forms(str(base)) & cands:
            return name

    row = (await db.execute(text(
        "SELECT name FROM peer_registries WHERE LOWER(spiffe_id) = LOWER(:v) "
        + _ACTIVE_FIRST + " LIMIT 1"), {"v": v})).first()
    if row:
        return row[0]

    # §TWOAGENT (2026-09-23) — a FRAME's own card source, `spiffe://<td>/registry/<name>`
    # (`spiffe://asia.theprotocol.cloud/registry/asia` on every ASIA-homed mirror EU holds). No branch here knew
    # that shape, and a runner-built frame's peer row carries no spiffe_id for the exact branch above to match,
    # so every contract offer from EU to an agent homed on ASIA (and back) answered 409 "not wired here yet"
    # while CONTRACTS_XFRAME_MODE was on: frame-to-frame §XHIRE was dead in both directions, found by two agents
    # trying to sign one. Resolved only when BOTH the name and the trust domain match the peer row, so a SVID
    # from another trust domain that happens to carry the slug resolves to nothing. The segment is the SLUG of the
    # frame's display name (`/registry/sandbox-beta` for the row `Sandbox Beta`, measured on the sandbox pair), so a
    # name matches as written or with its spaces as hyphens.
    import re   # local, like the branch below: `re` is a function-local name here, so it must be bound first
    m = re.match(r"^spiffe://([^/]+)/registry/([A-Za-z0-9._-]+)/?$", v, re.IGNORECASE)
    if m:
        row = (await db.execute(text(
            "SELECT name FROM peer_registries "
            "WHERE (LOWER(name) = LOWER(:c) OR LOWER(REPLACE(name, ' ', '-')) = LOWER(:c)) "
            "AND LOWER(COALESCE(trust_domain, '')) = LOWER(:td) "
            + _ACTIVE_FIRST + " LIMIT 1"), {"c": m.group(2), "td": m.group(1)})).first()
        if row:
            return row[0]

    # Last resort: dig the operator slug out of whichever shape this is. Production carries FOUR
    # spellings of the same peer, and this branch is why the set is discovered rather than
    # assumed — each was found by a real call failing to resolve:
    #   https://op-doha.op.theprotocol.cloud                              (base url)
    #   spiffe://frame-c.theprotocol.cloud/operator/op-doha/registry      (operator SVID)
    #   spiffe://theprotocol.cloud/service/registry-did:theprotocol:cloud:op-doha  (license SVID)
    #   op-doha                                                           (the name itself)
    # Every candidate is checked against peer_registries before it is returned — this widens
    # what we can RECOGNISE, never what we will trust.
    import re
    cands2 = []
    m = re.search(r"/operator/([A-Za-z0-9._-]+)/", v)
    if m:
        cands2.append(m.group(1))
    m = re.search(r"/service/registry-(.+)$", v)
    if m:
        tail = m.group(1)
        cands2.append(tail.rsplit(":", 1)[-1])   # did:theprotocol:cloud:op-doha → op-doha
        cands2.append(tail)
    m = re.search(r"https?://([A-Za-z0-9-]+)\.", v)
    if m:
        cands2.append(m.group(1))
    for cand in cands2:
        row = (await db.execute(text(
            "SELECT name, spiffe_id FROM peer_registries WHERE LOWER(name) = LOWER(:c) "
            + _ACTIVE_FIRST + " LIMIT 1"), {"c": cand})).first()
        if row:
            # §29 LIVE CALL SITE for I2 `trust_domain_bound`. THIS branch matched on a slug dug
            # out of the string, so it resolves a peer from ANY SVID carrying that slug —
            # including one minted in a FOREIGN trust domain. Python cannot compare trust
            # domains here: the exact-match branches above already failed, which is precisely
            # why we are guessing. So ask the policy whether the SVID we were handed actually
            # sits under the trust domain we have ON FILE for the peer we just resolved to.
            # Case-insensitive by construction (§PEERFIX class). Read-only — never changes
            # what this function returns.
            if v.lower().startswith("spiffe://") and row[1]:
                try:
                    from agentvault_registry import opa_shadow as _opa
                    _expected = str(row[1]).split("//", 1)[-1].split("/", 1)[0]
                    await _opa.shadow_check(
                        "agentvault/invariants/trust_domain_bound",
                        {"peer_spiffe_id": v, "expected_trust_domain": _expected},
                        True, f"xframe.resolve_peer_name:{row[0]}")
                except Exception:
                    pass   # observability must never break peer resolution
            return row[0]
    # §XFRAMETD 2026-09-10 — THE FRAME'S OWN SERVICE SVID, which every branch above is blind to.
    # A frame dials its peer carrying `spiffe://<td>/service/registry` (or `…/registry-a`), and
    # there is nothing in it for them to match: no name, no base_url, `peer_registries.spiffe_id`
    # is EMPTY on every frame row in this fleet (measured on all five registries), and the slug
    # regex digs out "a" or nothing. So `/contracts-for-peer` — the BOOTSTRAP pull that exists
    # precisely because push alone cannot establish a replica set — answered `{"contracts": []}`
    # to EVERY peer frame, silently, for as long as the endpoint has existed. Measured
    # 2026-09-09/10: 88 increments per 30 min over five nodes, four distinct values, every one of
    # them a frame's own SVID, and not one of them a contract problem.
    #
    # The trust domain IS a frame's identity, and it arrives here already authenticated: the mTLS
    # gate validated it upstream, so this reads a fact rather than a claim. `trust_domain` is the
    # column that holds our answer for it.
    #
    # NARROWED to ACTIVE frame/direct_peer rows, because a trust domain holds exactly one FRAME
    # and many of its OPERATORS — EU carries three ACTIVE rows under `asia.theprotocol.cloud`
    # (the frame plus hochiminh and shenzhen) and registry-a six under `agentvault.com`. If two
    # still qualify we REFUSE and name both: a mirror addressed to the wrong frame is worse than
    # a mirror not addressed at all, and this is the §29e rule — say what could not be
    # distinguished, never invent which one it was.
    td = service_svid_trust_domain(v)
    if td:
        td_rows = (await db.execute(text("""
            SELECT name FROM peer_registries
            WHERE UPPER(COALESCE(status, '')) = 'ACTIVE'
              AND LOWER(COALESCE(trust_domain, '')) = :td
              AND LOWER(COALESCE(peer_type, '')) IN ('frame', 'direct_peer')
            ORDER BY name
        """), {"td": td})).all()
        if len(td_rows) == 1:
            return td_rows[0][0]
        if len(td_rows) > 1:
            _count_unresolved("ambiguous_trust_domain")
            logger.warning(
                "[XFRAME] %r names trust domain %s, which %d ACTIVE frame/direct_peer peer rows "
                "claim (%s) — refusing to guess which one called",
                v, td, len(td_rows), ", ".join(str(r[0]) for r in td_rows))
            return None

    _count_unresolved("unmatched")
    logger.warning("[XFRAME] cannot resolve peer name from %r — mirror will not be addressed", v)
    return None


def mode() -> str:
    return (getattr(settings, "CONTRACTS_XFRAME_MODE", "off") or "off").lower()


def enabled() -> bool:
    """off → byte-inert. shadow → build/verify/log but never gate. enforce → gate."""
    return mode() in ("shadow", "enforce")


def _canonical(payload: Dict[str, Any]) -> bytes:
    """Byte-identical to the registry-card signer, so one verifier serves both."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def snapshot_of(row: Dict[str, Any], home_registry: str,
                released: Optional[List[int]] = None) -> Dict[str, Any]:
    """The canonical, signable view of a contract. Decimals become strings so the digest does
    not depend on anyone's float formatting. `released` (the released milestone seqs) rides outside
    the digest under its own signature (EXT_FIELD); None leaves the key out entirely."""
    amt = row.get("total_amount")
    snap = {
        "cid": row.get("id") or row.get("cid"),
        "home_registry": home_registry,
        "status": row.get("status"),
        "seq": int(row.get("seq") or 0),
        "client_did": row.get("client_did"),
        "provider_did": row.get("provider_did"),
        "currency": row.get("currency"),
        "total_amount": str(Decimal(str(amt))) if amt is not None else None,
        "title": row.get("title"),
    }
    if released is not None:
        snap[EXT_FIELD] = sorted({int(s) for s in released})
    return snap


def digest_of(snapshot: Dict[str, Any]) -> str:
    core = {k: snapshot.get(k) for k in DIGEST_FIELDS}
    return hashlib.sha256(_canonical(core)).hexdigest()


async def sign_snapshot(db: AsyncSession, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Sign with THIS registry's card key. Returns an envelope the peer can verify against our
    published JWKS — no shared secret, no direct reachability required."""
    from agentvault_registry.services.registry_card_builder import _build_spiffe_id
    from agentvault_registry.services.registry_card_keystore import get_or_mint_signing_key
    from agentvault_registry.services.registry_card_signer_impl import sign_with_keypair

    # Same key, same kid format and same JWKS the registry card is signed with, so a peer
    # verifies a replica with the machinery it already trusts for cards. NOTE: the keystore
    # COMMITS when it has to mint — in practice every registry already holds a card key, so the
    # early-return path is what runs here; a mint is a one-time event at first card publication.
    spiffe_id = _build_spiffe_id()
    key_row = await get_or_mint_signing_key(db, spiffe_id)
    core = {k: snapshot.get(k) for k in DIGEST_FIELDS}
    kid = f"{spiffe_id}#{key_row.rotation_seq}"
    env = {
        "payload": snapshot,
        "digest": digest_of(snapshot),
        "signature": {
            "alg": "EdDSA",
            "kid": kid,
            "value": sign_with_keypair(core, key_row),
        },
    }
    if EXT_FIELD in snapshot:
        env["signature_ext"] = {
            "alg": "EdDSA", "kid": kid, "covers": EXT_FIELD,
            "value": sign_with_keypair({**core, EXT_FIELD: snapshot[EXT_FIELD]}, key_row),
        }
    return env


def _check_extension(env: Dict[str, Any], core: Dict[str, Any], key: Dict[str, Any], verify) -> None:
    """Keep the released-milestone list only if ITS signature verifies with the key that verified the core; otherwise
    remove it from the payload, so no writer stores it and no notice reads it. The replica itself stands on the core."""
    payload = env.get("payload") or {}
    if EXT_FIELD not in payload:
        return
    lst = payload.get(EXT_FIELD)
    ext = env.get("signature_ext") or {}
    well_formed = isinstance(lst, list) and all(isinstance(s, int) and not isinstance(s, bool) for s in lst)
    if well_formed and ext.get("value") and verify({**core, EXT_FIELD: lst}, ext["value"], key):
        return
    payload.pop(EXT_FIELD, None)
    logger.warning("[XFRAME] released-milestone list for cid=%s did not verify; dropped (the replica stands on the "
                   "core signature)", payload.get("cid"))


async def released_milestone_seqs(db: AsyncSession, cid: str) -> List[int]:
    rows = (await db.execute(text(
        "SELECT seq FROM contract_milestones WHERE contract_id = :c AND status = 'released' ORDER BY seq"
    ), {"c": cid})).all()
    return [int(r[0]) for r in rows]


async def signed_envelope_for(db: AsyncSession, row: Dict[str, Any], seq: int) -> Dict[str, Any]:
    """THE envelope builder: every place that hands a peer a contract (the push mirror, the digest a reconciler pulls,
    the bootstrap list) goes through here, so none of them can forget the released milestones."""
    cid = row.get("id") or row.get("cid")
    snap = snapshot_of({**dict(row), "seq": seq}, self_federation_name(),
                       released=await released_milestone_seqs(db, cid))
    return await sign_snapshot(db, snap)


async def verify_envelope(db: AsyncSession, env: Dict[str, Any]) -> bool:
    """Verify a mirrored envelope against the HOME frame's published JWKS.

    An envelope that does not verify is dropped, never stored: a replica whose provenance we
    cannot establish is worse than no replica at all, because the UI would present it as fact.
    Handles home key rotation exactly as the passport path does — one forced refresh, then retry.
    """
    from agentvault_registry.services.exchange_passport import (
        fetch_home_jwks, _invalidate_home_jwks,
    )
    from agentvault_registry.services.registry_card_signer_impl import verify_with_jwk

    payload = env.get("payload") or {}
    sig = ((env.get("signature") or {}).get("value"))
    kid = ((env.get("signature") or {}).get("kid"))
    home = payload.get("home_registry")
    if not payload or not sig or not home:
        logger.warning("[XFRAME] envelope malformed (payload=%s sig=%s home=%s)",
                       bool(payload), bool(sig), home)
        return False

    # The digest must match the payload we were handed — otherwise a valid signature over a
    # DIFFERENT payload could be replayed alongside doctored fields.
    if env.get("digest") != digest_of(payload):
        logger.warning("[XFRAME] digest does not match payload for cid=%s", payload.get("cid"))
        return False

    core = {k: payload.get(k) for k in DIGEST_FIELDS}
    try:
        keys = await fetch_home_jwks(db, home)
        cands = [k for k in keys if not kid or k.get("kid") == kid] or keys
        good = next((k for k in cands if verify_with_jwk(core, sig, k)), None)
        if good is None:
            _invalidate_home_jwks(home)
            keys = await fetch_home_jwks(db, home, force=True)
            cands = [k for k in keys if not kid or k.get("kid") == kid] or keys
            good = next((k for k in cands if verify_with_jwk(core, sig, k)), None)
        if good is None:
            return False
        _check_extension(env, core, good, verify_with_jwk)
        return True
    except Exception:
        logger.warning("[XFRAME] signature verification errored for home=%s", home, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# HOME side — emit a mirror when a cross-frame contract moves
# ---------------------------------------------------------------------------
async def pending_mirrors(db: AsyncSession, limit: int = 100) -> List[dict]:
    """Cross-frame contracts whose committed event trail has moved past what we last mirrored.

    Reads only COMMITTED rows, so a transition that rolled back is never mirrored — which is
    why this is a worker over an outbox rather than a hook inside `audit()`.
    """
    rows = (await db.execute(text("""
        SELECT c.id AS cid, c.mirrored_seq, MAX(e.seq) AS max_seq
        FROM contracts c
        JOIN contract_events e ON e.contract_id = c.id
        WHERE c.counterparty_home_registry IS NOT NULL
        GROUP BY c.id, c.mirrored_seq
        HAVING MAX(e.seq) > c.mirrored_seq
        ORDER BY MAX(e.seq) DESC
        LIMIT :l
    """), {"l": limit})).mappings().all()
    return [dict(r) for r in rows]


async def mark_mirrored(db: AsyncSession, cid: str, seq: int) -> None:
    await db.execute(text(
        "UPDATE contracts SET mirrored_seq = :s WHERE id = :c AND mirrored_seq < :s"
    ), {"s": int(seq), "c": cid})


async def emit_mirror(db: AsyncSession, cid: str, *, reason: str = "transition") -> Optional[dict]:
    """Emit `ContractMirrored` for a contract whose counterparty lives on another frame.

    No-op when the contract is local: mirroring a contract to its own frame is pure noise.
    Best-effort by contract (see the module docstring) — the reconciler is what guarantees the
    peer converges, so a failed emit must never fail the transition that caused it.
    """
    if not enabled():
        return None
    try:
        row = (await db.execute(text("""
            SELECT id, status, client_did, provider_did, currency, total_amount, title,
                   counterparty_home_registry
            FROM contracts WHERE id = :c
        """), {"c": cid})).mappings().first()
        if not row or not row["counterparty_home_registry"]:
            return None

        seq = (await db.execute(text(
            "SELECT COALESCE(MAX(seq), 0) FROM contract_events WHERE contract_id = :c"
        ), {"c": cid})).scalar() or 0

        env = await signed_envelope_for(db, row, seq)
        # Address the mirror by resolved peer NAME, not by the raw column: the column holds
        # URLs and SPIFFE ids in production and no peer would ever recognise itself in those.
        env["peer_registry"] = await resolve_peer_name(db, row["counterparty_home_registry"])
        env["peer_registry_raw"] = row["counterparty_home_registry"]
        env["reason"] = reason

        from agentvault_registry.event_emitter import get_event_emitter
        emitter = get_event_emitter()
        # Deterministic key: a re-emitted transition dedups in the EventStore rather than
        # producing a second mirror the peer would have to reconcile away.
        await emitter.emit(
            event_type="ContractMirrored",
            aggregate_id=cid,
            data=env,
            aggregate_type="Contract",
            idempotency_key=f"ctrmirror-{cid}-{seq}",
        )
        logger.info("[XFRAME] mirrored cid=%s seq=%s → %s (%s)",
                    cid, seq, row["counterparty_home_registry"], reason)
        return env
    except Exception:
        # A mirror is an optimisation. Never let it fail the transition it describes.
        logger.warning("[XFRAME] emit_mirror failed for cid=%s", cid, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# PEER side — store / refresh a replica
# ---------------------------------------------------------------------------
async def upsert_replica(db: AsyncSession, env: Dict[str, Any], *, verified: bool) -> bool:
    """Write or refresh a replica. Refuses unverified envelopes outright.

    Monotonic in `seq`: an out-of-order event (the bus makes no ordering promise across frames)
    can never walk a replica backwards.
    """
    if not verified:
        return False
    p = env.get("payload") or {}
    cid = p.get("cid")
    if not cid:
        return False
    prev = (await db.execute(text("SELECT status FROM contract_replicas WHERE cid = :c"), {"c": cid})).scalar()
    # The released milestones this replica already knew. Only asked when the envelope carries a verified list (the
    # verifier drops an unverified one), and only for a replica that exists: first sight has nothing to compare with.
    prev_released = await _stored_released(db, cid) if (EXT_FIELD in p and prev is not None) else None
    res = await db.execute(text("""
        INSERT INTO contract_replicas
            (cid, home_registry, client_did, provider_did, title, currency, total_amount,
             status, seq, digest, signature, payload, stale, last_synced_at, updated_at)
        VALUES (:cid, :home, :client, :provider, :title, :cur, :amt, :st, :seq, :dg, :sig,
                CAST(:pl AS JSONB), false, now(), now())
        ON CONFLICT (cid) DO UPDATE SET
            status = EXCLUDED.status, seq = EXCLUDED.seq, digest = EXCLUDED.digest,
            signature = EXCLUDED.signature, payload = EXCLUDED.payload,
            provider_did = EXCLUDED.provider_did, title = EXCLUDED.title,
            currency = EXCLUDED.currency, total_amount = EXCLUDED.total_amount,
            stale = false, last_synced_at = now(), updated_at = now()
        -- Write only when something ACTUALLY differs. `seq <= EXCLUDED.seq` matched on
        -- EQUAL seq too, so every bootstrap pass rewrote all 8 unchanged rows and the
        -- worker logged 'adopted 8' forever — a count that read as 'new' and meant
        -- 'accepted'. Still monotonic: a lower seq can never win.
        WHERE contract_replicas.seq < EXCLUDED.seq
           OR (contract_replicas.seq = EXCLUDED.seq
               AND (contract_replicas.digest IS DISTINCT FROM EXCLUDED.digest
                    OR contract_replicas.stale))   -- re-clear a stale row at equal seq
    """), {
        "cid": cid, "home": p.get("home_registry"), "client": p.get("client_did"),
        "provider": p.get("provider_did"), "title": p.get("title"), "cur": p.get("currency"),
        "amt": p.get("total_amount"), "st": p.get("status"), "seq": int(p.get("seq") or 0),
        "dg": env.get("digest"), "sig": ((env.get("signature") or {}).get("value")),
        "pl": json.dumps(p, default=str),
    })
    changed = bool(res.rowcount)
    if changed:
        _notify_released_milestones(p, prev, prev_released)   # before the status notice, as the home announces them
    if changed and p.get("status") != prev:
        _notify_replica_transition(p, prev)
    return changed


async def _stored_released(db: AsyncSession, cid: str) -> Optional[List[int]]:
    """The released list in the payload this replica stored last, or None when that payload carries none (written by
    an older home, or before the list verified): no baseline, so no notice for this step."""
    raw = (await db.execute(text("SELECT payload FROM contract_replicas WHERE cid = :c"), {"c": cid})).scalar()
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    lst = raw.get(EXT_FIELD) if isinstance(raw, dict) else None
    return [int(s) for s in lst] if isinstance(lst, list) else None


def _notify_released_milestones(p: Dict[str, Any], prev: Optional[str], prev_released: Optional[List[int]]) -> None:
    """A milestone the home released since this replica last looked is announced here, where the PROVIDER's owner
    lives (the home's own announcement finds nobody for a party that is not its own)."""
    new = p.get(EXT_FIELD)
    if not isinstance(new, list) or prev_released is None:
        return
    fresh = sorted(set(new) - set(prev_released))
    if not fresh:
        return
    completes = p.get("status") == "completed" and prev != "completed"
    try:
        from agentvault_registry.services import contract_settlement as cs
        c = {"id": p.get("cid"), "status": p.get("status"), "client_did": p.get("client_did"),
             "provider_did": p.get("provider_did"), "title": p.get("title"),
             "total_amount": p.get("total_amount"), "currency": p.get("currency")}
        for s in fresh:
            cs.webhook("contract.milestone_released", c,
                       {"seq": s, "completed": bool(completes and s == fresh[-1]), "replica": True,
                        "home_registry": p.get("home_registry")})
    except Exception:  # noqa: BLE001 — a notice is advisory; the replica is already written
        logger.debug("[XFRAME] replica milestone notice skipped for %s", p.get("cid"), exc_info=True)


# §TWOAGENT G2 (2026-09-23) — the PROVIDER of a cross-frame contract lives on the frame that holds the replica, so the
# home's own contract webhooks never reach its owner (the owner lookup finds nobody there). The replica is where this
# frame learns of each transition, so that is where the owner is told: a new offer, its agreement, its end.
_REPLICA_EVENTS = {"offered": "contract.offered", "agreed": "contract.agreed", "completed": "contract.completed",
                   "cancelled": "contract.cancelled", "disputed": "contract.disputed"}


def _notify_replica_transition(p: Dict[str, Any], prev: Optional[str]) -> None:
    event = _REPLICA_EVENTS.get(p.get("status"))
    if not event:
        return
    try:
        from agentvault_registry.services import contract_settlement as cs
        cs.webhook(event, {"id": p.get("cid"), "status": p.get("status"), "client_did": p.get("client_did"),
                           "provider_did": p.get("provider_did")},
                   {"replica": True, "home_registry": p.get("home_registry"), "previous_status": prev})
    except Exception:  # noqa: BLE001 — a notice is advisory; the replica is already written
        logger.debug("[XFRAME] replica transition notice skipped for %s", p.get("cid"), exc_info=True)


async def active_peer_names(db: AsyncSession) -> List[str]:
    """Peers worth asking. Lives here, not in the worker, so the E2E can execute the real SQL.

    `peer_registries.status` is a PG enum with UPPERCASE labels — cast to text so this reads
    identically on a node where the column is a plain string. (A first cut guessed an
    `is_active` boolean that does not exist; every bootstrap cycle died on it, silently, in a
    caught exception. The query belongs somewhere a test can reach.)
    """
    return list((await db.execute(text(
        "SELECT name FROM peer_registries WHERE UPPER(status::text) = 'ACTIVE' ORDER BY name"
    ))).scalars().all())


async def open_replicas(db: AsyncSession, limit: int = 200) -> List[dict]:
    rows = (await db.execute(text(f"""
        SELECT cid, home_registry, digest, seq FROM contract_replicas
        WHERE status NOT IN {TERMINAL}
        ORDER BY last_synced_at ASC LIMIT :l
    """), {"l": limit})).mappings().all()
    return [dict(r) for r in rows]


async def touch_replica(db: AsyncSession, cid: str) -> None:
    """Record that we verified this replica against home, without touching its content.

    `last_synced_at` means "last agreed with home", and the reconciler orders its sweep by it.
    Once upsert_replica stopped rewriting unchanged rows, a replica that never changes would
    never have its timestamp bumped and would sort first forever, starving the tail of the
    sweep once a node holds more than one batch of replicas.
    """
    await db.execute(text(
        "UPDATE contract_replicas SET last_synced_at = now() WHERE cid = :c"), {"c": cid})


async def mark_stale(db: AsyncSession, cid: str, stale: bool = True) -> None:
    await db.execute(text(
        "UPDATE contract_replicas SET stale = :s, updated_at = now() WHERE cid = :c"
    ), {"s": stale, "c": cid})
