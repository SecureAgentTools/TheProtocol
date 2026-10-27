"""Agent Evals runner — leader-elected periodic worker.

Runs due eval suites against their target agents, scores each task deterministically,
writes eval_results, and (optionally) folds the outcome into EigenTrust reputation via
a local_trust edge and pays the agent per task through the reward waterfall.

Gated EVALS_ENABLED (default OFF). Cloned from the canary_runner leadership/interval
idiom. CQRS-clean: it issues DB writes + HTTP commands, never emits events directly.
"""
import asyncio
import datetime
import hashlib
import logging
import os
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy import select, text as sa_text

from .. import models
from ..config import settings
from ..database import get_db_context
from ..es_ssl_helper import get_httpx_verify
from ..services.eval_scoring import score_task, aggregate
from .leader import try_acquire_leadership

logger = logging.getLogger(__name__)

EVALS_ENABLED = os.getenv("EVALS_ENABLED", "false").lower() in ("1", "true", "yes")
EVAL_RUNNER_INTERVAL_SEC = int(os.getenv("EVAL_RUNNER_INTERVAL_SEC", "30"))
EVAL_RUNNER_LEADER_KEY = os.getenv("EVAL_RUNNER_LEADER_KEY", "eval_runner")
EVAL_TASK_TIMEOUT_SEC = float(os.getenv("EVAL_TASK_TIMEOUT_SEC", "15"))
EVAL_MAX_AGENTS_PER_TICK = int(os.getenv("EVAL_MAX_AGENTS_PER_TICK", "8"))
# Synthetic issuer of eval reputation edges (self-consistent, non-agent DID).
EVAL_ORACLE_DID = os.getenv("EVAL_ORACLE_DID", "did:theprotocol:eval-oracle")

_runner: Optional["EvalRunner"] = None


# §DOCSFIX review (D6-673, D6-687): a run's payment identity. A payment's replay key names the run it pays for, and the
# key must be the same wherever that run is executed twice: by two workers (the leader lease is 30 s and a tick can run
# longer, so a second worker can run a suite whose next_run_at the first has not committed yet), or by a tick that is
# re-run after a crash. A random run id names neither, and a run the payee can start itself (POST /forge/evals/run, a
# bounty's evaluation, run-now) must not be a fresh payment each time it is started.
def scheduled_pay_slot(suite) -> str:
    """The slot of a scheduled run: the next_run_at the scheduler found due (s0 for a suite's first run)."""
    due = getattr(suite, "next_run_at", None)
    return "s" + (str(int(due.timestamp())) if due is not None else "0")


def on_demand_pay_slot(now: Optional[datetime.datetime] = None) -> str:
    """The slot of a run started on demand: the UTC day, so such runs pay a passing agent once a day per suite."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return "d" + now.astimezone(datetime.timezone.utc).strftime("%Y%m%d")


class EvalRunner:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if not EVALS_ENABLED:
            logger.info("[EvalRunner] EVALS_ENABLED=false — not starting.")
            return
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._run_loop())
            logger.info("[EvalRunner] started (interval=%ss).", EVAL_RUNNER_INTERVAL_SEC)

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run_loop(self) -> None:
        from . import vitals as _vitals
        await _vitals.register(EVAL_RUNNER_LEADER_KEY, module=__name__, pattern="hand-rolled",
                               interval_sec=EVAL_RUNNER_INTERVAL_SEC, enabled=True)
        while not self._stop.is_set():
            try:
                if await try_acquire_leadership(EVAL_RUNNER_LEADER_KEY):
                    async with _vitals.cycle(EVAL_RUNNER_LEADER_KEY):
                        await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                logger.warning("[EvalRunner] tick error: %s", e)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=EVAL_RUNNER_INTERVAL_SEC)
            except asyncio.TimeoutError:
                pass

    async def _tick(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        async with get_db_context() as db:
            due = (await db.execute(
                select(models.EvalSuite).where(
                    models.EvalSuite.enabled.is_(True),
                    models.EvalSuite.interval_minutes.isnot(None),
                )
            )).scalars().all()
            due = [s for s in due if s.next_run_at is None or s.next_run_at <= now]
            for suite in due:
                try:
                    await self.run_suite(db, suite, pay_slot=scheduled_pay_slot(suite))
                except Exception as e:  # noqa: BLE001
                    logger.warning("[EvalRunner] suite '%s' failed: %s", suite.key, e)
                suite.next_run_at = now + datetime.timedelta(minutes=suite.interval_minutes or 60)
            await db.commit()

    async def run_suite(self, db, suite: "models.EvalSuite", only_dids=None, pay_slot: Optional[str] = None) -> str:
        """Execute one suite against its targets. Returns the run_id. Commits rows;
        the caller controls the outer transaction boundary. GÖDEL FORGE: ``only_dids`` scopes
        the run to a specific target list (a self-triggering harness) without persisting it.
        ``pay_slot`` names the run its payments are for (scheduled_pay_slot); a run started on demand passes none
        and is paid as the day's run (on_demand_pay_slot)."""
        run_id = uuid.uuid4().hex
        pay_slot = pay_slot or on_demand_pay_slot()
        tasks = (await db.execute(
            select(models.EvalTask).where(models.EvalTask.suite_id == suite.id)
        )).scalars().all()
        if not tasks:
            logger.info("[EvalRunner] suite '%s' has no tasks — skipping.", suite.key)
            return run_id

        target_dids = list(only_dids) if only_dids else await self._resolve_targets(db, suite)
        for did in target_dids[:EVAL_MAX_AGENTS_PER_TICK]:
            endpoint = await self._agent_endpoint(db, did)
            pair_scores: List[Tuple[float, float]] = []
            any_pass = False
            for task in tasks:
                score, passed, latency, excerpt, err = await self._run_one(
                    suite, task, did, endpoint, db, pay_slot=pay_slot
                )
                any_pass = any_pass or passed
                pair_scores.append((score, task.weight or 1.0))
                db.add(models.EvalResult(
                    run_id=run_id, suite_id=suite.id, task_id=task.id, agent_did=did,
                    score=score, passed=passed, latency_ms=latency,
                    response_excerpt=(excerpt or "")[:500], error=err,
                ))
            suite_score = aggregate(pair_scores)

            if suite.emit_reputation_signal:
                await self._fold_reputation(db, did, suite_score)
            if suite.pay_per_task and Decimal(str(suite.pay_per_task)) > 0 and any_pass:
                await self._pay_agent(db, did, suite, pay_slot)
        await db.commit()
        _ran = target_dids[:EVAL_MAX_AGENTS_PER_TICK]
        logger.info("[EvalRunner] suite '%s' run %s over %d agent(s).",
                    suite.key, run_id, len(_ran))

        # §NOTIFV2 evals.completed — wired at run_suite, the choke point shared by ALL THREE
        # entry points: run_suite_once (admin 'run now'), run_suite_once_for (Gödel Forge, via
        # routers/forge.py and routers/guild.py) and the scheduled runner loop. Recipients are the
        # owners of the agents that were actually evaluated — the people whose agent was scored.
        # The scheduled loop re-runs a suite every `interval_minutes`, which is precisely why this
        # type carries a coalesce window in the catalog (one push + "+N more", not one per tick).
        # D6-679: the click opens the leaderboard's Evals tab, a page every recipient can open (the console has no
        # #/evals route; #/admin/evals is an administrator's page, and the recipients are the agents' owners).
        try:
            import asyncio as _aio_n
            from agentvault_registry.background_tasks.push_notify import notify_agent_owners
            if _ran:
                _aio_n.create_task(notify_agent_owners(
                    "evals.completed", _ran,
                    title="Evaluation completed",
                    message=f"Suite '{suite.key}' ran over {len(_ran)} agent(s).",
                    tags="clipboard", priority="default", click="/ui/#/leaderboard?mode=evals"))
        except Exception:  # noqa: BLE001
            logger.debug("[NOTIFY] evals.completed emit failed", exc_info=True)

        return run_id

    async def _resolve_targets(self, db, suite) -> List[str]:
        # §DOCSFIX D6-674 (2026-10-16): least recently evaluated by this suite first (never-evaluated first). A run
        # evaluates at most EVAL_MAX_AGENTS_PER_TICK agents and took the first ones every time, so the rest of a longer
        # list, and all but those few of the default 50 (read in no fixed order), were never evaluated by the suite.
        if suite.target_dids:
            dids = [str(d) for d in suite.target_dids]
            last = {r[0]: r[1] for r in (await db.execute(sa_text(
                "SELECT agent_did, max(created_at) FROM eval_results "
                "WHERE suite_id = :s AND agent_did = ANY(:d) GROUP BY agent_did"
            ), {"s": suite.id, "d": dids})).fetchall()}
            return sorted(dids, key=lambda d: (d in last, last.get(d) or 0))   # stable: list order among ties
        rows = (await db.execute(sa_text(
            "SELECT c.agent_did FROM agent_cards c "
            "LEFT JOIN (SELECT agent_did, max(created_at) AS last_at FROM eval_results "
            "WHERE suite_id = :s GROUP BY agent_did) r ON r.agent_did = c.agent_did "
            "WHERE c.is_active = true "
            "AND c.card_data #>> '{federation_metadata,source_registry}' IS NULL "
            "ORDER BY r.last_at ASC NULLS FIRST, c.agent_did "
            "LIMIT 50"
        ), {"s": suite.id})).fetchall()
        return [r[0] for r in rows]

    async def _agent_endpoint(self, db, did: str) -> Optional[str]:
        """Best-effort agent service URL from its card (agent_host / first interface)."""
        row = (await db.execute(sa_text(
            "SELECT card_data FROM agent_cards WHERE agent_did = :d LIMIT 1"
        ), {"d": did})).first()
        if not row or not row[0]:
            return None
        cd = row[0] if isinstance(row[0], dict) else {}
        host = cd.get("agent_host") or cd.get("url")
        if not host:
            ifaces = (cd.get("supportedInterfaces") or cd.get("interfaces") or [])
            if ifaces and isinstance(ifaces, list):
                host = (ifaces[0] or {}).get("url")
        return host

    async def _run_one(self, suite, task, did, endpoint, db=None,
                       pay_slot: Optional[str] = None) -> Tuple[float, bool, Optional[int], Optional[str], Optional[str]]:
        # GÖDEL FORGE — code_patch tasks are scored by the N-of-M staked verifier quorum
        # (services/forge_verify), NOT a shallow HTTP probe: the candidate never self-reports.
        # Verifiers run the held-out hidden tests on their own infra; the score settles only on
        # quorum agreement. Inconclusive quorum → 0/not-passed (never a silent pass).
        if task.scorer == "code_patch":
            try:
                from ..services import forge_verify
                # Commit BEFORE the quorum fan-out: verifier dispatches are long-running HTTP calls,
                # and holding the session's open transaction across them gets the connection killed
                # by the 60s idle-in-transaction reaper (the §V0119 federation_sync failure class) →
                # PendingRollbackError poisons the rest of the run. Committed work is append-only.
                if db is not None:
                    await db.commit()
                if db is not None:
                    frac, qmeta = await forge_verify.run_quorum(db, task, did, self._agent_endpoint,
                                                                pay_slot=pay_slot)
                else:
                    frac, qmeta = None, {}
            except Exception as e:  # noqa: BLE001
                return (0.0, False, None, None, f"quorum_error:{str(e)[:120]}")
            score, passed = score_task("code_patch", task.expected,
                                       status_code=None, body=None, latency_ms=None, quorum_score=frac)
            _qsuffix = f" responders={qmeta.get('responders', 0)} signed={qmeta.get('signed', 0)}" if qmeta else ""
            return (score, passed, None,
                    (f"quorum_fraction={frac}" + _qsuffix) if frac is not None else ("quorum_inconclusive" + _qsuffix),
                    None if frac is not None else "quorum_no_settlement")
        if not endpoint:
            return (0.0, False, None, None, "no_endpoint")
        task_input = task.input or {}
        path = task_input.get("path", "")
        url = endpoint.rstrip("/") + (path if path.startswith("/") else "/" + path if path else "")
        started = None
        try:
            async with httpx.AsyncClient(timeout=EVAL_TASK_TIMEOUT_SEC, verify=get_httpx_verify()) as client:
                import time as _t
                started = _t.perf_counter()
                if suite.task_type == "a2a_message":
                    resp = await client.post(url, json=task_input.get("message", {"parts": [{"text": "eval ping"}]}))
                else:  # http_probe
                    resp = await client.get(url)
                latency = int((_t.perf_counter() - started) * 1000)
                body = resp.text[:2000]
                score, passed = score_task(
                    task.scorer, task.expected,
                    status_code=resp.status_code, body=body, latency_ms=latency,
                )
                return (score, passed, latency, body[:200], None)
        except Exception as e:  # noqa: BLE001
            return (0.0, False, None, None, str(e)[:200])

    async def _fold_reputation(self, db, did: str, suite_score: float) -> None:
        """Upsert a local_trust edge (eval-oracle → agent) that the hourly EigenTrust
        epoch absorbs. No new ranking system — reuses the existing trust graph."""
        try:
            sat = 1 if suite_score >= 0.5 else 0
            unsat = 0 if suite_score >= 0.5 else 1
            await db.execute(sa_text("""
                INSERT INTO local_trust_scores
                    (id, from_did, to_did, satisfactory, unsatisfactory, local_trust, normalized, tx_volume, last_updated)
                VALUES (:id, :f, :t, :sat, :unsat, :lt, 0, 0, now())
                ON CONFLICT (from_did, to_did) DO UPDATE SET
                    satisfactory   = local_trust_scores.satisfactory + :sat,
                    unsatisfactory = local_trust_scores.unsatisfactory + :unsat,
                    local_trust    = :lt,
                    last_updated   = now()
            """), {
                "id": uuid.uuid4().hex, "f": EVAL_ORACLE_DID, "t": did,
                "sat": sat, "unsat": unsat, "lt": float(suite_score),
            })
        except Exception as e:  # noqa: BLE001
            logger.debug("[EvalRunner] reputation fold failed for %s: %s", did, e)

    async def _pay_agent(self, db, did: str, suite, pay_slot: str) -> None:
        """Pay the agent per completed suite via the reward waterfall (Δ=0 preserved).

        GÖDEL FORGE: when FORGE_ROYALTY_ENABLED, the same treasury payout is CARVED into legs —
        the earner plus its nearest fork-ancestor org treasuries — that sum EXACTLY to
        pay_per_task, so the total leaving the treasury is unchanged (Δ=0 by construction)."""
        try:
            from ..routers.teg_integration import (
                _fund_agent_from_treasury_internal, TreasuryFundAgentRequest,
            )
            from ..services import forge_royalty
            legs = await forge_royalty.compute_legs(db, suite.pay_per_task, did)
            single = len(legs) <= 1
            for i, (rdid, amt) in enumerate(legs):
                if amt <= 0:
                    continue
                ref = f"eval:{suite.key}" if single else f"roy-eval:{suite.key}:{did[-8:]}:{i}"
                req = TreasuryFundAgentRequest(
                    target_agent_did=rdid, amount=str(amt),
                    reason="reward", reference_id=ref,
                )
                # §MONEY-R36 (class): `ref` is deterministic, so a re-run of the
                # same suite for the same candidate would pay the royalty legs
                # again. Key it to the same tuple the memo names.
                # §DOCSFIX D6-673: ...and the key names exactly one payment: this run, this agent, this leg. Keyed on
                # the suite alone, a second agent inside the TEG's 24 h key window was refused (409, other parameters)
                # and the next run was answered from the first payment, so a paid suite paid at most once a day.
                # §DOCSFIX review: the run is its pay slot (the scheduled slot, or the day of a run started on demand),
                # not a random run id: with one, an agent paid itself again from the treasury with every run it
                # started (POST /forge/evals/run), and two workers running one slot paid it twice. The agent as a
                # digest keeps the key inside the TEG's 255 characters.
                who = hashlib.sha256(did.encode()).hexdigest()[:24]
                await _fund_agent_from_treasury_internal(
                    db, req, actor_label="eval_runner",
                    idempotency_key=f"eval-pay-{suite.id}-{pay_slot}-{who}-{i}",
                )
            if not single:
                logger.info("[FORGE] royalty carve on eval pay: %d legs, earner=%s", len(legs), did)
                # §NOTIFV2 forge.royalty_received — after the funding loop above.
                await forge_royalty.notify_royalty_legs(
                    legs, source=f"eval suite '{suite.key}'")
        except Exception as e:  # noqa: BLE001
            logger.warning("[EvalRunner] eval payment failed for %s: %s", did, e)


async def start_eval_runner() -> None:
    global _runner
    if _runner is None:
        _runner = EvalRunner()
    await _runner.start()


async def stop_eval_runner() -> None:
    global _runner
    if _runner is not None:
        await _runner.stop()


async def run_suite_once(suite_id: int) -> Optional[str]:
    """Admin 'run now' — execute a single suite immediately, return run_id."""
    runner = EvalRunner()
    async with get_db_context() as db:
        suite = (await db.execute(
            select(models.EvalSuite).where(models.EvalSuite.id == suite_id)
        )).scalar_one_or_none()
        if suite is None:
            return None
        return await runner.run_suite(db, suite)


async def run_suite_once_for(suite_id: int, only_did: str) -> Optional[str]:
    """GÖDEL FORGE — run one suite immediately against a SINGLE agent (a self-triggering
    harness); returns run_id, or None if the suite is missing. Scopes without persisting."""
    runner = EvalRunner()
    async with get_db_context() as db:
        suite = (await db.execute(
            select(models.EvalSuite).where(models.EvalSuite.id == suite_id)
        )).scalar_one_or_none()
        if suite is None:
            return None
        return await runner.run_suite(db, suite, only_dids=[only_did])
