"""The TLS trust context must not be gated on the EventStore's URL scheme.

§XFRAMEMTLS (2026-09-04). `_build_es_ssl_context` returned None whenever
`EVENT_STORE_URL` was not https/wss. But `get_httpx_verify()` — which wraps it —
is the verify argument for a dozen-plus callers that never touch the EventStore:
the TEG client, the token bridge, the federation blocklist, operator
self-service, balance reconciliation, developers, flare shop, admin agents. On a
frame whose ES is reached over INTERNAL plain HTTP (`http://<frame>-event-store:8200`,
which is exactly what the frame-test template configures and is correct for a
single-host frame) every one of them silently fell back to the system CA store
and could no longer verify a SPIRE-served peer.

Measured: a cross-registry transfer between the two sandbox frames answered
503 "FX pool: reserve read failed: [SSL: CERTIFICATE_VERIFY_FAILED] unable to
get local issuer certificate". The federation's core money rail, dead, because a
shared TLS helper was keyed on ONE caller's URL scheme. Every cloud operator has
an https ES URL and so never showed it — the defect was invisible until a frame
with an internal ES tried to speak mTLS outward.

These tests need no certificates: the bug was the EARLY RETURN, and its absence
is observable without any SVID material.
"""
import importlib

import pytest


def _fresh(monkeypatch, es_url: str, cert_dir: str):
    """Re-evaluate the builder with a given ES URL, and no cached context."""
    from agentvault_registry import es_ssl_helper as H
    monkeypatch.setenv("EVENT_STORE_URL", es_url)
    monkeypatch.setenv("SVID_CERT_DIR", cert_dir)
    monkeypatch.setattr(H, "_CACHED_CTX", None, raising=False)
    monkeypatch.setattr(H, "_CACHED_STAMP", (), raising=False)
    return H._build_es_ssl_context()


@pytest.mark.parametrize("es_url", [
    "http://sbx-alpha-event-store:8200",    # ← the frame-test template's value
    "https://nginx-event-store:8443",       # ← registry-a's value
    "wss://nginx-event-store:8443",
    "",                                      # unset entirely
])
def test_context_is_built_regardless_of_event_store_scheme(monkeypatch, tmp_path, es_url):
    """A context is produced for every ES URL shape, including plain HTTP.

    Before the fix, the first and last parameters returned None — and None means
    `get_httpx_verify()` hands httpx a bare True, i.e. system CAs only and no
    SPIRE anchors, for every unrelated caller on that node.
    """
    ctx = _fresh(monkeypatch, es_url, str(tmp_path))
    assert ctx is not None, (
        f"EVENT_STORE_URL={es_url!r} suppressed the trust context; every non-ES "
        f"caller on this node loses its SPIRE anchors")


def test_the_context_still_carries_public_roots(monkeypatch, tmp_path):
    """Public HTTPS callers must keep working — CONSUL fetches public peer URLs.

    With no SPIRE bundle on disk the context is the system store, which is what a
    certless node had before via `verify=True`. So the change cannot break a node
    that has no SVID material: it gets an equivalent context instead of None.
    """
    ctx = _fresh(monkeypatch, "http://es:8200", str(tmp_path))
    assert ctx is not None
    assert len(ctx.get_ca_certs()) > 0, "system CA roots missing from the context"
