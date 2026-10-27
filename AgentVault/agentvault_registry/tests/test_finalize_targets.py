"""§BATCH9 (2026-09-06, §BATCH7 residue) — the bilateral finalize callback dialed the initiator's
mTLS gateway certless and unverified (400 on every standup). It now dials in two legs: the gateway
with OUR SVID, then the initiator's public url with public roots — and the public url is the gateway
url with its port stripped, never a guess."""
import types

from agentvault_registry.routers import frame_invitations as fi


def _inv(url):
    return types.SimpleNamespace(id="inv-1", initiator_federation_endpoint_url=url)


def test_public_url_is_the_gateway_without_its_port():
    assert fi._public_url_from_federation_url("https://juice.example.test:8443/") == "https://juice.example.test"
    assert fi._public_url_from_federation_url("https://juice.example.test") == "https://juice.example.test"


def test_legs_when_the_svid_is_loaded(monkeypatch):
    import agentvault_registry.identity.svid_client as sc
    monkeypatch.setattr(sc, "get_client_cert_config", lambda target_url="": {"cert": ("/tmp/c.pem", "/tmp/k.pem")}, raising=False)
    legs = fi._finalize_targets(_inv("https://brrr.example.test:8443"))
    assert [l[0] for l in legs] == ["mtls", "public"]
    assert legs[0][1] == "https://brrr.example.test:8443/api/v1/federation/frame-invitations/inv-1/finalize"
    assert legs[0][2]["cert"] == ("/tmp/c.pem", "/tmp/k.pem") and legs[0][2]["verify"] is not False
    assert legs[1][1] == "https://brrr.example.test/api/v1/federation/frame-invitations/inv-1/finalize"
    assert legs[1][2] == {"verify": True}


def test_legs_without_an_svid_fall_to_the_public_url_only(monkeypatch):
    import agentvault_registry.identity.svid_client as sc
    monkeypatch.setattr(sc, "get_client_cert_config", lambda target_url="": None, raising=False)
    legs = fi._finalize_targets(_inv("https://brrr.example.test:8443"))
    assert [l[0] for l in legs] == ["public"] and legs[0][2] == {"verify": True}
    # a gateway url with no port: the public leg still exists and is never certless-unverified
    legs = fi._finalize_targets(_inv("https://brrr.example.test"))
    assert legs == [("public", "https://brrr.example.test/api/v1/federation/frame-invitations/inv-1/finalize", {"verify": True})]
