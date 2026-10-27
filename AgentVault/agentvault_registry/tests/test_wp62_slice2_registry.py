"""§F6 WP6.2 slice 2 (2026-09-26, his words "continue with wp6.2 slice 2 on the sandbox pair"): the registry's side.

  - CONTAINER_OBSERVE_VIA (local default | runner): the docker-stats collector and the operator health census read
    through the frame runner's containers_census / container_stats, fail closed, and keep today's answer unset.
  - OPERATOR_LIFECYCLE_VIA=runner: the operator revoke's SPIRE cascade is the runner's operator_revoke_spire; a PURGE
    teardown hands its host half to operator_purge, its SPIRE half to operator_revoke_spire, and its rows elsewhere to
    each peer frame's own API, and never runs psql in another frame's database or the docker socket.
  - POST /api/v1/federation/operators/{op}/purge-rows deletes only the caller's operator's rows, for an ACTIVE peer frame.
Every runner-mode test also proves the docker path was NOT taken (a fake docker module that raises when touched).
"""
import asyncio
import sys
import types

import pytest
from fastapi import HTTPException

from agentvault_registry import models
from agentvault_registry.routers import admin_health as ah
from agentvault_registry.routers import cloud_operators as co
from agentvault_registry.routers import federation_operator_purge as fop
from agentvault_registry.services import cloud_provisioner as cp
from agentvault_registry.services import host_observe as ho
from agentvault_registry.services import operator_revoker as orv
from agentvault_registry.services import spire_ops_client as soc


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    """asyncio.run() closes its loop and leaves the thread with none; the NEXT file's get_event_loop() would raise."""
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def _stats_doc(total=200, pre=100, system=1000, pre_system=500):
    return {"cpu_stats": {"cpu_usage": {"total_usage": total, "percpu_usage": [1, 2]}, "system_cpu_usage": system},
            "precpu_stats": {"cpu_usage": {"total_usage": pre}, "system_cpu_usage": pre_system},
            "memory_stats": {"usage": 5 * 1024 * 1024, "limit": 100 * 1024 * 1024},
            "networks": {"eth0": {"rx_bytes": 10, "tx_bytes": 20}},
            "blkio_stats": {"io_service_bytes_recursive": [{"op": "Read", "value": 7}, {"op": "Write", "value": 9}]}}


@pytest.fixture
def no_docker(monkeypatch):
    boom = types.ModuleType("docker")

    def _raise(*a, **k):
        raise AssertionError("the docker socket was touched on the runner route")
    boom.from_env = _raise
    boom.DockerClient = _raise
    monkeypatch.setitem(sys.modules, "docker", boom)
    monkeypatch.setattr(ah, "docker", boom, raising=False)
    return boom


@pytest.fixture
def runner_calls(monkeypatch):
    calls, answers = [], {}

    def fake_call(op, *, timeout=30.0, **fields):
        calls.append((op, fields))
        a = answers.get(op)
        if isinstance(a, Exception):
            raise a
        return a if a is not None else {}
    monkeypatch.setattr(soc, "call", fake_call)
    return calls, answers


# ── CONTAINER_OBSERVE_VIA ────────────────────────────────────────────────────────────────────────────────────────

def test_the_observe_flag_is_local_runner_or_refused(monkeypatch):
    monkeypatch.delenv(ho.OBSERVE_VIA_ENV, raising=False)
    assert ho.observe_via() == "local"
    monkeypatch.setenv(ho.OBSERVE_VIA_ENV, "Runner")
    assert ho.observe_via() == "runner"
    monkeypatch.setenv(ho.OBSERVE_VIA_ENV, "socket")
    with pytest.raises(ho.ObserveUnavailable, match="neither 'local' nor 'runner'"):
        ho.observe_via()


def test_census_and_stats_ask_one_op_and_fail_closed(runner_calls):
    calls, answers = runner_calls
    ho.census("sbxop")
    ho.stats()
    assert calls == [("containers_census", {"operator": "sbxop"}), ("container_stats", {})]
    answers["container_stats"] = soc.SpireOpsUnavailable("the frame runner refused container_stats: not a frame")
    with pytest.raises(ho.ObserveUnavailable, match="not a frame"):
        ho.stats()


def test_a_runner_row_reads_like_an_sdk_container():
    c = ho.RunnerContainer({"id": "0123456789abcdef", "name": "sbx-registry", "state": "running", "stats": _stats_doc()})
    assert (c.name, c.short_id, c.status) == ("sbx-registry", "0123456789", "running") and c.stats()["memory_stats"]
    bad = ho.RunnerContainer({"id": "x", "name": "sbx-db", "state": "running", "stats": None, "error": "daemon said no"})
    with pytest.raises(RuntimeError, match="daemon said no"):
        bad.stats()


def test_docker_stats_on_the_runner_route_is_this_frames_project_computed_the_same_way(monkeypatch, runner_calls, no_docker):
    calls, answers = runner_calls
    monkeypatch.setenv(ho.OBSERVE_VIA_ENV, "runner")
    answers["container_stats"] = {"containers": [
        {"id": "aaaaaaaaaaaa1", "name": "sbx-registry", "state": "running", "stats": _stats_doc()},
        {"id": "bbbbbbbbbbbb2", "name": "sbx-db", "state": "running", "stats": None, "error": "gone"}]}
    out = ah._collect_docker_stats_sync()
    assert calls == [("container_stats", {})]
    assert set(out["containers"]) == {"sbx-registry"} and out["container_count"] == 1
    assert out["source"].startswith("runner")
    # the view's own arithmetic, unchanged: the same numbers the SDK route computes from the same stats document
    sdk_like = types.SimpleNamespace(name="sbx-registry", short_id="aaaaaaaaaa", status="running",
                                     stats=lambda stream=False: _stats_doc())
    assert out["containers"]["sbx-registry"] == ah._stats_for_one_container(sdk_like)[1]


def test_docker_stats_unset_keeps_todays_answer(monkeypatch, runner_calls):
    calls, _ = runner_calls
    monkeypatch.delenv(ho.OBSERVE_VIA_ENV, raising=False)
    legacy = types.SimpleNamespace(name="agentvault-registry-a", short_id="cccccccccc", status="running",
                                   stats=lambda stream=False: _stats_doc())
    other = types.SimpleNamespace(name="eu-registry", short_id="dddddddddd", status="running",
                                  stats=lambda stream=False: _stats_doc())
    fake = types.ModuleType("docker")
    fake.from_env = lambda: types.SimpleNamespace(containers=types.SimpleNamespace(list=lambda **kw: [legacy, other]))
    monkeypatch.setattr(ah, "docker", fake, raising=False)
    out = ah._collect_docker_stats_sync()
    assert calls == [] and set(out["containers"]) == {"agentvault-registry-a"} and "source" not in out


def test_operator_health_census_on_the_runner_route(monkeypatch, runner_calls):
    calls, answers = runner_calls
    monkeypatch.setenv(ho.OBSERVE_VIA_ENV, "runner")
    monkeypatch.setattr(co.subprocess, "run", lambda *a, **k: pytest.fail("docker ps ran on the runner route"))
    answers["containers_census"] = {"containers": [
        {"name": "cloud-op-sbxop-registry", "status": "Up 1 hour (healthy)"},
        {"name": "cloud-op-sbxop-teg", "status": "Up 1 hour"}]}
    out = asyncio.run(co._operator_container_statuses("sbxop"))
    assert calls == [("containers_census", {"operator": "sbxop"})]
    assert out["registry"] == "Up 1 hour (healthy)" and out["teg"] == "Up 1 hour" and out["db"] == "not found"
    assert set(out) == set(co._HEALTH_SERVICES)
    answers["containers_census"] = soc.SpireOpsUnavailable("the frame runner refused containers_census: operator 'sbxop' "
                                                           "is not an operator of the calling frame sbx-alpha")
    out = asyncio.run(co._operator_container_statuses("sbxop"))
    assert set(out) == {"note"} and "not an operator of the calling frame" in out["note"]
    monkeypatch.setenv(ho.OBSERVE_VIA_ENV, "sometimes")
    assert "neither 'local' nor 'runner'" in asyncio.run(co._operator_container_statuses("sbxop"))["note"]


# ── the operator revoke ──────────────────────────────────────────────────────────────────────────────────────────

def test_revoke_on_the_runner_route_is_one_op_and_its_result(monkeypatch, runner_calls, no_docker):
    calls, answers = runner_calls
    monkeypatch.setenv(cp.OPERATOR_LIFECYCLE_VIA_ENV, "runner")
    answers["operator_revoke_spire"] = {"node": "spiffe://x/spire/agent/x509pop/" + "a" * 40, "node_listed": True,
                                        "banned": True, "entries_found": 4, "entries_deleted": 4, "evicted": True, "errors": []}
    r = orv.revoke_operator_spire("sbxop", "a" * 40)
    assert calls == [("operator_revoke_spire", {"operator": "sbxop", "fingerprint": "a" * 40})]
    assert (r.spire_agent_banned, r.spire_entries_deleted, r.spire_agent_evicted, r.errors) == (True, 4, True, [])


def test_revoke_refused_or_unlisted_is_an_error_never_the_socket(monkeypatch, runner_calls, no_docker):
    calls, answers = runner_calls
    monkeypatch.setenv(cp.OPERATOR_LIFECYCLE_VIA_ENV, "runner")
    answers["operator_revoke_spire"] = soc.SpireOpsUnavailable("the frame runner refused operator_revoke_spire: node "
                                                               "parents 3 identities outside /operator/sbxop/")
    r = orv.revoke_operator_spire("sbxop", "a" * 40)
    assert not r.spire_agent_banned and "outside /operator/sbxop/" in r.errors[0]
    answers["operator_revoke_spire"] = {"node": "n", "node_listed": False, "entries_found": 0, "entries_deleted": 0}
    r = orv.revoke_operator_spire("sbxop", "a" * 40)
    # §OPPROV: an unattested node is a FACT both halves report (a never-started operator has none), not an error
    assert r.node_listed is False and r.errors == [] and not r.spire_agent_banned
    monkeypatch.setenv(cp.OPERATOR_LIFECYCLE_VIA_ENV, "sidecar")
    r = orv.revoke_operator_spire("sbxop", "a" * 40)
    assert "neither 'local' nor 'runner'" in r.errors[0]


# ── the purge teardown ───────────────────────────────────────────────────────────────────────────────────────────

class _Result:
    def __init__(self, items):
        self._items = list(items)

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None

    def scalars(self):
        return self

    def first(self):
        return self._items[0] if self._items else None

    def all(self):
        return list(self._items)


class _Session:
    def __init__(self, answers):
        self.answers = list(answers)
        self.statements, self.deleted, self.commits, self.flushes = [], [], 0, 0

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _Result(self.answers.pop(0) if self.answers else [])

    async def delete(self, row):
        self.deleted.append(row)

    async def commit(self):
        self.commits += 1

    async def flush(self):
        self.flushes += 1


def _app():
    return types.SimpleNamespace(id="app-1", name="sbxop", cloud_stack_dir=None, cloud_url="https://sbxop.op.example.org")


@pytest.fixture
def purge_rig(monkeypatch, tmp_path, no_docker):
    monkeypatch.setenv(cp.OPERATOR_LIFECYCLE_VIA_ENV, "runner")
    monkeypatch.setattr(cp, "HOST_STACK_MOUNT", str(tmp_path))
    (tmp_path / "cloud-op-sbxop").mkdir()
    calls, answers = [], {
        "operator_purge": {"drain": {"ok": True, "drained": False}, "compose_rc": 0,
                           "sweep": {"containers": {"swept": 0, "left": 0}}, "edge": [{"nginx_removed": True}],
                           "stack": {"stack_removed": True}, "archives_removed": []},
        "operator_revoke_spire": {"entries_found": 4, "entries_deleted": 4},
    }

    async def through_runner(op, timeout, **fields):
        calls.append((op, fields))
        a = answers[op]
        if isinstance(a, Exception):
            raise a
        return a
    monkeypatch.setattr(cp, "_operator_lifecycle_through_runner", through_runner)
    api = []

    async def by_api(db, safe):
        api.append(safe)
        return {"peers": {"sbx-alpha": {"http": 200, "deleted": 1}}}
    monkeypatch.setattr(cp, "_purge_op_rows_by_api", by_api)
    monkeypatch.setattr(cp, "_drain_op_treasury", lambda safe: pytest.fail("the socket drain ran on the runner route"))
    monkeypatch.setattr(cp, "_purge_op_rows_all_frames", lambda *a: pytest.fail("psql ran in another frame's database"))
    monkeypatch.setattr(cp, "_delete_op_spire_entries", lambda safe: pytest.fail("the socket SPIRE sweep ran"))
    return calls, answers, api, tmp_path


def test_a_purge_on_the_runner_route_asks_the_runner_and_the_peers_never_the_socket(purge_rig):
    calls, answers, api, tmp = purge_rig
    peer = types.SimpleNamespace(id=7, name="sbxop", base_url="https://sbxop.op.example.org:8443", status="ACTIVE")
    db = _Session([[peer], []])                    # the peer row, then no licence
    res = asyncio.run(cp.teardown_cloud_operator(_app(), "proof", db, purge=True))
    assert calls == [("operator_purge", {"operator": "sbxop"}), ("operator_revoke_spire", {"operator": "sbxop"})]
    assert api == ["sbxop"] and db.deleted == [peer]
    assert res.containers_stopped is True and res.nginx_removed is True and res.purged is True
    assert (tmp / "cloud-op-sbxop").exists(), "the registry must not touch host dirs on the runner route"


def test_a_purge_evicts_the_operators_node_when_its_fingerprint_is_known(purge_rig):
    calls, answers, api, tmp = purge_rig
    app = _app()
    app.spire_fingerprint = "AB" * 20
    asyncio.run(cp.teardown_cloud_operator(app, "proof", _Session([[], []]), purge=True))
    assert calls[1] == ("operator_revoke_spire", {"operator": "sbxop", "fingerprint": "ab" * 20})


def test_a_refused_purge_writes_nothing(purge_rig):
    calls, answers, api, tmp = purge_rig
    answers["operator_purge"] = RuntimeError("through the frame runner: the frame runner refused operator_purge: "
                                             "operator sbxop: the drain did not report success; nothing was removed")
    db = _Session([])
    with pytest.raises(RuntimeError, match="nothing was removed"):
        asyncio.run(cp.teardown_cloud_operator(_app(), "proof", db, purge=True))
    assert db.statements == [] and db.deleted == [] and db.flushes == 0 and api == []


def test_a_purge_off_the_runner_route_keeps_its_socket_path_and_asks_the_peers(monkeypatch, purge_rig):
    # §OPPROV (2026-09-27): the socket route drains, sweeps and cleans this frame's own databases as before, and now also
    # asks every ACTIVE peer frame to purge its own copies through its API: the psql loop alone never reached a peer
    # (measured: sbx-alpha's purge of opprovs left sbx-beta's copy); `api == []` was the old contract
    calls, answers, api, tmp = purge_rig
    monkeypatch.setenv(cp.OPERATOR_LIFECYCLE_VIA_ENV, "local")
    ran = []
    monkeypatch.setattr(cp, "_drain_op_treasury", lambda safe: ran.append("drain") or {"ok": True, "drained": False})
    monkeypatch.setattr(cp, "_purge_op_rows_all_frames", lambda *a: ran.append("psql"))
    monkeypatch.setattr(cp, "_delete_op_spire_entries", lambda safe: ran.append("spire") or 0)
    from agentvault_registry.core import host_reach
    monkeypatch.setattr(host_reach, "host_route", lambda: ("direct", "test"))
    fake = types.ModuleType("docker")
    fake.from_env = lambda: types.SimpleNamespace(
        containers=types.SimpleNamespace(list=lambda all=True: []),
        volumes=types.SimpleNamespace(list=lambda: []),
        networks=types.SimpleNamespace(list=lambda names=None: []))
    monkeypatch.setitem(sys.modules, "docker", fake)
    monkeypatch.setattr(cp, "_run", lambda *a, **k: None, raising=False)
    db = _Session([[], []])
    asyncio.run(cp.teardown_cloud_operator(_app(), "proof", db, purge=True))
    assert ran == ["drain", "spire", "psql"] and calls == [] and api == ["sbxop"]


def test_a_socket_purge_whose_drain_did_not_move_the_value_removes_nothing(monkeypatch, purge_rig):
    # §OPPROV: the old drain was best-effort and the purge went on; its key-era read met a 403, parsed as a zero
    calls, answers, api, tmp = purge_rig
    monkeypatch.setenv(cp.OPERATOR_LIFECYCLE_VIA_ENV, "local")
    ran = []
    monkeypatch.setattr(cp, "_drain_op_treasury", lambda safe: ran.append("drain") or {
        "ok": False, "drained": False, "note": "the operator treasury could not be read (its TEG answered 403)"})
    monkeypatch.setattr(cp, "_purge_op_rows_all_frames", lambda *a: ran.append("psql"))
    monkeypatch.setattr(cp, "_delete_op_spire_entries", lambda safe: ran.append("spire") or 0)
    from agentvault_registry.core import host_reach
    monkeypatch.setattr(host_reach, "host_route", lambda: ("direct", "test"))
    fake = types.ModuleType("docker")
    fake.from_env = lambda: pytest.fail("a container was touched after the drain refused")
    monkeypatch.setitem(sys.modules, "docker", fake)
    db = _Session([])
    with pytest.raises(RuntimeError, match="answered 403.*nothing was removed"):
        asyncio.run(cp.teardown_cloud_operator(_app(), "proof", db, purge=True))
    assert ran == ["drain"] and db.statements == [] and db.deleted == [] and calls == []
    assert (tmp / "cloud-op-sbxop").exists()


def test_a_socket_purge_bans_the_operators_node_as_the_runner_purge_does(monkeypatch, purge_rig):
    # §OPPROV: the socket purge did only the sweep, so a purged operator's node stayed attested and unbanned
    calls, answers, api, tmp = purge_rig
    monkeypatch.setenv(cp.OPERATOR_LIFECYCLE_VIA_ENV, "local")
    ran = []
    monkeypatch.setattr(cp, "_drain_op_treasury", lambda safe: {"ok": True, "drained": False})
    monkeypatch.setattr(cp, "_purge_op_rows_all_frames", lambda *a: None)
    monkeypatch.setattr(cp, "_delete_op_spire_entries", lambda safe: ran.append("sweep") or 0)
    monkeypatch.setattr(orv, "revoke_operator_spire",
                        lambda name, fp: ran.append(("ban", name, fp)) or orv.RevokeResult(spire_agent_banned=True))
    from agentvault_registry.core import host_reach
    monkeypatch.setattr(host_reach, "host_route", lambda: ("direct", "test"))
    fake = types.ModuleType("docker")
    fake.from_env = lambda: types.SimpleNamespace(
        containers=types.SimpleNamespace(list=lambda all=True: []),
        volumes=types.SimpleNamespace(list=lambda: []),
        networks=types.SimpleNamespace(list=lambda names=None: []))
    monkeypatch.setitem(sys.modules, "docker", fake)
    monkeypatch.setattr(cp, "_run", lambda *a, **k: None, raising=False)
    app = _app()
    app.spire_fingerprint = "AB" * 20
    asyncio.run(cp.teardown_cloud_operator(app, "proof", _Session([[], []]), purge=True))
    assert ran == [("ban", "sbxop", "ab" * 20), "sweep"] and calls == []


def test_a_socket_purge_on_a_frame_with_no_socket_refuses_before_anything(monkeypatch, purge_rig):
    calls, answers, api, tmp = purge_rig
    monkeypatch.setenv(cp.OPERATOR_LIFECYCLE_VIA_ENV, "local")
    monkeypatch.setattr(cp, "_drain_op_treasury", lambda safe: pytest.fail("drained without a socket"))
    from agentvault_registry.core import host_reach
    monkeypatch.setattr(host_reach, "host_route", lambda: ("runner", "no socket here"))
    db = _Session([])
    with pytest.raises(RuntimeError, match="OPERATOR_LIFECYCLE_VIA=runner.*Nothing was removed"):
        asyncio.run(cp.teardown_cloud_operator(_app(), "proof", db, purge=True))
    assert db.statements == [] and calls == []


def test_the_fan_out_asks_each_active_peer_frame_and_suspends_only_this_operators_store_rows(monkeypatch):
    from agentvault_registry.services import exchange_passport as xp
    from agentvault_registry.services import frame_data_plane_sync as dps
    asked, suspended = [], []

    async def peer_request(db, name, method, path, body=None):
        asked.append((name, method, path))
        if name == "down":
            raise xp.PassportError(502, "peer 'down' unreachable")
        return 200, {"deleted": 1}

    async def list_ops():
        return True, "ok", {"operators": [
            {"id": "1", "spiffe_id": "spiffe://sbx/operator/sbxop/registry", "status": "active"},
            {"id": "2", "spiffe_id": "spiffe://sbx/operator/sbxop/teg", "status": "suspended"},
            {"id": "3", "spiffe_id": "spiffe://sbx/operator/sbxopx/registry", "status": "active"}]}

    async def post(path, body):
        suspended.append(path)
        return True, "ok", {}
    monkeypatch.setattr(xp, "peer_request", peer_request)
    monkeypatch.setattr(dps, "list_federation_operators", list_ops)
    monkeypatch.setattr(dps, "_post", post)
    frames = [types.SimpleNamespace(name="sbx-alpha"), types.SimpleNamespace(name="down")]
    out = asyncio.run(cp._purge_op_rows_by_api(_Session([frames]), "sbxop"))
    assert asked == [("sbx-alpha", "POST", "/api/v1/federation/operators/sbxop/purge-rows"),
                     ("down", "POST", "/api/v1/federation/operators/sbxop/purge-rows")]
    assert out["peers"]["sbx-alpha"] == {"http": 200, "deleted": 1} and "unreachable" in out["peers"]["down"]["error"]
    assert suspended == ["/api/v1/admin/federation-operators/1/suspend"]      # not the already-suspended one, not sbxopx


# ── the purge-rows route ─────────────────────────────────────────────────────────────────────────────────────────

def _compiled(stmt):
    return str(stmt.compile(compile_kwargs={"literal_binds": True})).lower()


def test_purge_rows_deletes_only_the_callers_operator_rows(monkeypatch):
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "sandbox-a.theprotocol.cloud")
    frame = types.SimpleNamespace(name="sbx-beta")
    row = types.SimpleNamespace(id=9, name="sbxop", peer_type="discovered")
    db = _Session([[frame], [row]])
    out = asyncio.run(fop.purge_operator_rows("SbxOp", "spiffe://sandbox-b.theprotocol.cloud/service/sbx-beta-registry", db))
    assert out["deleted"] == 1 and db.deleted == [row] and db.commits == 1 and out["peer_frame"] == "sbx-beta"
    q_frame, q_rows = (_compiled(s) for s in db.statements)
    assert "peer_type = 'frame'" in q_frame and "status = 'active'" in q_frame
    assert "lower(peer_registries.trust_domain) = 'sandbox-b.theprotocol.cloud'" in q_rows
    assert "peer_type in ('cloud_operator', 'discovered')" in q_rows
    for form in ("'sbxop'", "'op-sbxop'", "'cloud-op-sbxop'", "'cloud-op-op-sbxop'"):
        assert form in q_rows


def test_purge_rows_refuses_what_is_not_a_peer_frame(monkeypatch):
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "sandbox-a.theprotocol.cloud")
    for sid in ("spiffe://sandbox-a.theprotocol.cloud/service/registry", "not-a-spiffe-id"):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(fop.purge_operator_rows("sbxop", sid, _Session([])))
        assert exc.value.status_code == 403
    db = _Session([[]])                                                     # no ACTIVE frame with that trust domain
    with pytest.raises(HTTPException) as exc:
        asyncio.run(fop.purge_operator_rows("sbxop", "spiffe://elsewhere.example.org/service/registry", db))
    assert exc.value.status_code == 403 and db.deleted == []
    for bad in ("-x", "a_b", "../etc", "x" * 50):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(fop.purge_operator_rows(bad, "spiffe://sandbox-b.theprotocol.cloud/service/registry", _Session([])))
        assert exc.value.status_code == 422
