"""Redis-backed leader election check.

Each registry runs background tasks behind a Redis leader lock. The lock
key is `leader:{task_name}` with a 30s TTL renewed every 15s. Stale or
missing → background work isn't running on this registry.
"""

import time

from agentvault_registry.background_tasks.leader import get_redis

from ..schemas import CheckResult

CHECK_ID = "leader-election"
TITLE = "Redis leader election"
DESCRIPTION = "Verifies background-task leader keys exist in Redis with healthy TTL."
CATEGORY = "leader"
COST_MS = 80

def applies(target: dict) -> bool:
    # V0562: this registry itself is measured; an operator only says "not measured" (its keys are in its own Redis), so
    # an operator known from its peer row alone (no containers) is not asked at all
    return (bool(target.get("self")) or target.get("role") in ("mainframe", "frame")
            or (target.get("role") == "operator" and bool(target.get("containers"))))


async def run(target: dict, probe) -> CheckResult:
    started = time.monotonic()
    r = await get_redis()
    if r is None:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="unknown",
            latency_ms=int((time.monotonic() - started) * 1000),
            summary="REDIS_URL not configured (single-worker mode)",
        )

    # We can only inspect *this* registry's Redis — operators have their own
    # Redis (different DB index) which we can't reach from here in phase 1.
    # §MCPTEST30 (V0561): this answered "ok" for every target but registry-a (retired), so every operator on every
    # frame wore a green leader-election tick that measured nothing. "unknown" is neutral in the target aggregate
    # (admin_diagnostics._aggregate_status), so the honest word costs the aggregate nothing.
    # §MCPTEST30 (V0562): this registry itself (targets.self_target) is measured: its leader keys ARE in this Redis
    if target["operator_id"] != "registry-a" and not target.get("self"):
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="unknown",
            latency_ms=int((time.monotonic() - started) * 1000),
            summary="not measured: an operator's leader keys live in its own Redis, which this registry cannot read",
        )

    held = []
    stale = []
    try:
        keys = await r.keys("leader:*")
    except Exception as e:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="fail",
            latency_ms=int((time.monotonic() - started) * 1000),
            summary=f"redis KEYS failed: {e}",
        )

    # §CCFIX (2026-07-28) — this check raced its own measurement. It takes a KEYS snapshot and
    # then GETs each key; a leader key that expires in that gap is EXACTLY what leader election
    # is supposed to do (SET NX EX + renew), but it was being counted "stale". With ~72 keys,
    # catching one mid-renewal is routine, so registry-a flapped ok<->warn on "71 held, 1 stale".
    # Correct semantics:
    #   ttl > 0            → held
    #   ttl == -2 / gone   → expired between scan and read = normal churn, NOT a fault
    #   ttl == -1          → key exists with NO expiry = a genuinely leaked lock that will never
    #                        release, which is the only case worth warning about
    churn = []
    for key in keys:
        try:
            value = await r.get(key)
            ttl = await r.ttl(key)
            entry = {"task": key.replace("leader:", ""), "worker_id": value, "ttl_s": ttl}
            if value and ttl is not None and ttl > 0:
                held.append(entry)
            elif ttl == -1:
                stale.append(entry)          # no TTL → leaked lock
            else:
                churn.append(entry)          # expired between KEYS and GET → benign
        except Exception:
            churn.append({"task": key, "worker_id": None, "ttl_s": None})

    latency_ms = int((time.monotonic() - started) * 1000)
    details = {"held": held, "stale": stale, "churn": churn, "total": len(keys)}

    if not held and not stale and not churn:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="fail",
            latency_ms=latency_ms,
            summary="no leader keys found — background tasks may not be running",
            details=details,
        )
    if stale:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="warn",
            latency_ms=latency_ms,
            summary=f"{len(held)} held, {len(stale)} leaked (no TTL), {len(churn)} renewing",
            details=details,
        )
    return CheckResult(
        check_id=CHECK_ID,
        target=target["operator_id"],
        status="ok",
        latency_ms=latency_ms,
        summary=f"{len(held)} leader key(s) held",
        details=details,
    )
