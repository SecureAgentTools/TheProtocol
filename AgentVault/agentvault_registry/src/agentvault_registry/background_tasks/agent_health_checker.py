"""
Background worker: Agent health checking.

Pings agent URLs every 5 minutes. Updates agent status
and fires agent.health_changed webhook when status changes.

§pass29 Phase 7 (2026-05-17) — refactored to inherit BackgroundWorker.
Adds 4 Prom metrics + per-cycle snapshot for the Tier-3 modal.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.database import AsyncSessionLocal
from ._worker_base import BackgroundWorker

logger = logging.getLogger(__name__)

def _origin_health(url: str) -> str:
    """scheme://host[:port]/health for any declared URL.

    A card's `url` was historically the agent's BASE; a `supportedInterfaces[].url` is
    one specific endpoint. Deriving the origin makes one rule serve both shapes instead
    of asking a JSONRPC path for a health page it never had.
    """
    from urllib.parse import urlsplit
    p = urlsplit(url)
    if not p.scheme or not p.netloc:
        return f"{url.rstrip('/')}/health"
    return f"{p.scheme}://{p.netloc}/health"


def _own_hosts() -> set:
    """The hostnames THIS registry answers on, lowercased, port stripped.

    §CARDLINK (2026-09-08): needed so the origin fallback below can tell a DEDICATED host
    (one subdomain, one agent) from a SHARED one (this frame, hundreds of agents).
    """
    from urllib.parse import urlsplit
    out = set()
    for _k in ("PUBLIC_UI_URL", "BASE_URL", "PUBLIC_URL", "MAINFRAME_PUBLIC_URL"):
        v = (os.getenv(_k) or "").strip()
        if not v:
            continue
        h = urlsplit(v).hostname if "//" in v else v.split("/")[0]
        if h:
            out.add(str(h).lower())
    return out


def _origin_is_dedicated(url: str) -> bool:
    """True when the URL's host is NOT one this registry itself answers on.

    A dedicated host's `/health` is a fact ABOUT THAT AGENT (the sovereign subdomains:
    one host, one process). A shared host's `/health` is a fact about the FRAME and says
    nothing about any agent on it.
    """
    from urllib.parse import urlsplit
    h = (urlsplit(url).hostname or "").lower()
    return bool(h) and h not in _own_hosts()


# §CARDLINK (2026-09-08) — WHAT THE PROBE IS ALLOWED TO CONCLUDE.
#
# His report was that published card addresses are dead. They were: 30 of 34 agents on EU
# carried `https://eu.theprotocol.cloud/agents/<slug>/…`, every one answered 404, and THIS
# WORKER CALLED ALL OF THEM `healthy`. Not a near miss — the reason is structural.
# `_origin_health()` reduced every one of those addresses to `https://eu.theprotocol.cloud/health`,
# the FRAME's own health page, which is 200 by definition. The probe was answering an easier
# question than the one it is named for, and its answer then endorsed the defect for a day.
# §29e's rule aimed at the instrument: a verdict that cannot distinguish two states must not
# pick one, and "the frame is up" is not "this agent's address exists".
#
# So: ASK THE DECLARED ADDRESS ITSELF. The status word discriminates cleanly —
#   404/410  the address is not there            -> unhealthy  (this is the case that was lost)
#   405/401/402/403/422/2xx/3xx  it IS there and answering, refusing or wrong-method
#                                                -> healthy   (an unpaid A2A call is a 402;
#                                                              a GET on a JSON-RPC route is a 405)
#   5xx      it is there and broken              -> unhealthy
#   no answer at all (DNS/connect/timeout)       -> unreachable
# The origin `/health` survives only as a FALLBACK and only for a DEDICATED host, which is the
# §COCKPITA case it was written for (sovereign subdomains) and never the shared-frame case.
async def _probe_declared(client, url: str):
    """(verdict, detail) read from the declared address, never from something easier."""
    last = None
    for method in ("HEAD", "GET"):
        try:
            resp = await client.request(method, url, follow_redirects=True)
        except Exception as exc:
            last = ("unreachable", f"{method} {type(exc).__name__}")
            continue
        sc = resp.status_code
        if sc in (404, 410):
            # A HEAD and a GET can genuinely disagree; ask the other one before concluding.
            last = ("unhealthy", f"{method} {sc}")
            continue
        if sc >= 500:
            return "unhealthy", f"{method} {sc}"
        return "healthy", f"{method} {sc}"
    return last or ("unreachable", "no answer")


CHECK_INTERVAL = 300  # 5 minutes
PING_TIMEOUT = 10  # 10 second timeout per agent


# §pass29 Phase 7 — Prometheus metrics (lazy, best-effort).
try:
    from prometheus_client import Counter as _AHCounter, Gauge as _AHGauge

    AGENT_HEALTH_CYCLE_TOTAL = _AHCounter(
        "agent_health_cycle_total",
        "Agent-health-check cycles run (leader only)",
        labelnames=["registry_id"],
    )
    AGENT_HEALTH_PROBES_TOTAL = _AHCounter(
        "agent_health_probes_total",
        "Probes attempted by outcome",
        labelnames=["registry_id", "outcome"],  # healthy | unhealthy | unreachable | first_observation
    )
    AGENT_HEALTH_STATE_CHANGES_TOTAL = _AHCounter(
        "agent_health_state_changes_total",
        "Probes that resulted in a state transition (webhook fired)",
        labelnames=["registry_id", "from_state", "to_state"],
    )
    AGENT_HEALTH_LAST_CYCLE_DURATION_MS = _AHGauge(
        "agent_health_last_cycle_duration_ms",
        "Wall-clock duration of the most recent cycle, ms",
        labelnames=["registry_id"],
        multiprocess_mode="max",
    )
except Exception:  # pragma: no cover
    AGENT_HEALTH_CYCLE_TOTAL = None
    AGENT_HEALTH_PROBES_TOTAL = None
    AGENT_HEALTH_STATE_CHANGES_TOTAL = None
    AGENT_HEALTH_LAST_CYCLE_DURATION_MS = None


_REGISTRY_ID_LABEL = os.getenv("REGISTRY_NAME", "registry-a")


# Most recent cycle stats — populated by _check_all_agents, read by snapshot().
_LAST_CYCLE_STATS: Dict[str, Any] = {
    "last_cycle_iso": None,
    "last_duration_ms": 0,
    "checked": 0,
    "healthy": 0,
    "unhealthy": 0,
    "unreachable": 0,
    "first_observations": 0,
    "state_changes": 0,
    "errors": 0,
    "cycle_error": None,
}

# Per-DID recent transition log (bounded ring buffer; modal feed).
# Each entry: {agent_did, from_state, to_state, observed_iso, url}
_RECENT_TRANSITIONS: list = []
_RECENT_TRANSITIONS_MAX = 200


def _push_transition(agent_did: str, from_state: str, to_state: str, url: str) -> None:
    _RECENT_TRANSITIONS.append({
        "agent_did": agent_did,
        "from_state": from_state,
        "to_state": to_state,
        "url": url,
        "observed_iso": datetime.now(timezone.utc).isoformat(),
    })
    # Keep last N — pop from front when over capacity.
    while len(_RECENT_TRANSITIONS) > _RECENT_TRANSITIONS_MAX:
        _RECENT_TRANSITIONS.pop(0)


async def _check_all_agents() -> tuple:
    """Ping all agents that have a URL in their agent card.

    §pass15 (2026-05-15) — Tier C-1 fix. Previously the checker compared the
    probe result (`healthy`/`unhealthy`/`unreachable`) against `agents.status`,
    which holds a mix of governance state (`active`/`suspended`/...) and
    historical health state. Active agents always got `status='active'` →
    probe always returned `'healthy'` → inequality always tripped → every
    cycle fanned out 100 false-positive health_changed webhooks.

    Now the probe compares against the new `agents.last_health` column.
    Governance state stays untouched; health flap detection is correct.
    First observation (last_health IS NULL) writes the row but does NOT
    fire a webhook — there's no prior state to compare to.
    """
    checked = 0
    changed = 0
    healthy = 0
    unhealthy = 0
    unreachable = 0
    first_obs = 0
    errs = 0

    try:
        async with AsyncSessionLocal() as db:
            # Pull (id, did, last_health, url). last_health is NULL on first
            # observation — see migration 0055_agent_health_column.
            #
            # §pass16 (2026-05-16) — Filter non-routable URLs at the SQL layer.
            # Sandbox-a had 7,194 test agents with url='http://localhost:8000/a2a'
            # — probing them generated ~553 /a2a/health 404 warnings per hour.
            # Probes against `localhost`, `127.*`, or `0.0.0.0` are meaningless
            # from the registry's perspective; skip them.
            # §COCKPITA R2 (§RUNTIME, 2026-08-31) — TWO defects, both measured on
            # registry-a before this was changed:
            #
            # (1) THIS QUERY COULD NOT SEE THE ONLY AGENTS THAT MATTER. It selected on
            #     `card_data->>'url'`, but a canonicalized A2A card has NO top-level
            #     `url` — its address lives in `supportedInterfaces[].url`. Measured:
            #     4,098 candidates visible, and ZERO of the eleven sovereign agents that
            #     actually run on this host. Their `last_health` words were therefore
            #     fossils that could never be rewritten — Greedy Gregory read
            #     `unreachable` while answering 200 at its public subdomain. COALESCE now
            #     falls back to the first declared interface URL.
            #
            # (2) `LIMIT 100` WITH NO `ORDER BY` IS A LOTTERY, NOT A SWEEP. Over ~4,098
            #     candidates the same rows can be probed forever while others are never
            #     probed at all. `ORDER BY last_health_at NULLS FIRST` (mig 0168) makes
            #     the same limit a fair round-robin: never-checked first, then
            #     least-recently-checked.
            #
            # The localhost/127/0.0.0.0 exclusions (§pass16) apply to the RESOLVED url,
            # so a card that hides a loopback address in supportedInterfaces is still
            # skipped — the filter must follow the value actually probed, not the field
            # it used to come from.
            result = await db.execute(text("""
                -- §COCKPITSHOW (2026-08-31) — PICK THE FIRST PROBEABLE CANDIDATE, NOT THE
                -- FIRST CANDIDATE AND THEN GIVE UP.
                --
                -- §COCKPITA made this a COALESCE over (top-level url, first interface url)
                -- and then excluded loopback in the WHERE. That order throws away a
                -- perfectly probeable agent whenever the two disagree: Ironhand Alpha
                -- publishes `https://localhost:8051/` at the top level and
                -- `http://ironhand-alpha:8051/a2a` as its interface, so COALESCE took the
                -- loopback one, the WHERE dropped the row, and a RUNNING agent that
                -- answers 200 from inside this container was never probed at all —
                -- rendering as "never probed" beside eleven healthy siblings.
                --
                -- Measured before the change: all four Ironhands answer 200 on the docker
                -- network from the registry container; three of them had NULL last_health.
                --
                -- ⚠ This can only WIDEN the candidate set — an agent whose every address
                -- is loopback still resolves to NULL and is still skipped. A change to a
                -- health rail that could narrow it would be the §COCKPITA bug again.
                --
                -- The candidates are ranked in card order and the FIRST probeable one
                -- wins, expressed as a LATERAL rather than a COALESCE so the loopback
                -- test applies per candidate instead of to whatever COALESCE picked.
                -- ⚠ The loopback patterns are broadened from the original `http://127.%`
                -- to any scheme: `https://127.0.0.1` resolves to this container too, so
                -- treating it as probeable only ever produced a verdict about ourselves.
                WITH cand AS (
                    SELECT a.id, a.did, a.last_health, a.last_health_at, u.url
                    FROM agents a
                    JOIN agent_cards ac ON ac.agent_did = a.did
                    CROSS JOIN LATERAL (
                        SELECT x.url
                        FROM (VALUES
                            (1, NULLIF(ac.card_data->>'url', '')),
                            (2, NULLIF(ac.card_data->'supportedInterfaces'->0->>'url', '')),
                            (3, NULLIF(ac.card_data->'supportedInterfaces'->1->>'url', ''))
                        ) AS x(ord, url)
                        WHERE x.url IS NOT NULL
                          AND x.url NOT LIKE '%localhost%'
                          AND x.url NOT LIKE '%127.0.0.1%'
                          AND x.url NOT LIKE '%0.0.0.0%'
                        ORDER BY x.ord
                        LIMIT 1
                    ) u
                    WHERE a.status IN ('active', 'healthy', 'unhealthy', 'unreachable')
                )
                SELECT id, did, last_health, url FROM cand
                ORDER BY last_health_at ASC NULLS FIRST
                LIMIT 100
            """))
            agents = result.fetchall()

            if not agents:
                return 0, 0, 0, 0, 0, 0, 0

            async with httpx.AsyncClient(timeout=PING_TIMEOUT) as client:
                for agent_id, agent_did, last_health, url in agents:
                    checked += 1
                    try:
                        url_str = str(url)
                        # §CARDLINK — the DECLARED ADDRESS is the question. See _probe_declared.
                        new_health, probe_detail = await _probe_declared(client, url_str)
                        if new_health != "healthy" and _origin_is_dedicated(url_str):
                            # §COCKPITA R2's case, correctly scoped: on a host that belongs to
                            # ONE agent, the origin's /health is a fact about that agent, so a
                            # stale path on a live sovereign subdomain still reads healthy.
                            # On this frame's own host it is a fact about the frame and is not
                            # consulted at all — that substitution is the bug this closes.
                            for _alt in (_origin_health(url_str), f"{url_str.rstrip('/')}/health"):
                                try:
                                    resp = await client.get(_alt, follow_redirects=True)
                                except Exception:
                                    continue
                                if 200 <= resp.status_code < 400:
                                    new_health = "healthy"
                                    probe_detail = f"origin {resp.status_code}"
                                    break
                        if new_health != "healthy":
                            logger.debug("[AgentHealth] %s -> %s (%s)", url_str, new_health, probe_detail)

                        if new_health == "healthy":
                            healthy += 1
                        elif new_health == "unhealthy":
                            unhealthy += 1
                        else:
                            unreachable += 1

                        if AGENT_HEALTH_PROBES_TOTAL is not None:
                            try:
                                AGENT_HEALTH_PROBES_TOTAL.labels(
                                    registry_id=_REGISTRY_ID_LABEL,
                                    outcome=new_health if last_health is not None else "first_observation",
                                ).inc()
                            except Exception:
                                pass

                        # Bump last_active_at for healthy probes (cosmetic UX only).
                        # NEVER write to `status` — that's governance state.
                        if new_health == "healthy":
                            await db.execute(text(
                                "UPDATE agents SET last_active_at = :now WHERE id = :id"
                            ), {"now": datetime.now(timezone.utc), "id": agent_id})

                        # Always persist the latest probe so the next cycle's
                        # comparison is well-grounded.
                        await db.execute(text(
                            "UPDATE agents SET last_health = :h, last_health_at = :seen WHERE id = :id"
                        ), {"h": new_health, "seen": datetime.now(timezone.utc), "id": agent_id})

                        # §V0151 (RCA 2026-07-10 lock forensics): commit PER AGENT.
                        # One end-of-sweep commit held every touched agents-row lock
                        # while the remaining ~100 HTTP probes ran (idle-in-transaction,
                        # the §V0119 class) — transfer-path writes (last_active_at /
                        # liquid_balance) queued behind it into lock_timeout, surfacing
                        # as canary slo_window_exceeded. Row locks now live microseconds.
                        await db.commit()

                        # Compare against the previously-stored health probe,
                        # NOT against `status`. On first observation
                        # (last_health IS NULL), record but don't fire.
                        if last_health is None:
                            first_obs += 1
                            continue

                        if new_health == last_health:
                            continue

                        changed += 1
                        _push_transition(agent_did, last_health, new_health, url_str)
                        if AGENT_HEALTH_STATE_CHANGES_TOTAL is not None:
                            try:
                                AGENT_HEALTH_STATE_CHANGES_TOTAL.labels(
                                    registry_id=_REGISTRY_ID_LABEL,
                                    from_state=last_health,
                                    to_state=new_health,
                                ).inc()
                            except Exception:
                                pass
                        logger.info(
                            f"[AgentHealth] {agent_did}: {last_health} → {new_health}"
                        )

                        # §NOTIFV2 agent.health_changed — this is the ONLY transition point in the
                        # checker (verified: `_push_transition` has exactly one caller, right
                        # above). Guarded by the same `new_health == last_health: continue` above,
                        # so a flapping-but-unchanged probe never notifies; the catalog's 600s
                        # coalesce window covers genuine flapping.
                        try:
                            import asyncio as _aio_n
                            from agentvault_registry.background_tasks.push_notify import (
                                notify_agent_owners,
                            )
                            _aio_n.create_task(notify_agent_owners(
                                "agent.health_changed", [agent_did],
                                title=f"Agent {new_health}",
                                message=f"{agent_did[:40]}: {last_health} → {new_health}",
                                tags=("warning" if new_health != "healthy" else "white_check_mark"),
                                priority=("high" if new_health != "healthy" else "default"),
                                # D6-781: the owner's agent list (the console has no #/agents; Pocket opens its own Agents tab)
                                click="/ui/#/my-agents"))
                        except Exception:  # noqa: BLE001
                            logger.debug("[NOTIFY] agent.health_changed emit failed", exc_info=True)

                        # Fire webhook for the actual transition.
                        # §TWOAGENT #34 class (2026-09-23): to the agent's OWN developer (emit_event's agent_did does not
                        # filter subscribers; only a developer id does), never every agent.health_changed subscriber.
                        try:
                            from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_for_agents
                            await dispatch_webhook_for_agents(
                                "agent.health_changed",
                                {
                                    "agent_did": agent_did,
                                    "old_health": last_health,
                                    "new_health": new_health,
                                    "checked_at": datetime.now(timezone.utc).isoformat(),
                                },
                                [agent_did],
                                source_label="agent_health_checker",
                            )
                        except Exception as we:
                            logger.error(f"[AgentHealth] Webhook failed for {agent_did}: {we}")
                        # flush webhook delivery rows for THIS transition immediately
                        await db.commit()

                    except Exception as e:
                        errs += 1
                        logger.debug(f"[AgentHealth] Check failed for {agent_did}: {e}")
                        # §V0151: a failed statement poisons the txn — roll back so the
                        # next agent's writes don't all fail against an aborted txn.
                        try:
                            await db.rollback()
                        except Exception:
                            pass

            await db.commit()
    except Exception as e:
        errs += 1
        logger.error(f"[AgentHealth] DB error: {e}")
        return checked, changed, healthy, unhealthy, unreachable, first_obs, errs

    return checked, changed, healthy, unhealthy, unreachable, first_obs, errs


class AgentHealthChecker(BackgroundWorker):
    """Periodic agent-health probe (§pass29 Phase 7: BackgroundWorker)."""

    worker_id = "agent_health_checker"
    leader_key = "agent_health_checker"
    interval_sec = CHECK_INTERVAL
    # Wait 60s after startup before first check (preserved from prior pattern).
    cold_start_delay_sec = 60

    async def _cycle_once(self) -> None:
        import time as _t
        t0 = _t.time()
        cycle_iso = datetime.now(timezone.utc).isoformat()
        if AGENT_HEALTH_CYCLE_TOTAL is not None:
            try:
                AGENT_HEALTH_CYCLE_TOTAL.labels(registry_id=_REGISTRY_ID_LABEL).inc()
            except Exception:
                pass
        try:
            checked, changed, healthy, unhealthy, unreachable, first_obs, errs = await _check_all_agents()
            _LAST_CYCLE_STATS.update({
                "last_cycle_iso": cycle_iso,
                "checked": checked,
                "healthy": healthy,
                "unhealthy": unhealthy,
                "unreachable": unreachable,
                "first_observations": first_obs,
                "state_changes": changed,
                "errors": errs,
                "cycle_error": None,
            })
            if checked > 0:
                logger.info(f"[AgentHealth] Checked {checked} agents, {changed} status changes")
        except Exception as e:
            _LAST_CYCLE_STATS["cycle_error"] = str(e)[:240]
            logger.error(f"[AgentHealth] Cycle error: {e}", exc_info=True)
        finally:
            dur_ms = int((_t.time() - t0) * 1000)
            _LAST_CYCLE_STATS["last_duration_ms"] = dur_ms
            if AGENT_HEALTH_LAST_CYCLE_DURATION_MS is not None:
                try:
                    AGENT_HEALTH_LAST_CYCLE_DURATION_MS.labels(registry_id=_REGISTRY_ID_LABEL).set(dur_ms)
                except Exception:
                    pass
            self._stats = dict(_LAST_CYCLE_STATS)


_worker: Optional[AgentHealthChecker] = None


def _get_worker() -> AgentHealthChecker:
    global _worker
    if _worker is None:
        _worker = AgentHealthChecker()
    return _worker


async def start_agent_health_checker():
    await _get_worker().start()


async def stop_agent_health_checker():
    global _worker
    if _worker is not None:
        await _worker.stop()


def get_last_cycle_stats() -> Dict[str, Any]:
    """Read-only access to most recent cycle stats."""
    return dict(_LAST_CYCLE_STATS)


def get_recent_transitions(limit: int = 100) -> list:
    """Most-recent agent-health transitions (newest first)."""
    # Return a copy, newest-first, capped at limit.
    return list(reversed(_RECENT_TRANSITIONS))[:limit]
