"""§BUYSERVICE — buying a foreign agent's service, priced honestly and called safely.

Measured 2026-08-24 on the live fleet: a frame-c (BVT) buyer CAN already pay a
registry-a (AVT) service agent. Nothing federated was missing — the service agents
resolve `X-Payment-Issuer` against their trusted-registry set and verify the token
at the ISSUING registry themselves (Agents/*/showcase_base.py). The same token that
returned 402 "Token not found" without that header returned a real weather report
with it. So this module does not build a payment rail; it makes the existing one
reachable:

  * `quote()`      — what the card charges, what that costs YOU, at what rate.
                     Converted the SAME direction the agent's own §PAYCHECK gate
                     converts, so a quoted amount clears the agent's floor instead
                     of being refused as underpayment.
  * `call_agent()` — POST the A2A JSON-RPC to the endpoint the agent's own card
                     declares, carrying the token and the issuer. SSRF-guarded:
                     the URL is never caller-supplied.

No money moves here. Authorization and settlement stay on the existing
/a2a-payment rails (rule 14).
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import socket
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# The agent re-prices at call time; a rate that drifts between quote and call must
# not turn a good-faith payment into an "insufficient" refusal. Tunable per frame.
DEFAULT_HEADROOM_PCT = Decimal(os.getenv("A2A_QUOTE_HEADROOM_PCT", "2") or "2")

_CALL_TIMEOUT = float(os.getenv("A2A_CALL_TIMEOUT_SEC", "45") or "45")
_CALL_MAX_BYTES = int(os.getenv("A2A_CALL_MAX_BYTES", "262144") or "262144")  # 256 KiB


# ── FX ────────────────────────────────────────────────────────────────────────

def rate_payer_to_target(pairs: list, payer_ccy: str, target_ccy: str) -> Optional[Decimal]:
    """Rate that converts ONE unit of the payer's currency into the target's.

    Deliberately mirrors the agent-side lookup in showcase_base.py §PAYCHECK
    (`/api/v1/teg/fx/rates`, all-pairs): for a pair {a,b} it takes `b_per_a` when
    a is the payer's currency and `a_per_b` when b is. If the screen and the agent
    disagree about direction, every quote is wrong by the square of the rate — so
    this is one function, tested, rather than an inline expression at each site.
    """
    if not payer_ccy or not target_ccy:
        return None
    if payer_ccy == target_ccy:
        return Decimal("1")
    for p in pairs or []:
        a, b = (p.get("a") or "").upper(), (p.get("b") or "").upper()
        try:
            if a == payer_ccy and b == target_ccy and p.get("b_per_a"):
                return Decimal(str(p["b_per_a"]))
            if b == payer_ccy and a == target_ccy and p.get("a_per_b"):
                return Decimal(str(p["a_per_b"]))
        except (InvalidOperation, TypeError):
            return None
    return None


async def fetch_fx_pairs(self_base: str, client: httpx.AsyncClient) -> Tuple[list, str]:
    """(pairs, as_of) from this registry's own public all-pairs FX rail; ([], "") if down."""
    try:
        r = await client.get(f"{self_base.rstrip('/')}/api/v1/teg/fx/rates", timeout=8.0)
        if r.status_code != 200:
            return [], ""
        d = r.json()
        if not isinstance(d, dict) or not d.get("available"):
            return [], ""
        return (d.get("pairs") or []), str(d.get("as_of") or "")
    except Exception as e:  # noqa: BLE001 — a quote degrades, it never raises
        logger.debug("[BUYSERVICE] fx rates unavailable: %s", e)
        return [], ""


def price_in_payer_currency(
    price: Decimal, price_ccy: str, payer_ccy: str, pairs: list,
    headroom_pct: Optional[Decimal] = None,
) -> Dict[str, Any]:
    """What `price price_ccy` costs a payer holding `payer_ccy`.

    Returns {ok, exact, recommended, rate, headroom_pct, reason}. `rate` is the
    payer→target rate, so exact = price / rate: the agent multiplies BACK by that
    same rate and must land on (or above) its own floor.
    """
    out: Dict[str, Any] = {
        "ok": False, "exact": None, "recommended": None,
        "rate": None, "headroom_pct": None, "reason": "",
    }
    if price_ccy == payer_ccy:
        out.update(ok=True, exact=f"{price:.6f}", recommended=f"{price:.6f}",
                   rate="1", headroom_pct="0")
        return out
    rate = rate_payer_to_target(pairs, payer_ccy, price_ccy)
    if not rate or rate <= 0:
        # Refuse rather than guess — the agent refuses an unpriceable payment too,
        # and a 1:1 fallback would quietly underpay by the whole FX spread.
        out["reason"] = f"No live {payer_ccy}→{price_ccy} rate — the price cannot be converted right now."
        return out
    hp = DEFAULT_HEADROOM_PCT if headroom_pct is None else headroom_pct
    exact = price / rate
    recommended = exact * (Decimal("1") + hp / Decimal("100"))
    out.update(
        ok=True,
        exact=f"{exact:.6f}",
        recommended=f"{recommended:.6f}",
        rate=f"{rate:.6f}",
        headroom_pct=f"{hp:g}",
    )
    return out


# ── SSRF guard ────────────────────────────────────────────────────────────────

class UnsafeEndpoint(ValueError):
    """The agent's declared endpoint is not somewhere this registry will call."""


def assert_callable_endpoint(url: str) -> str:
    """Refuse anything that would turn the buy rail into an SSRF gadget.

    The URL always comes from a REGISTERED agent card, never from the caller — but
    a card is developer-supplied data, so it is still untrusted input. https only,
    no credentials, and every resolved address must be a public unicast one.
    """
    if not url or not isinstance(url, str):
        raise UnsafeEndpoint("Agent card declares no endpoint URL")
    p = urlparse(url.strip())
    if p.scheme != "https":
        raise UnsafeEndpoint(f"Agent endpoint must be https (card declares {p.scheme or 'no scheme'})")
    if p.username or p.password:
        raise UnsafeEndpoint("Agent endpoint must not embed credentials")
    host = p.hostname
    if not host:
        raise UnsafeEndpoint("Agent endpoint has no host")
    try:
        infos = socket.getaddrinfo(host, p.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise UnsafeEndpoint(f"Agent endpoint host does not resolve: {host}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            raise UnsafeEndpoint(
                f"Agent endpoint {host} resolves to a non-public address ({ip}) — refusing to call it"
            )
    return url.strip()


# ── the call ──────────────────────────────────────────────────────────────────

# ── did the agent actually DO the work? ────────────────────────────────────
# The failure terminals, taken from what this codebase already agrees on
# (theprotocol_orchestrator.orchestrator, GlassGerald.mission_runner, and every
# Agents/*/showcase_base.py) rather than invented here. Bare forms included
# because both spellings appear on the wire.
_A2A_FAILED = {
    "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_CANCELLED", "TASK_STATE_REJECTED",
    "FAILED", "CANCELED", "CANCELLED", "REJECTED",
}


def delivery_verdict(body: Any) -> Tuple[bool, str]:
    """Did the agent deliver? Returns (delivered, reason_when_not).

    🔴 WHY THIS EXISTS. Delivery used to be judged by `called["ok"]`, which is a
    TRANSPORT fact: did the HTTP request succeed. An agent that answers 200 with
    `"state": "TASK_STATE_FAILED"` was therefore recorded as "delivered" and the
    payment was settled with a hardcoded `success: True`. Measured 2026-08-26 on
    the live showcase: WeatherAgent replied `City '<a did>' not found.` with
    TASK_STATE_FAILED, and 0.604182 BVT moved for it. Twice.

    CONSERVATIVE BY DESIGN: only a POSITIVELY identified failure counts as one.
    An unknown, absent or unparseable state is treated as delivered, exactly as
    before — so this can refuse to charge, and can never start wrongly charging.
    """
    if not isinstance(body, (dict, list)):
        return True, ""
    # JSON-RPC: a top-level `error` member means the call itself failed.
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        msg = str(body["error"].get("message") or body["error"].get("detail") or "").strip()
        return False, msg or "the agent returned a JSON-RPC error"

    found: Dict[str, str] = {}

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 8 or found:
            return
        if isinstance(node, list):
            for v in node:
                walk(v, depth + 1)
            return
        if not isinstance(node, dict):
            return
        st = node.get("state")
        if isinstance(st, str) and st.strip().upper() in _A2A_FAILED:
            err = node.get("error")
            if isinstance(err, dict):
                err = err.get("message") or err.get("detail")
            found["state"] = st.strip().upper()
            found["reason"] = str(err or "").strip()
            return
        for v in node.values():
            walk(v, depth + 1)

    walk(body)
    if not found:
        return True, ""
    return False, found["reason"] or f"the agent reported {found['state']}"


def build_a2a_message(text: str, request_id: str = "1") -> dict:
    """A2A v1.0 JSON-RPC `message/send` envelope (the shape the showcase agents parse)."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "message/send",
        "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": text}]}},
    }


async def call_agent(
    client: httpx.AsyncClient,
    endpoint_url: str,
    payload: dict,
    token: Optional[str],
    issuer: Optional[str],
) -> Dict[str, Any]:
    """POST the A2A payload, carrying the payment token and its ISSUER.

    `X-Payment-Issuer` is the whole reason a cross-registry purchase works: without
    it the agent falls back to its own registry, which never minted the token and
    correctly answers "Token not found" (measured — it is the 402 every foreign
    buyer has been hitting). Returns {ok, http_status, body, error}.
    """
    safe = assert_callable_endpoint(endpoint_url)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Payment-Token"] = token
    if issuer:
        headers["X-Payment-Issuer"] = issuer.rstrip("/")
    try:
        r = await client.post(safe, json=payload, headers=headers,
                              timeout=_CALL_TIMEOUT, follow_redirects=False)
    except httpx.RequestError as e:
        return {"ok": False, "http_status": 0, "body": None,
                "error": f"Agent endpoint unreachable: {e.__class__.__name__}"}
    raw = r.content[:_CALL_MAX_BYTES]
    try:
        body = r.json() if raw else None
    except Exception:  # noqa: BLE001
        body = {"raw": raw.decode("utf-8", "replace")[:4000]}
    # A JSON-RPC error is a 200-with-error just as often as a 4xx; treat both as failure
    # so the caller is never told a purchase succeeded because the HTTP status was 200.
    rpc_err = (body or {}).get("error") if isinstance(body, dict) else None
    ok = (200 <= r.status_code < 300) and not rpc_err
    err = ""
    if rpc_err:
        err = error_words(rpc_err)
        if not (200 <= r.status_code < 300) and not _is_jsonrpc_error(rpc_err):
            # not the agent's JSON-RPC answer but an HTTP error page at the address (the card's address answered 404):
            # the status says which
            err = f"HTTP {r.status_code}: {err}" if err else f"HTTP {r.status_code}"
    elif not ok:
        words = error_words(body, as_json=False) if isinstance(body, dict) else ""
        err = f"HTTP {r.status_code}: {words}" if words else f"HTTP {r.status_code}"
    return {"ok": ok, "http_status": r.status_code, "body": body, "error": err}


def _is_jsonrpc_error(e: Any) -> bool:
    return isinstance(e, dict) and ("code" in e or "message" in e)


def error_words(e: Any, *, as_json: bool = True) -> str:
    """An error as words: a JSON-RPC error's message, or an HTTP error body's detail or title, never the Python repr
    of a dict (§MCPTEST30, V0641: the card's address answered 404 with {"error": {"detail": "Not Found", "type":
    "not_found"}} and the buy door showed "{'detail': 'Not Found', 'type': 'not_found'}"). A dict that says nothing
    in words is compact JSON, or nothing with as_json=False (an error page's body is not an answer to quote)."""
    if isinstance(e, dict):
        for k in ("message", "detail", "title", "error"):
            v = e.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, dict):
                w = error_words(v, as_json=as_json)
                if w:
                    return w
        if not as_json or not e:
            return ""
        try:
            return json.dumps(e, sort_keys=True, default=str)[:300]
        except (TypeError, ValueError):
            return ""
    return str(e).strip() if e is not None else ""
