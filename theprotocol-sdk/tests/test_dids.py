"""0.7.5: agent DIDs that name their frame (did:theprotocol:<issuer>:<uuid4>), and every older shape unchanged."""
import logging

import pytest

from theprotocol.bridges.anp import ANPBridge, KeyPair, did_wba_from_cos, native_did_from_wba
from theprotocol.bridges.anp.did_wba import did_cos_from_wba
from theprotocol.dids import did_from_spiffe_path, split_agent_did, valid_issuer
from theprotocol.payment.authenticator import A2AAuthenticator, _did_from_spiffe_id

U = "3f1c2a9e-8b4d-4e2f-9a61-5d7e0c4b2a18"
ISSUER_DID = f"did:theprotocol:eu.theprotocol.cloud:{U}"


def test_split_agent_did_reads_the_issuer():
    assert split_agent_did(ISSUER_DID) == ("theprotocol", "eu.theprotocol.cloud", U)
    assert split_agent_did(f"did:theprotocol:{U}") == ("theprotocol", None, U)
    # a reserved second segment is a system DID, never an issuer
    assert split_agent_did(f"did:theprotocol:treasury:{U}") == ("theprotocol", None, f"treasury:{U}")
    assert not valid_issuer("treasury") and valid_issuer("asia.theprotocol.cloud")


def test_issuer_did_maps_to_the_did_wba_a_registry_recognises():
    # the registry's ANP middleware maps did:wba:<x> to did:theprotocol:<x>: the prefix swap
    assert did_wba_from_cos(ISSUER_DID) == f"did:wba:eu.theprotocol.cloud:{U}"
    assert native_did_from_wba(f"did:wba:eu.theprotocol.cloud:{U}") == ISSUER_DID


def test_every_older_shape_maps_as_before():
    assert did_wba_from_cos("did:cos:abc-123") == "did:wba:api.theprotocol.cloud:agents:abc-123"
    assert did_cos_from_wba("did:wba:api.theprotocol.cloud:agents:abc-123") == "did:cos:abc-123"
    assert native_did_from_wba("did:wba:api.theprotocol.cloud:agents:abc-123") == "did:cos:abc-123"
    assert native_did_from_wba("did:wba:other.domain:agents:abc-123") is None
    assert did_wba_from_cos(f"did:theprotocol:treasury:{U}").startswith("did:wba:api.theprotocol.cloud:agents:")


def test_anp_bridge_carries_the_issuer_did():
    bridge = ANPBridge(agent_did_cos=ISSUER_DID, keypair=KeyPair.generate(), domain="eu.theprotocol.cloud")
    assert bridge.did_wba == f"did:wba:eu.theprotocol.cloud:{U}"
    assert bridge.did_document.to_dict()["id"] == bridge.did_wba


def test_spiffe_path_restores_the_issuer_colon():
    path = f"did-theprotocol-eu.theprotocol.cloud-{U}"
    assert did_from_spiffe_path(path) == ISSUER_DID
    sid = f"spiffe://eu.theprotocol.cloud/agent/{path}"
    assert _did_from_spiffe_id(sid, "eu.theprotocol.cloud") == ISSUER_DID


def test_spiffe_path_older_shapes_unchanged():
    assert _did_from_spiffe_id("spiffe://agentvault.com/agent/did-theprotocol-4c783710-64d5-f8c3-3f6c",
                               "agentvault.com") == "did:theprotocol:4c783710-64d5-f8c3-3f6c"
    assert did_from_spiffe_path(f"did-theprotocol-{U}") == f"did:theprotocol:{U}"
    assert _did_from_spiffe_id(f"spiffe://other.td/agent/did-theprotocol-{U}", "eu.theprotocol.cloud") is None


@pytest.fixture
def quiet_env(monkeypatch):
    for k in ("THEPROTOCOL_TRUST_DOMAIN", "REGISTRY_URL", "EVENT_STORE_WS_URL"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_trust_domain_from_the_environment(quiet_env):
    quiet_env.setenv("THEPROTOCOL_TRUST_DOMAIN", "eu.theprotocol.cloud,asia.theprotocol.cloud")
    auth = A2AAuthenticator(auto_jwt_verifier=False)
    assert auth.trusted_domains == ["eu.theprotocol.cloud", "asia.theprotocol.cloud"]


def test_an_explicit_trust_domain_beats_the_environment(quiet_env):
    quiet_env.setenv("THEPROTOCOL_TRUST_DOMAIN", "asia.theprotocol.cloud")
    auth = A2AAuthenticator(trust_domain="eu.theprotocol.cloud", auto_jwt_verifier=False)
    assert auth.trusted_domains == ["eu.theprotocol.cloud"]


def test_no_trust_domain_keeps_the_old_default_and_says_so(quiet_env, caplog):
    with caplog.at_level(logging.WARNING):
        auth = A2AAuthenticator(auto_jwt_verifier=False)
    assert auth.trusted_domains == ["agentvault.com"]
    assert "THEPROTOCOL_TRUST_DOMAIN" in caplog.text
