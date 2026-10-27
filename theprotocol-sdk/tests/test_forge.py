"""Tests for theprotocol.forge.ForgeClient (GÖDEL FORGE arena) — hermetic via MockTransport."""
import json

import httpx
import pytest

from theprotocol.forge import ForgeClient, ForgeError, ForgeDisabledError


def _client_with(handler):
    return ForgeClient("https://reg.example", transport=httpx.MockTransport(handler))


# ── arena reads ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_status_live_arena():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={
            "enabled": True, "lineages": [{"org_id": "o-1", "name": "verifier-guild", "bundles": 3}],
            "flags": {"royalty": True}, "counts": {"verifiers": 8},
        })

    c = _client_with(handler)
    out = await c.get_status()
    await c.close()

    assert captured["url"] == "https://reg.example/api/v1/forge/status"
    assert captured["auth"] is None  # public read — no bearer
    assert out["enabled"] is True and out["counts"]["verifiers"] == 8


@pytest.mark.asyncio
async def test_get_status_dark_arena_surfaces_enabled_false_not_raise():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "GÖDEL FORGE is not enabled on this registry (FORGE_ENABLED)"})

    c = _client_with(handler)
    out = await c.get_status()
    await c.close()

    assert out["enabled"] is False
    assert "FORGE_ENABLED" in out["detail"]


@pytest.mark.asyncio
async def test_get_lineage_url_and_payload():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={
            "org_id": "org-42", "nodes": [{"type": "agent", "did": "did:theprotocol:a"}],
            "edges": [], "agent_count": 1, "bundle_count": 0,
        })

    c = _client_with(handler)
    out = await c.get_lineage("org-42")
    await c.close()

    assert captured["url"] == "https://reg.example/api/v1/forge/lineages/org-42"
    assert out["agent_count"] == 1


@pytest.mark.asyncio
async def test_get_lineage_dark_arena_raises_disabled():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "GÖDEL FORGE is not enabled on this registry (FORGE_ENABLED)"})

    c = _client_with(handler)
    with pytest.raises(ForgeDisabledError) as ei:
        await c.get_lineage("org-42")
    await c.close()

    assert ei.value.status_code == 403


# ── eval trigger ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_eval_posts_body_and_bearer():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"suite_id": 3, "target_did": "did:theprotocol:me",
                                         "run_id": 77, "status": "completed"})

    c = _client_with(handler)
    out = await c.run_eval("jwt-a", 3)
    await c.close()

    assert captured["url"] == "https://reg.example/api/v1/forge/evals/run"
    assert captured["auth"] == "Bearer jwt-a"
    assert captured["body"] == {"suite_id": 3}  # target_did omitted → self-eval
    assert out["run_id"] == 77


@pytest.mark.asyncio
async def test_run_eval_with_target_and_non_forge_403_raises_forge_error():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(403, json={"detail": "Evaluating another agent requires forge.evolve_for_org"})

    c = _client_with(handler)
    with pytest.raises(ForgeError) as ei:
        await c.run_eval("jwt-a", 3, target_did="did:theprotocol:other")
    await c.close()

    assert captured["body"] == {"suite_id": 3, "target_did": "did:theprotocol:other"}
    assert ei.value.status_code == 403
    assert not isinstance(ei.value, ForgeDisabledError)  # a perms 403 is not "arena dark"
    assert "forge.evolve_for_org" in str(ei.value.detail)


# ── fork / version / activate ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fork_bundle_path_body_and_auth():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"bundle_id": "bdl-child", "status": "restored"})

    c = _client_with(handler)
    out = await c.fork_bundle("jwt-a", "bdl-parent", royalty_bps=250, name="variant-7")
    await c.close()

    assert captured["url"] == "https://reg.example/api/v1/agents/bundles/bdl-parent/fork"
    assert captured["auth"] == "Bearer jwt-a"
    assert captured["body"] == {"name": "variant-7", "royalty_bps": 250}
    assert out["bundle_id"] == "bdl-child"


@pytest.mark.asyncio
async def test_self_version_maps_notes_and_returns_version_id():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"version_id": "v-uuid-1", "version": "1.1.0"})

    c = _client_with(handler)
    out = await c.self_version("jwt-a", "1.1.0", artifacts={"image": "x:1.1.0"}, notes="variant 7")
    await c.close()

    assert captured["url"] == "https://reg.example/api/v1/agents/self/version"
    assert captured["body"] == {"version": "1.1.0", "release_notes": "variant 7",
                                "artifacts": {"image": "x:1.1.0"}}
    assert out["version_id"] == "v-uuid-1"


@pytest.mark.asyncio
async def test_self_version_normalizes_id_to_version_id():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "v-uuid-2", "version": "1.2.0"})

    c = _client_with(handler)
    out = await c.self_version("jwt-a", "1.2.0")
    await c.close()

    assert out["version_id"] == "v-uuid-2"


@pytest.mark.asyncio
async def test_activate_version_path_and_error_path():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        if "v-good" in str(request.url):
            return httpx.Response(200, json={"version_id": "v-good", "is_active": True})
        return httpx.Response(404, json={"detail": "Version not found"})

    c = _client_with(handler)
    out = await c.activate_version("jwt-a", "v-good")
    assert captured["url"] == "https://reg.example/api/v1/agents/self/versions/v-good/activate"
    assert captured["auth"] == "Bearer jwt-a"
    assert out["is_active"] is True

    with pytest.raises(ForgeError) as ei:
        await c.activate_version("jwt-a", "v-missing")
    await c.close()
    assert ei.value.status_code == 404
