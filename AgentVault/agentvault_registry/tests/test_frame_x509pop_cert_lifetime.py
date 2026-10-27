"""§MCPTEST30 (V0550): a new frame's x509pop attestation CA and agent certificate outlive the frame.

They were signed for 30 days (a lifetime for frames torn down after a test), and long-lived frames were stood up with it:
sbx-alpha's and sbx-beta's expire 2026-10-03, EU's and ASIA's 2026-10-07 (measured 2026-10-02, agentvault2-15). A SPIRE
agent that must attest again after that is refused. New frames: the CA ten years, the agent certificate two, each
overridable, and the CA never shorter than the certificate it signs.
"""
from __future__ import annotations

import inspect

from agentvault_registry.services import frame_test_provisioner as ftp


def test_the_defaults_outlive_a_long_lived_frame(monkeypatch):
    monkeypatch.delenv("FRAME_X509POP_CA_DAYS", raising=False)
    monkeypatch.delenv("FRAME_X509POP_AGENT_DAYS", raising=False)
    assert ftp.x509pop_cert_days() == (3650, 730)


def test_overrides_and_their_guards(monkeypatch):
    monkeypatch.setenv("FRAME_X509POP_CA_DAYS", "30")
    monkeypatch.setenv("FRAME_X509POP_AGENT_DAYS", "90")
    assert ftp.x509pop_cert_days() == (90, 90), "the CA never expires before the certificate it signed"
    monkeypatch.setenv("FRAME_X509POP_CA_DAYS", "not-a-number")
    monkeypatch.setenv("FRAME_X509POP_AGENT_DAYS", "0")
    assert ftp.x509pop_cert_days() == (3650, 1)


def test_the_openssl_script_uses_them_and_no_literal_lifetime():
    src = inspect.getsource(ftp.generate_spire_x509pop_certs)
    assert "-days {ca_days}" in src and "-days {agent_days}" in src
    assert "-days 30 " not in src and "-days 30 -sha256" not in src
