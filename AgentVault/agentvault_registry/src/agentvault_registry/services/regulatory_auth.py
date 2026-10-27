"""Regulatory Authorization Rail (REGAUTH, SPEC 2026-08-15).

Jurisdiction Profiles v1 say "feature allowed/denied". This rail adds the missing
third state: **allowed only with a recorded regulatory authorization**. The
operator declares WHICH lifecycle acts need state approval inside the jurisdiction
profile (a `requires_authorization` block over a closed vocabulary); the gate
PARKS those acts (409 + an actionable blockers checklist, the org-delete pattern)
until an authorization row (the state's reference id + optional evidence hash +
optional countersigned contract ref) covers them; active authorizations ride the
SIGNED registry card (v0.6 `compliance` block) as public proof.

Trust model: the system never verifies a state's stamp. The operator ATTESTS with
their liability behind it; the claim is public, signed, and evented, so a false
reference is provable misrepresentation. The Provider ships mechanism, never
legal conclusions (jurisdiction module doctrine): no per-country rules library,
defaults byte-inert.

Mode resolution: the global JURISDICTION_MODE stays the master kill switch
(`off` = byte-inert). Each `requires_authorization` entry carries its OWN
`mode: shadow|enforce` (default shadow), and entry-level `enforce` enforces even
while the global mode is `shadow`, because the operator explicitly wrote it into
their own signed declaration. That makes activation a runtime profile PUT with no
container recreate. Feature-deny semantics (v1) are untouched.

Fail-open/closed split: profile corruption stays fail-open (jurisdiction.py
doctrine: a broken declaration must not freeze a frame). A DECLARED requirement
whose authorization LOOKUP errors fails CLOSED (503, honest "cannot verify"):
the operator opted into strictness and traffic on these acts is admin-rare.

Deny-only, pre-escrow, delta-irrelevant by construction.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Closed action vocabulary (v1). Additive later (bridge, forge publication, ...).
# Unknown actions are rejected at profile PUT and at record time, so an older
# deployment can never silently misread a newer declaration.
REG_ACTIONS = (
    "exchange.listing",     # AGORA listing approval (admin act)
    "exchange.ipo",         # opening an IPO float to purchase (same admin act)
    "fiat.lane",            # the fiat purchase lane (registry scope)
    "registry.operation",   # the deployment's own operating license (display-only)
)

# Declared + recorded + published on the card + auditor-visible, but NEVER gated:
# enforcing the meta-license would freeze the deployment that declares it.
DISPLAY_ONLY_ACTIONS = ("registry.operation",)

# Default scope per action when the declaring entry omits it.
_DEFAULT_SCOPE = {
    "exchange.listing": "per_subject",
    "exchange.ipo": "per_subject",
    "fiat.lane": "registry",
    "registry.operation": "registry",
}


def declared_scope(action: str, entry: Dict[str, Any]) -> str:
    """The scope a declaring entry applies: its own, else the action's default. ONE rule for the gate and for the
    signed card (§DOCSFIX CB-412: the card published 'registry' for an entry declared without a scope, while the gate
    applied the action's default, per_subject for exchange.listing and exchange.ipo)."""
    return entry.get("scope", _DEFAULT_SCOPE.get(action, "registry"))

_EVIDENCE_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

try:  # metrics are best-effort; never let observability break the gate
    from prometheus_client import Counter
    _DECISIONS = Counter(
        "regauth_decisions_total",
        "Regulatory authorization gate decisions",
        ["action", "decision", "mode"],
    )
except Exception:  # pragma: no cover
    _DECISIONS = None


def _count(action: str, decision: str, mode: str) -> None:
    if _DECISIONS is not None:
        try:
            _DECISIONS.labels(action=action, decision=decision, mode=mode).inc()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Profile block validation (called from jurisdiction.validate_profile)
# ---------------------------------------------------------------------------

def validate_requirements_block(block: Any) -> List[str]:
    """Validate a profile's `requires_authorization` block. Returns problems;
    empty list = valid. Never raises. Shape:

        "requires_authorization": {
          "exchange.ipo": {"authority": "BaFin", "scope": "per_subject",
                            "mode": "enforce", "note": "..."}
        }
    """
    errs: List[str] = []
    if not isinstance(block, dict):
        return ["requires_authorization: must be an object of action -> entry"]
    for action, entry in block.items():
        prefix = f"requires_authorization.{action}"
        if action not in REG_ACTIONS:
            errs.append(f"{prefix}: unknown action (known: {', '.join(REG_ACTIONS)})")
            continue
        if not isinstance(entry, dict):
            errs.append(f"{prefix}: must be an object")
            continue
        authority = entry.get("authority")
        if not isinstance(authority, str) or not (1 <= len(authority.strip()) <= 120):
            errs.append(f"{prefix}.authority: required string (1-120 chars)")
        scope = entry.get("scope", _DEFAULT_SCOPE.get(action, "registry"))
        if scope not in ("registry", "per_subject"):
            errs.append(f"{prefix}.scope: must be 'registry' or 'per_subject'")
        mode = entry.get("mode", "shadow")
        if mode not in ("shadow", "enforce"):
            errs.append(f"{prefix}.mode: must be 'shadow' or 'enforce'")
        note = entry.get("note")
        if note is not None and (not isinstance(note, str) or len(note) > 500):
            errs.append(f"{prefix}.note: must be a string (max 500 chars)")
        for k in entry.keys():
            if k not in ("authority", "scope", "mode", "note"):
                errs.append(f"{prefix}.{k}: unknown key")
    return errs


def declared_requirement(profile: Optional[Dict[str, Any]], action: str) -> Optional[Dict[str, Any]]:
    """The declaring entry for an action, or None when nothing is declared."""
    if not profile:
        return None
    block = profile.get("requires_authorization")
    if not isinstance(block, dict):
        return None
    entry = block.get(action)
    return entry if isinstance(entry, dict) else None


# ---------------------------------------------------------------------------
# Authorization lookup (liveness re-derived at use; no snapshots, no sweeper)
# ---------------------------------------------------------------------------

async def active_authorization(db: AsyncSession, action: str, subject_ref: Optional[str]):
    """One covering ACTIVE-and-in-window row, or None. Lookup is STRICT by scope:
    per_subject requires an exact subject match; registry scope requires a
    subject-less row. May raise (DB errors propagate; the gate fails CLOSED on a
    declared requirement it cannot verify)."""
    from agentvault_registry.models import RegulatoryAuthorization
    now = datetime.now(timezone.utc)
    q = select(RegulatoryAuthorization).where(
        RegulatoryAuthorization.action == action,
        RegulatoryAuthorization.status == "active",
        RegulatoryAuthorization.valid_from <= now,
    )
    if subject_ref is None:
        q = q.where(RegulatoryAuthorization.subject_ref.is_(None))
    else:
        q = q.where(RegulatoryAuthorization.subject_ref == subject_ref)
    rows = (await db.execute(q)).scalars().all()
    for row in rows:
        if row.valid_until is None or row.valid_until > now:
            return row
    return None


# ---------------------------------------------------------------------------
# THE GATE — call at the lifecycle-act choke point, before any state change
# ---------------------------------------------------------------------------

async def check_regulatory_authorization(
    db: AsyncSession,
    action: str,
    *,
    subject_ref: Optional[str] = None,
    actor: str = "",
) -> None:
    """Park a declared-regulated act until an authorization covers it.

    off (global) or nothing declared -> no-op. Declared + covered -> allow.
    Declared + uncovered: entry mode shadow -> log '[REGAUTH] decision=would-park'
    and proceed; entry mode enforce -> 409 with a structured blockers checklist
    (the org-delete E1b shape; note the RFC7807 handler stringifies dict details,
    consumers JSON.parse them back).
    """
    from agentvault_registry.services import jurisdiction as _juris
    if _juris.mode() == "off":
        return
    if action in DISPLAY_ONLY_ACTIONS:
        return
    profile = await _juris.get_profile(db)
    req = declared_requirement(profile, action)
    if req is None:
        return

    scope = declared_scope(action, req)
    lookup_subject = subject_ref if scope == "per_subject" else None
    try:
        auth = await active_authorization(db, action, lookup_subject)
    except Exception as e:
        # Decision #2: a DECLARED requirement we cannot verify fails CLOSED.
        logger.error("[REGAUTH] decision=unverifiable action=%s subject=%s error=%s",
                     action, lookup_subject or "-", e)
        _count(action, "UNVERIFIABLE", "n/a")
        raise HTTPException(status_code=503, detail=(
            f"regulatory_authorization_unverifiable: this deployment declares that "
            f"'{action}' requires a regulatory authorization, and the authorization "
            "record could not be read. Refusing rather than guessing; retry shortly."
        ))

    entry_mode = "enforce" if req.get("mode") == "enforce" else "shadow"
    if auth is not None:
        _count(action, "ALLOW", entry_mode)
        logger.info(
            "[REGAUTH] decision=allow action=%s subject=%s auth=%s ref=%s actor=%s",
            action, lookup_subject or "-", auth.id, auth.reference_id, actor or "-",
        )
        return

    authority = req.get("authority", "?")
    if entry_mode != "enforce":
        _count(action, "WOULD_PARK", "shadow")
        logger.warning(
            "[REGAUTH] decision=would-park mode=shadow action=%s subject=%s authority=%s actor=%s",
            action, lookup_subject or "-", authority, actor or "-",
        )
        return

    _count(action, "PARK", "enforce")
    logger.warning(
        "[REGAUTH] decision=park mode=enforce action=%s subject=%s authority=%s actor=%s",
        action, lookup_subject or "-", authority, actor or "-",
    )
    raise HTTPException(status_code=409, detail={
        "message": (
            "This act is parked: the deployment's jurisdiction profile declares it "
            "requires a regulatory authorization, and none is on file. Record the "
            "authorization, then retry."
        ),
        "blockers": [{
            "kind": "regulatory_authorization_required",
            "action": action,
            "authority": authority,
            "subject_ref": lookup_subject,
            "how": (
                "Obtain approval from the declared authority out-of-band, then record "
                "its reference id via POST /api/v1/admin/jurisdiction-profile/authorizations "
                "(admin, Settings > Jurisdiction in the UI) and retry this act."
            ),
        }],
    })


# ---------------------------------------------------------------------------
# Record / list / revoke (router-facing helpers; router owns commit + audit)
# ---------------------------------------------------------------------------

def _parse_ts(value: Any, field: str) -> Optional[datetime]:
    if value in (None, ""):
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail=f"{field}: must be an ISO-8601 timestamp")
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def validate_record_payload(body: Dict[str, Any]) -> Dict[str, Any]:
    """Validate + normalize a record request. Raises 422 on problems."""
    errs: List[str] = []
    action = body.get("action")
    if action not in REG_ACTIONS:
        errs.append(f"action: must be one of {', '.join(REG_ACTIONS)}")
    for field, limit in (("authority", 200), ("jurisdiction", 120), ("reference_id", 255)):
        v = body.get(field)
        if not isinstance(v, str) or not (1 <= len(v.strip()) <= limit):
            errs.append(f"{field}: required string (1-{limit} chars)")
    subject_ref = body.get("subject_ref")
    if subject_ref is not None and (not isinstance(subject_ref, str) or not (1 <= len(subject_ref) <= 255)):
        errs.append("subject_ref: must be a string (1-255 chars) or null for registry scope")
    evidence_hash = body.get("evidence_hash")
    if evidence_hash is not None and (
        not isinstance(evidence_hash, str) or not _EVIDENCE_HASH_RE.match(evidence_hash)
    ):
        errs.append("evidence_hash: must match sha256:<64 hex chars> (hash only, never the document)")
    for field, limit in (("evidence_note", 1000), ("contract_ref", 255)):
        v = body.get(field)
        if v is not None and (not isinstance(v, str) or len(v) > limit):
            errs.append(f"{field}: must be a string (max {limit} chars)")
    if errs:
        raise HTTPException(status_code=422, detail={"message": "invalid authorization record", "errors": errs})

    valid_from = _parse_ts(body.get("valid_from"), "valid_from") or datetime.now(timezone.utc)
    valid_until = _parse_ts(body.get("valid_until"), "valid_until")
    if valid_until is not None and valid_until <= valid_from:
        raise HTTPException(status_code=422, detail="valid_until: must be after valid_from")
    return {
        "action": action,
        "subject_ref": (subject_ref.strip() if isinstance(subject_ref, str) else None),
        "authority": body["authority"].strip(),
        "jurisdiction": body["jurisdiction"].strip(),
        "reference_id": body["reference_id"].strip(),
        "valid_from": valid_from,
        "valid_until": valid_until,
        "evidence_hash": evidence_hash,
        "evidence_note": body.get("evidence_note"),
        "contract_ref": body.get("contract_ref"),
    }


async def record_authorization(db: AsyncSession, payload: Dict[str, Any], *,
                               recorded_by_dev_id: int, presence_method: str = "none"):
    """Insert one authorization row (caller commits). Refuses an exact live
    duplicate (same action + subject + reference already active) with 409:
    renewals carry a NEW reference or come after a revoke.

    §VCSIGN: a contract_ref, when present, must point at an attestation-grade
    contract (exists + agreed + zero-value) — 422 otherwise. Renewals ride the
    same path. Legacy rows are NOT backfilled; the card's omit-when-unresolvable
    rule keeps those honest."""
    from agentvault_registry.models import RegulatoryAuthorization
    if payload.get("contract_ref"):
        contract, problem = await classify_attestation_contract(db, payload["contract_ref"])
        if problem is not None:
            reasons = {
                "missing": "contract_ref: no contract with this id exists on this registry",
                "nonzero_value": (
                    "contract_ref: the referenced contract is not zero-value; a "
                    "countersigned attestation contract must carry no money"
                ),
                "not_agreed": (
                    "contract_ref: the referenced contract is not in the agreed state "
                    f"(status={contract.get('status') if contract else '?'}); "
                    "countersign it first"
                ),
            }
            raise HTTPException(status_code=422, detail={
                "message": "invalid authorization record", "errors": [reasons[problem]]})
    dup_q = select(RegulatoryAuthorization.id).where(
        RegulatoryAuthorization.action == payload["action"],
        RegulatoryAuthorization.reference_id == payload["reference_id"],
        RegulatoryAuthorization.status == "active",
    )
    if payload["subject_ref"] is None:
        dup_q = dup_q.where(RegulatoryAuthorization.subject_ref.is_(None))
    else:
        dup_q = dup_q.where(RegulatoryAuthorization.subject_ref == payload["subject_ref"])
    if (await db.execute(dup_q)).scalar() is not None:
        raise HTTPException(status_code=409, detail=(
            "duplicate: an active authorization with this action, subject and "
            "reference id already exists. Revoke it first, or record the renewal "
            "under its own reference id."
        ))
    row = RegulatoryAuthorization(
        **payload,
        status="active",
        recorded_by_dev_id=recorded_by_dev_id,
        presence_method=presence_method or "none",
    )
    db.add(row)
    await db.flush()
    return row


async def revoke_authorization(db: AsyncSession, auth_id: str, *, reason: str):
    """Status-only revoke (caller commits). 404 unknown id, 409 already revoked."""
    from agentvault_registry.models import RegulatoryAuthorization
    row = (await db.execute(
        select(RegulatoryAuthorization).where(RegulatoryAuthorization.id == auth_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="authorization not found")
    if row.status == "revoked":
        raise HTTPException(status_code=409, detail="authorization is already revoked")
    row.status = "revoked"
    row.revoked_at = datetime.now(timezone.utc)
    row.revoke_reason = reason
    await db.flush()
    return row


async def list_authorizations(db: AsyncSession, *, include_revoked: bool = False,
                              action: Optional[str] = None):
    from agentvault_registry.models import RegulatoryAuthorization
    q = select(RegulatoryAuthorization)
    if not include_revoked:
        q = q.where(RegulatoryAuthorization.status == "active")
    if action:
        q = q.where(RegulatoryAuthorization.action == action)
    q = q.order_by(RegulatoryAuthorization.created_at.desc())
    return (await db.execute(q)).scalars().all()


def is_live(row, now: Optional[datetime] = None) -> bool:
    """The same liveness the gate derives: active + inside the validity window."""
    now = now or datetime.now(timezone.utc)
    return (
        row.status == "active"
        and row.valid_from <= now
        and (row.valid_until is None or row.valid_until > now)
    )


def to_public(row) -> Dict[str, Any]:
    """The public/card shape: attestation facts only, no recorder identity."""
    return {
        "action": row.action,
        "subject_ref": row.subject_ref,
        "authority": row.authority,
        "jurisdiction": row.jurisdiction,
        "reference_id": row.reference_id,
        "valid_from": row.valid_from.isoformat() if row.valid_from else None,
        "valid_until": row.valid_until.isoformat() if row.valid_until else None,
        "evidence_hash": row.evidence_hash,
        "contract_ref": row.contract_ref,
    }


def to_admin(row) -> Dict[str, Any]:
    out = to_public(row)
    out.update({
        "id": row.id,
        "status": row.status,
        "live": is_live(row),
        "evidence_note": row.evidence_note,
        "recorded_by_dev_id": row.recorded_by_dev_id,
        "presence_method": row.presence_method,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "revoke_reason": row.revoke_reason,
    })
    return out


# ---------------------------------------------------------------------------
# Countersigned contract attestation (§VCSIGN 2026-08-15) — tier-3 evidence
# made independently verifiable. ONE subset/digest/classifier for the card,
# the admin list, the public endpoint and record-time validation.
# ---------------------------------------------------------------------------

CONTRACT_ATTESTATION_FIELDS = (
    "id", "title", "contract_type", "total_amount", "client_did",
    "provider_did", "terms", "created_at", "agreed_at",
)


def contract_attestation_subset(contract: Dict[str, Any]) -> Dict[str, Any]:
    """The digestable view of a countersigned attestation contract: IMMUTABLE
    fields only — `status` is deliberately excluded so the digest is stable
    from the moment of agreement forever. Timestamps ISO, amount stringified
    (the same str() the contracts detail endpoint serializes with)."""
    out: Dict[str, Any] = {}
    for k in CONTRACT_ATTESTATION_FIELDS:
        v = contract.get(k)
        if isinstance(v, datetime):
            v = v.isoformat()
        elif k == "total_amount" and v is not None:
            v = str(v)
        out[k] = v
    return out


def contract_attestation_digest(subset: Dict[str, Any]) -> str:
    """sha256 over the canonical subset — the sibling digests' canonical json
    (sorted keys, tight separators, ensure_ascii), so a browser recomputes it
    with sorted keys + JSON.stringify + a \\uXXXX escape pass over non-ASCII."""
    canonical = json.dumps(subset, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def classify_loaded_attestation_contract(contract: Optional[Dict[str, Any]]) -> Optional[str]:
    """None = attestation-grade (exists + agreed + zero-value); else the problem:
    'missing' | 'nonzero_value' | 'not_agreed'. The card attaches a digest, the
    public endpoint serves, and record-time validation accepts under this ONE
    rule — the card must never claim what the public endpoint would refuse."""
    if contract is None:
        return "missing"
    amount = contract.get("total_amount")
    try:
        if amount is not None and Decimal(str(amount)) != 0:
            return "nonzero_value"
    except Exception:
        return "nonzero_value"
    if contract.get("status") != "agreed":
        return "not_agreed"
    return None


async def classify_attestation_contract(
    db: AsyncSession, cid: str
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Load via THE contract loader and classify. Returns (contract, problem)."""
    from agentvault_registry.services.contract_settlement import load_contract
    contract = await load_contract(db, cid)
    return contract, classify_loaded_attestation_contract(contract)


async def load_attestation_contracts(
    db: AsyncSession, refs: List[Optional[str]]
) -> Dict[str, Dict[str, Any]]:
    """Batch-load contracts for a set of contract_refs, keyed by id."""
    ids = sorted({r for r in refs if r})
    if not ids:
        return {}
    from sqlalchemy import bindparam, text
    stmt = text("SELECT * FROM contracts WHERE id IN :ids").bindparams(
        bindparam("ids", expanding=True))
    rows = (await db.execute(stmt, {"ids": ids})).mappings().all()
    return {row["id"]: dict(row) for row in rows}


async def live_authorizations_for_contract(db: AsyncSession, cid: str):
    """LIVE authorization ROWS whose countersign points at cid (one query; the
    refs helper below and the break-watcher both ride this — never a copy)."""
    from agentvault_registry.models import RegulatoryAuthorization
    rows = (await db.execute(
        select(RegulatoryAuthorization).where(
            RegulatoryAuthorization.contract_ref == cid,
            RegulatoryAuthorization.status == "active",
        )
    )).scalars().all()
    now = datetime.now(timezone.utc)
    return [r for r in rows if is_live(r, now)]


async def live_references_for_contract(db: AsyncSession, cid: str) -> List[str]:
    """reference_ids of LIVE authorizations whose countersign points at cid.
    Empty list = the public endpoint must 404 (proof surface, not a browser)."""
    return sorted({r.reference_id for r in await live_authorizations_for_contract(db, cid)})


async def emit_regauth_event(event_type: str, aggregate_id: str, data: Dict[str, Any]) -> None:
    """Best-effort ledger event (the org-service pattern): the DB row is the
    durable state; the event is the audit trail. A failed emit must never fail
    its caller. (Moved here from the admin router so the break-watcher shares
    the ONE implementation.)"""
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        emitter = get_event_emitter()
        await emitter.emit(event_type=event_type, aggregate_id=aggregate_id, data=data)
    except Exception as e:  # noqa: BLE001
        logger.warning("[REGAUTH] emit %s for %s failed: %s", event_type, aggregate_id, e)


# ---------------------------------------------------------------------------
# Card surface (registry card v0.6 compliance block)
# ---------------------------------------------------------------------------

async def active_card_authorizations(db: AsyncSession) -> List[Dict[str, Any]]:
    """LIVE authorizations in the public card shape, deterministically ordered
    (digest stability). Entries whose contract_ref resolves to an
    attestation-grade contract (agreed + zero-value) additionally carry
    `contract_digest`; the key is OMITTED otherwise, so the card only ever
    claims what /api/v1/jurisdiction/contracts/{cid} can prove. May raise; the
    card builder wraps best-effort."""
    rows = await list_authorizations(db, include_revoked=False)
    now = datetime.now(timezone.utc)
    live_rows = [r for r in rows if is_live(r, now)]
    contracts = await load_attestation_contracts(db, [r.contract_ref for r in live_rows])
    live = []
    for r in live_rows:
        pub = to_public(r)
        if r.contract_ref:
            c = contracts.get(r.contract_ref)
            if classify_loaded_attestation_contract(c) is None:
                pub["contract_digest"] = contract_attestation_digest(
                    contract_attestation_subset(c))
        live.append(pub)
    live.sort(key=lambda a: (a["action"], a["subject_ref"] or "", a["reference_id"]))
    return live


def authorizations_digest(auths: List[Dict[str, Any]]) -> str:
    canonical = json.dumps(auths, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compliance_digest(block: Dict[str, Any]) -> str:
    """sha256 over the canonical compliance block content (minus the digest
    itself). Recomputable by any verifier from the card's own bytes, so signing
    this ONE leaf (v0.6 signed path `compliance.digest`) covers the whole block
    without whole-block canonicalization mismatches."""
    content = {k: v for k, v in block.items() if k != "digest"}
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
