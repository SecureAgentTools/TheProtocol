"""Tests for theprotocol.authz.AuthzClient (IRONKEY L3/L4) — hermetic via MockTransport."""
import json

import httpx
import pytest

from theprotocol.authz import AuthzClient, AuthzError


def _client_with(handler):
    return AuthzClient("https://reg.example", transport=httpx.MockTransport(handler))


def test_capability_headers_helper():
    assert AuthzClient.capability_headers("att_abc123") == {"X-Capability-Token": "att_abc123"}


# ── L3 — delegation grants ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_delegations_path_and_dev_bearer():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"agent_did": "did:theprotocol:a", "grants": [
            {"id": 1, "principal": "dev:2", "permissions": ["guild.bid_for_org"],
             "may_redelegate": False, "max_depth": 1, "expires_at": None, "revoked": False},
        ]})

    c = _client_with(handler)
    out = await c.list_delegations("dev-jwt", "did:theprotocol:a")
    await c.close()

    assert captured["url"] == "https://reg.example/api/v1/agents/did:theprotocol:a/delegations"
    assert captured["auth"] == "Bearer dev-jwt"
    assert out["grants"][0]["principal"] == "dev:2"


# ── L4 — capability tokens ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_issue_capability_merges_caveats_and_permissions():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "id": 41, "token": "att_" + "x" * 60, "issuer_did": "did:theprotocol:parent",
            "depth": 0, "caveats": {"permissions": ["exchange.trade"]},
            "expires_at": "2026-07-20T00:00:00+00:00", "note": "token shown once — store it now",
        })

    c = _client_with(handler)
    out = await c.issue_capability(
        "jwt-parent", ["exchange.trade", "teg.transfer"],
        holder_agent_did="did:theprotocol:clerk", budget_total=400.0, currency="BVT",
        ttl_seconds=86400, caveats={"max_per_tx": 25.0, "no_redelegate": True},
    )
    await c.close()

    assert captured["url"] == "https://reg.example/api/v1/agents/capabilities"
    assert captured["auth"] == "Bearer jwt-parent"
    assert captured["body"] == {
        "caveats": {"max_per_tx": 25.0, "no_redelegate": True,
                    "permissions": ["exchange.trade", "teg.transfer"]},
        "holder_agent_did": "did:theprotocol:clerk",
        "budget_total": 400.0, "currency": "BVT", "ttl_seconds": 86400,
    }
    assert out["id"] == 41 and out["token"].startswith("att_")


@pytest.mark.asyncio
async def test_issue_capability_over_delegation_raises_authz_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "Cannot delegate permissions you lack: ['teg.system_transfer']"})

    c = _client_with(handler)
    with pytest.raises(AuthzError) as ei:
        await c.issue_capability("jwt-parent", ["teg.system_transfer"])
    await c.close()

    assert ei.value.status_code == 422
    assert "Cannot delegate" in str(ei.value.detail)


@pytest.mark.asyncio
async def test_attenuate_path_and_omits_unset_optionals():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": 42, "token": "att_child", "depth": 1,
                                         "caveats": {"permissions": ["exchange.trade"]}})

    c = _client_with(handler)
    out = await c.attenuate("jwt-clerk", 41, ["exchange.trade"], budget_total=50.0)
    await c.close()

    assert captured["url"] == "https://reg.example/api/v1/agents/capabilities/41/attenuate"
    assert captured["body"] == {"caveats": {"permissions": ["exchange.trade"]}, "budget_total": 50.0}
    assert out["depth"] == 1


@pytest.mark.asyncio
async def test_my_capabilities_and_revoke_subtree():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url), request.headers.get("authorization")))
        if request.method == "GET":
            return httpx.Response(200, json={"agent_did": "did:theprotocol:clerk", "mode": "off",
                                             "tokens": [{"id": 41, "role": "holder", "status": "issued"}]})
        return httpx.Response(200, json={"ok": True, "root_token_id": 41, "revoked_count": 3})

    c = _client_with(handler)
    mine = await c.my_capabilities("jwt-clerk")
    gone = await c.revoke_capability("jwt-parent", 41)
    await c.close()

    assert calls[0] == ("GET", "https://reg.example/api/v1/agents/capabilities/mine", "Bearer jwt-clerk")
    assert calls[1] == ("DELETE", "https://reg.example/api/v1/agents/capabilities/41", "Bearer jwt-parent")
    assert mine["tokens"][0]["id"] == 41
    assert gone["revoked_count"] == 3  # whole subtree cascaded


@pytest.mark.asyncio
async def test_revoke_by_stranger_raises_authz_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "Only the issuer or holder may revoke"})

    c = _client_with(handler)
    with pytest.raises(AuthzError) as ei:
        await c.revoke_capability("jwt-stranger", 41)
    await c.close()

    assert ei.value.status_code == 403
    assert "issuer or holder" in str(ei.value.detail)
