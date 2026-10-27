"""§DOCSFIX CB-277: the card's capabilities.bridge_capability follows the bridge's own switch.

The signed card said `frame_to_frame` on every registry with FEDERATION_ENABLED, whatever TOKEN_BRIDGE_ENABLED said:
EU's card claimed the wrapped-unit bridge while its registry-config said token_bridge_enabled false and
/api/v1/bridge/* was not mounted (main.py mounts routers/token_bridge.py only where surface_enabled says on).
"""
import pytest

from agentvault_registry.core.legacy_surfaces import surface_enabled
from agentvault_registry.services import registry_card_builder as rcb


@pytest.fixture(autouse=True)
def _federated(monkeypatch):
    monkeypatch.setenv("FEDERATION_ENABLED", "true")


def test_where_the_bridge_is_off_the_card_says_none(monkeypatch):
    monkeypatch.setenv("TOKEN_BRIDGE_ENABLED", "false")
    assert rcb._build_capabilities_block()["bridge_capability"] == "none"


def test_where_the_bridge_is_mounted_the_card_says_frame_to_frame(monkeypatch):
    monkeypatch.delenv("TOKEN_BRIDGE_ENABLED", raising=False)   # the code default is on
    assert rcb._build_capabilities_block()["bridge_capability"] == "frame_to_frame"


@pytest.mark.parametrize("value", ["false", "0", "off", "no", "true", "1", "", "garbage"])
def test_the_card_asks_what_mounts_the_routes(monkeypatch, value):
    monkeypatch.setenv("TOKEN_BRIDGE_ENABLED", value)
    on_card = rcb._build_capabilities_block()["bridge_capability"] == "frame_to_frame"
    assert on_card == surface_enabled("TOKEN_BRIDGE_ENABLED")


def test_an_unfederated_registry_bridges_nothing(monkeypatch):
    monkeypatch.setenv("FEDERATION_ENABLED", "false")
    monkeypatch.delenv("TOKEN_BRIDGE_ENABLED", raising=False)
    assert rcb._build_capabilities_block()["bridge_capability"] == "none"
