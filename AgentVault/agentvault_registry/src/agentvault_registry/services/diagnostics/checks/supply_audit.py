"""Supply invariant audit — tokens_issued must equal tokens_circulating.

Calls the EventStore /projections/supply-audit endpoint for the target's frame.
Only meaningful for mainframe targets (Frame A and Frame B each have one ES).
"""

import asyncio
import time
from typing import Any

import httpx

from ..schemas import CheckResult, RemediationHint

CHECK_ID = "supply-audit"
TITLE = "Supply invariant audit"
DESCRIPTION = "Verifies tokens_issued equals tokens_circulating in EventStore."
CATEGORY = "supply"
COST_MS = 200


def applies(target: dict) -> bool:
    return target.get("role") in ("mainframe", "frame")


def _own_store() -> tuple:
    """(base url, headers, verify) of THIS registry's event store, the way the registry reads its own ledger (the
    compliance page's events route): its mTLS sidecar with the SVID context, and the internal key when one is set."""
    from agentvault_registry.config import settings
    from agentvault_registry.es_ssl_helper import get_httpx_verify
    key = getattr(settings, "EVENT_STORE_API_KEY", None) or getattr(settings, "EVENT_STORE_INTERNAL_KEY", None)
    return (getattr(settings, "EVENT_STORE_URL", None) or "").rstrip("/"), ({"X-Internal-Key": key} if key else {}), \
        get_httpx_verify()


async def _read_again(url, headers: dict, verify: Any, target: dict):
    """The audit's body on a second read, or None when it could not be read."""
    try:
        async with httpx.AsyncClient(timeout=5.0 if target.get("self") else 3.0, verify=verify, headers=headers) as client:
            r = await client.get(str(url))
        return r.json() if r.status_code == 200 else None
    except Exception:  # noqa: BLE001 — a second read that fails leaves the first read's finding standing
        return None


async def run(target: dict, probe) -> CheckResult:
    started = time.monotonic()
    headers: dict = {}
    verify: Any = False
    if target.get("self"):
        # §MCPTEST30 (V0562): this registry's own store, the ledger its supply invariant is about
        own, headers, verify = _own_store()
        candidates = [own] if own else []
    else:
        candidates = [target.get("event_store_url"), target.get("event_store_public_url")]
    candidates = [u for u in candidates if u]
    if not candidates:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="unknown",
            latency_ms=int((time.monotonic() - started) * 1000),
            summary="no event_store_url configured",
        )
    last_error = None
    resp = None
    for base in candidates:
        url = f"{base}/api/v1/projections/supply-audit"
        try:
            async with httpx.AsyncClient(timeout=5.0 if target.get("self") else 3.0, verify=verify,
                                         headers=headers) as client:
                resp = await client.get(url)
            if resp.status_code < 500:
                break
        except Exception as e:
            last_error = e
            resp = None
            continue
    latency_ms = int((time.monotonic() - started) * 1000)
    if resp is None:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="fail",
            latency_ms=latency_ms,
            summary=f"event store unreachable: {str(last_error)[:120]}",
            evidence=str(last_error)[:512] if last_error else "",
        )
    try:
        if resp.status_code != 200:
            return CheckResult(
                check_id=CHECK_ID,
                target=target["operator_id"],
                status="fail",
                latency_ms=latency_ms,
                summary=f"event store returned HTTP {resp.status_code}",
                evidence=resp.text[:1024],
            )
        body: Any = resp.json()
        delta = float(body.get("delta", 0))
        status_text = str(body.get("status", "")).upper()
        details = {
            "tokens_issued": body.get("tokens_issued"),
            "total_circulating": body.get("total_circulating"),
            "delta": delta,
            "status": status_text,
        }
        if status_text == "BREACH" or abs(delta) > 0.001:
            # §MCPTEST30 (V0562): the HTTP audit reads its two sums in two queries, so under cross-frame load a non-zero
            # delta can be read skew (CLAUDE.md part 4: the atomic single-statement delta is the truth). Read once more
            # after a pause; a delta that persists is the finding, one that does not is said as skew, never as a breach.
            await asyncio.sleep(2.0)
            second = await _read_again(resp.request.url, headers, verify, target)
            if second is not None and str(second.get("status", "")).upper() != "BREACH" \
                    and abs(float(second.get("delta", 0) or 0)) <= 0.001:
                return CheckResult(
                    check_id=CHECK_ID,
                    target=target["operator_id"],
                    status="ok",
                    latency_ms=int((time.monotonic() - started) * 1000),
                    summary=f"delta=0 on a second read (the first read {delta} was read skew between two queries)",
                    details={**details, "first_delta": delta, "second_delta": float(second.get("delta", 0) or 0)},
                )
            return CheckResult(
                check_id=CHECK_ID,
                target=target["operator_id"],
                status="fail",
                latency_ms=latency_ms,
                summary=f"BREACH delta={delta}",
                details=details,
                evidence=resp.text[:1024],
                remediation=RemediationHint(
                    action_id="manual-investigate",
                    description="Supply invariant breach — manual investigation required (do not auto-remediate).",
                    destructive=False,
                ),
            )
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="ok",
            latency_ms=latency_ms,
            summary=f"delta={delta}",
            details=details,
        )
    except Exception as e:
        return CheckResult(
            check_id=CHECK_ID,
            target=target["operator_id"],
            status="fail",
            latency_ms=int((time.monotonic() - started) * 1000),
            summary=f"event store unreachable: {str(e)[:120]}",
            evidence=str(e)[:512],
        )
