"""The card's capabilities.bridge_capability: `none` on every registry since the token bridge's retirement.

§DOCSFIX CB-277 made the card follow the bridge's switch (it said `frame_to_frame` on every federated registry, EU's
included, where /api/v1/bridge/* was not mounted). V0651 (p) (order gwo_b109ec1d4454d0db66ef6d32, 2026-10-31) retired
the bridge on every registry: its routes answer 410 Gone whatever TOKEN_BRIDGE_ENABLED says, so no card offers it, and
the retired switch can no longer turn the card's entity tag either. The cases that set the switch fail on 48d07ecf2
(V0650), whose card still said `frame_to_frame` where the switch was on or unset.
"""
import pytest

from agentvault_registry.services import registry_card_builder as rcb


@pytest.fixture(autouse=True)
def _federated(monkeypatch):
    monkeypatch.setenv("FEDERATION_ENABLED", "true")


@pytest.mark.parametrize("value", [None, "false", "0", "off", "no", "true", "1", "on", "", "garbage"])
def test_no_card_offers_the_retired_bridge(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("TOKEN_BRIDGE_ENABLED", raising=False)   # the code default was on
    else:
        monkeypatch.setenv("TOKEN_BRIDGE_ENABLED", value)
    assert rcb._build_capabilities_block()["bridge_capability"] == "none"


def test_an_unfederated_registry_bridges_nothing(monkeypatch):
    monkeypatch.setenv("FEDERATION_ENABLED", "false")
    monkeypatch.delenv("TOKEN_BRIDGE_ENABLED", raising=False)
    assert rcb._build_capabilities_block()["bridge_capability"] == "none"


def test_the_retired_switch_turns_no_tag(monkeypatch):
    def tag():
        return rcb._etag_from_basis({}, rcb._id_subset({}), None)

    monkeypatch.delenv("TOKEN_BRIDGE_ENABLED", raising=False)
    before = tag()
    for value in ("false", "true", "off"):
        monkeypatch.setenv("TOKEN_BRIDGE_ENABLED", value)
        assert tag() == before, value
