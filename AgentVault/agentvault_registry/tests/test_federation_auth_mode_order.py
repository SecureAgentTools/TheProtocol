"""§FRAMELIC findings row 193 — a wrong internal secret must not answer for the whole request.

`get_federation_identity` documents itself as "Authentication modes (tried in order)" and then
Mode 2 RAISED on a secret mismatch, so Mode 3 (the federation licence) was never reached.
`_fx_route_delegate` presents BOTH credentials whenever it holds both — and every frame holds an
internal secret, for its OWN cluster — so a cross-frame call carrying a perfectly good licence was
refused with 401 "Invalid federation secret". Measured live 2026-09-07: EU → ASIA
POST /teg/fx/route-hop, on the leg that had just converted currency.

⚠ THE POINT OF THIS FILE IS THE CONTROLS, NOT THE FIX. Falling through must grant NOTHING: a
caller who omits the secret header already reaches Mode 3, so the only behaviour that may change
is that presenting a wrong secret no longer *costs* you the licence you also presented. Every
other refusal in this function must be exactly as it was.
"""
import pytest
from fastapi import HTTPException

from agentvault_registry.core import federation_auth


class _Client:
    def __init__(self, host):
        self.host = host


class _Headers(dict):
    """⚠ CASE-INSENSITIVE, because Starlette's Headers are and a plain dict is not.

    The first version of this fixture used a plain dict, so `is_internal_request`'s
    `"x-forwarded-for" in headers` was False against a key stored as "X-Forwarded-For" — and the
    external-caller test reported DID NOT RAISE. That read exactly like the gate not working;
    it was the fixture not modelling the object. A fake that is more permissive than the real
    type tests a system that does not exist.
    """

    def __init__(self, mapping):
        super().__init__({k.lower(): v for k, v in mapping.items()})

    def __contains__(self, key):
        return super().__contains__(str(key).lower())

    def get(self, key, default=None):
        return super().get(str(key).lower(), default)


class _Req:
    """Headers, plus the peer address — because `is_internal_request` needs BOTH halves: no edge
    headers (X-Forwarded-For / X-Real-IP) AND a private peer. Default is an INTERNAL container
    caller, which is the only shape allowed to use the shared-secret rail (findings row 195)."""

    def __init__(self, _peer="172.16.0.9", **headers):
        self.headers = _Headers({k.replace("_", "-"): v for k, v in headers.items() if v is not None})
        self.client = _Client(_peer) if _peer else None


def _external(**headers):
    """A caller that reached us THROUGH our edge — which is what every internet request is.
    nginx appends the real peer to X-Forwarded-For, so its presence is the tell."""
    return _Req(_peer="127.0.0.1", X_Forwarded_For="203.0.113.9", **headers)


@pytest.fixture(autouse=True)
def _no_client_cert(monkeypatch):
    """Mode 1 off for every test here: an mTLS cert would authenticate before we reach Mode 2,
    which is the production path and is not what this file is about."""
    async def _no_cert(_request):
        raise HTTPException(status_code=401, detail="no client certificate")
    monkeypatch.setattr(federation_auth, "get_client_spiffe_id", _no_cert)


@pytest.fixture(autouse=True)
def _trusted_domains(monkeypatch):
    import agentvault_registry.core.mtls_auth as mtls
    monkeypatch.setattr(mtls, "TRUSTED_SPIFFE_DOMAINS", ["eu.theprotocol.cloud"], raising=False)


def _set_secret(monkeypatch, value):
    monkeypatch.setattr(federation_auth, "FEDERATION_INTERNAL_SECRET", value)


def _license_returns(monkeypatch, identity):
    async def _verify(key, request):
        return identity
    monkeypatch.setattr(federation_auth, "_verify_license_key", _verify)


async def _call(req):
    return await federation_auth.get_federation_identity(req, None, None)


# ── THE DEFECT ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_wrong_secret_no_longer_swallows_a_valid_license(monkeypatch):
    """The live failure, reproduced: our own cluster secret presented to a sovereign peer,
    alongside the licence that peer actually issued us."""
    _set_secret(monkeypatch, "asias-own-cluster-secret")
    _license_returns(monkeypatch, "license:eu.theprotocol.cloud")
    ident = await _call(_Req(
        X_Federation_Secret="eus-own-cluster-secret",          # cannot match — different cluster
        X_Federation_SPIFFE_ID="spiffe://eu.theprotocol.cloud/service/registry-eu",
        X_Federation_License="tp_fed_valid",
    ))
    assert ident == "license:eu.theprotocol.cloud"


# ── THE CONTROLS: falling through must grant NOTHING ──────────────────────────────────────

@pytest.mark.asyncio
async def test_a_wrong_secret_with_no_license_is_still_refused(monkeypatch):
    """The control that matters most. Without a licence there is nothing to fall through TO,
    and the answer must still be 401."""
    _set_secret(monkeypatch, "the-real-secret")
    with pytest.raises(HTTPException) as e:
        await _call(_Req(
            X_Federation_Secret="wrong",
            X_Federation_SPIFFE_ID="spiffe://eu.theprotocol.cloud/service/registry-eu",
        ))
    assert e.value.status_code == 401


@pytest.mark.asyncio
async def test_a_wrong_secret_with_an_invalid_license_is_still_refused(monkeypatch):
    """A bad credential plus a bad credential is not a good credential."""
    _set_secret(monkeypatch, "the-real-secret")
    _license_returns(monkeypatch, None)          # the verifier rejects it
    with pytest.raises(HTTPException) as e:
        await _call(_Req(
            X_Federation_Secret="wrong",
            X_Federation_SPIFFE_ID="spiffe://eu.theprotocol.cloud/service/registry-eu",
            X_Federation_License="tp_fed_bogus",
        ))
    assert e.value.status_code == 401


@pytest.mark.asyncio
async def test_an_empty_configured_secret_still_authenticates_nobody(monkeypatch):
    """P21-001's other half: a node with no secret configured must not be opened by a caller
    sending an empty one. Unchanged by the fall-through."""
    _set_secret(monkeypatch, "")
    with pytest.raises(HTTPException) as e:
        await _call(_Req(
            X_Federation_Secret="",
            X_Federation_SPIFFE_ID="spiffe://eu.theprotocol.cloud/service/registry-eu",
        ))
    assert e.value.status_code == 401


@pytest.mark.asyncio
async def test_no_credentials_at_all_is_still_refused(monkeypatch):
    _set_secret(monkeypatch, "the-real-secret")
    with pytest.raises(HTTPException) as e:
        await _call(_Req())
    assert e.value.status_code == 401


# ── THE PATHS THAT MUST NOT HAVE MOVED ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_correct_secret_still_authenticates(monkeypatch):
    _set_secret(monkeypatch, "the-real-secret")
    ident = await _call(_Req(
        X_Federation_Secret="the-real-secret",
        X_Federation_SPIFFE_ID="spiffe://eu.theprotocol.cloud/service/registry-eu",
    ))
    assert ident == "spiffe://eu.theprotocol.cloud/service/registry-eu"


@pytest.mark.asyncio
async def test_a_correct_secret_from_an_untrusted_domain_still_403s(monkeypatch):
    """DELIBERATELY unchanged: the secret DID authenticate, so this is an authorization refusal
    about a caller we recognised — not a reason to go looking for a second credential. If this
    ever falls through, a caller could bypass the trust-domain check by attaching a licence."""
    _set_secret(monkeypatch, "the-real-secret")
    _license_returns(monkeypatch, "license:somebody")
    with pytest.raises(HTTPException) as e:
        await _call(_Req(
            X_Federation_Secret="the-real-secret",
            X_Federation_SPIFFE_ID="spiffe://attacker.example/service/registry-x",
            X_Federation_License="tp_fed_valid",
        ))
    assert e.value.status_code == 403


@pytest.mark.asyncio
async def test_a_license_alone_still_works(monkeypatch):
    """The path that always worked — proving the fall-through did not disturb it."""
    _set_secret(monkeypatch, "the-real-secret")
    _license_returns(monkeypatch, "license:operator-x")
    assert await _call(_Req(X_Federation_License="tp_fed_valid")) == "license:operator-x"


# ── findings row 195: the shared-secret rail is INTERNAL ONLY ─────────────────────────────

@pytest.mark.asyncio
async def test_a_correct_secret_from_OUTSIDE_is_refused(monkeypatch):
    """THE GATE. The secret is a shared bearer whose identity the caller declares — one leak
    authenticates as any identity in a trusted domain. It exists for container-to-container
    hops over plain HTTP; it must not be presentable by anything that came through our edge.
    Measured before shipping: 1,414 live federation authentications, all via mTLS, so nothing
    real presents this from outside."""
    _set_secret(monkeypatch, "the-real-secret")
    with pytest.raises(HTTPException) as e:
        await _call(_external(
            X_Federation_Secret="the-real-secret",          # the CORRECT secret
            X_Federation_SPIFFE_ID="spiffe://eu.theprotocol.cloud/service/registry-eu",
        ))
    assert e.value.status_code == 401
    assert "not reachable from outside" in str(e.value.detail)


@pytest.mark.asyncio
async def test_the_external_refusal_does_not_also_kill_a_valid_license(monkeypatch):
    """The gate and the fall-through composing: an external caller presenting the secret it
    should not have AND a licence it legitimately holds is authenticated by the licence."""
    _set_secret(monkeypatch, "the-real-secret")
    _license_returns(monkeypatch, "license:operator-x")
    ident = await _call(_external(
        X_Federation_Secret="the-real-secret",
        X_Federation_SPIFFE_ID="spiffe://eu.theprotocol.cloud/service/registry-eu",
        X_Federation_License="tp_fed_valid",
    ))
    assert ident == "license:operator-x"


@pytest.mark.asyncio
async def test_an_internal_caller_may_still_use_the_secret(monkeypatch):
    """The control that keeps the internal rails alive: a container-to-container hop has no edge
    headers and a private peer, and must still authenticate. If this ever goes red, federation
    sync, the compliance poller and the canary runner have lost their credential."""
    _set_secret(monkeypatch, "the-real-secret")
    ident = await _call(_Req(
        _peer="172.16.0.9",
        X_Federation_Secret="the-real-secret",
        X_Federation_SPIFFE_ID="spiffe://eu.theprotocol.cloud/service/registry-eu",
    ))
    assert ident == "spiffe://eu.theprotocol.cloud/service/registry-eu"


@pytest.mark.asyncio
async def test_an_external_caller_cannot_reach_the_secret_rail_via_x_real_ip_either(monkeypatch):
    """X-Real-IP REPLACES rather than appends, so it is the other half of the edge tell.
    Without this leg the gate would be one header away from being bypassable."""
    _set_secret(monkeypatch, "the-real-secret")
    req = _Req(_peer="127.0.0.1",
               X_Real_IP="203.0.113.9",
               X_Federation_Secret="the-real-secret",
               X_Federation_SPIFFE_ID="spiffe://eu.theprotocol.cloud/service/registry-eu")
    with pytest.raises(HTTPException) as e:
        await _call(req)
    assert e.value.status_code == 401


# ── THE REFUSAL MUST SAY WHAT IT TRIED ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_refusal_names_the_modes_it_tried(monkeypatch):
    """What sent me down the wrong path for an hour: a 401 that named the credential that failed
    and said nothing about the one it never read."""
    _set_secret(monkeypatch, "the-real-secret")
    _license_returns(monkeypatch, None)
    with pytest.raises(HTTPException) as e:
        await _call(_Req(
            X_Federation_Secret="wrong",
            X_Federation_SPIFFE_ID="spiffe://eu.theprotocol.cloud/service/registry-eu",
            X_Federation_License="tp_fed_bogus",
        ))
    detail = str(e.value.detail)
    assert "internal secret was tried and refused" in detail
    assert "license key was presented and did not verify" in detail
