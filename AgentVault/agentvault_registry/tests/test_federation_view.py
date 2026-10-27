"""§FEFRAME W2: the frame manifest's trust rules (core/federation_view.py), DB-free and network-free.

The cards below are shaped like the live cluster's (2026-09-30: EU and ASIA are sovereign mainframes with their own
trust domains; amsterdam is EU's cloud operator and shares EU's trust domain; hochiminh is ASIA's and reaches EU as a
`discovered` row). Each rule has a control: the same input with the one property that makes it trustworthy removed.
"""
import pytest

from agentvault_registry.core import federation_view as fv


def _card(name, tier, td, public_url, currency, theme="neural", icon="/static/registry-cards/x/icon.png", display=None):
    return {
        "identity": {"registry_name": name, "display_name": display or name, "tier": tier, "trust_domain": td,
                     "public_url": public_url},
        "fees": {"settlement_currency": currency},
        "visual": {"theme": theme, "icon_url": icon},
    }


ASIA = _card("ASIA", "sovereign-mainframe", "asia.theprotocol.cloud", "https://asia.theprotocol.cloud", "ACU", "sovereign")
HCM = _card("hochiminh", "cloud-operator", "asia.theprotocol.cloud", "https://hochiminh.op.theprotocol.cloud", "ACU",
            "sovereign", display="Ho Chi Minh City")
AMS = _card("amsterdam", "cloud-operator", "eu.theprotocol.cloud", "https://amsterdam.op.theprotocol.cloud", "ECU")


@pytest.mark.parametrize("url,want", [
    ("https://asia.theprotocol.cloud", "https://asia.theprotocol.cloud"),
    ("https://asia.theprotocol.cloud:8443/api/v1", "https://asia.theprotocol.cloud"),
    ("https://ASIA.theprotocol.cloud/", "https://asia.theprotocol.cloud"),
    ("http://asia.theprotocol.cloud", None),
    ("https://127.0.0.1:8360", None),
    ("https://localhost", None),
    ("https://registry-a:8000", None),
    ("https://[::1]:443", None),
    ("javascript:alert(1)", None),
    ("", None),
    (None, None),
])
def test_web_origin(url, want):
    assert fv.web_origin(url) == want


def test_verified_card_on_the_admitted_host_names_the_public_url():
    e = fv.entry_from_card(HCM, name="hochiminh", base_url="https://hochiminh.op.theprotocol.cloud:8443",
                           peer_type="discovered", verified=True)
    assert e["public_url"] == "https://hochiminh.op.theprotocol.cloud"
    assert e["role"] == fv.ROLE_OPERATOR and e["trust_domain"] == "asia.theprotocol.cloud"
    assert e["currency"] == "ACU" and e["theme"] == "sovereign" and e["display_name"] == "Ho Chi Minh City"
    assert e["icon_url"] == "https://hochiminh.op.theprotocol.cloud/static/registry-cards/x/icon.png"


def test_a_card_may_not_claim_another_host():
    """A peer admitted on hochiminh's host whose card claims theprotocol.cloud keeps its own federation origin."""
    forged = _card("hochiminh", "cloud-operator", "asia.theprotocol.cloud", "https://theprotocol.cloud", "ACU")
    e = fv.entry_from_card(forged, name="hochiminh", base_url="https://hochiminh.op.theprotocol.cloud:8443",
                           peer_type="discovered", verified=True)
    assert e["public_url"] == "https://hochiminh.op.theprotocol.cloud"


def test_an_unverified_card_does_not_name_the_public_url():
    moved = _card("asia", "sovereign-mainframe", "asia.theprotocol.cloud", "https://asia.theprotocol.cloud", "ACU")
    e = fv.entry_from_card(moved, name="asia", base_url="https://asia-fed.theprotocol.cloud:8443", peer_type="frame",
                           verified=False)
    assert e["public_url"] == "https://asia-fed.theprotocol.cloud"
    # the control: the same card, verified, still may not move the host
    e2 = fv.entry_from_card(moved, name="asia", base_url="https://asia-fed.theprotocol.cloud:8443", peer_type="frame",
                            verified=True)
    assert e2["public_url"] == "https://asia-fed.theprotocol.cloud"


def test_role_from_the_signed_tier_before_the_row_type():
    assert fv.role_of("cloud-operator", "frame") == fv.ROLE_OPERATOR
    assert fv.role_of("sovereign-mainframe", "discovered") == fv.ROLE_FRAME
    assert fv.role_of(None, "frame") == fv.ROLE_FRAME
    assert fv.role_of(None, "cloud_operator") == fv.ROLE_OPERATOR
    assert fv.role_of(None, "discovered") is None


def test_parents_and_ledgers_by_trust_domain():
    me = {"key": "eu", "role": fv.ROLE_FRAME, "trust_domain": "eu.theprotocol.cloud", "public_url": "https://eu.theprotocol.cloud",
          "console_url": "https://theprotocol.cloud", "ledger_ws": "wss://eu.theprotocol.cloud/ws/events"}
    asia = fv.entry_from_card(ASIA, name="asia", base_url="https://asia.theprotocol.cloud:8443", peer_type="frame",
                              verified=True)
    hcm = fv.entry_from_card(HCM, name="hochiminh", base_url="https://hochiminh.op.theprotocol.cloud:8443",
                             peer_type="discovered", verified=True)
    ams = fv.entry_from_card(AMS, name="amsterdam", base_url="https://amsterdam.op.theprotocol.cloud:8443",
                             peer_type="cloud_operator", verified=True)
    out = {e["key"]: e for e in fv.resolve_parents([me, asia, hcm, ams])}
    assert out["hochiminh"]["parent"] == "asia" and out["amsterdam"]["parent"] == "eu"
    assert out["asia"]["ledger_ws"] == "wss://asia.theprotocol.cloud/ws/events"
    assert out["hochiminh"]["ledger_ws"] == "wss://asia.theprotocol.cloud/ws/events"   # an operator streams its frame
    assert out["amsterdam"]["ledger_ws"] == "wss://eu.theprotocol.cloud/ws/events"
    assert out["eu"]["parent"] is None and out["asia"]["parent"] is None


def test_a_role_the_card_did_not_state_is_resolved_by_trust_domain():
    me = {"key": "eu", "role": fv.ROLE_FRAME, "trust_domain": "eu.theprotocol.cloud",
          "console_url": "https://theprotocol.cloud"}
    bare = {"key": "lisbon", "role": None, "trust_domain": "eu.theprotocol.cloud",
            "console_url": "https://lisbon.op.theprotocol.cloud"}
    lone = {"key": "tartu", "role": None, "trust_domain": "tartu.example.org",
            "console_url": "https://console.tartu.example.org", "public_url": "https://tartu.example.org"}
    out = {e["key"]: e for e in fv.resolve_parents([me, bare, lone])}
    assert out["lisbon"]["role"] == fv.ROLE_OPERATOR and out["lisbon"]["parent"] == "eu"
    assert out["tartu"]["role"] == fv.ROLE_FRAME and out["tartu"]["ledger_ws"] == "wss://tartu.example.org/ws/events"


def test_peer_manifest_fields_are_taken_only_from_the_registry_they_describe():
    m = {"self": {"public_url": "https://eu.theprotocol.cloud", "console_url": "https://theprotocol.cloud",
                  "ledger_ws": "wss://theprotocol.cloud/ws/events", "currency_name": "European Compute Unit"}}
    got = fv.peer_manifest_fields(m, expect_host="eu.theprotocol.cloud")
    assert got == {"console_url": "https://theprotocol.cloud", "ledger_ws": "wss://theprotocol.cloud/ws/events",
                   "currency_name": "European Compute Unit"}
    assert fv.peer_manifest_fields(m, expect_host="asia.theprotocol.cloud") == {}   # a manifest about someone else
    bad = {"self": {"public_url": "https://eu.theprotocol.cloud", "console_url": "http://theprotocol.cloud",
                    "ledger_ws": "ws://theprotocol.cloud/ws/events", "currency_name": "x" * 200}}
    assert fv.peer_manifest_fields(bad, expect_host="eu.theprotocol.cloud") == {}
    other_path = {"self": {"public_url": "https://eu.theprotocol.cloud", "ledger_ws": "wss://theprotocol.cloud/api/v1/ws"}}
    assert fv.peer_manifest_fields(other_path, expect_host="eu.theprotocol.cloud") == {}


def test_dedupe_drops_self_echoes_and_prefers_a_verified_card():
    rows = [
        {"key": "asia", "verified": False, "role": "frame"},
        {"key": "asia", "verified": True, "role": "frame", "tag": "good"},
        {"key": "eu", "verified": True, "role": "frame"},
        {"key": "amsterdam", "verified": True, "role": "operator"},
    ]
    out = fv.dedupe_peers(rows, self_key="eu")
    assert [e["key"] for e in out] == ["asia", "amsterdam"]
    assert out[0]["tag"] == "good"


def test_self_entry_from_the_environment(monkeypatch):
    monkeypatch.setenv("REGISTRY_NAME", "EU")
    monkeypatch.setenv("PUBLIC_UI_URL", "https://theprotocol.cloud")
    monkeypatch.setenv("PUBLIC_URL", "https://eu.theprotocol.cloud")
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "eu.theprotocol.cloud")
    monkeypatch.setenv("FRAME_CURRENCY", "ecu")
    monkeypatch.delenv("MINTING_AUTHORITY", raising=False)
    from agentvault_registry.config import settings
    monkeypatch.setattr(settings, "BASE_URL", "https://eu.theprotocol.cloud", raising=False)
    me = fv.self_entry({"identity": {"tier": "sovereign-mainframe", "display_name": "EU"},
                        "visual": {"theme": "neural", "icon_url": "/static/registry-cards/eu/icon.png"}})
    assert me["key"] == "eu" and me["role"] == fv.ROLE_FRAME and me["currency"] == "ECU"
    assert me["public_url"] == "https://eu.theprotocol.cloud" and me["console_url"] == "https://theprotocol.cloud"
    assert me["ledger_ws"] == "wss://eu.theprotocol.cloud/ws/events"     # the PUBLIC host, never the apex console
    assert me["icon_url"] == "https://eu.theprotocol.cloud/static/registry-cards/eu/icon.png"


def test_an_operator_self_has_no_ledger_of_its_own(monkeypatch):
    monkeypatch.setenv("REGISTRY_NAME", "amsterdam")
    monkeypatch.setenv("MINTING_AUTHORITY", "disabled")
    monkeypatch.setenv("PUBLIC_URL", "https://amsterdam.op.theprotocol.cloud")
    monkeypatch.delenv("PUBLIC_UI_URL", raising=False)
    from agentvault_registry.config import settings
    monkeypatch.setattr(settings, "BASE_URL", "http://localhost:8000", raising=False)
    me = fv.self_entry({})
    assert me["role"] == fv.ROLE_OPERATOR and me["ledger_ws"] is None
    assert me["console_url"] == "https://amsterdam.op.theprotocol.cloud"


async def test_build_manifest_assembles_eus_view(monkeypatch):
    """EU's view of the live cluster: ASIA a frame, amsterdam its own operator, hochiminh ASIA's (a `discovered` row),
    a row named after EU itself (a fan-out echo) dropped; two frames = multi_frame."""
    monkeypatch.setenv("REGISTRY_NAME", "EU")
    monkeypatch.setenv("PUBLIC_UI_URL", "https://theprotocol.cloud")
    monkeypatch.setenv("PUBLIC_URL", "https://eu.theprotocol.cloud")
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "eu.theprotocol.cloud")
    monkeypatch.setenv("FRAME_CURRENCY", "ECU")
    monkeypatch.delenv("MINTING_AUTHORITY", raising=False)
    from agentvault_registry.config import settings
    monkeypatch.setattr(settings, "BASE_URL", "https://eu.theprotocol.cloud", raising=False)

    async def own(db):
        return {"visual": {"theme": "neural"}, "operator": {"display_name": "EU"}}

    async def peers(db, redis=None):
        rows = [
            fv.entry_from_card(ASIA, name="asia", base_url="https://asia.theprotocol.cloud:8443", peer_type="frame",
                               verified=True),
            fv.entry_from_card(AMS, name="amsterdam", base_url="https://amsterdam.op.theprotocol.cloud:8443",
                               peer_type="cloud_operator", verified=True),
            fv.entry_from_card(HCM, name="hochiminh", base_url="https://hochiminh.op.theprotocol.cloud:8443",
                               peer_type="discovered", verified=True),
            {"key": "eu", "role": "frame", "verified": True},
        ]
        rows[0] = fv.merge_peer_manifest(rows[0], {"console_url": "https://asia.theprotocol.cloud",
                                                   "currency_name": "Asian Compute Unit"})
        return rows

    monkeypatch.setattr(fv, "_own_card_subset", own)
    monkeypatch.setattr(fv, "active_peer_entries", peers)
    m = await fv.build_manifest(None, None, use_cache=False)
    assert m["manifest_version"] == 1 and m["multi_frame"] is True
    assert m["self"]["key"] == "eu" and m["self"]["console_url"] == "https://theprotocol.cloud"
    keys = [p["key"] for p in m["peers"]]
    assert keys == ["asia", "amsterdam", "hochiminh"]                      # frames first, never self
    by = {p["key"]: p for p in m["peers"]}
    assert by["asia"]["currency_name"] == "Asian Compute Unit"
    assert by["hochiminh"]["parent"] == "asia" and by["amsterdam"]["parent"] == "eu"
    assert by["amsterdam"]["ledger_ws"] == "wss://eu.theprotocol.cloud/ws/events"
    origins = fv.manifest_origins(m)
    assert "https://theprotocol.cloud" in origins and "https://asia.theprotocol.cloud" in origins
    assert "https://hochiminh.op.theprotocol.cloud" in origins


@pytest.mark.parametrize("override,base,want", [
    ("localhost:8350", "https://eu.theprotocol.cloud", "eu.theprotocol.cloud"),        # the template's value: refused
    ("127.0.0.1:8150", "https://sandbox-a.theprotocol.cloud", "sandbox-a.theprotocol.cloud"),
    ("registry-a:8000", "https://eu.theprotocol.cloud", "eu.theprotocol.cloud"),        # a container name: refused
    ("ws.example.org", "https://eu.theprotocol.cloud", "ws.example.org"),               # a public override stands
    ("", "https://asia.theprotocol.cloud", "asia.theprotocol.cloud"),
    ("", "http://localhost:8000", "api.theprotocol.cloud"),                             # the baked default: refused
])
def test_the_operator_ledger_lane_host_is_public(monkeypatch, override, base, want):
    """§FEFRAME W2: services/cloud_provisioner._frame_ws_events_host (the provisioner AND the renamer write it into
    every operator vhost's /ws/events). The template's localhost:<registry port> made all six lanes 502."""
    from agentvault_registry.services import cloud_provisioner as cp
    monkeypatch.setenv("WS_EVENTS_PROXY_HOST", override)
    monkeypatch.setenv("BASE_URL", base)
    assert cp._frame_ws_events_host() == want


@pytest.mark.parametrize("name,key", [("EU", "eu"), ("eu", "eu"), ("Sandbox Beta", "sandbox-beta"),
                                      ("  ASIA ", "asia"), ("op_frame--x", "op-frame-x"), ("", "")])
def test_one_key_rule_for_every_spelling(name, key):
    """Peer rows spell one registry several ways (2026-10-01: 'EU' on amsterdam, 'eu' on shenzhen, 'Sandbox Beta' on
    sbxalphaop): the key is derived by one rule on every side, so a peer's key equals its own self key."""
    assert fv.key_of(name) == key


def test_a_self_echo_spelled_differently_is_still_dropped():
    rows = [{"key": fv.key_of("Sandbox Alpha"), "verified": True, "role": "frame"},
            {"key": fv.key_of("sbxbetaop"), "verified": True, "role": "operator"}]
    out = fv.dedupe_peers(rows, self_key=fv.key_of("Sandbox Alpha"))
    assert [e["key"] for e in out] == ["sbxbetaop"]


def test_an_operator_names_itself_as_its_card_does(monkeypatch):
    """2026-10-01 on the sandbox (V0503): sbxalphaop's REGISTRY_NAME is its container label `cloud-op-sbxalphaop`, its card
    and every peer row say `sbxalphaop`. The self entry follows the card (REGISTRY_FEDERATION_NAME first), so its key is
    the key its parent lists it under. Control: without the federation name the label would be the key."""
    monkeypatch.setenv("REGISTRY_NAME", "cloud-op-sbxalphaop")
    monkeypatch.setenv("REGISTRY_FEDERATION_NAME", "sbxalphaop")
    monkeypatch.setenv("MINTING_AUTHORITY", "disabled")
    monkeypatch.setenv("PUBLIC_URL", "https://sbxalphaop.op.theprotocol.cloud")
    me = fv.self_entry({})
    assert me["key"] == "sbxalphaop" and me["name"] == "sbxalphaop" and me["display_name"] == "sbxalphaop"
    monkeypatch.delenv("REGISTRY_FEDERATION_NAME")
    assert fv.self_entry({})["key"] == "cloud-op-sbxalphaop"


def test_the_display_name_is_the_cards_not_the_operator_persona():
    subset = {"display_name": "Sandbox Alpha", "operator": {"display_name": "TheProtocol Sandbox"}}
    assert fv._self_display_card(subset)["identity"]["display_name"] == "Sandbox Alpha"
    # no top-level display name: the builder falls back to the federation name, never the persona
    assert "display_name" not in fv._self_display_card({"operator": {"display_name": "TheProtocol Sandbox"}})["identity"]


def test_a_self_echo_under_another_name_is_dropped_by_host():
    rows = [{"key": "sbxalphaop", "verified": True, "role": "operator", "public_url": "https://sbxalphaop.op.theprotocol.cloud"},
            {"key": "sandbox-alpha", "verified": True, "role": "frame", "public_url": "https://sandbox-a.theprotocol.cloud"}]
    out = fv.dedupe_peers(rows, self_key="cloud-op-sbxalphaop", self_host="sbxalphaop.op.theprotocol.cloud")
    assert [e["key"] for e in out] == ["sandbox-alpha"]
    # control: without the host the echo survives (the V0503 sandbox reading)
    assert len(fv.dedupe_peers(rows, self_key="cloud-op-sbxalphaop")) == 2
