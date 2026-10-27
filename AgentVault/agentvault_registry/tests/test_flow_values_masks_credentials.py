"""§MCPTEST30 (2026-10-01) — GET /admin/api-test/flow-values hands out the API tester's state, never its credentials.

Found by the MCP tester's credential census in round 4 on sbx-alpha: getApiTestFlowValues returned the sandbox fixture
account's refresh token (`values.refresh_token`, a bearer JWT) as written. DYNAMIC_VALUES also carries a recovery key and
invitation and recovery tokens. The tester uses them in process; the read shows the state with every credential masked.
"""
from __future__ import annotations

import asyncio
import base64
import json

from starlette.requests import Request

from agentvault_registry.routers import admin_api_test as R

# §SUITES1018 (2026-10-18): the routes take the request (a console whose tester targets another registry hands the call
# there); a registry that targets itself never reads it.
_REQ = Request({"type": "http", "method": "GET", "path": "/api/v1/admin/api-test/flow-values", "headers": []})


def _seg(d):
    return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")


REFRESH = f"{_seg({'alg': 'HS256', 'typ': 'JWT'})}.{_seg({'sub': '7', 'type': 'refresh', 'exp': 4102444800})}.c2lnbmF0dXJlc2ln"
STATE = {
    "refresh_token": REFRESH, "recovery_key": "RK-7Q2F-9XK3-LM4P-ZZ81", "invitation_token": "inv-tok-1a2b3c4d5e6f7a8b",
    "recovery_token": "rec-tok-9f8e7d6c5b4a", "accept_test_token": "acc-tok-0123456789ab",
    "note_with_a_token_inside": f"Bearer {REFRESH}",
    "agent_did": "did:theprotocol:sandbox-a:abc", "webhook_id": 41, "org_slug": "phase3-org", "passed": 12, "failed": 0,
    "skipped": 1, "tool_count": 13,
}


def test_the_read_masks_every_credential_and_keeps_the_state():
    shown = R._flow_values_for_display(dict(STATE))
    blob = json.dumps(shown)
    for secret in (REFRESH, "RK-7Q2F-9XK3-LM4P-ZZ81", "inv-tok-1a2b3c4d5e6f7a8b", "rec-tok-9f8e7d6c5b4a",
                   "acc-tok-0123456789ab"):
        assert secret not in blob, secret
    for k in ("refresh_token", "recovery_key", "invitation_token", "recovery_token", "accept_test_token"):
        assert str(shown[k]).startswith("<redacted"), k
    for k in ("agent_did", "webhook_id", "org_slug", "passed", "failed", "skipped", "tool_count"):
        assert shown[k] == STATE[k], k
    # the console's heartbeat reads these counters from this route
    assert (shown["passed"], shown["failed"], shown["skipped"], shown["tool_count"]) == (12, 0, 1, 13)


def test_the_route_returns_the_masked_state(monkeypatch):
    monkeypatch.setattr(R, "DYNAMIC_VALUES", {**STATE, "unset": None})
    out = asyncio.run(R.get_flow_values(_REQ, current_developer=None))
    assert "unset" not in out["values"] and REFRESH not in json.dumps(out)
    assert out["values"]["agent_did"] == STATE["agent_did"] and "timestamp" in out


def test_a_masking_failure_withholds_everything(monkeypatch):
    import agentvault_registry.mcp.audit_sanitizer as S

    def boom(_v):
        raise RuntimeError("no sanitizer")
    monkeypatch.setattr(S, "sanitize_result", boom)
    shown = R._flow_values_for_display(dict(STATE))
    assert set(shown) == set(STATE) and all(str(v).startswith("<withheld") for v in shown.values())


class _Values(dict):
    async def clear_redis(self):
        self.cleared = True


class _Tokens:
    async def clear_redis(self):
        return None


def test_the_reset_echoes_the_cleared_state_masked(monkeypatch):
    """Round 7 (2026-10-01): resetApiTestFlowValues echoed the refresh token and the recovery key as it cleared them;
    the read's mask covers this door too."""
    vals = _Values({**STATE, "unset": None})
    monkeypatch.setattr(R, "DYNAMIC_VALUES", vals)
    monkeypatch.setattr(R, "_sandbox_tokens", _Tokens())
    monkeypatch.setattr(R, "reset_category_prereqs", lambda: None)
    out = asyncio.run(R.reset_flow_values(_REQ, current_developer=None))
    blob = json.dumps(out)
    for secret in (REFRESH, "RK-7Q2F-9XK3-LM4P-ZZ81", "inv-tok-1a2b3c4d5e6f7a8b"):
        assert secret not in blob, secret
    assert out["cleared_values"]["agent_did"] == STATE["agent_did"] and "unset" not in out["cleared_values"]
    assert all(v is None for v in vals.values()) and vals.cleared
