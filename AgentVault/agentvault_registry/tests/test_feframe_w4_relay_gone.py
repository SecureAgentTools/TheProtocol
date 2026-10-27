"""§FEFRAME W4 (V0507): the admin relay is gone.

`/admin/peer/{key}/…` relayed a console's calls to a sibling registry, with an allowlist from PEER_REGISTRY_{A,B,C}_URL or
COMMAND_RELAY_URL_MAP at COMMAND_RELAY_SCOPE=fleet. No live registry set either, so it answered for the retired frames
only. A console signs in at a registry's own address now (the frame manifest's console_url). Pinned here:
no route under /api/v1/admin/peer, no relay module, no relay helpers or letter maps in the command router, no
`relay_console` capability, and the directory entry without a `relay` block.
"""
import importlib

import pytest

from agentvault_registry.core import auth_tiers


@pytest.fixture(scope="module")
def app():
    from agentvault_registry.main import app as _app
    return _app


def test_no_route_under_the_relay_prefix(app):
    paths = {c.path_format for c in auth_tiers.api_routes(app)}
    assert len(paths) > 1000                                     # the walk reached the nested routers (the control)
    assert not [p for p in paths if p.startswith("/api/v1/admin/peer/") or p == "/api/v1/admin/peer"]
    assert "/api/v1/admin/command/registry-directory" in paths  # the command centre stays


def test_the_relay_module_is_gone():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("agentvault_registry.routers.admin_peer_proxy")


def test_the_command_router_has_no_relay_and_no_letters():
    from agentvault_registry.routers import admin_command as ac
    for name in ("resolve_relay_base", "relay_scope", "_relay_url_map", "_LEGACY_FRAME_LETTER", "_LETTER_TO_KEYS",
                 "_FRAME_TD", "_frame_for"):
        assert not hasattr(ac, name), name
    for tier, peer_type, is_local in (("sovereign-mainframe", "frame", False), ("cloud-operator", "cloud_operator", False),
                                      ("sovereign-mainframe", "local", True)):
        assert "relay_console" not in ac._capabilities(tier, peer_type, is_local)
    entry = ac._entry(key="asia", name="asia", trust_domain="asia.theprotocol.cloud", peer_type="frame",
                      tier="sovereign-mainframe", currency="ACU", hop=1, is_local=False, card_version=None,
                      card_pulled_at=None, manifest_entry={"key": "asia", "console_url": "https://asia.theprotocol.cloud"},
                      frame_key="asia")
    assert "relay" not in entry and entry["frame"] == "asia" and entry["console_url"] == "https://asia.theprotocol.cloud"


def test_fleet_status_probes_only_what_the_operator_names(monkeypatch):
    from agentvault_registry.routers import admin_command as ac
    monkeypatch.delenv("COMMAND_RELAY_URL_MAP", raising=False)
    assert ac._probe_url_map() == {}
    monkeypatch.setenv("COMMAND_RELAY_URL_MAP", '{"ASIA": "https://asia.example/", "x": ""}')
    assert ac._probe_url_map() == {"asia": "https://asia.example"}
    monkeypatch.setenv("COMMAND_RELAY_URL_MAP", "{not json")
    assert ac._probe_url_map() == {}
