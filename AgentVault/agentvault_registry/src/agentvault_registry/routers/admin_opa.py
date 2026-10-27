"""OPA policy console — admin API (§29, 2026-07-28).

Serves the `/ui#/admin/opa` view. Read-only against live OPA plus one simulate endpoint.

WHY THE SIMULATOR IS THE POINT.
OPA has sat in shadow since 2026-05-23 because nobody could answer "what breaks if I enforce
this". `/simulate` answers it against REAL traffic: it loads a candidate policy under a scratch
id, replays the retained decision inputs through it, and reports exactly which requests would
flip allow->deny. The scratch policy is always deleted, and nothing here can change enforcement
(`OPA_ENFORCE` is read-only from this router).

Δ-irrelevant throughout: authorization is deny-only and pre-escrow, and these endpoints only
read. Admin-gated like the rest of /admin.
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Security
from pydantic import BaseModel, Field

from agentvault_registry import opa_client, opa_shadow, security
from agentvault_registry.es_ssl_helper import get_httpx_verify

logger = logging.getLogger(__name__)
# Router-level gate (mirrors admin_diagnostics): no endpoint here can be left ungated by
# forgetting a per-endpoint dependency.
router = APIRouter(
    prefix="/api/v1/admin/opa",
    tags=["Admin - OPA"],
    dependencies=[Security(security.require_admin_flag("admin_platform"))],
)

_TIMEOUT = 5.0


async def _opa_get(path: str) -> Any:
    async with httpx.AsyncClient(timeout=_TIMEOUT, verify=get_httpx_verify()) as c:
        r = await c.get(f"{opa_client.opa_url()}{path}")
        r.raise_for_status()
        return r.json()


@router.get("/status", summary="OPA integration status (flags, sidecar, divergence)")
async def opa_status():
    """Live flags + sidecar reachability + the retained-window divergence summary."""
    enabled = opa_client.opa_enabled()
    enforce = os.getenv("OPA_ENFORCE", "false").lower() == "true"
    sidecar: Dict[str, Any] = {"reachable": False}
    if enabled:
        try:
            await _opa_get("/health")
            sidecar = {"reachable": True, "url": opa_client.opa_url()}
        except Exception as exc:
            sidecar = {"reachable": False, "url": opa_client.opa_url(), "error": type(exc).__name__}
    return {
        "opa_enabled": enabled,
        "opa_enforce": enforce,
        # Spelled out because the combination is the thing people get wrong: shadow observes
        # and can never block; enforce returns `python AND opa` (tighten-only, never grant).
        "mode": "enforce" if (enabled and enforce) else ("shadow" if enabled else "off"),
        "sidecar": sidecar,
        "divergence": await opa_shadow.fleet_stats(),
        # §29 LIVE CALL SITE for I1 `flag_pairing_ok`. A policy with no call site is documentation,
        # not enforcement — so this actually ASKS OPA whether THIS registry's IRONKEY flags are a
        # safe pairing, using the real live env. `rbac=enforce` + `delegation=off` silently strips
        # capability-token authority (proven 2026-07-28 on the forge children). Read-only and off
        # the request path; a self-check that would have caught the trap before we hit it.
        "ironkey_pairing": await _ironkey_pairing(),
    }


async def _ironkey_pairing() -> Dict[str, Any]:
    """Evaluate agentvault.invariants.flag_pairing_ok against this registry's OWN live flags."""
    rbac = os.getenv("AGENT_RBAC_MODE", "off").strip().lower()
    deleg = os.getenv("AGENT_DELEGATION_MODE", "off").strip().lower()
    out: Dict[str, Any] = {"rbac_mode": rbac, "delegation_mode": deleg, "ok": None}
    if not opa_client.opa_enabled():
        return out
    try:
        body = await opa_client.query_opa(
            "agentvault/invariants/flag_pairing_ok",
            {"rbac_mode": rbac, "delegation_mode": deleg},
        )
        res = (body or {}).get("result")
        out["ok"] = bool(res) if isinstance(res, bool) else None
    except Exception as exc:
        out["error"] = type(exc).__name__
    if out["ok"] is False:
        out["hint"] = ("rbac=enforce requires delegation=enforce — capability-token authority "
                       "is not consulted while delegation is off")
    return out


@router.get("/decisions", summary="Recent shadow decisions with the input that produced them")
async def opa_decisions(
    limit: int = Query(200, ge=1, le=500),
    only_mismatch: bool = Query(False, description="Only decisions where OPA disagreed with Python"),

):
    """Newest-first. Per-worker sample by construction (the ring is in-process and the registry
    runs many gunicorn workers) — honest for divergence review, not a complete audit log. The
    authoritative totals are `opa_decisions_total` in Prometheus."""
    # Prefer the Redis mirror: it is the ALL-WORKER view. The local deque is one worker of 32,
    # which made retained counts jump (0/3/11/22) and gave the simulator a fraction of the window.
    # `source` is returned so the console can say which view it is showing rather than implying
    # the partial one is complete.
    items = await opa_shadow.redis_decisions(limit)
    source = "redis"
    if items is None:
        items, source = opa_shadow.recent_decisions(limit), "worker-local"
    if only_mismatch:
        items = [i for i in items if i.get("match") is False]
    return {"count": len(items), "source": source, "decisions": items,
            "stats": opa_shadow.stats_for(items)}


@router.get("/policies", summary="Loaded policy catalog with source")
async def opa_policies():
    """Every .rego currently loaded in the sidecar, with its source, so the security spec is
    readable from the console instead of only from disk."""
    if not opa_client.opa_enabled():
        return {"enabled": False, "policies": []}
    try:
        body = await _opa_get("/v1/policies")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OPA unreachable: {type(exc).__name__}")
    out: List[Dict[str, Any]] = []
    for p in body.get("result", []) or []:
        raw = p.get("raw") or ""
        pid = p.get("id") or ""
        pkg = ""
        for line in raw.splitlines():
            if line.startswith("package "):
                pkg = line.split("package ", 1)[1].strip()
                break
        # Rule names = `default X = ...` / `X if {`. Cheap parse, good enough for a catalog.
        rules = sorted({
            ln.split()[1].rstrip("=").strip()
            for ln in raw.splitlines()
            if ln.startswith("default ") and len(ln.split()) > 1
        })
        # The honest label: a policy that merely restates the Python check it mirrors can
        # never disagree, and enforcing it buys nothing but latency.
        #
        # `jurisdiction` is grouped with the invariants rather than with the domain policies.
        # Its per-feature clauses do mirror services/jurisdiction.py, but `profile_coherent`
        # asserts something no Python path owns: that a registry's PUBLISHED declaration
        # matches the features actually switched on there. That rule can disagree with
        # reality, which is the entire test for belonging in this group — and the console
        # tells operators to look here for exactly that kind of policy.
        if "invariants" in pid or "jurisdiction" in pid:
            kind = "invariant"
        elif pkg.startswith("agentvault.") and pkg.split(".")[-1] in ("admin", "developer", "agent"):
            kind = "mirror"
        else:
            kind = "domain"
        out.append({
            "id": pid,
            "package": pkg,
            "rules": rules,
            "lines": len(raw.splitlines()),
            "bytes": len(raw),
            "source": raw,
            "kind": kind,
        })
    return {"enabled": True, "count": len(out), "policies": out}


class SimulateRequest(BaseModel):
    rego: str = Field(..., min_length=10, description="Candidate policy source")
    rule_path: str = Field(..., description="e.g. agentvault/invariants/flag_pairing_ok")
    policy_filter: Optional[str] = Field(None, description="Only replay decisions for this policy path")
    limit: int = Field(200, ge=1, le=500)


_REGO_PACKAGE = re.compile(r"^[ \t]*package[ \t]+([^\s#]+)", re.MULTILINE)


def rego_package(rego: str) -> Optional[str]:
    """The package a rego module declares (its package statement), or None."""
    m = _REGO_PACKAGE.search(rego or "")
    return m.group(1) if m else None


def refuses_system_package(rego: str) -> bool:
    """True for a module in OPA's own `system` package (system, system.authz, system["authz"]). OPA ORs the rules of every
    module in a package together, so a scratch `package system.authz` with `allow { true }` would open the API of the
    server it is uploaded to (§MTLSHOPS: OPA's native mTLS authorizes by path through data.system.authz)."""
    pkg = rego_package(rego) or ""
    return pkg == "system" or pkg.startswith(("system.", "system["))


@router.post("/simulate", summary="Replay real decisions against a candidate policy")
async def opa_simulate(
    req: SimulateRequest,

):
    """Load `rego` under a scratch id, evaluate every retained decision input against
    `rule_path`, and report which would flip. ALWAYS deletes the scratch policy, including on
    error — a simulation must never leave a policy behind that could later be enforced."""
    if not opa_client.opa_enabled():
        raise HTTPException(status_code=400, detail="OPA is disabled on this registry")

    if refuses_system_package(req.rego):
        raise HTTPException(
            status_code=422,
            detail="a simulation module may not declare OPA's system package: it would join the authorization policy "
                   "of the server it is uploaded to",
        )
    scratch = f"__simulate_{uuid.uuid4().hex[:12]}"
    base = opa_client.opa_url()
    inputs = await opa_shadow.redis_decisions(req.limit)
    if inputs is None:
        inputs = opa_shadow.recent_decisions(req.limit)
    if req.policy_filter:
        inputs = [i for i in inputs if i.get("policy") == req.policy_filter]

    results: List[Dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, verify=get_httpx_verify()) as c:
            put = await c.put(f"{base}/v1/policies/{scratch}", content=req.rego.encode(),
                              headers={"Content-Type": "text/plain"})
            if put.status_code >= 400:
                # Compile errors come back structured — surface them verbatim so the editor
                # can point at the offending line instead of saying "invalid".
                raise HTTPException(status_code=422, detail=put.json())

            for item in inputs:
                try:
                    r = await c.post(f"{base}/v1/data/{req.rule_path.strip('/')}",
                                     json={"input": item.get("input") or {}})
                    val = r.json().get("result") if r.status_code == 200 else None
                except Exception:
                    val = None
                prev = item.get("python")
                results.append({
                    "ts": item.get("ts"),
                    "policy": item.get("policy"),
                    "label": item.get("label"),
                    "input": item.get("input"),
                    "current": prev,
                    "candidate": val,
                    # The number people actually care about: would enforcing this DENY
                    # something that is allowed today?
                    "would_break": (prev is True and val is False),
                    "would_tighten": (prev is True and val is False),
                    "undecided": val is None,
                })
    finally:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, verify=get_httpx_verify()) as c:
                await c.delete(f"{base}/v1/policies/{scratch}")
        except Exception as exc:
            # Loud: a leaked scratch policy is a real (if minor) security artifact.
            logger.warning(f"[OPA-SIM] scratch policy {scratch} not deleted: {exc!r}")

    breaks = sum(1 for r in results if r["would_break"])
    undecided = sum(1 for r in results if r["undecided"])
    return {
        "evaluated": len(results),
        "would_break": breaks,
        "undecided": undecided,
        "safe_to_enforce": breaks == 0 and undecided == 0 and len(results) > 0,
        "verdict": (
            "no decisions retained yet — run traffic first" if not results
            else f"{breaks} of {len(results)} retained decisions would flip allow->deny"
        ),
        "results": results,
    }
