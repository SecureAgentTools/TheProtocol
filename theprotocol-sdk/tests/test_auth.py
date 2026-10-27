"""Q-C W4 (2026-05-12) — Unified A2A Authenticator (BL-3 core).

Tests:
- AgentJwtVerifier returns success/failure correctly + caches results
- A2AAuthenticator fans out across mTLS / JWT / Payment strategies
- Auto-instantiation of AgentJwtVerifier when registry_url is supplied
- required=True raises 401 when no strategy succeeds
- auto_jwt_verifier=False preserves pre-BL-3 backwards compat

Uses unittest.mock + AsyncMock for network isolation — CI-safe.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── AgentJwtVerifier ─────────────────────────────────────────────────────────


class TestAgentJwtVerifier:
    @pytest.mark.asyncio
    async def test_valid_jwt_returns_caller_did(self):
        from theprotocol.auth.jwt_verifier import AgentJwtVerifier, _verify_cache
        _verify_cache.clear()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "did": "did:theprotocol:abc-123",
            "client_id": "agent-xyz",
            "status": "active",
        }

        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = AsyncMock(return_value=mock_resp)

            verifier = AgentJwtVerifier(registry_url="https://r.test")
            result = await verifier.verify("valid.jwt.token")

        assert result["verified"] is True
        assert result["caller_did"] == "did:theprotocol:abc-123"
        assert result["client_id"] == "agent-xyz"
        assert result["registry"] == "https://r.test"

    @pytest.mark.asyncio
    async def test_401_returns_unverified(self):
        from theprotocol.auth.jwt_verifier import AgentJwtVerifier, _verify_cache
        _verify_cache.clear()

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"detail": "Could not validate agent credentials"}

        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = AsyncMock(return_value=mock_resp)

            verifier = AgentJwtVerifier(registry_url="https://r.test")
            result = await verifier.verify("bad.jwt")

        assert result["verified"] is False
        assert "Could not validate" in result.get("reason", "")

    @pytest.mark.asyncio
    async def test_empty_token_short_circuits(self):
        from theprotocol.auth.jwt_verifier import AgentJwtVerifier, _verify_cache
        _verify_cache.clear()
        verifier = AgentJwtVerifier(registry_url="https://r.test")
        result = await verifier.verify("")
        assert result["verified"] is False
        assert result["reason"] == "missing_token"

    @pytest.mark.asyncio
    async def test_transport_error_returns_unverified(self):
        from theprotocol.auth.jwt_verifier import AgentJwtVerifier, _verify_cache
        _verify_cache.clear()

        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = AsyncMock(side_effect=ConnectionError("registry unreachable"))

            verifier = AgentJwtVerifier(registry_url="https://r.test")
            result = await verifier.verify("any.jwt")

        assert result["verified"] is False
        assert "transport_error" in result.get("reason", "")

    @pytest.mark.asyncio
    async def test_cache_hit_skips_network(self):
        from theprotocol.auth.jwt_verifier import AgentJwtVerifier, _verify_cache
        _verify_cache.clear()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"did": "did:theprotocol:cache-hit", "client_id": "x"}

        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = AsyncMock(return_value=mock_resp)

            verifier = AgentJwtVerifier(registry_url="https://r.test", cache_ttl=10)
            r1 = await verifier.verify("tok-A")
            r2 = await verifier.verify("tok-A")

            assert r1["verified"] is True
            assert r2["verified"] is True
            # Second call should be cache-served — single network call.
            assert instance.get.await_count == 1

    @pytest.mark.asyncio
    async def test_callable_pulls_bearer_from_headers(self):
        from theprotocol.auth.jwt_verifier import AgentJwtVerifier, _verify_cache
        _verify_cache.clear()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"did": "did:theprotocol:bearer", "client_id": "x"}

        class FakeRequest:
            headers = {"Authorization": "Bearer token-from-header"}

        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = AsyncMock(return_value=mock_resp)

            verifier = AgentJwtVerifier(registry_url="https://r.test")
            result = await verifier(FakeRequest())

        assert result["verified"] is True
        assert result["caller_did"] == "did:theprotocol:bearer"

    @pytest.mark.asyncio
    async def test_callable_missing_bearer_returns_unverified(self):
        from theprotocol.auth.jwt_verifier import AgentJwtVerifier, _verify_cache
        _verify_cache.clear()

        class FakeRequest:
            headers = {}

        verifier = AgentJwtVerifier(registry_url="https://r.test")
        result = await verifier(FakeRequest())
        assert result["verified"] is False
        assert "missing_authorization_bearer" in result.get("reason", "")


# ─── A2AAuthenticator unification ─────────────────────────────────────────────


class TestA2AAuthenticatorUnified:
    @pytest.mark.asyncio
    async def test_auto_instantiates_jwt_verifier(self):
        from theprotocol.payment.authenticator import A2AAuthenticator
        auth = A2AAuthenticator(registry_url="https://r.test", auto_jwt_verifier=True)
        assert auth.agent_jwt_verifier is not None

    @pytest.mark.asyncio
    async def test_disable_auto_jwt(self):
        from theprotocol.payment.authenticator import A2AAuthenticator
        # No registry_url + no explicit verifier means nothing to auto-build
        auth = A2AAuthenticator(auto_jwt_verifier=False)
        assert auth.agent_jwt_verifier is None

    @pytest.mark.asyncio
    async def test_bearer_jwt_strategy_hits(self):
        from theprotocol.payment.authenticator import A2AAuthenticator

        class FakeRequest:
            headers = {"Authorization": "Bearer good-token"}
            scope = {}
            state = MagicMock()

        mock_verifier = AsyncMock(return_value={
            "verified": True,
            "caller_did": "did:theprotocol:bearer-caller",
            "client_id": "ag-1",
            "status": "active",
            "registry": "https://r.test",
        })
        auth = A2AAuthenticator(agent_jwt_verifier=mock_verifier, required=False)
        result = await auth(FakeRequest())
        assert result["verified"] is True
        assert result["method"] == "agent_jwt"
        assert result["agent_did"] == "did:theprotocol:bearer-caller"
        assert result["jwt_info"]["client_id"] == "ag-1"

    @pytest.mark.asyncio
    async def test_jwt_failure_falls_through_to_payment(self):
        from theprotocol.payment.authenticator import A2AAuthenticator

        class FakeRequest:
            headers = {"Authorization": "Bearer bad-token", "X-Payment-Token": "apt_xxx"}
            scope = {}
            state = MagicMock()

        mock_jwt = AsyncMock(return_value={"verified": False, "reason": "invalid"})
        mock_payment = AsyncMock(return_value={
            "verified": True,
            "caller_did": "did:theprotocol:payment-caller",
        })
        auth = A2AAuthenticator(
            agent_jwt_verifier=mock_jwt,
            payment_verifier=mock_payment,
            required=False,
        )
        result = await auth(FakeRequest())
        assert result["verified"] is True
        assert result["method"] == "payment"
        assert result["agent_did"] == "did:theprotocol:payment-caller"

    @pytest.mark.asyncio
    async def test_required_no_auth_raises_401(self):
        from fastapi import HTTPException
        from theprotocol.payment.authenticator import A2AAuthenticator

        class FakeRequest:
            headers = {}
            scope = {}
            state = MagicMock()

        auth = A2AAuthenticator(
            agent_jwt_verifier=AsyncMock(return_value={"verified": False}),
            required=True,
        )
        with pytest.raises(HTTPException) as exc_info:
            await auth(FakeRequest())
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_required_with_valid_jwt_passes(self):
        from theprotocol.payment.authenticator import A2AAuthenticator

        class FakeRequest:
            headers = {"Authorization": "Bearer valid"}
            scope = {}
            state = MagicMock()

        mock_jwt = AsyncMock(return_value={
            "verified": True,
            "caller_did": "did:theprotocol:passes",
            "client_id": "x",
        })
        auth = A2AAuthenticator(agent_jwt_verifier=mock_jwt, required=True)
        result = await auth(FakeRequest())
        assert result["verified"] is True
        assert result["method"] == "agent_jwt"


# ─── theprotocol.auth re-exports ──────────────────────────────────────────────


class TestAuthModuleReExports:
    def test_a2a_authenticator_importable_from_auth(self):
        from theprotocol.auth import A2AAuthenticator
        assert A2AAuthenticator is not None

    def test_agent_jwt_verifier_importable_from_auth(self):
        from theprotocol.auth import AgentJwtVerifier
        assert AgentJwtVerifier is not None

    def test_legacy_import_path_still_works(self):
        """The original ``theprotocol.payment.A2AAuthenticator`` keeps working."""
        from theprotocol.payment import A2AAuthenticator
        assert A2AAuthenticator is not None
