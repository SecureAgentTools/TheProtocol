"""V0660 (d): quantum workloads on a frame, as its registry states and gates them.

Everything here waits for QUANTUM_WORKLOADS_MODE (core/quantum_mode.py). off, the source default, is byte-inert: no block
on the registry card or in the public registry-config, nothing read and nothing held on the funding rail.

1. The derived block, `quantum_workloads` (quantum_workloads_block()): the registry card signs it whole and the public
   registry-config repeats it. It is read from this registry's own switches on every call, never from an operator's card
   edit, and offers only what a rail here runs:
     status              shadow or on (an off frame publishes no block at all);
     receipt_schema      the job receipt format a job settled here carries (V0660 (b): a hash-linked chain, each step
                         signed by its participant) and the signature algorithms this registry verifies, named as the
                         agent card extension names them (services/quantum_receipts.py holds the constants for both);
     acceptance_tests    the rungs a verdict can settle (1: check the answer; 2: test circuits or an independent repeat)
                         and the rails that settle it here: the Guild's verify step where the Guild runs, a contract
                         milestone where contracts v2 run, read through the rails' own predicates; no rail, no rungs;
     metering_circuit    the resource-usage circuit the attestation rail verifies (shots or seconds reported against a
                         log a meter committed to), when this registry verifies it;
     allocation_profile  present when the frame declares one (2. below): its name, version, the number of allocations and
                         the hash of the document, or {"state": "invalid"}; never the holders or the caps, which would let
                         a long profile pass the card's size limit.

2. The allocation-frame profile for research consortia (the whitepaper's section 7): a centre's frame grants quantum time
   by proposal, in its own unit, and declares its allocations in QUANTUM_ALLOCATION_PROFILE, a JSON document:
     {"name": "...", "version": 1, "unit": "<the frame's unit; optional>", "note": "...",
      "allocations": [{"id": "proj-017", "holder": "<the agent's DID>", "cap": "5000", "note": "..."}]}
   A treasury grant (POST /api/v1/teg/treasury/fund-agent) whose reason is `allocation:<id>` draws on that allocation and
   is held against its cap before the TEG is called (allocation_grant_hold): on refuses a grant past the cap, for an
   allocation the profile does not declare or for another holder (403, its code word first); shadow makes the same
   decision, reports it and lets the grant through. The amount granted under each allocation is counted in exchange_flags
   (`quantum_alloc:<id>`, the per-frame flag store, no migration) under a row lock, from the moment the switch is shadow
   or on (grants made while it was off are not in the count). Room is given back only on evidence of what moved: the
   ledger gate's refusal or a request that never left this registry (nothing moved), or the TEG's own `exhausted` account
   (what it funded stays counted, only the rest is given back). A balance read is never that evidence (the waterfall can
   commit legs before it answers 400, and a cached balance can be stale), so any other failure, and a lost answer, keeps
   the whole amount counted: the room left can only shrink, never grow, and the cap holds.

No new rail and no new ledger: the grant is the funding rail's own and the frame's ledger records it with its reason (the
memo treasury_fund:allocation:<id>), so anyone holding the profile can check each cap against the ledger.
"""
from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from fastapi import HTTPException

from ..core.quantum_mode import MODES, quantum_workloads_mode
from .quantum_receipts import ACCEPTANCE_RUNGS, METERING_CIRCUIT, RECEIPT_SCHEMA_VERSION
from .quantum_receipts import SIGNING_ALGORITHMS as RECEIPT_SIGNATURE_ALGORITHMS

logger = logging.getLogger(__name__)

PUBLISHED_STATUSES = tuple(m for m in MODES if m != "off")   # an off frame publishes no block
PROFILE_ENV = "QUANTUM_ALLOCATION_PROFILE"
GRANT_REASON_PREFIX = "allocation:"
TALLY_KEY_PREFIX = "quantum_alloc:"
MAX_ALLOCATIONS = 200
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")   # with the prefix, within exchange_flags.key's 64
_PROFILE_KEYS = ("name", "version", "unit", "note", "allocations")
_ALLOCATION_KEYS = ("id", "holder", "cap", "note")

try:  # best-effort, like the jurisdiction gate's: a metric never breaks the rail
    from prometheus_client import Counter
    _DECISIONS = Counter("quantum_allocation_grant_decisions_total",
                         "Allocation grant decisions on the treasury funding rail", ["decision", "mode", "reason"])
except Exception:  # pragma: no cover
    _DECISIONS = None


# ── the block ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def settled_through() -> List[str]:
    """The rails here a verdict settles through, by the predicates the rails themselves refuse on."""
    rails: List[str] = []
    try:
        from ..routers.guild import guild_enabled
        if guild_enabled():
            rails.append("guild_work_order")
    except Exception:  # noqa: BLE001: a rail whose switch cannot be read is not offered
        logger.warning("[QUANTUM] the Guild's switch could not be read: no work-order acceptance is offered")
    try:
        from ..routers.contracts_v2 import contracts_v2_enabled
        if contracts_v2_enabled():
            rails.append("contract_milestone")
    except Exception:  # noqa: BLE001
        logger.warning("[QUANTUM] the contracts' switch could not be read: no milestone acceptance is offered")
    return rails


def metering_circuit() -> Optional[str]:
    """The resource-usage circuit, when this registry's verifier lists it (core/zkp_verifier)."""
    try:
        from ..core.zkp_verifier import get_supported_circuits
        return METERING_CIRCUIT if METERING_CIRCUIT in get_supported_circuits() else None
    except Exception:  # noqa: BLE001: a circuit that cannot be confirmed is not offered
        return None


def quantum_workloads_block() -> Optional[Dict[str, Any]]:
    """The block the card and the registry-config publish; None while the switch is off. Never raises."""
    mode = quantum_workloads_mode()
    if mode == "off":
        return None
    rails = settled_through()
    block: Dict[str, Any] = {
        "status": mode,
        "receipt_schema": {"version": RECEIPT_SCHEMA_VERSION,
                           "signature_algorithms": list(RECEIPT_SIGNATURE_ALGORITHMS)},
        "acceptance_tests": {"rungs": list(ACCEPTANCE_RUNGS) if rails else [], "settled_through": rails},
        "metering_circuit": metering_circuit(),
    }
    try:
        summary = allocation_profile_summary()
    except Exception:  # noqa: BLE001: a profile that cannot be read is reported as such, never as absent
        summary = {"state": "invalid"}
    if summary is not None:
        block["allocation_profile"] = summary
    return block


def registry_config_fields() -> Dict[str, Any]:
    """The public registry-config's share: the same block, or nothing at all while the switch is off."""
    block = quantum_workloads_block()
    return {} if block is None else {"quantum_workloads": block}


# ── the allocation profile ────────────────────────────────────────────────────────────────────────────────────────────

def _frame_unit() -> str:
    from ..core.frame_currency import frame_currency
    return frame_currency()


def _cap(value: Any) -> Optional[Decimal]:
    """A cap as a positive finite amount, or None."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        cap = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return cap if cap.is_finite() and cap > 0 else None


def validate_profile(doc: Any, frame_unit: str) -> List[str]:
    """The problems with an allocation profile document; empty when it is valid. Never raises."""
    from ..input_validators import DID_PATTERN
    if not isinstance(doc, dict):
        return ["the profile must be a JSON object"]
    errs = [f"{k}: unknown key (known: {', '.join(_PROFILE_KEYS)})" for k in doc if k not in _PROFILE_KEYS]
    name = doc.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 120:      # the card publishes it as written
        errs.append("name: a string of 1 to 120 characters is required")
    version = doc.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        errs.append("version: an integer of at least 1 is required")
    if "unit" in doc and doc.get("unit") != frame_unit:
        errs.append(f"unit: this frame's unit is {frame_unit}, the profile names {doc.get('unit')!r}")
    if "note" in doc and (not isinstance(doc.get("note"), str) or len(doc["note"]) > 500):
        errs.append("note: a string of at most 500 characters")
    allocations = doc.get("allocations")
    if not isinstance(allocations, list) or not 1 <= len(allocations) <= MAX_ALLOCATIONS:
        errs.append(f"allocations: a list of 1 to {MAX_ALLOCATIONS} allocations is required")
        return errs
    seen = set()
    for i, a in enumerate(allocations):
        where = f"allocations[{i}]"
        if not isinstance(a, dict):
            errs.append(f"{where}: an object is required")
            continue
        errs.extend(f"{where}.{k}: unknown key (known: {', '.join(_ALLOCATION_KEYS)})" for k in a if k not in _ALLOCATION_KEYS)
        aid = a.get("id")
        if not isinstance(aid, str) or not _ID_RE.match(aid):
            errs.append(f"{where}.id: 1 to 48 lower-case letters, digits, '.', '_' or '-', starting with a letter or digit")
        elif aid in seen:
            errs.append(f"{where}.id: {aid!r} is declared twice")
        else:
            seen.add(aid)
        holder = a.get("holder")
        if not isinstance(holder, str) or len(holder) > 120 or not DID_PATTERN.match(holder):
            errs.append(f"{where}.holder: the DID of the agent the allocation is granted to")
        if _cap(a.get("cap")) is None:
            errs.append(f"{where}.cap: a positive amount in the frame's unit")
        if "note" in a and (not isinstance(a.get("note"), str) or len(a["note"]) > 200):
            errs.append(f"{where}.note: a string of at most 200 characters")
    return errs


def profile_hash(doc: Dict[str, Any]) -> str:
    """'sha256:' and the hex SHA-256 of the profile's canonical JSON (the jurisdiction profile's form)."""
    canonical = json.dumps(doc, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@functools.lru_cache(maxsize=8)
def _parsed(raw: str, frame_unit: str) -> Tuple[Optional[Dict[str, Any]], Tuple[str, ...]]:
    """(the document, ()) or (None, its problems); once per distinct text, so a bad one is logged once. Read-only."""
    try:
        doc = json.loads(raw)
    except ValueError:
        errs: List[str] = ["the profile is not JSON"]
    else:
        errs = validate_profile(doc, frame_unit)
        if not errs:
            return doc, ()
    logger.error("[QUANTUM] %s is invalid, so no grant can draw on an allocation: %s", PROFILE_ENV, "; ".join(errs[:5]))
    return None, tuple(errs)


def declared_profile() -> Tuple[Optional[Dict[str, Any]], str]:
    """(the profile, "declared"), (None, "invalid") or (None, "none")."""
    raw = (os.environ.get(PROFILE_ENV) or "").strip()
    if not raw:
        return None, "none"
    doc, _errs = _parsed(raw, _frame_unit())
    return (doc, "declared") if doc is not None else (None, "invalid")


def allocation_profile_summary() -> Optional[Dict[str, Any]]:
    """What the card says about the profile: None when none is declared."""
    doc, state = declared_profile()
    if state == "none":
        return None
    if doc is None:
        return {"state": "invalid"}
    return {"state": "declared", "name": doc["name"], "version": doc["version"],
            "allocation_count": len(doc["allocations"]), "profile_hash": profile_hash(doc)}


def _find(doc: Optional[Dict[str, Any]], allocation_id: str) -> Optional[Dict[str, Any]]:
    return next((a for a in (doc or {}).get("allocations", []) if a.get("id") == allocation_id), None)


def _fmt(value: Decimal) -> str:
    """An amount as plain digits, never an exponent (str(Decimal("1E+3")) is "1E+3")."""
    out = format(value, "f")
    if "." in out:
        out = out.rstrip("0").rstrip(".")
    return out or "0"


def evaluate_grant(profile: Optional[Dict[str, Any]], allocation_id: str, holder_did: str, amount: Decimal,
                   granted: Decimal) -> Tuple[bool, Optional[str], str]:
    """Pure decision for a grant that names an allocation: (allowed, the refusal's code word or None, the sentence)."""
    if profile is None:
        return False, "allocation_profile_missing", (
            f"this frame declares no allocation profile ({PROFILE_ENV}), so a grant cannot draw on an allocation")
    alloc = _find(profile, allocation_id)
    if alloc is None:
        return False, "allocation_unknown", (
            f"allocation {allocation_id!r} is not in this frame's allocation profile {profile.get('name')!r}")
    if alloc.get("holder") != holder_did:
        return False, "allocation_holder_mismatch", f"allocation {allocation_id!r} is declared for another agent"
    cap = _cap(alloc.get("cap")) or Decimal("0")
    after = granted + amount
    if after > cap:
        return False, "allocation_cap_exceeded", (
            f"this grant of {_fmt(amount)} would take allocation {allocation_id!r} to {_fmt(after)}, past its cap of "
            f"{_fmt(cap)}; {_fmt(max(cap - granted, Decimal('0')))} remain under it")
    return True, None, f"allocation {allocation_id!r}: {_fmt(after)} of its cap of {_fmt(cap)} granted"


def allocation_named_by(reason: Any) -> Optional[str]:
    """The allocation a grant's reason names (`allocation:<id>`), or None."""
    if isinstance(reason, str) and reason.startswith(GRANT_REASON_PREFIX):
        return reason[len(GRANT_REASON_PREFIX):]
    return None


# ── the tally and the hold ────────────────────────────────────────────────────────────────────────────────────────────

def tally_key(allocation_id: str) -> str:
    return TALLY_KEY_PREFIX + allocation_id


def _tally_insert(key: str):
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from ..models import ExchangeFlag
    return pg_insert(ExchangeFlag).values(key=key, value="0").on_conflict_do_nothing(index_elements=["key"])


def _tally_select(key: str):
    from sqlalchemy import select
    from ..models import ExchangeFlag
    return select(ExchangeFlag.value).where(ExchangeFlag.key == key).with_for_update()


def _tally_update(key: str, value: Decimal):
    from sqlalchemy import func, update
    from ..models import ExchangeFlag
    return update(ExchangeFlag).where(ExchangeFlag.key == key).values(value=_fmt(value), updated_at=func.now())


def _session_factory():
    """The session maker the tally opens its own short transactions with, apart from the caller's session."""
    from ..database import AsyncSessionLocal
    return AsyncSessionLocal


def _count(decision: str, mode: str, reason: str) -> None:
    if _DECISIONS is not None:
        try:
            _DECISIONS.labels(decision=decision, mode=mode, reason=reason).inc()
        except Exception:  # noqa: BLE001
            pass


def _moved_amount(value: Any) -> Optional[Decimal]:
    """An amount the TEG reports as moved: finite and not negative, or None."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return amount if amount.is_finite() and amount >= 0 else None


@dataclass
class AllocationHold:
    """What a grant holds against its allocation while the TEG is asked; empty when nothing is held. `give_back` is the
    part of the held amount the caller has evidence did not move; it stays 0, the whole amount counted, without it."""
    allocation_id: Optional[str] = None
    amount: Decimal = Decimal("0")
    reserved: bool = False
    give_back: Decimal = Decimal("0")

    def nothing_moved(self) -> None:
        """The caller has evidence the TEG moved nothing: its ledger gate refused, or the request never left (no
        connection was made). Never a balance read."""
        self.give_back = self.amount

    def teg_account(self, body: Any) -> None:
        """The TEG's own account of a waterfall it could not finish (reward-fund answers 400 with status `exhausted`, the
        legs it committed and their funded amount): what it funded stays counted and the rest is given back. An account
        that does not add up (not a number, more than the grant, a leg with nothing funded, funds with no leg) gives
        nothing back."""
        if not self.reserved or not isinstance(body, dict) or body.get("status") != "exhausted":
            return
        funded = _moved_amount(body.get("funded_amount"))
        legs = body.get("legs")
        if funded is None or not isinstance(legs, list) or funded > self.amount or (funded == 0) != (not legs):
            logger.warning("[QUANTUM] allocation %s: the TEG's account of a grant of %s does not add up; it stays counted",
                           self.allocation_id, _fmt(self.amount))
            return
        self.give_back = self.amount - funded


def _refuse(mode: str, allocation_id: str, code: str, sentence: str) -> None:
    _count("DENY", mode, code)
    logger.warning("[QUANTUM] allocation grant decision=DENY mode=%s allocation=%s reason=%s: %s",
                   mode, allocation_id, code, sentence)
    raise HTTPException(status_code=403, detail=f"{code}: {sentence}")


def _report(mode: str, allocation_id: str, code: Optional[str], sentence: str) -> None:
    if code is None:
        _count("ALLOW", mode, "allowed")
        logger.info("[QUANTUM] allocation grant decision=ALLOW mode=%s allocation=%s: %s", mode, allocation_id, sentence)
        return
    _count("DENY", mode, code)
    logger.warning("[QUANTUM] allocation grant decision=DENY mode=%s allocation=%s reason=%s (reported, let through): %s",
                   mode, allocation_id, code, sentence)


async def _reserve(hold: AllocationHold, mode: str, allocation_id: str, holder_did: str, amount: Decimal) -> None:
    doc, state = declared_profile()
    alloc = _find(doc, allocation_id)
    code: Optional[str] = None
    sentence = ""
    if state == "invalid":
        code, sentence = "allocation_profile_invalid", (
            f"this frame's allocation profile ({PROFILE_ENV}) does not parse, so a grant cannot draw on an allocation "
            "until it does")
    elif doc is None or alloc is None or alloc.get("holder") != holder_did:
        _allowed, code, sentence = evaluate_grant(doc, allocation_id, holder_did, amount, Decimal("0"))
    if code is not None and mode == "on":
        _refuse(mode, allocation_id, code, sentence)            # decided without the tally
    if not _ID_RE.match(allocation_id):
        _report(mode, allocation_id, code, sentence)            # shadow: nothing a tally could be keyed by
        return
    key = tally_key(allocation_id)
    refusal: Optional[Tuple[str, str]] = None
    try:
        async with _session_factory()() as s:
            await s.execute(_tally_insert(key))
            granted = Decimal(str((await s.execute(_tally_select(key))).scalar_one()))
            if code is None:
                _allowed, code, sentence = evaluate_grant(doc, allocation_id, holder_did, amount, granted)
            if code is not None and mode == "on":
                await s.rollback()
                refusal = (code, sentence)
            else:
                await s.execute(_tally_update(key, granted + amount))
                await s.commit()
                hold.allocation_id, hold.amount, hold.reserved = allocation_id, amount, True
    except Exception:  # noqa: BLE001: never the exception's text in an answer
        logger.error("[QUANTUM] allocation %s: the amount granted under it could not be read or written (mode=%s)",
                     allocation_id, mode, exc_info=True)
        _count("UNAVAILABLE", mode, "allocation_tally_unavailable")
        if mode == "on":
            raise HTTPException(status_code=503, detail=(
                "allocation_tally_unavailable: the amount already granted under this allocation could not be read, so "
                "the grant was not made; try again"))
        return
    if refusal is not None:
        _refuse(mode, allocation_id, *refusal)
    _report(mode, allocation_id, code, sentence)


async def _release(hold: AllocationHold) -> None:
    key = tally_key(hold.allocation_id or "")
    back = min(hold.give_back, hold.amount)
    try:
        async with _session_factory()() as s:
            raw = (await s.execute(_tally_select(key))).scalar_one_or_none()
            if raw is not None:
                await s.execute(_tally_update(key, max(Decimal(str(raw)) - back, Decimal("0"))))
                await s.commit()
        logger.info("[QUANTUM] allocation %s: %s of a grant of %s did not move; that room is given back",
                    hold.allocation_id, _fmt(back), _fmt(hold.amount))
    except Exception:  # noqa: BLE001: the room stays counted, which can only make it smaller
        logger.error("[QUANTUM] allocation %s: %s of a grant of %s that did not move could not be given back; it stays "
                     "counted", hold.allocation_id, _fmt(back), _fmt(hold.amount), exc_info=True)


@contextlib.asynccontextmanager
async def allocation_grant_hold(reason: Any, holder_did: str, amount: Any) -> AsyncIterator[AllocationHold]:
    """Around a treasury grant's TEG call. A grant naming no allocation, or any grant while the switch is off, holds
    nothing and reads nothing. Otherwise the decision is made before the call (on refuses, shadow reports) and the amount
    is counted; the part the caller has evidence did not move is given back (hold.nothing_moved(), hold.teg_account())."""
    hold = AllocationHold()
    mode = quantum_workloads_mode()
    allocation_id = allocation_named_by(reason)
    if mode == "off" or allocation_id is None:
        yield hold
        return
    await _reserve(hold, mode, allocation_id, holder_did, Decimal(str(amount)))
    try:
        yield hold
    finally:
        if hold.reserved and hold.give_back > 0:
            await _release(hold)
