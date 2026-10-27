"""§TWOAGENT (V0438, 2026-09-23) — a cloud operator names itself in cross-registry chat.

Measured on V0437: with CHAT_FEDERATION_ENABLED on, sbxalphaop's `/chat/federation/status` answered `enabled: true,
host_base_url: ""`, and sbx-beta refused its deliveries with 422. `chat_federation.self_base_url()` read PUBLIC_BASE_URL,
then BASE_URL, then REGISTRY_SELF_URL, and a cloud operator is provisioned with none of them (it carries PUBLIC_URL;
BASE_URL is withheld on purpose, §V0160). Every envelope it sent named no host and every remote key it minted read `x@`.
V0437 shipped with PUBLIC_BASE_URL set by the roll driver on all six operators as the workaround; this is the source fix,
so the next operator provisioned needs no hand-carried variable. It reads the one request-free reader of this node's
public address (`core.public_url.public_base_url_static`), rejects a loopback at every step, and answers in
`public_form`, the only form a peer keys us by. Measured before the change on all ten running registries: the answer it
gives equals the one each already gives, the operators' included (their PUBLIC_URL and PUBLIC_BASE_URL name one host).

Found beside it: `public_form` tested the scheme case-sensitively, so `HTTPS://peer` parsed as the host `https` and
answered "" (a peer row so spelled was no peer, and a PUBLIC_BASE_URL so spelled named nobody).

RED on 6e04fbb3 (V0437): all but the control.
"""
from __future__ import annotations

import os
import types

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@localhost:5432/ci")
os.environ.setdefault("API_KEY_SECRET", "ci-dummy-secret-0123456789abcdef")

import pytest


@pytest.fixture
def operator_env(monkeypatch):
    """An operator as provisioned: PUBLIC_URL (here with its external mTLS port), the image's baked BASE_URL default,
    no PUBLIC_BASE_URL, no REGISTRY_SELF_URL (the measured env of the six operators before V0437's workaround)."""
    from agentvault_registry.config import settings
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("BASE_URL", raising=False)
    monkeypatch.delenv("REGISTRY_SELF_URL", raising=False)
    monkeypatch.setattr(settings, "BASE_URL", "http://localhost:8000", raising=False)
    monkeypatch.setenv("PUBLIC_URL", "https://op-x.example:27543")
    return monkeypatch


def test_an_operator_names_itself_by_the_public_url_it_carries(operator_env):
    from agentvault_registry.services import chat_federation as fed
    assert fed.self_base_url() == "https://op-x.example"
    assert fed.remote_key("Alice", fed.self_base_url()) == "alice@https://op-x.example"


def test_the_envelope_an_operator_sends_names_its_host(operator_env):
    from agentvault_registry.services import chat_federation as fed
    conv = types.SimpleNamespace(id="c1", kind="dm", title=None)
    msg = types.SimpleNamespace(id="m1", seq=1, kind="text", body="hi", card=None, client_ref=None, created_at=None,
                                sender_ptype="agent", sender_id="did:theprotocol:op-x:0001")
    env = fed.message_envelope(conv, msg, "Agent", [])
    assert env["host_registry"] == "https://op-x.example"
    assert env["message"]["sender"]["registry"] == "https://op-x.example"


def test_a_loopback_is_never_the_answer(operator_env):
    """REGISTRY_SELF_URL is the in-container dispatch address on most nodes; a peer cannot reach it."""
    from agentvault_registry.services import chat_federation as fed
    operator_env.delenv("PUBLIC_URL", raising=False)
    operator_env.setenv("REGISTRY_SELF_URL", "http://localhost:8000")
    assert fed.self_base_url() == ""
    operator_env.setenv("PUBLIC_BASE_URL", "http://127.0.0.1:8360")
    assert fed.self_base_url() == ""


def test_control_the_explicit_knob_and_a_frames_base_url_are_unchanged(monkeypatch):
    """Passes on both trees: what a frame and a hand-configured node answer today."""
    from agentvault_registry.config import settings
    from agentvault_registry.services import chat_federation as fed
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("REGISTRY_SELF_URL", raising=False)
    monkeypatch.setenv("BASE_URL", "https://eu.theprotocol.cloud")
    monkeypatch.setattr(settings, "BASE_URL", "https://eu.theprotocol.cloud", raising=False)
    assert fed.self_base_url() == "https://eu.theprotocol.cloud"
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://sandbox-a.theprotocol.cloud")
    assert fed.self_base_url() == "https://sandbox-a.theprotocol.cloud"


def test_a_scheme_in_capitals_is_the_same_address():
    from agentvault_registry.services import chat_federation as fed
    assert fed.public_form("HTTPS://Peer.Example:8443/") == "https://peer.example"
    assert fed.public_form("Http://Peer.Example") == "http://peer.example"


async def test_a_peer_row_spelled_in_capitals_is_a_peer():
    from agentvault_registry.services import chat_federation as fed

    class _Db:
        async def execute(self, stmt, params=None):
            return types.SimpleNamespace(all=lambda: [("peer-one", "HTTPS://Peer.Example:8443"),
                                                      ("peer-two", "https://two.example")])

    peers = await fed.peer_base_urls(_Db())
    assert peers == {"https://peer.example": "peer-one", "https://two.example": "peer-two"}
