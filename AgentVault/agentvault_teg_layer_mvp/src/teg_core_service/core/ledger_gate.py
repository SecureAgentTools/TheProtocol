"""§LEDGERGATE (2026-10-11) — no new value movement while the ledger cannot record it.

His ask 2026-10-11: "we also have to make actions fail that have event emissions while cqrs outbox to evenstore is
unhealthy. this will safe us a lot of trouble." Every balance change on this TEG is journaled in its own transaction
(balance_ledger_journal), and the balance outbox carries the journal to the event store. When the store stops taking
it, the TEG still moves money and the store's projection falls behind: the projection reads accounts as lower than they
are (the legacy frames' "negative" accounts) and the auditor reads a ledger that is not the TEG's. This gate refuses a
request that STARTS a value movement while the ledger's health (core/ledger_health.py, published by the outbox leader)
says unhealthy.

    TEG_LEDGER_GATE_MODE   off | shadow | enforce   (default off; an unknown value is served as shadow and said loudly)

  off       nothing is read, nothing is counted.
  shadow    the decision is made and counted (`teg_ledger_gate_decisions_total{route,decision}`), nothing is refused.
  enforce   an unhealthy ledger refuses a starting request: 503, Retry-After, the TEG's RFC 7807 body with code
            `ledger_unavailable` and the sentence the registry and the console pass on: "The ledger cannot record this
            right now. Nothing was moved. Try again shortly."

What passes, always:
  - readers (a GET, HEAD or OPTIONS never touches a balance);
  - FINISHING work: the commit or abort of a 2PC transfer already locked, the credit leg of a transfer whose debit
    already happened (credit-async, the treasury-fund receive, the bridge's mint and unlock), refunds and reversals,
    payouts out of the exchange escrow or the FX reserve. They are bounded by what is already in flight, the journal
    records them in the same transaction (nothing is lost), and refusing them would strand money that is locked;
  - every route of a TEG whose balance outbox is off (`TEG_BALANCE_OUTBOX_ENABLED` unset or false: its balance changes
    reach the store only as the registry's typed events, so the gate has no reading to act on there, and says "inert"
    in /health). The setting decides, never the TEG's role: the provisioner writes the outbox ON for every cloud
    operator (services/cloud_provisioner.py), whose balance changes reach its parent frame's store through it, so an
    operator's TEG is gated like its frame's.

The ledger's state comes from Redis (one verdict per TEG, read at most once a second per worker). A missing verdict is
never read as healthy: in a worker's first 60 s it passes as "unknown"; after that the gate measures the journal
itself (the oldest row the store has not taken, and how many wait): over the unhealthy thresholds it refuses, under
them it passes as degraded ("no_verdict"), so a change of outbox leader does not stop the TEG and a dead leader with
work waiting does.

The route classes below are the whole list of this TEG's write routes; tests/test_ledger_gate.py fails when a write
route is in none of them, in two of them, or when an entry names a route the TEG does not serve.
"""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import ledger_health as _lh

logger = logging.getLogger(__name__)

MODES = ("off", "shadow", "enforce")
SENTENCE = "The ledger cannot record this right now. Nothing was moved. Try again shortly."
DETAIL = f"ledger_unavailable: {SENTENCE}"
ERROR_TYPE = "ledger-unavailable"
CODE = "ledger_unavailable"
BOOT_GRACE_S = 60.0
CACHE_S = 1.0
_LOG_EVERY_S = 60.0

# ----------------------------------------------------------------------------------------------- the route classes
# (method, path as FastAPI declares it, with the /api/v1 prefix)
STARTING: Tuple[Tuple[str, str], ...] = (
    ("POST", "/api/v1/token/transfer"),
    ("POST", "/api/v1/token/transfer/bulk"),
    ("POST", "/api/v1/token/transfer/to-system"),
    ("POST", "/api/v1/token/testing/faucet"),
    ("POST", "/api/v1/admin/token/issue"),
    ("POST", "/api/v1/admin/token/burn"),
    ("POST", "/api/v1/admin/treasury/transfer"),
    ("POST", "/api/v1/admin/treasury/receive"),
    ("POST", "/api/v1/admin/treasury/external-credit"),   # retired (§SECFIX-11): refuses before it moves anything
    ("POST", "/api/v1/admin/treasury/external-debit"),
    ("POST", "/api/v1/admin/treasury/cross-teg-fund-send"),
    ("POST", "/api/v1/admin/fee-collector/distribute"),
    ("POST", "/api/v1/admin/reward-fund"),
    ("POST", "/api/v1/cross-teg/transfer"),
    ("POST", "/api/v1/cross-teg/lock-async"),
    ("POST", "/api/v1/cross-teg/prepare/{transfer_id}"),
    ("POST", "/api/v1/bridge/lock"),
    ("POST", "/api/v1/bridge/burn"),
    ("POST", "/api/v1/governance/staking/stake"),
    ("POST", "/api/v1/governance/staking/unstake"),
    ("POST", "/api/v1/governance/admin/staking/trigger-reward-cycle"),
    ("POST", "/api/v1/tokenomics/stake"),
    ("POST", "/api/v1/tokenomics/unstake"),
    ("POST", "/api/v1/tokenomics/lock"),
    ("POST", "/api/v1/tokenomics/unlock"),
    ("POST", "/api/v1/tokenomics/rewards/claim"),
    ("POST", "/api/v1/disputes/{dispute_id}/resolve"),        # a penalty moves the defendant's balance
    ("POST", "/api/v1/onboarding/onboard/register"),           # the onboarding issuance (D8)
)

FINISHING: Tuple[Tuple[str, str], ...] = (
    ("POST", "/api/v1/cross-teg/commit/{transfer_id}"),
    ("POST", "/api/v1/cross-teg/abort/{transfer_id}"),
    ("POST", "/api/v1/cross-teg/accept"),
    ("POST", "/api/v1/cross-teg/credit-async"),
    ("POST", "/api/v1/cross-teg/credit-async-bulk"),
    ("POST", "/api/v1/cross-teg/refund-async"),
    ("POST", "/api/v1/cross-teg/reverse-async"),
    ("POST", "/api/v1/cross-teg/treasury-fund"),
    ("POST", "/api/v1/bridge/mint"),
    ("POST", "/api/v1/bridge/unlock"),
)

# Decided inside the handler, because one route does both: into the account it holds STARTS a movement, out of it
# FINISHES one (the handler calls require_ledger() before it moves money into the account).
IN_HANDLER: Tuple[Tuple[str, str], ...] = (
    ("POST", "/api/v1/admin/exchange/move"),   # into the exchange escrow: an order, an IPO, a dividend pot
    ("POST", "/api/v1/admin/fx/move"),         # into the FX reserve: a swap's first leg, the keeper's top-up
)

# Write routes that move no balance (status, configuration, metadata, logs, credentials). An opening balance on the
# two initialize routes is refused (§MONEY-R35); /agent/initialize's welcome bonus reads a setting the TEG does not
# define (the census test pins that, so the bonus cannot come back without this list changing).
NO_VALUE: Tuple[Tuple[str, str], ...] = (
    ("DELETE", "/api/v1/governance/admin/policies/{policy_id}"),
    ("DELETE", "/api/v1/onboarding/admin/bootstrap/cleanup-expired"),
    ("POST", "/api/v1/admin/agents/{agent_id}/reinstate"),
    ("POST", "/api/v1/admin/agents/{agent_id}/suspend"),
    ("POST", "/api/v1/admin/attestations/{submission_id}/verify"),
    ("POST", "/api/v1/admin/auditor/flags/bulk-update"),
    ("POST", "/api/v1/admin/auditor/flags/{flag_id}/escalate"),
    ("POST", "/api/v1/admin/auditor/flags/{flag_id}/update"),
    ("POST", "/api/v1/admin/reputation/recalculate/{agent_id}"),
    ("POST", "/api/v1/agent/{agent_id}/reactivate"),
    ("POST", "/api/v1/agent/bulk-initialize"),
    ("POST", "/api/v1/agent/capabilities/register"),
    ("POST", "/api/v1/agent/deactivate"),
    ("POST", "/api/v1/agent/initialize"),
    ("POST", "/api/v1/agent/initialize-teg-account"),
    ("POST", "/api/v1/agent/services/register"),
    ("POST", "/api/v1/attestation/submit"),
    ("POST", "/api/v1/auditor/flags/bulk-resolution"),
    ("POST", "/api/v1/auditor/flags"),
    ("POST", "/api/v1/auditor/flags/{flag_id}/escalate"),
    ("POST", "/api/v1/auth/token"),
    ("POST", "/api/v1/avtp/log_transaction_summary"),
    ("POST", "/api/v1/cross-teg/admin/agents/{agent_did:path}/block"),
    ("POST", "/api/v1/cross-teg/admin/agents/{agent_did:path}/unblock"),
    ("POST", "/api/v1/cross-teg/admin/emission-policy/refresh"),
    ("POST", "/api/v1/cross-teg/config/add-partner"),
    ("POST", "/api/v1/cross-teg/config/remove-partner"),
    ("POST", "/api/v1/disputes/admin/disputes/{dispute_log_id}/update_status"),
    ("POST", "/api/v1/disputes/"),
    ("POST", "/api/v1/governance/admin/policies"),
    ("POST", "/api/v1/governance/admin/rewards/config"),
    ("POST", "/api/v1/governance/staking/delegate"),
    ("POST", "/api/v1/governance/staking/undelegate/{delegation_id}"),
    ("POST", "/api/v1/internal/create-agent-profile"),
    ("POST", "/api/v1/onboarding/bootstrap/request-token"),
    ("POST", "/api/v1/reputation/signal"),
    ("POST", "/api/v1/token/{transaction_id}/reputation-signal"),
    ("PUT", "/api/v1/admin/auditor/rules/config"),
    ("PUT", "/api/v1/admin/disputes/{dispute_id}/status"),
    ("PUT", "/api/v1/admin/reward-funding/policy"),
    ("PUT", "/api/v1/agent/profile/metadata"),
    ("PUT", "/api/v1/auditor/flags/{flag_id}/status"),
    ("PUT", "/api/v1/auditor/rules/{rule_id}/disable"),
    ("PUT", "/api/v1/auditor/rules/{rule_id}/thresholds"),
    ("PUT", "/api/v1/governance/admin/policies/{policy_id}"),
    ("PUT", "/api/v1/governance/admin/rewards/config/{reward_id}"),
)

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _norm(path: str) -> str:
    return path.rstrip("/") or "/"


def _template_regex(template: str) -> "re.Pattern[str]":
    out, pos = [], 0
    for m in re.finditer(r"\{([^}:]+)(:path)?\}", template):
        out.append(re.escape(template[pos:m.start()]))
        out.append(".+" if m.group(2) else "[^/]+")
        pos = m.end()
    out.append(re.escape(template[pos:]))
    return re.compile("^" + "".join(out) + "$")


_STARTING_RX: List[Tuple[str, str, "re.Pattern[str]"]] = [
    (m, _norm(p), _template_regex(_norm(p))) for (m, p) in STARTING
]


def starting_route(method: str, path: str) -> Optional[str]:
    """The route template a request starts a value movement on, or None."""
    method = (method or "").upper()
    if method not in WRITE_METHODS:
        return None
    p = _norm(path or "")
    for m, template, rx in _STARTING_RX:
        if m == method and rx.match(p):
            return template
    return None


# ----------------------------------------------------------------------------------------------- the switch
def resolve_mode(raw: Optional[str]) -> str:
    m = (raw or "off").strip().lower()
    if m not in MODES:
        logger.error("[LEDGER-GATE] TEG_LEDGER_GATE_MODE=%r is not one of %s; serving as shadow", m[:40], MODES)
        return "shadow"
    return m


def outbox_enabled(env=os.environ) -> bool:
    return (env.get("TEG_BALANCE_OUTBOX_ENABLED") or "false").strip().lower() == "true"


def decide(mode: str, inert: bool, state: str) -> str:
    """The gate's decision for a starting request, from the mode and the ledger's state."""
    if mode == "off" or inert:
        return "pass_off"
    if state == _lh.OK:
        return "pass"
    if state == _lh.DEGRADED:
        return "pass_degraded"
    if state != _lh.UNHEALTHY:
        return "pass_unknown"
    return "refuse" if mode == "enforce" else "would_refuse"


# ----------------------------------------------------------------------------------------------- the reading
def _teg_id() -> str:
    from .balance_outbox import _teg_id as outbox_teg_id
    return outbox_teg_id()


_BOOTED_AT = time.monotonic()
_THRESHOLDS = _lh.Thresholds.from_env()
_cache: Dict[str, Any] = {"at": -1e9, "value": None}


async def _measure_journal() -> Tuple[int, Optional[float]]:
    from sqlalchemy import text
    from ..database.db_session import AsyncSessionLocal
    if AsyncSessionLocal is None:
        raise RuntimeError("no async session")
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(_lh.WAITING_SQL), {"stuck": []})).fetchone()
    waiting, age, _s, _sa = _lh.waiting_from_row(row or ())
    return waiting, age


async def read_verdict(now: Optional[float] = None, redis=None, use_redis_client: bool = True,
                       measure=None) -> Dict[str, Any]:
    """The ledger's state for this TEG: the leader's published verdict, else (after the boot grace) the journal's."""
    now = time.monotonic() if now is None else now
    if redis is None and use_redis_client:
        try:
            from ..redis_client import get_redis
            redis = await get_redis()
        except Exception:  # noqa: BLE001
            redis = None
    body, why = await _lh.read(redis, _teg_id())
    if body is not None:
        return {"state": body["state"], "reason": body.get("reason") or body["state"], "source": "leader",
                "retry_after_s": int(body.get("retry_after_s") or 30),
                "waiting_rows": body.get("waiting_rows"), "oldest_waiting_age_s": body.get("oldest_waiting_age_s"),
                "stuck_rows": body.get("stuck_rows"), "failed_cycles": body.get("failed_cycles"),
                "updated_at": body.get("updated_at")}
    if now - _BOOTED_AT < BOOT_GRACE_S:
        return {"state": "unknown", "reason": f"boot_grace ({why})", "source": "none", "retry_after_s": 10}
    try:
        waiting, age = await (measure or _measure_journal)()
    except Exception as e:  # noqa: BLE001
        return {"state": _lh.UNHEALTHY, "reason": f"unmeasured ({why}; the journal: {type(e).__name__})",
                "source": "none", "retry_after_s": 30}
    t = _THRESHOLDS
    behind = waiting > t.unhealthy_backlog or (age or 0.0) > t.unhealthy_age_s
    return {"state": _lh.UNHEALTHY if behind else _lh.DEGRADED,
            "reason": f"no_verdict ({why}){' and rows wait' if behind else ''}", "source": "journal",
            "retry_after_s": 30 if behind else 10, "waiting_rows": waiting,
            "oldest_waiting_age_s": None if age is None else round(age, 3)}


async def verdict() -> Dict[str, Any]:
    now = time.monotonic()
    if _cache["value"] is not None and now - _cache["at"] < CACHE_S:
        return _cache["value"]
    v = await read_verdict(now)
    _cache["value"], _cache["at"] = v, now
    return v


# ----------------------------------------------------------------------------------------------- counting, refusing
try:
    from prometheus_client import Counter as _C

    LEDGER_GATE_DECISIONS = _C(
        "teg_ledger_gate_decisions_total",
        "The ledger gate's decisions on requests that start a value movement "
        "(pass, pass_degraded, pass_unknown, would_refuse in shadow, refuse in enforce)",
        ["route", "decision"],
    )
except Exception:  # pragma: no cover
    LEDGER_GATE_DECISIONS = None

_last_logged: Dict[str, float] = {}


def _count(route: str, decision: str) -> None:
    if LEDGER_GATE_DECISIONS is not None:
        try:
            LEDGER_GATE_DECISIONS.labels(route=route, decision=decision).inc()
        except Exception:  # pragma: no cover
            pass


def _note(route: str, decision: str, v: Dict[str, Any]) -> None:
    if decision not in ("refuse", "would_refuse"):
        return
    key = f"{decision}:{route}"
    now = time.monotonic()
    if now - _last_logged.get(key, -1e9) < _LOG_EVERY_S:
        return
    _last_logged[key] = now
    logger.warning("[LEDGER-GATE] %s %s: the ledger is %s (%s, from %s)", "REFUSED" if decision == "refuse" else
                   "would refuse", route, v.get("state"), v.get("reason"), v.get("source"))


def problem_response(path: str, v: Dict[str, Any]):
    """The TEG's own RFC 7807 body (errors.create_error_response), code ledger_unavailable, with Retry-After."""
    from types import SimpleNamespace
    from ..errors import create_error_response
    retry = int(v.get("retry_after_s") or 30)
    resp = create_error_response(
        detail=DETAIL, status_code=503, error_type=ERROR_TYPE, error_code=CODE,
        context={"ledger": {"state": v.get("state"), "reason": v.get("reason"), "source": v.get("source")},
                 "retry_after_s": retry, "sentence": SENTENCE},
        request=SimpleNamespace(url=SimpleNamespace(path=path)),
    )
    resp.headers["Retry-After"] = str(retry)
    return resp


class LedgerUnavailableError(Exception):
    """Raised by require_ledger() in a handler that decides for itself (the exchange and FX movers)."""

    def __init__(self, verdict: Dict[str, Any]):
        super().__init__(DETAIL)
        self.verdict = verdict


class _Config:
    mode: str = resolve_mode(os.getenv("TEG_LEDGER_GATE_MODE"))
    inert: bool = not outbox_enabled()


def configure(mode: Optional[str] = None, inert: Optional[bool] = None) -> None:
    """For tests: set the mode and the inert flag the module read at import."""
    if mode is not None:
        _Config.mode = resolve_mode(mode)
    if inert is not None:
        _Config.inert = bool(inert)
    _cache["value"], _cache["at"] = None, -1e9


async def require_ledger(route: str) -> None:
    """In a handler, before it starts a value movement: refuse (enforce) when the ledger cannot record it."""
    if _Config.mode == "off" or _Config.inert:
        return
    v = await verdict()
    d = decide(_Config.mode, _Config.inert, v.get("state"))
    _count(route, d)
    _note(route, d, v)
    if d == "refuse":
        raise LedgerUnavailableError(v)


class LedgerGate:
    """Pure ASGI middleware over the STARTING routes."""

    def __init__(self, app):
        self.app = app
        logger.info("[LEDGER-GATE] mode=%s%s", _Config.mode,
                    " (inert: the balance outbox is off on this TEG)" if _Config.inert else "")

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or _Config.mode == "off" or _Config.inert:
            await self.app(scope, receive, send)
            return
        route = starting_route(scope.get("method", ""), scope.get("path", ""))
        if route is None:
            await self.app(scope, receive, send)
            return
        try:
            v = await verdict()
        except Exception as e:  # noqa: BLE001 — a reading that raised is unmeasured, never healthy
            v = {"state": _lh.UNHEALTHY, "reason": f"unmeasured ({type(e).__name__})", "source": "none",
                 "retry_after_s": 30}
        d = decide(_Config.mode, _Config.inert, v.get("state"))
        _count(route, d)
        _note(route, d, v)
        if d != "refuse":
            await self.app(scope, receive, send)
            return
        await problem_response(scope.get("path", ""), v)(scope, receive, send)


async def status() -> Dict[str, Any]:
    """For /health: the mode, and this worker's current reading (cached a second)."""
    if _Config.mode == "off":
        return {"mode": "off"}
    if _Config.inert:
        return {"mode": _Config.mode, "inert": True,
                "reason": "the balance outbox is off on this TEG (its balance changes reach the store as typed events)"}
    try:
        v = await verdict()
    except Exception as e:  # noqa: BLE001
        v = {"state": _lh.UNHEALTHY, "reason": f"unmeasured ({type(e).__name__})", "source": "none"}
    return {"mode": _Config.mode, "ledger": v}


def all_rows() -> Iterable[Tuple[str, str, str]]:
    """(class, method, path) for every classified write route (the census test reads this)."""
    for cls, rows in (("starting", STARTING), ("finishing", FINISHING), ("in_handler", IN_HANDLER),
                      ("no_value", NO_VALUE)):
        for m, p in rows:
            yield cls, m, p
