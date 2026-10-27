"""§VENUEGW — the deposit gateway must name an account on the ledger that pays it.

The gateway DID used to be derived from the CURRENCY alone. A cloud-op shares its
frame's currency but keeps its own TEG, so a currency-only DID named an account on the
FRAME's ledger while the op's venue sweeper polled its own — every inbound passport buy
sat in 'funding' until it expired. Measured before the fix: registry-a 221,045 filled
passport orders, frame-b 227,600, every cloud-op zero.

The load-bearing assertion here is the FIRST one: a mainframe's DID must not move.
Three live gateway balances and ~448k settled orders hang off those exact strings.
"""
import importlib

import pytest


def _did(monkeypatch, **env):
    for k in ("IS_CENTRAL_REGISTRY", "REGISTRY_NAME", "AGORA_GATEWAY_SLUG", "FRAME_CURRENCY"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    svc = importlib.import_module("agentvault_registry.services.exchange_service")
    return svc.gateway_did()


@pytest.mark.parametrize(
    "env,expected",
    [
        # ── mainframes: BYTE-IDENTICAL to the pre-VENUEGW value. Do not "improve" these.
        ({"IS_CENTRAL_REGISTRY": "true", "REGISTRY_NAME": "Registry-A"},
         "did:theprotocol:agora-gateway-avt"),
        ({"IS_CENTRAL_REGISTRY": "true", "REGISTRY_NAME": "Frame-B", "FRAME_CURRENCY": "JDAY"},
         "did:theprotocol:agora-gateway-jday"),
        ({"IS_CENTRAL_REGISTRY": "true", "REGISTRY_NAME": "Frame-C", "FRAME_CURRENCY": "BVT"},
         "did:theprotocol:agora-gateway-bvt"),
        # ── cloud-ops: scoped to the venue that owns the TEG.
        ({"REGISTRY_NAME": "cloud-op-op-london"},
         "did:theprotocol:agora-gateway-op-london-avt"),
        ({"REGISTRY_NAME": "cloud-op-op-doha", "FRAME_CURRENCY": "BVT"},
         "did:theprotocol:agora-gateway-op-doha-bvt"),
        ({"REGISTRY_NAME": "cloud-op-op-tokyo", "FRAME_CURRENCY": "JDAY"},
         "did:theprotocol:agora-gateway-op-tokyo-jday"),
        ({"REGISTRY_NAME": "cloud-op-qatest16"},
         "did:theprotocol:agora-gateway-qatest16-avt"),
        # ── explicit override wins over the derived name.
        ({"REGISTRY_NAME": "cloud-op-op-london", "AGORA_GATEWAY_SLUG": "venue-x"},
         "did:theprotocol:agora-gateway-venue-x-avt"),
        # ── junk in a name never produces a junk DID.
        ({"REGISTRY_NAME": "Cloud-Op-OP Weird__Name!!"},
         "did:theprotocol:agora-gateway-op-weird-name-avt"),
    ],
)
def test_gateway_did(monkeypatch, env, expected):
    assert _did(monkeypatch, **env) == expected


def test_central_flag_beats_a_name(monkeypatch):
    """A mainframe that also carries an op-shaped name still keeps the frame DID."""
    assert _did(monkeypatch, IS_CENTRAL_REGISTRY="true", REGISTRY_NAME="cloud-op-op-london") == \
        "did:theprotocol:agora-gateway-avt"


def test_unnamed_non_central_falls_back_and_warns(monkeypatch, caplog):
    """No name to scope with → keep today's behaviour, but never silently."""
    with caplog.at_level("WARNING"):
        got = _did(monkeypatch)
    assert got == "did:theprotocol:agora-gateway-avt"
    assert any("gateway falls back" in r.message for r in caplog.records)


def test_currency_is_still_the_last_token(monkeypatch):
    """Both shapes end in the currency, so a rsplit('-',1) reader cannot be wrong."""
    for env in ({"IS_CENTRAL_REGISTRY": "true"}, {"REGISTRY_NAME": "cloud-op-op-london"}):
        assert _did(monkeypatch, **env).rsplit("-", 1)[-1] == "avt"


def test_the_two_modules_agree(monkeypatch):
    """One definition. Two copies of a money identity is a drift waiting to happen."""
    import agentvault_registry.services.exchange_passport as pp
    import agentvault_registry.services.exchange_service as svc
    assert pp.GATEWAY_DID == svc.GATEWAY_DID
