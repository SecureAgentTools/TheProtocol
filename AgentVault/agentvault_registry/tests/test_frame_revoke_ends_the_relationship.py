"""§F6 WP6.2 (2026-09-26): a frame revoke ends the SPIRE federation RELATIONSHIP with the peer, then deletes its bundle.

Before this a revoke deleted the bundle alone and left the relationship on both sides: the WP6.1 proof measured it on the
throwaway f6proof and sbx-beta (`federation list` still named each other after the revoke; the teardown had to delete
sbx-beta's host-side). While a relationship stands, the server's refresher keeps asking the peer's bundle endpoint for a
bundle it may import again. Both routes are pinned (FRAME_TRUST_SPIRE_VIA local and runner), and only SPIRE's own
"federation relationship not found" reads as already gone.
"""
import asyncio

import pytest

from agentvault_registry.routers import frame_invitations as fi
from agentvault_registry.services import frame_trust_manager as ftm
from agentvault_registry.services import spire_ops_client as soc

NOT_FOUND = 'Error: failed to delete federation relationship "p.example.org": federation relationship not found'


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    """asyncio.run() closes its loop and leaves the thread with none; the NEXT file's get_event_loop() would raise."""
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def _manager():
    return ftm.FrameTrustManager(spire_container="x-spire-server", local_trust_domain="x.example.org")


@pytest.fixture
def local_spire(monkeypatch):
    monkeypatch.delenv(soc.TRUST_VIA_ENV, raising=False)
    seen, answers = [], {}

    async def fake_exec(container, cmd, *, timeout=0, stdin_data=None):
        seen.append((container, list(cmd)))
        return answers.get(tuple(cmd[1:3]), (0, "ok", ""))
    monkeypatch.setattr(ftm, "_run_docker_exec", fake_exec)
    return seen, answers


@pytest.fixture
def runner_spire(monkeypatch):
    monkeypatch.setenv(soc.TRUST_VIA_ENV, "runner")
    calls, answers = [], {}

    def fake_call(op, *, timeout=30.0, **fields):
        calls.append((op, fields))
        a = answers.get(op, {"rc": 0, "stdout": "ok", "stderr": ""})
        if isinstance(a, Exception):
            raise a
        return a

    async def no_docker(*a, **k):
        raise AssertionError("the docker path was taken in runner mode")
    monkeypatch.setattr(soc, "call", fake_call)
    monkeypatch.setattr(ftm, "_run_docker_exec", no_docker)
    return calls, answers


def test_the_relationship_delete_is_one_exact_argv_on_the_local_route(local_spire):
    seen, _ = local_spire
    res = asyncio.run(_manager().delete_federation_relationship("spiffe://P.example.org/"))
    assert res.ok, res.message
    assert seen == [("x-spire-server", [ftm.SPIRE_BIN_PATH, "federation", "delete", "-id", "spiffe://p.example.org"])]


def test_the_relationship_delete_is_one_runner_op_on_the_runner_route(runner_spire):
    calls, _ = runner_spire
    assert asyncio.run(_manager().delete_federation_relationship("p.example.org")).ok
    assert calls == [("spire_federation_delete", {"trust_domain": "p.example.org"})]


def test_only_spires_own_not_found_reads_as_already_gone(runner_spire):
    calls, answers = runner_spire
    answers["spire_federation_delete"] = {"rc": 1, "stdout": "", "stderr": NOT_FOUND}
    assert asyncio.run(_manager().delete_federation_relationship("p.example.org")).ok
    # a refusal that happens to contain "not found" is a failure, never "already gone"
    answers["spire_federation_delete"] = soc.SpireOpsUnavailable("the frame runner refused it: project not found")
    res = asyncio.run(_manager().delete_federation_relationship("p.example.org"))
    assert not res.ok and "project not found" in res.message
    answers["spire_federation_delete"] = {"rc": 1, "stdout": "", "stderr": "Error: rpc error: code = Unavailable"}
    assert not asyncio.run(_manager().delete_federation_relationship("p.example.org")).ok


def test_the_frames_own_trust_domain_is_never_deleted(runner_spire):
    calls, _ = runner_spire
    for td in ("x.example.org", "spiffe://x.example.org", ""):
        assert not asyncio.run(_manager().delete_federation_relationship(td)).ok
    assert calls == []


def test_a_revoke_ends_the_relationship_before_the_bundle(runner_spire):
    calls, _ = runner_spire
    relationship, bundle = asyncio.run(fi.revoke_spire_federation(_manager(), "p.example.org"))
    assert relationship.ok and bundle.ok
    assert [c[0] for c in calls] == ["spire_federation_delete", "spire_bundle_delete"]
    assert calls[1][1] == {"mode": "dissociate", "trust_domain": "p.example.org"}


def test_a_failed_relationship_delete_still_deletes_the_bundle_and_says_so(runner_spire):
    calls, answers = runner_spire
    answers["spire_federation_delete"] = soc.SpireOpsUnavailable("the frame runner refused it: not the calling frame")
    relationship, bundle = asyncio.run(fi.revoke_spire_federation(_manager(), "p.example.org"))
    assert not relationship.ok and "not the calling frame" in relationship.message
    assert bundle.ok and [c[0] for c in calls] == ["spire_federation_delete", "spire_bundle_delete"]


def test_the_route_reports_both_halves():
    import inspect
    src = inspect.getsource(fi.revoke_frame_federation)
    assert "revoke_spire_federation(" in src and "remove_peer_bundle(" not in src
    assert src.count('"spire_relationship_remove_ok": relationship.ok') == 2    # the event and the answer
