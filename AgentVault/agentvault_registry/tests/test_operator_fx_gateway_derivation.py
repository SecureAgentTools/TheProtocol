"""§SBXFXROUTE — an operator's FX gateway is its OWN parent, never Frame A's.

The provisioner chose the gateway with a hardcoded three-way branch on the
parent's SPIRE trust domain, and everything that was not frame-b or frame-c fell
into the Frame-A branch. Measured 2026-09-06 on the live box: `amsterdam`,
`lisbon`, `shenzhen` and `hochiminh` — the four operators of the EU/ASIA cluster
being rehearsed for a production standup — each carried

    FX_ROUTE_ENABLED=true
    FX_ROUTE_GATEWAY_REGISTRY_ID=registry-a
    FX_ROUTE_GATEWAY_TEG_ID=teg-layer-a
    FX_ROUTE_GATEWAY_ROUTER_DID=did:theprotocol:16968217-03a0-e909-5026

while their parents are EU (ECU) and ASIA (ACU). The JUICE/BRRR pair's operators
carried the same. A cross-currency transfer originated on one of them ingresses
1:1 into a FOREIGN frame's transit account; both legs are ordinary transfers, so
Δ stays 0 on every frame and the money is simply on the wrong one.

These tests pin the derivation and BOTH controls: the frames that were already
right must stay byte-identical, and a frame that cannot name itself must name
NOTHING rather than name someone else.
"""
import pytest

# The suite is run IN THE IMAGE with the tree's tests/ mounted over it, so this file
# can meet an image built before the fix. A bare import would then raise at IMPORT —
# and a test module that raises at import interrupts the WHOLE collection (finding
# row 70: 2352 tests reported as "1 skipped, 2 errors"). Skip loudly instead, naming
# the reason, so an old image reads as "not measured here" and never as green.
derived_fx_gateway = None
try:
    from agentvault_registry.services.cloud_provisioner import derived_fx_gateway
except ImportError:  # pragma: no cover - only on a pre-fix image
    pass

pytestmark = pytest.mark.skipif(
    derived_fx_gateway is None,
    reason="this image predates §SBXFXROUTE: cloud_provisioner has no derived_fx_gateway "
           "(the operator FX gateway is still chosen by the hardcoded trust-domain branch)",
)

FRAME_A_DID = "did:theprotocol:16968217-03a0-e909-5026"


def test_derives_the_frames_own_identity():
    reg, did, teg, url = derived_fx_gateway(
        "eu.theprotocol.cloud", "EU", "did:theprotocol:11111111-2222-3333-4444-555555555555")
    assert reg == "eu"
    assert teg == "teg-layer-eu"
    assert did == "did:theprotocol:11111111-2222-3333-4444-555555555555"
    assert url == "https://eu.theprotocol.cloud:8443"


def test_uses_the_card_name_not_the_container_name():
    # measured: the peer ROW is named from the CARD ("Sandbox Alpha"), while
    # REGISTRY_NAME on the same frame is `sbx-alpha`. `_fx_route_find_active_peer`
    # matches the row, so the card name is the only one that resolves.
    reg, _did, teg, _url = derived_fx_gateway("sbx-alpha", "Sandbox Alpha", "did:theprotocol:abc")
    assert reg == "sandbox-alpha"
    assert teg == "teg-layer-sandbox-alpha"


def test_never_names_frame_a():
    # the whole point: the derived gateway can never come out as production Frame A
    for name in ("EU", "ASIA", "JUICE", "BRRR", "Sandbox Alpha", "Sandbox Beta"):
        reg, did, teg, _url = derived_fx_gateway("x.example", name, "did:theprotocol:own")
        assert reg != "registry-a"
        assert teg != "teg-layer-a"
        assert did != FRAME_A_DID


@pytest.mark.parametrize("name,router_did", [
    ("EU", ""),            # frame has an identity but no @fx_router transit account
    ("", "did:theprotocol:own"),   # frame cannot read its own card name
    ("", ""),
    (None, "did:theprotocol:own"),
])
def test_names_nothing_when_it_cannot_name_itself(name, router_did):
    # OFF is strictly better than pointing at another frame: the failure is then a
    # refusal the caller can read, not a misdelivery no invariant can see.
    assert derived_fx_gateway("x.example", name, router_did) == ("", "", "", None)


def test_the_control_a_populated_call_returns_something():
    # without this the test above passes for a helper that returns empties always
    assert derived_fx_gateway("x.example", "EU", "did:theprotocol:own") != ("", "", "", None)
