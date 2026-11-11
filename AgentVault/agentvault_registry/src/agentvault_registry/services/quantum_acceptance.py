"""V0660 (b): acceptance tests on the rails that already settle work: a Guild work order's verify step and a contracts v2
milestone's release step. No new money rail: a verdict only decides whether the existing step may settle.

Everything here waits for QUANTUM_WORKLOADS_MODE (core/quantum_mode.py). Under off, the source default, nothing is read
and nothing changes: the routes answer 403 and are left out of the OpenAPI schema, and settlement_gate() returns before
it touches the database.

1. The agreement, made before the run (POST /api/v1/quantum/acceptance): the poster of an open work order, or the
   client of a contract not yet accepted for a pending milestone, names an acceptance test (services/quantum_receipts.py
   check_agreement: a template, its parameters, the error rates of a rung 2 test, optionally the verifier and the keys
   the participants sign with). It is recorded once, in the rail's own event log (guild_order_events or
   contract_events, event `quantum_test_agreed`), with its digest; the run's first receipt step names that digest.
   The registry writes the piece of work into the agreement it records (`work`: the rail, the reference and a
   milestone's number), so the same terms agreed for two pieces of work have two digests, and a chain made for one is
   refused for any other. A pin adds a key only for a DID that is not an agent here.

2. The verdict (POST /api/v1/quantum/verdicts): a party hands in the receipt chain and the evidence once the work is
   delivered. The registry checks the chain, the keys (each step's key must be its participant's: registered here,
   current or within its rotation grace, or pinned in the agreement), and recomputes the verdict from the evidence; the
   verifier's signed verdict must be that one, and the agreement must name the work the chain is handed in for. Each
   step must also come from the right party of record (role_problems):
   the payer submits the circuits, the worker (or a provider the agreement pins) runs them, the named verifier or else a
   party signs the verdict, and an independent repeat runs at neither party. Then it records the verdict, hashes and the verdict only, never circuits,
   counts or results (event `quantum_verdict`). One verdict per agreement: a second run cannot be shopped for.

3. The gate (settlement_gate()), called by the verify and release steps before they claim the money: an order or a
   milestone with an agreement settles only on a passing verdict. on refuses (409 quantum_verdict_required or
   quantum_verdict_failed); shadow reports and lets it through. A failed verdict leaves the existing reject step, which
   opens a dispute as it always did.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import bindparam, text

from ..core.quantum_mode import quantum_workloads_mode
from . import quantum_receipts as qr

logger = logging.getLogger(__name__)

RAILS = ("guild_work_order", "contract_milestone")
# event_type is VARCHAR(24) in guild_order_events (0114) and VARCHAR(32) in contract_events (0129)
AGREED_EVENT = "quantum_test_agreed"
VERDICT_EVENT = "quantum_verdict"
MAX_AGREEMENT_BYTES = 64_000
MAX_SUBMISSION_BYTES = 2_000_000

try:  # metrics are best-effort; observability never breaks a settlement
    from prometheus_client import Counter as _Counter
    _GATE = _Counter("quantum_acceptance_gate_decisions_total",
                     "Acceptance-test decisions at the verify and release steps", ["rail", "mode", "decision"])
except Exception:  # pragma: no cover
    _GATE = None


def _count(rail: str, mode: str, decision: str) -> None:
    if _GATE is not None:
        try:
            _GATE.labels(rail=rail, mode=mode, decision=decision).inc()
        except Exception:  # noqa: BLE001
            pass


def _payload(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    return raw if isinstance(raw, dict) else {}


# ── what the rails' event logs hold ──────────────────────────────────────────────────────────────────────────────────

async def recorded(db, rail: str, ref: str, seq: Optional[int] = None) -> Tuple[Optional[Dict[str, Any]],
                                                                                   Optional[Dict[str, Any]]]:
    """(the agreement event's payload, the verdict event's payload) for an order or a milestone; None where absent.
    The first agreement counts, and the first verdict recorded under its digest."""
    if rail == "guild_work_order":
        rows = (await db.execute(text(
            "SELECT event_type, payload FROM guild_order_events WHERE order_id = :r "
            "AND event_type IN (:a, :v) ORDER BY seq ASC"), {"r": ref, "a": AGREED_EVENT, "v": VERDICT_EVENT})).all()
    else:
        rows = (await db.execute(text(
            "SELECT event_type, payload FROM contract_events WHERE contract_id = :r "
            "AND event_type IN (:a, :v) AND payload->>'milestone' = :s ORDER BY seq ASC"),
            {"r": ref, "a": AGREED_EVENT, "v": VERDICT_EVENT, "s": str(seq)})).all()
    agreement: Optional[Dict[str, Any]] = None
    verdict: Optional[Dict[str, Any]] = None
    for etype, raw in rows:
        p = _payload(raw)
        if etype == AGREED_EVENT and agreement is None:
            agreement = p
        elif etype == VERDICT_EVENT and verdict is None and agreement is not None \
                and p.get("acceptance_digest") == agreement.get("acceptance_digest"):
            verdict = p
    return agreement, verdict


async def registered_keys(db, dids: Iterable[str]) -> Dict[str, List[Any]]:
    """The public keys each DID signs with on this registry: the agent's current key and every rotated one still in its
    grace window (agent_signing_keys)."""
    wanted = sorted({d for d in dids if isinstance(d, str)})
    keys: Dict[str, List[Any]] = {d: [] for d in wanted}
    if not wanted:
        return keys
    rows = (await db.execute(text("SELECT did, public_key_jwk FROM agents WHERE did IN :d")
                             .bindparams(bindparam("d", expanding=True)), {"d": wanted})).all()
    rows += (await db.execute(text(
        "SELECT agent_did, public_jwk FROM agent_signing_keys WHERE agent_did IN :d "
        "AND (expires_at IS NULL OR expires_at > now())").bindparams(bindparam("d", expanding=True)),
        {"d": wanted})).all()
    for did, jwk in rows:
        jwk = _payload(jwk)
        if jwk and did in keys:
            keys[did].append(jwk)
    return keys


async def local_dids(db, dids: Iterable[str]) -> List[str]:
    """The DIDs that are agents of this registry. Their keys are the ones registered here; an agreement cannot pin
    another one for them."""
    wanted = sorted({d for d in dids if isinstance(d, str)})
    if not wanted:
        return []
    rows = (await db.execute(text("SELECT did FROM agents WHERE did IN :d")
                             .bindparams(bindparam("d", expanding=True)), {"d": wanted})).all()
    found = {r[0] for r in rows}
    return [d for d in wanted if d in found]


def pin_problems(local: Iterable[str]) -> List[str]:
    return [f"participants: {d} is an agent of this registry; it signs with the keys registered here, and an agreement "
            "cannot pin another key for it" for d in local]


def work_of(rail: str, ref: str, seq: Optional[int] = None) -> Dict[str, Any]:
    """The piece of work an agreement settles, as the agreement's `work` member names it."""
    work: Dict[str, Any] = {"rail": rail, "ref": ref}
    if seq is not None:
        work["seq"] = seq
    return work


_PROVIDER_STEPS = ("circuit_compiled", "backend_bound", "run_executed", "result_reported")


def role_problems(agreement: Any, chain: Any, evidence: Any, *, payer: Optional[str],
                  worker: Optional[str]) -> List[str]:
    """Who signed each step, against the parties of record (the receipt module checks the keys; this checks the people).

    - circuit_submitted: the payer (the poster or the client), or a DID the agreement pins (a router);
    - circuit_compiled, backend_bound, run_executed, result_reported: the worker of record (the worker or the provider),
      or a DID the agreement pins (a provider on another registry); never the payer;
    - verdict: the verifier the agreement names (the receipt module checks that), or with none named, the payer or the
      worker;
    - an independent repeat (evidence.repeat_chain): submitted by a party or a pinned DID, run at neither party.
    Pins are written by the payer before the work is awarded, so the worker sees them before it takes the work."""
    if not isinstance(agreement, dict):
        return []
    pinned = set(qr.pinned_keys(agreement))
    out: List[str] = []
    if not worker:
        out.append("quantum_receipt_role: the work has no worker of record")
    for i, step in enumerate(chain if isinstance(chain, list) else []):
        if not isinstance(step, dict):
            continue
        kind, who = step.get("kind"), step.get("participant")
        where = f"step {i} ({kind})"
        if kind == "circuit_submitted" and who != payer and who not in pinned:
            out.append(f"quantum_receipt_role: {where}: signed by {who}; the payer ({payer}) submits the circuits, or a "
                       "router the agreement pins")
        elif kind in _PROVIDER_STEPS and (who == payer or (who != worker and who not in pinned)):
            out.append(f"quantum_receipt_role: {where}: signed by {who}; this step is signed by the worker of record "
                       f"({worker}) or a provider the agreement pins")
        elif kind == "verdict" and not agreement.get("verifier") and who not in (payer, worker):
            out.append(f"quantum_receipt_role: {where}: signed by {who}; the agreement names no verifier, so the verdict "
                       "is signed by the payer or the worker")
    repeat = evidence.get("repeat_chain") if isinstance(evidence, dict) else None
    if agreement.get("template") == "independent-repeat/v1.0" and isinstance(repeat, list):
        for i, step in enumerate(repeat):
            if not isinstance(step, dict):
                continue
            kind, who = step.get("kind"), step.get("participant")
            where = f"evidence.repeat_chain: step {i} ({kind})"
            if kind == "circuit_submitted" and who not in (payer, worker) and who not in pinned:
                out.append(f"quantum_receipt_role: {where}: signed by {who}; a party or a DID the agreement pins "
                           "submits the repeat")
            elif kind in _PROVIDER_STEPS and who in (payer, worker):
                out.append(f"quantum_receipt_role: {where}: signed by {who}; an independent repeat runs at neither "
                           "party")
    return out


# ── the gate at the verify and release steps ─────────────────────────────────────────────────────────────────────────

async def settlement_gate(db, rail: str, ref: str, seq: Optional[int] = None) -> None:
    """Before the existing verify or release step claims the money. Under off: returns at once, nothing read. An order
    or a milestone with no agreement settles as it always did. With one, it settles on a passing verdict; on refuses
    anything else (409), shadow reports it and lets the step go on."""
    mode = quantum_workloads_mode()
    if mode == "off":
        return
    try:
        agreement, verdict = await recorded(db, rail, ref, seq)
    except Exception:  # noqa: BLE001: never the exception's text in an answer
        logger.error("[QUANTUM] %s %s: the acceptance test could not be read (mode=%s)", rail, ref, mode, exc_info=True)
        _count(rail, mode, "unavailable")
        if mode == "on":
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=(
                "quantum_acceptance_unavailable: whether this work has an acceptance test could not be read, so it "
                "was not settled; try again"))
        return
    if agreement is None:
        return
    where = f"{rail} {ref}" + (f" milestone {seq}" if seq is not None else "")
    if verdict is not None and verdict.get("passed") is True:
        _count(rail, mode, "passed")
        logger.info("[QUANTUM] %s settles on its passing verdict (%s, head %s)", where, verdict.get("template"),
                    verdict.get("head"))
        return
    if verdict is None:
        code, sentence = "quantum_verdict_required", (
            f"this work settles on its acceptance test ({agreement.get('template')}), and no verdict is recorded yet; "
            "hand in the receipt chain and the evidence (POST /api/v1/quantum/verdicts)")
    else:
        code, sentence = "quantum_verdict_failed", (
            f"the acceptance test ({verdict.get('template')}) failed: {verdict.get('reason')}; the reject step opens "
            "a dispute")
    _count(rail, mode, code)
    if mode == "shadow":
        logger.warning("[QUANTUM-SHADOW] %s would be refused under QUANTUM_WORKLOADS_MODE=on: %s: %s", where, code,
                       sentence)
        return
    logger.info("[QUANTUM] %s refused: %s", where, code)
    raise HTTPException(status.HTTP_409_CONFLICT, detail=f"{code}: {sentence}")


__all__ = ["RAILS", "AGREED_EVENT", "VERDICT_EVENT", "MAX_AGREEMENT_BYTES", "MAX_SUBMISSION_BYTES", "recorded",
           "registered_keys", "local_dids", "pin_problems", "work_of", "role_problems", "settlement_gate"]
