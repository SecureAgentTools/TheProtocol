"""§MTLSGAP — the console reads the federated index THROUGH the registry, over mTLS.

Before this the console reached the index over a hand-added `location /directory/ { proxy_pass
http://127.0.0.1:8600/; }` — plain http on loopback, no identity at either end, on a fleet where
TEG and federation run `ssl_verify_client on`. The index is the one component that AGGREGATES every
frame's cards and `DISCOVERY_VIA_DIRECTORY` means registries RENDER what it returns, so an
unauthenticated index is a place to inject.

What these pin is the part that is easy to get subtly wrong and impossible to see from outside:
the verify chooser (§FABRICVERIFY — a chooser that looks right and fails one whole population),
the fixed target (this is a proxy, not a relay), and the refusal SHAPE (a lane that swallows an
error renders an empty index, which reads to a person as "nobody is out there").
"""
import os

import pytest

from agentvault_registry.routers import public_directory as pd


def test_the_target_is_server_side_and_nothing_in_a_request_can_change_it(monkeypatch):
    """A FIXED-TARGET PROXY, NOT A RELAY. The upstream comes from env and from nowhere else."""
    monkeypatch.setenv("DIRECTORY_MTLS_URL", "https://directory-nginx:8443")
    assert pd._upstream() == "https://directory-nginx:8443"
    src = open(pd.__file__).read()
    # the only place a URL is built is from _upstream(); no request field may reach httpx
    assert 'client.post(f"{up}/graphql"' in src
    assert "request.query_params" not in src and "request.headers.get(\"x-upstream\"" not in src


def test_a_trailing_slash_cannot_produce_a_double_slash(monkeypatch):
    monkeypatch.setenv("DIRECTORY_MTLS_URL", "https://directory-nginx:8443/")
    assert pd._upstream() == "https://directory-nginx:8443"


def test_unconfigured_is_a_named_refusal_not_a_crash(monkeypatch):
    monkeypatch.delenv("DIRECTORY_MTLS_URL", raising=False)
    assert pd._upstream() == ""


class _Cfg:
    """Stands in for svid_client, which is a singleton a fresh process holds UNINITIALISED
    (§V0221's lesson — a probe that reads it measures itself)."""
    def __init__(self, cfg): self.cfg = cfg
    def get_client_cert_config(self, url): return self.cfg


def _with_svid(monkeypatch, cfg):
    """⚠ PATCH THE PACKAGE ATTRIBUTE, WHICH IS THE INSTANCE.

    The first version of this helper patched `agentvault_registry.identity.svid_client` THE MODULE
    and the first version of the code read the module's attribute — so test and code agreed with
    each other and neither matched how the app imports the singleton (`from ..identity import
    svid_client`, which every other caller uses). Seven tests passed against a route that could
    never present a certificate; the live wiring found it in one read, because the route's own
    warning names what the no-SVID path IS. A fixture written from the same assumption as the code
    tests the assumption, not the code.
    """
    import agentvault_registry.identity as identity_pkg
    monkeypatch.setattr(identity_pkg, "svid_client", _Cfg(cfg), raising=False)


def test_the_svid_is_presented_when_there_is_one(monkeypatch):
    _with_svid(monkeypatch, {"cert": ("/certs/svid.0.pem", "/certs/svid.0.key"),
                             "verify": "/certs/bundle.0.pem"})
    kw = pd._client_kwargs("https://directory-nginx:8443")
    assert kw["cert"] == ("/certs/svid.0.pem", "/certs/svid.0.key")
    assert kw["verify"] == "/certs/bundle.0.pem", "a fabric name verifies against the SPIRE bundle"


def test_no_svid_still_makes_the_call_and_says_so(monkeypatch, caplog):
    """UNKNOWN IS NOT EMPTY. An index the console cannot read is worse than one read without a
    certificate — but the far side runs `ssl_verify_client on`, so the log has to name what this
    path IS: what a refusal will look like."""
    _with_svid(monkeypatch, None)
    with caplog.at_level("WARNING"):
        kw = pd._client_kwargs("https://directory-nginx:8443")
    assert "cert" not in kw
    assert any("WITHOUT a client SVID" in r.message for r in caplog.records)


def test_the_refusals_are_graphql_shaped(monkeypatch):
    """A GraphQL client parses `errors[]`. A refusal that is not that shape becomes an empty list
    on screen, which tells the reader "nobody is out there" — a different sentence entirely."""
    src = open(pd.__file__).read()
    for msg in ("no federated index is configured on this registry",
                "the federated index is unreachable",
                "query too large"):
        assert f'"errors":[{{"message":"{msg}"}}]' in src.replace("'", '"'), msg


def test_the_body_is_capped():
    """256 KB: a GraphQL query with variables is a few KB, and this rail is unauthenticated."""
    assert pd._MAX_BODY == 256 * 1024


def test_it_uses_the_same_import_every_other_caller_uses():
    """THE REGRESSION. `agentvault_registry.identity` exports the svid_client INSTANCE; reaching
    for `<module>.svid_client` raises AttributeError and the route silently dials with no
    certificate. Pinned as a source fact because the behaviour is only visible against a real
    gateway that verifies clients."""
    src = open(pd.__file__).read()
    assert "from agentvault_registry.identity import svid_client" in src
    assert "_svid.svid_client" not in src, "the module-attribute form is the bug"


def test_a_wiring_fault_is_reported_louder_than_a_posture(monkeypatch, caplog):
    """"the SVID client has no config" is a posture; "I could not even ask it" is a defect. They
    must not read the same, or the next one hides for as long as this one did."""
    import agentvault_registry.identity as identity_pkg

    class _Broken:
        def get_client_cert_config(self, url):
            raise AttributeError("boom")

    monkeypatch.setattr(identity_pkg, "svid_client", _Broken(), raising=False)
    with caplog.at_level("WARNING"):
        pd._client_kwargs("https://directory-nginx:8443")
    assert any("WIRING fault" in r.message for r in caplog.records)
