"""This registry's own TEG, through the mTLS sidecar the registry uses for every money call (§MCPTEST30 V0562).

GET <TEG_API_BASE_URL>/health with the registry's SVID context: the TEG's own verdict and its own checks (database,
configuration, ...). No Docker socket: the same hop as a transfer.
"""

import time

import httpx

from ..schemas import CheckResult

CHECK_ID = "frame-teg-health"
TITLE = "TEG health"
DESCRIPTION = "This registry's TEG answers its health route through the mTLS sidecar, and calls itself healthy."
CATEGORY = "teg"
COST_MS = 150


def applies(target: dict) -> bool:
    return bool(target.get("self"))


async def run(target: dict, probe) -> CheckResult:
    import os
    from agentvault_registry.es_ssl_helper import get_httpx_verify
    started = time.monotonic()

    def result(status, summary, **kw):
        return CheckResult(check_id=CHECK_ID, target=target["operator_id"], status=status,
                           latency_ms=int((time.monotonic() - started) * 1000), summary=summary, **kw)

    base = (os.getenv("TEG_API_BASE_URL") or "").rstrip("/")
    if not base:
        return result("unknown", "not measured: TEG_API_BASE_URL is not set on this registry")
    try:
        async with httpx.AsyncClient(timeout=5.0, verify=get_httpx_verify()) as client:
            resp = await client.get(f"{base}/health")
    except Exception as e:  # noqa: BLE001 — the hop itself failed: that is the finding
        return result("fail", f"the TEG did not answer: {type(e).__name__}: {str(e)[:120]}", evidence=str(e)[:512])
    if resp.status_code != 200:
        return result("fail", f"the TEG answered HTTP {resp.status_code}", evidence=resp.text[:512])
    try:
        body = resp.json()
    except ValueError:
        return result("fail", "the TEG's health answer is not JSON", evidence=resp.text[:512])
    verdict = str(body.get("status") or "").lower()
    checks = body.get("checks") if isinstance(body.get("checks"), dict) else {}
    bad = sorted(k for k, v in checks.items() if isinstance(v, dict) and str(v.get("status", "")).lower() not in
                 ("healthy", "ok", "pass", "up"))
    details = {"status": verdict, "checks": {k: (v.get("status") if isinstance(v, dict) else v) for k, v in checks.items()}}
    if verdict == "healthy" and not bad:
        return result("ok", f"healthy ({len(checks)} checks)", details=details)
    if verdict in ("degraded", "warning") or (verdict == "healthy" and bad):
        return result("warn", f"{verdict or 'answered'}; not healthy: {', '.join(bad) or '-'}", details=details)
    return result("fail", f"the TEG says {verdict or 'nothing'}; not healthy: {', '.join(bad) or '-'}", details=details)
