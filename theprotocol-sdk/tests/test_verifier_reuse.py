"""Tests for PaymentVerifier reject_reused_tokens (P25-001 opt-in, SDK 0.5.0)."""
import pytest

from theprotocol.payment.verifier import PaymentVerifier, _verify_cache


class _Req:
    """Minimal request stand-in: headers dict + state attr."""
    def __init__(self, headers):
        self.headers = headers
        self.state = type("S", (), {})()


def _valid_result(token_id="tok-1"):
    return {"valid": True, "token_id": token_id,
            "caller_did": "did:caller", "target_agent_did": "did:me", "amount": "5"}


@pytest.fixture(autouse=True)
def _clear_cache():
    _verify_cache.clear()
    yield
    _verify_cache.clear()


@pytest.mark.asyncio
async def test_default_allows_reverify(monkeypatch):
    v = PaymentVerifier("https://reg.example", "did:me")  # default: no reuse rejection
    async def fake_verify(url, token):
        return _valid_result()
    monkeypatch.setattr(v, "_verify_with_registry", fake_verify)

    req = _Req({"X-Payment-Token": "apt_abc"})
    assert (await v(req))["verified"] is True
    assert (await v(req))["verified"] is True  # second verify still fine (registry semantics)


@pytest.mark.asyncio
async def test_reject_reused_blocks_second_acceptance(monkeypatch):
    from fastapi import HTTPException
    v = PaymentVerifier("https://reg.example", "did:me", reject_reused_tokens=True)
    async def fake_verify(url, token):
        return _valid_result()
    monkeypatch.setattr(v, "_verify_with_registry", fake_verify)

    req = _Req({"X-Payment-Token": "apt_abc"})
    first = await v(req)
    assert first["verified"] is True
    with pytest.raises(HTTPException) as ei:
        await v(_Req({"X-Payment-Token": "apt_abc"}))
    assert ei.value.status_code == 402
    assert "already used" in str(ei.value.detail)


@pytest.mark.asyncio
async def test_reject_reused_optional_mode_returns_unverified(monkeypatch):
    v = PaymentVerifier("https://reg.example", "did:me",
                        required=False, reject_reused_tokens=True)
    async def fake_verify(url, token):
        return _valid_result()
    monkeypatch.setattr(v, "_verify_with_registry", fake_verify)

    assert (await v(_Req({"X-Payment-Token": "apt_x"})))["verified"] is True
    second = await v(_Req({"X-Payment-Token": "apt_x"}))
    assert second == {"verified": False}
