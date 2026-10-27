"""treasury_low_watch — "the treasury is running low" reaches a person BEFORE it reaches a caller.

§MONEY-R43 (2026-09-04). His ask: *"notification for low treasury (only for admins and configurable
amount) … so there will always be someone informed that treasury is running low. also for org and
their admins that have access."*

§MONEY-M3b made a short treasury FAIL LOUDLY at the moment of use — R19 turned the cross-TEG seed's
mint-on-demand into `409 mint first`, R23 made lost-callback compensation refuse rather than mint.
Correct, and strictly better than silently creating supply; but it means the first person to learn
the treasury is empty is a caller getting a refusal mid-provisioning. This worker is the other half:
warn before the refusal, not at it.

Measured before writing (2026-09-04): `curl :8000/metrics | grep -i treasury` returned 46 lines and
every one of them was a §VITALS *worker* metric for treasury_market_maker — the BALANCE itself was
scraped nowhere, so no alert rule could be written. Hence the gauge first, then the check, then the
vmalert rule (`TreasuryLow`, monitoring/prometheus_alerts.yml).

The contract
  · PLATFORM — read the TEG treasury through the shared client (`get_teg_client().get_treasury_info()`,
    which since §MONEY-R27 RAISES on an unreachable TEG instead of inventing numbers). §SECFIX D6-254
    (2026-10-16, his word): the BALANCE is not exported (`registry_treasury_balance` is gone: /metrics answers
    whoever reaches the registry); the rule reads `registry_treasury_low_active`, the threshold is published.
  · THRESHOLD — `TREASURY_LOW_NOTIFY_THRESHOLD`, absolute, in the frame's currency. `0` = disabled,
    which is today's fleet (his standing "defaults are deliberately quiet"). The network profile owns
    it: lowsupply sizes it at S0 * 25 / 100 — ABOVE the genesis floor (20 % of S0, R14) so the warning
    arrives before grants start deferring, not after.
  · HYSTERESIS — one state per scope in redis (`treasury_low:state:<scope>`; 38 gunicorn workers make
    in-process state unreadable, §SUPPORTBATCH1). Notify on the crossing DOWN, once; on the crossing
    back UP, once. Never on every cycle: an alarm that repeats gets muted, and a muted alarm is no alarm.
    Without redis the state falls back to this process's memory and says so — a leadership move can
    then repeat one notice, which is the lesser evil against staying silent.
  · ORGS — any organization whose settings carry `treasury_low_notify_threshold` > 0 (a real key in
    ORG_SETTING_CATALOG, so a PUT under it validates and a typo is refused) gets its treasury resolved
    (`services.org_treasury.resolve_org_treasury_did`, the same reader `GET /organizations/{id}/treasury`
    uses), read through the exchange mover (TEG truth, never the registry cache), and its owners and
    admins notified under `org.treasury.low` on the same two transitions. Org balances are NOT
    exported as gauges (one series per org is a cardinality trap); they are notification-only.
  · THREE STATES — a platform read that FAILS raises, so the base loop stamps the cycle ERROR
    (§VITALS) and the state is left untouched: "could not read" is neither above nor below the floor,
    and must never be reported as "recovered". A failed ORG read is a per-item failure: counted in the
    stats, that org skipped, the cycle goes on (a per-item failure is not a cycle failure).
  · Δ — read-only. Nothing here moves money.

Env: TREASURY_LOW_WATCH_ENABLED (default true) · TREASURY_LOW_WATCH_INTERVAL_SECONDS (default 300) ·
TREASURY_LOW_NOTIFY_THRESHOLD (default 0 = disabled; profile-owned).
"""
from __future__ import annotations

import logging
import os
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from ._worker_base import BackgroundWorker
from ..database import AsyncSessionLocal

logger = logging.getLogger(__name__)

TREASURY_LOW_KEY = "treasury.low"
ORG_TREASURY_LOW_KEY = "org.treasury.low"
ORG_SETTING_KEY = "treasury_low_notify_threshold"
_STATE_LOW = "low"
_STATE_OK = "ok"

try:
    from prometheus_client import Counter as _Counter, Gauge as _Gauge

    TREASURY_LOW_THRESHOLD = _Gauge(
        "registry_treasury_low_threshold",
        "TREASURY_LOW_NOTIFY_THRESHOLD as the watcher reads it (0 = disabled)",
        ["scope"], multiprocess_mode="livemostrecent",
    )
    TREASURY_LOW_ACTIVE = _Gauge(
        "registry_treasury_low_active",
        "1 while the treasury sits below its notify threshold, else 0 (§MONEY-R43)",
        ["scope"], multiprocess_mode="livemostrecent",
    )
    TREASURY_LOW_NOTIFICATIONS = _Counter(
        "registry_treasury_low_notifications_total",
        "Treasury-low notices sent, by scope and transition (low | recovered)",
        ["scope", "transition"],
    )
    TREASURY_LOW_READ_FAILURES = _Counter(
        "registry_treasury_low_read_failures_total",
        "Treasury reads that failed inside the watcher, by scope",
        ["scope"],
    )
except Exception:  # noqa: BLE001 — metrics never break the worker
    TREASURY_LOW_THRESHOLD = TREASURY_LOW_ACTIVE = None
    TREASURY_LOW_NOTIFICATIONS = TREASURY_LOW_READ_FAILURES = None


def _threshold() -> Decimal:
    """`TREASURY_LOW_NOTIFY_THRESHOLD` — the network profile's knob (network_profile_knobs.py).
    Unparseable or negative reads as 0 = disabled, and says so."""
    raw = (os.getenv("TREASURY_LOW_NOTIFY_THRESHOLD", "0") or "0").strip()
    try:
        v = Decimal(raw)
    except (InvalidOperation, ValueError):
        logger.warning("[TreasuryLow] TREASURY_LOW_NOTIFY_THRESHOLD=%r is not a number — treated as disabled", raw)
        return Decimal("0")
    return v if v > 0 else Decimal("0")


def _interval() -> int:
    try:
        return max(30, int(os.getenv("TREASURY_LOW_WATCH_INTERVAL_SECONDS", "300")))
    except (ValueError, TypeError):
        return 300


def _transition(prev: Optional[str], is_low: bool) -> Optional[str]:
    """The hysteresis rule, pure so it can be tested. Returns 'low' | 'recovered' | None.
    An UNKNOWN previous state (first observation, or redis lost it) that is low DOES notify —
    the whole point is that somebody hears; an unknown state that is fine notifies nobody."""
    if is_low and prev != _STATE_LOW:
        return "low"
    if not is_low and prev == _STATE_LOW:
        return "recovered"
    return None


def _fmt(d: Decimal) -> str:
    return f"{d:,.6f}".rstrip("0").rstrip(".")


class TreasuryLowWatchWorker(BackgroundWorker):
    worker_id = "treasury_low_watch"
    leader_key = "leader:treasury_low_watch"
    interval_sec = _interval()
    cold_start_delay_sec = 90

    def __init__(self) -> None:
        super().__init__()
        self._mem_state: Dict[str, str] = {}   # fallback only, when redis is unavailable
        self._warned_no_redis = False

    def _should_run(self) -> bool:
        return (os.getenv("TREASURY_LOW_WATCH_ENABLED", "true") or "true").strip().lower() in ("1", "true", "yes", "on")

    # ---- state (hysteresis) -------------------------------------------------
    async def _get_state(self, scope: str) -> Optional[str]:
        try:
            from .leader import get_redis
            r = await get_redis()
        except Exception:  # noqa: BLE001
            r = None
        if r is None:
            if not self._warned_no_redis:
                logger.warning("[TreasuryLow] redis unavailable — hysteresis state is per-process until it returns")
                self._warned_no_redis = True
            return self._mem_state.get(scope)
        try:
            v = await r.get(f"treasury_low:state:{scope}")
            return v.decode() if isinstance(v, (bytes, bytearray)) else (str(v) if v is not None else None)
        except Exception:  # noqa: BLE001
            return self._mem_state.get(scope)

    async def _set_state(self, scope: str, state: str) -> None:
        self._mem_state[scope] = state
        try:
            from .leader import get_redis
            r = await get_redis()
            if r is not None:
                await r.set(f"treasury_low:state:{scope}", state)
        except Exception:  # noqa: BLE001
            pass

    # ---- reads (overridable in tests) --------------------------------------
    async def _read_platform_balance(self) -> Decimal:
        """TEG truth through the shared client. RAISES on failure (R27) — never a number it made up."""
        from ..teg_client import get_teg_client
        info = await get_teg_client().get_treasury_info()
        return Decimal(str(info.get("treasury_balance", "0")))

    async def _org_candidates(self) -> List[Dict[str, Any]]:
        """Orgs that SET a threshold. Only those — the org half is opt-in by design."""
        out: List[Dict[str, Any]] = []
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(text(
                "SELECT id, name, settings ->> :k AS thr FROM organizations "
                "WHERE settings ->> :k IS NOT NULL"
            ), {"k": ORG_SETTING_KEY})).all()
            for org_id, name, thr in rows:
                try:
                    t = Decimal(str(thr))
                except (InvalidOperation, ValueError):
                    continue
                if t <= 0:
                    continue
                from ..services.org_treasury import resolve_org_treasury_did
                did = await resolve_org_treasury_did(db, org_id)
                if not did:
                    continue
                admins = (await db.execute(text(
                    "SELECT developer_id FROM organization_members "
                    "WHERE organization_id = :o AND role IN ('owner', 'admin')"
                ), {"o": org_id})).all()
                out.append({"id": org_id, "name": name, "threshold": t, "did": did,
                            "developer_ids": [r[0] for r in admins]})
        return out

    async def _read_org_balance(self, did: str) -> Decimal:
        from ..services.exchange_service import mover
        return Decimal(str(await mover.agent_balance(did)))

    # ---- notify --------------------------------------------------------------
    async def _notify_platform(self, transition: str, balance: Decimal, threshold: Decimal, currency: str) -> None:
        from .push_notify import notify_audience
        if transition == "low":
            title = f"Treasury running low: {_fmt(balance)} {currency}"
            message = (f"The frame treasury holds {_fmt(balance)} {currency}, below the notify floor of "
                       f"{_fmt(threshold)} {currency}. Below the genesis floor grants defer and operator seeds "
                       f"refuse (issue units first). Issue through the registry rail when you decide to.")
        else:
            title = f"Treasury back above its floor: {_fmt(balance)} {currency}"
            message = f"The frame treasury is back above {_fmt(threshold)} {currency}."
        await notify_audience(TREASURY_LOW_KEY, title=title, message=message,
                              tags="warning" if transition == "low" else "white_check_mark",
                              priority="high" if transition == "low" else "default")

    async def _notify_org(self, org: Dict[str, Any], transition: str, balance: Decimal, currency: str) -> None:
        from .push_notify import notify
        if not org["developer_ids"]:
            return
        if transition == "low":
            title = f"{org['name']}: org treasury running low ({_fmt(balance)} {currency})"
            message = (f"The treasury of {org['name']} holds {_fmt(balance)} {currency}, below the floor of "
                       f"{_fmt(org['threshold'])} {currency} its admins set. Remit or fund before its agents run dry.")
        else:
            title = f"{org['name']}: org treasury back above its floor ({_fmt(balance)} {currency})"
            message = f"The treasury of {org['name']} is back above {_fmt(org['threshold'])} {currency}."
        await notify(ORG_TREASURY_LOW_KEY, org["developer_ids"], title=title, message=message,
                     tags="warning" if transition == "low" else "white_check_mark",
                     priority="high" if transition == "low" else "default")

    # ---- the cycle -----------------------------------------------------------
    async def _cycle_once(self) -> None:
        from ..core.frame_currency import frame_currency
        currency = frame_currency()
        threshold = _threshold()
        stats: Dict[str, Any] = {"currency": currency, "threshold": str(threshold), "notified": 0,
                                 "orgs_checked": 0, "org_read_failed": 0}

        # PLATFORM. A failed read RAISES: the base loop stamps ERROR and no state moves.
        try:
            balance = await self._read_platform_balance()
        except Exception:
            if TREASURY_LOW_READ_FAILURES is not None:
                try:
                    TREASURY_LOW_READ_FAILURES.labels(scope="platform").inc()
                except Exception:  # noqa: BLE001
                    pass
            raise
        stats["platform_balance"] = str(balance)
        if TREASURY_LOW_THRESHOLD is not None:
            try:
                TREASURY_LOW_THRESHOLD.labels(scope="platform").set(float(threshold))
            except Exception:  # noqa: BLE001
                pass
        if threshold > 0:
            is_low = balance < threshold
            prev = await self._get_state("platform")
            tr = _transition(prev, is_low)
            if TREASURY_LOW_ACTIVE is not None:
                try:
                    TREASURY_LOW_ACTIVE.labels(scope="platform").set(1.0 if is_low else 0.0)
                except Exception:  # noqa: BLE001
                    pass
            if tr:
                await self._notify_platform(tr, balance, threshold, currency)
                stats["notified"] += 1
                if TREASURY_LOW_NOTIFICATIONS is not None:
                    try:
                        TREASURY_LOW_NOTIFICATIONS.labels(scope="platform", transition=tr).inc()
                    except Exception:  # noqa: BLE001
                        pass
                logger.warning("[TreasuryLow] platform %s: balance=%s threshold=%s", tr, balance, threshold)
            await self._set_state("platform", _STATE_LOW if is_low else _STATE_OK)
            stats["state"] = _STATE_LOW if is_low else _STATE_OK
        else:
            stats["state"] = "disabled"
            if TREASURY_LOW_ACTIVE is not None:
                try:
                    TREASURY_LOW_ACTIVE.labels(scope="platform").set(0.0)
                except Exception:  # noqa: BLE001
                    pass

        # ORGS — opt-in, per-item failures counted, never the cycle's.
        try:
            orgs = await self._org_candidates()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[TreasuryLow] org candidate query failed: %s", exc)
            orgs = []
        for org in orgs:
            stats["orgs_checked"] += 1
            scope = f"org:{org['id']}"
            try:
                bal = await self._read_org_balance(org["did"])
            except Exception as exc:  # noqa: BLE001
                stats["org_read_failed"] += 1
                if TREASURY_LOW_READ_FAILURES is not None:
                    try:
                        TREASURY_LOW_READ_FAILURES.labels(scope="org").inc()
                    except Exception:  # noqa: BLE001
                        pass
                logger.warning("[TreasuryLow] org %s treasury read failed: %s", org["id"], exc)
                continue
            is_low = bal < org["threshold"]
            tr = _transition(await self._get_state(scope), is_low)
            if tr:
                await self._notify_org(org, tr, bal, currency)
                stats["notified"] += 1
                if TREASURY_LOW_NOTIFICATIONS is not None:
                    try:
                        TREASURY_LOW_NOTIFICATIONS.labels(scope="org", transition=tr).inc()
                    except Exception:  # noqa: BLE001
                        pass
            await self._set_state(scope, _STATE_LOW if is_low else _STATE_OK)

        self._stats = stats


treasury_low_watch_worker = TreasuryLowWatchWorker()
