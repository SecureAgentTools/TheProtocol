"""§F6 WP6.1 (2026-09-26): the registry asks the frame runner for its SPIRE work when a rail is set to runner, and never
falls back to the docker socket.

Two flags, each read per call: FRAME_TRUST_SPIRE_VIA (local | runner) for the frame-invitation rail and the workload
entries' federation, IRONHAND_SPIRE_MODE (auto | local | proxy | runner) for IRONHAND. Unset keeps today's path byte for
byte. Every runner-mode test also proves the docker path was NOT taken: a fake that raises if docker is touched.
"""
import asyncio
import base64
import json

import pytest

from agentvault_registry.services import agent_spire as ih
from agentvault_registry.services import frame_test_provisioner as ftp
from agentvault_registry.services import frame_trust_manager as ftm
from agentvault_registry.services import spire_ops_client as soc

NODE_FP = "a" * 40
NODE = f"spiffe://{ih.TRUST_DOMAIN}/spire/agent/x509pop/{NODE_FP}"


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    """These sync tests drive coroutines with asyncio.run(), which closes its loop and leaves the thread with none: the
    NEXT file's get_event_loop() then raises (measured in the V0458 build: four reds in test_sqlalchemy_error_handler_422,
    green alone). Put one back after every test."""
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


@pytest.fixture
def runner_ops(monkeypatch):
    """A recorder in place of the runner's operator socket; canned answers by op."""
    calls, answers = [], {}

    def fake_call(op, *, timeout=30.0, **fields):
        calls.append((op, fields))
        a = answers.get(op, {"rc": 0, "stdout": "ok", "stderr": ""})
        if isinstance(a, Exception):
            raise a
        return a(fields) if callable(a) else a

    monkeypatch.setattr(soc, "call", fake_call)
    return calls, answers


@pytest.fixture
def no_docker(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the docker path was taken in runner mode")

    async def aboom(*a, **k):
        raise AssertionError("the docker path was taken in runner mode")
    monkeypatch.setattr(ftm, "_run_docker_exec", aboom)
    monkeypatch.setattr(ftm, "_put_file_into_spire_container", aboom)
    monkeypatch.setattr(ftp, "_docker_client", boom)
    monkeypatch.setattr(ih, "_get_docker_client", boom)


# ── the client ───────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("argv,op,fields", [
    ([soc.SPIRE_BIN, "bundle", "list"], "spire_bundle_list", {}),
    (["bundle", "list", "-id", "spiffe://p.example.org", "-format", "pem"], "spire_bundle_list",
     {"trust_domain": "p.example.org", "format": "pem"}),
    (["bundle", "delete", "-mode", "dissociate", "-id", "spiffe://p.example.org"], "spire_bundle_delete",
     {"mode": "dissociate", "trust_domain": "p.example.org"}),
    (["federation", "create", "-trustDomain", "p.example.org", "-bundleEndpointURL", "https://h:8443",
      "-bundleEndpointProfile", "https_spiffe", "-endpointSpiffeID", "spiffe://p.example.org/spire/server"],
     "spire_federation_create", {"trust_domain": "p.example.org", "bundle_endpoint_url": "https://h:8443",
                                 "profile": "https_spiffe", "endpoint_spiffe_id": "spiffe://p.example.org/spire/server"}),
    (["federation", "delete", "-id", "spiffe://p.example.org"], "spire_federation_delete", {"trust_domain": "p.example.org"}),
    (["entry", "show", "-spiffeID", "spiffe://x/agent/a"], "spire_entry_show", {"spiffe_id": "spiffe://x/agent/a"}),
    (["entry", "count"], "spire_entry_count", {}),
    (["agent", "list"], "spire_agent_list", {}),
])
def test_each_argv_the_registry_builds_maps_to_one_op(argv, op, fields):
    assert soc.op_for_argv(argv) == (op, fields)


@pytest.mark.parametrize("argv", [["entry", "create", "-spiffeID", "x"], ["bundle", "set", "-id", "x"],
                                  ["bundle", "list", "-id"], ["bundle", "list", "-path", "/tmp/x"], ["x509", "mint"]])
def test_a_shape_without_an_op_is_refused_not_widened(argv):
    with pytest.raises(soc.SpireOpsUnavailable):
        soc.op_for_argv(argv)


def test_the_client_fails_closed_with_the_runners_sentence(monkeypatch, tmp_path):
    sock = tmp_path / "op.sock"
    monkeypatch.setenv(soc.OPERATOR_SOCKET_ENV, str(sock))
    with pytest.raises(soc.SpireOpsUnavailable, match="no frame runner operator socket"):
        soc.call("spire_entry_count")
    sock.write_text("")
    monkeypatch.setattr(soc._frc, "_exchange", lambda p, r, t: {"ok": False, "refused": "frame 'x' is not the calling frame"})
    with pytest.raises(soc.SpireOpsUnavailable, match="not the calling frame"):
        soc.call("spire_entry_count")
    monkeypatch.setattr(soc._frc, "_exchange", lambda p, r, t: {"ok": True, "result": {"rc": 0, "stdout": "3"}})
    assert soc.call("spire_entry_count") == {"rc": 0, "stdout": "3"}


def test_the_trust_flag_is_local_runner_or_refused(monkeypatch):
    monkeypatch.delenv(soc.TRUST_VIA_ENV, raising=False)
    assert soc.trust_via() == "local"
    monkeypatch.setenv(soc.TRUST_VIA_ENV, "Runner")
    assert soc.trust_via() == "runner"
    monkeypatch.setenv(soc.TRUST_VIA_ENV, "sidecar")
    with pytest.raises(soc.SpireOpsUnavailable):
        soc.trust_via()


# ── the frame-invitation rail (FrameTrustManager) ────────────────────────────────────────────────────────────────

def _manager():
    return ftm.FrameTrustManager(spire_container="x-spire-server", local_trust_domain="x.example.org")


def test_the_trust_manager_asks_the_runner_and_never_docker(monkeypatch, runner_ops, no_docker):
    calls, answers = runner_ops
    monkeypatch.setenv(soc.TRUST_VIA_ENV, "runner")
    mgr = _manager()
    assert asyncio.run(mgr.add_peer_bundle("p.example.org", '{"keys": []}', format_hint="spiffe")).ok
    assert calls[-1] == ("spire_bundle_set", {"trust_domain": "p.example.org", "bundle": '{"keys": []}', "format": "spiffe"})
    assert asyncio.run(mgr.remove_peer_bundle("p.example.org")).ok
    assert calls[-1] == ("spire_bundle_delete", {"mode": "dissociate", "trust_domain": "p.example.org"})
    answers["spire_bundle_list"] = {"rc": 0, "stdout": "****\n* p.example.org\n****\n-----BEGIN CERTIFICATE-----\n", "stderr": ""}
    assert asyncio.run(mgr.list_federated_trust_domains()) == (["p.example.org"], None)
    answers["spire_federation_list"] = {"rc": 0, "stdout": "Found 0 federation relationships\n", "stderr": ""}
    ok, detail = asyncio.run(mgr.ensure_federation_relationship("p.example.org", "https://spire.p.example.org:8443/x"))
    assert ok and detail["decision"] == "create"
    assert [c[0] for c in calls[-2:]] == ["spire_federation_list", "spire_federation_create"]
    assert calls[-1][1] == {"trust_domain": "p.example.org", "bundle_endpoint_url": "https://spire.p.example.org:8443",
                            "profile": "https_spiffe", "endpoint_spiffe_id": "spiffe://p.example.org/spire/server"}


def test_a_runner_refusal_is_a_failure_never_a_fallback(monkeypatch, runner_ops, no_docker):
    calls, answers = runner_ops
    monkeypatch.setenv(soc.TRUST_VIA_ENV, "runner")
    for op in ("spire_bundle_set", "spire_bundle_delete", "spire_bundle_list"):
        answers[op] = soc.SpireOpsUnavailable("the frame runner refused it: not the calling frame")
    res = asyncio.run(_manager().add_peer_bundle("p.example.org", "x", format_hint="pem"))
    assert not res.ok and "not the calling frame" in res.message
    res = asyncio.run(_manager().remove_peer_bundle("p.example.org"))
    assert not res.ok and "not the calling frame" in res.message
    domains, err = asyncio.run(_manager().list_federated_trust_domains())
    assert domains == [] and "not the calling frame" in err


def test_unset_the_trust_manager_keeps_the_docker_path(monkeypatch, runner_ops):
    calls, _ = runner_ops
    monkeypatch.delenv(soc.TRUST_VIA_ENV, raising=False)
    seen = []

    async def fake_exec(container, cmd, *, timeout=0, stdin_data=None):
        seen.append(list(cmd))
        return 0, "deleted", ""
    monkeypatch.setattr(ftm, "_run_docker_exec", fake_exec)
    assert asyncio.run(_manager().remove_peer_bundle("p.example.org")).ok
    assert seen and not calls


# ── the entries' federation (frame_test_provisioner) ─────────────────────────────────────────────────────────────

ENTRIES = "\n".join([
    "Entry ID : e-reg", "SPIFFE ID : spiffe://x.example.org/service/registry", "Parent ID : spiffe://x.example.org/spire/agent/x509pop/ab", "",
    "Entry ID : e-data", "SPIFFE ID : spiffe://x.example.org/service/data", "Parent ID : spiffe://x.example.org/spire/agent/x509pop/ab", "",
    "Entry ID : e-broker", "SPIFFE ID : spiffe://x.example.org/service/x-redpanda", "Parent ID : spiffe://x.example.org/spire/agent/x509pop/ab", "",
    "Entry ID : e-op", "SPIFFE ID : spiffe://x.example.org/operator/amsterdam/service/registry",
    "Parent ID : spiffe://x.example.org/spire/agent/x509pop/cd", "",
    "Entry ID : e-agent", "SPIFFE ID : spiffe://x.example.org/agent/did-theprotocol-1", "Parent ID : spiffe://x.example.org/spire/agent/x509pop/ab", "",
])


def test_the_never_federated_identities():
    assert ftp.never_federated("service/data") and ftp.never_federated("service/asia-redpanda")
    for p in ("service/registry", "service/redpanda", "service/x-redpanda/y", "operator/a/service/x-redpanda", "service/-redpanda"[:0]):
        assert not ftp.never_federated(p), p


def test_federating_the_entries_through_the_runner(monkeypatch, runner_ops, no_docker):
    calls, answers = runner_ops
    monkeypatch.setenv(soc.TRUST_VIA_ENV, "runner")
    answers["spire_entry_show"] = {"rc": 0, "stdout": ENTRIES, "stderr": ""}
    answers["spire_entry_update_federates"] = lambda f: ({"rc": 1, "stdout": "", "stderr": "boom"} if f["entry_id"] == "e-op"
                                                         else {"rc": 0, "stdout": "", "stderr": "", "already": False})
    ok, detail = ftp.federate_frame_workload_entries("x-spire-server", "spiffe://p.example.org")
    updates = [f["entry_id"] for op, f in calls if op == "spire_entry_update_federates"]
    assert updates == ["e-reg", "e-op"]                      # data, the broker and the agent are skipped
    assert detail["updated"] == 1 and detail["skipped"] == 3 and len(detail["failed"]) == 1 and not ok
    assert all(f["add"] == ["p.example.org"] for op, f in calls if op == "spire_entry_update_federates")


# ── IRONHAND ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_ironhand_mode_is_known_or_refused(monkeypatch):
    monkeypatch.delenv(ih.IRONHAND_MODE_ENV, raising=False)
    assert ih.ironhand_mode() == ("local" if ih._LOCAL_SPIRE_AVAILABLE else "proxy")
    monkeypatch.setenv(ih.IRONHAND_MODE_ENV, "runner")
    assert ih.ironhand_mode() == "runner"
    monkeypatch.setenv(ih.IRONHAND_MODE_ENV, "socket")
    with pytest.raises(RuntimeError, match="not local, proxy, runner or auto"):
        ih.ironhand_mode()


@pytest.fixture
def ironhand_runner(monkeypatch, runner_ops, no_docker):
    calls, answers = runner_ops
    monkeypatch.setenv(ih.IRONHAND_MODE_ENV, "runner")
    monkeypatch.setenv("OPERATOR_SPIRE_AGENT_FINGERPRINT", NODE_FP)
    answers["spire_agent_list"] = {"rc": 0, "stdout": f"SPIFFE ID : {NODE}\n", "stderr": ""}
    return calls, answers


def test_ironhand_registers_deletes_and_counts_through_the_runner(ironhand_runner):
    calls, answers = ironhand_runner
    did = "did:theprotocol:4c783710-64d5"
    sid = ih.register_agent_spire_entry(did, dns_sans=["a.example.org"])
    assert sid == f"spiffe://{ih.TRUST_DOMAIN}/agent/did-theprotocol-4c783710-64d5"
    op, f = calls[-1]
    assert op == "spire_entry_create" and f["parent_id"] == NODE and f["ttl"] == int(ih.SVID_TTL)
    assert f["selectors"] == ["docker:label:com.theprotocol.agent-did:did-theprotocol-4c783710-64d5"] and f["dns"] == ["a.example.org"]
    answers["spire_entry_show"] = {"rc": 0, "stdout": "Found 1 entry\nEntry ID : e-9\n", "stderr": ""}
    assert ih.check_agent_spire_entry(did) == "e-9"
    assert ih.delete_agent_spire_entry(did) is True and calls[-1] == ("spire_entry_delete", {"entry_id": "e-9"})
    answers["spire_entry_count"] = {"rc": 0, "stdout": "42 registration entries\n", "stderr": ""}
    assert ih.get_spire_entry_count() == 42
    with pytest.raises(RuntimeError, match="another frame's"):
        ih.register_agent_spire_entry(did, trust_domain="elsewhere.example.org")


def test_ironhand_mints_through_the_runner(ironhand_runner):
    calls, answers = ironhand_runner
    der = base64.b64encode(bytes([0x30, 0x03, 0x02, 0x01, 0x01])).decode()
    answers["spire_x509_mint"] = {"rc": 0, "stdout": json.dumps([{"x509_svid": der, "private_key": der, "root_cas": [der]}]),
                                  "stderr": ""}
    out = ih.mint_agent_svid("did:theprotocol:4c783710-64d5", ttl_seconds=600, dns_sans=[])
    assert calls[-1][0] == "spire_x509_mint" and calls[-1][1]["ttl"] == 600
    assert out["svid_pem"].startswith("-----BEGIN CERTIFICATE-----") and out["key_pem"].startswith("-----BEGIN " + "PRIVATE KEY-----")
    answers["spire_x509_mint"] = {"rc": 1, "stdout": "", "stderr": "is not under /agent/"}
    with pytest.raises(RuntimeError, match="through the frame runner failed"):
        ih.mint_agent_svid("did:theprotocol:4c783710-64d5", ttl_seconds=600)


# ── the frame's own bundle (the approve and finalize-retry legs) ───────────────────────────────────────────────────
# Found while preparing the WP6.1 proof: the invitation rail's _read_local_bundle still ran `docker exec` itself, so a
# socket-less approver would have approved, then answered its own callback with "Local bundle unreadable".

def test_the_own_bundle_is_read_through_the_runner(monkeypatch, runner_ops, no_docker):
    calls, answers = runner_ops
    monkeypatch.setenv(soc.TRUST_VIA_ENV, "runner")
    answers["spire_bundle_show"] = {"rc": 0, "stdout": '{"keys": [{"use": "x509-svid"}]}', "stderr": ""}
    body, err = asyncio.run(_manager().read_own_bundle("spiffe"))
    assert body.startswith('{"keys"') and err == ""
    assert calls[-1] == ("spire_bundle_show", {"format": "spiffe"})
    answers["spire_bundle_show"] = soc.SpireOpsUnavailable("the frame runner refused it: no spire server in the project")
    body, err = asyncio.run(_manager().read_own_bundle("spiffe"))
    assert body is None and "no spire server in the project" in err


def test_unset_the_own_bundle_keeps_the_docker_read(monkeypatch, runner_ops):
    calls, _ = runner_ops
    monkeypatch.delenv(soc.TRUST_VIA_ENV, raising=False)
    seen = []

    async def fake_exec(container, cmd, *, timeout=0, stdin_data=None):
        seen.append((container, list(cmd), timeout))
        return 0, '{"keys": []}', ""
    monkeypatch.setattr(ftm, "_run_docker_exec", fake_exec)
    assert asyncio.run(_manager().read_own_bundle("spiffe")) == ('{"keys": []}', "")
    assert seen == [("x-spire-server", [ftm.SPIRE_BIN_PATH, "bundle", "show", "-format", "spiffe"],
                     ftm.DOCKER_EXEC_TIMEOUT_SECONDS)] and not calls


def test_the_invitation_rail_reads_its_bundle_through_the_manager(monkeypatch):
    from agentvault_registry.routers import frame_invitations as inv
    asked = []

    class _Mgr:
        async def read_own_bundle(self, fmt="spiffe"):
            asked.append(fmt)
            return '{"keys": []}', ""
    monkeypatch.setattr(inv, "get_frame_trust_manager", lambda: _Mgr())
    monkeypatch.setattr(ftm, "_run_docker_exec", None)     # a call to it would raise TypeError here
    assert asyncio.run(inv._read_local_bundle()) == ('{"keys": []}', "") and asked == ["spiffe"]


# ── IRONHAND's monitoring view (/admin/ironhand/identities) ─────────────────────────────────────────────────────────

def test_the_ironhand_view_lists_through_the_runner(ironhand_runner):
    from agentvault_registry.routers import agent_mtls as mt
    calls, answers = ironhand_runner
    answers["spire_entry_count"] = {"rc": 0, "stdout": "2 registration entries\n", "stderr": ""}
    answers["spire_entry_show"] = {"rc": 0, "stdout": ENTRIES, "stderr": ""}
    count_out, show_out = mt._ironhand_spire_listing()
    assert "2 registration" in count_out and "e-agent" in show_out
    assert [c for c in calls[-2:]] == [("spire_entry_count", {}), ("spire_entry_show", {})]


def test_unset_the_ironhand_view_keeps_the_docker_read(monkeypatch, runner_ops):
    from agentvault_registry.routers import agent_mtls as mt
    calls, _ = runner_ops
    monkeypatch.setenv(ih.IRONHAND_MODE_ENV, "local")
    ran = []

    class _Container:
        def exec_run(self, argv, demux=True):
            ran.append(list(argv))
            return 0, (b"1 registration entry\n" if argv[-1] == "count" else b"Entry ID : e-1\n", b"")

    class _Client:
        def __init__(self, base_url=None):
            self.containers = type("C", (), {"get": staticmethod(lambda name: _Container() if name == ih.SPIRE_CONTAINER
                                                                  else pytest.fail(f"read {name}, not this frame's server"))})
    import docker
    monkeypatch.setattr(docker, "DockerClient", _Client)
    assert mt._ironhand_spire_listing() == ("1 registration entry\n", "Entry ID : e-1\n")
    assert ran == [["/opt/spire/bin/spire-server", "entry", "count"], ["/opt/spire/bin/spire-server", "entry", "show"]]
    assert not calls


# ── IRONHAND's parent detection (found by the WP6.1 proof on a runner-built frame) ──────────────────────────────────
# The candidate list was composed from REGISTRY_NAME, the DISPLAY name ("Sandbox Beta" -> /service/registry-sandbox beta),
# and one try around the whole loop let that candidate's refusal end the search: every enrollment answered 503 on a
# runner-mode frame. The docker path answered "0 entries" for the same id, the quieter version of the same bug.

SPIRE_OWN = "Found 1 entry\nEntry ID : e-reg\nSPIFFE ID : spiffe://{td}/service/registry\nParent ID : spiffe://{td}/spire/agent/x509pop/" + NODE_FP + "\n"


@pytest.fixture
def display_name_with_a_space(monkeypatch):
    monkeypatch.setenv("REGISTRY_NAME", "Sandbox Beta")
    monkeypatch.setenv("TEG_LAYER_URL", "https://sbx-beta-nginx-teg:8443")
    monkeypatch.delenv("REGISTRY_SAFE_NAME", raising=False)
    monkeypatch.delenv("OPERATOR_SPIRE_AGENT_FINGERPRINT", raising=False)
    monkeypatch.setattr(ih, "_cached_local_fingerprint", None)


def test_every_candidate_is_a_valid_id_and_the_slug_names_follow(display_name_with_a_space, monkeypatch):
    td = ih.TRUST_DOMAIN
    # "Sandbox Beta" derives `registry-sandbox beta`: not composed; the template's two names, the second from the slug
    assert ih.own_entry_candidates() == [f"spiffe://{td}/service/registry", f"spiffe://{td}/service/sbx-beta-registry"]
    monkeypatch.setenv("REGISTRY_SAFE_NAME", "legacy")                 # an operator-style explicit slug comes first
    assert ih.own_entry_candidates()[0] == f"spiffe://{td}/service/registry-legacy"
    monkeypatch.setenv("REGISTRY_SAFE_NAME", "has space")              # an id no SPIRE server can hold is never composed
    assert not any(" " in c for c in ih.own_entry_candidates())
    # Frame A's measured naming: REGISTRY_NAME "Registry-A", no REGISTRY_SAFE_NAME, its entry /service/registry-a (first)
    monkeypatch.delenv("REGISTRY_SAFE_NAME")
    monkeypatch.setenv("REGISTRY_NAME", "Registry-A")
    monkeypatch.setenv("TEG_LAYER_URL", "http://teg-layer:8080")
    assert ih.own_entry_candidates()[:2] == [f"spiffe://{td}/service/registry-a", f"spiffe://{td}/service/registry"]


def test_runner_detection_goes_past_a_refused_candidate(monkeypatch, display_name_with_a_space, runner_ops, no_docker):
    calls, answers = runner_ops
    monkeypatch.setenv(ih.IRONHAND_MODE_ENV, "runner")
    monkeypatch.setenv("REGISTRY_SAFE_NAME", "legacy")

    def show(f):
        sid = f.get("spiffe_id", "")
        if sid.endswith("/service/registry-legacy"):
            raise soc.SpireOpsUnavailable("the frame runner refused spire_entry_show: not this frame's")
        if sid.endswith("/service/registry"):
            return {"rc": 0, "stdout": SPIRE_OWN.format(td=ih.TRUST_DOMAIN), "stderr": ""}
        return {"rc": 0, "stdout": "Found 0 entries\n", "stderr": ""}
    answers["spire_entry_show"] = show
    assert ih._autodetect_local_fingerprint() == NODE_FP
    asked = [f["spiffe_id"] for op, f in calls if op == "spire_entry_show"]
    assert asked == [f"spiffe://{ih.TRUST_DOMAIN}/service/registry-legacy", f"spiffe://{ih.TRUST_DOMAIN}/service/registry"]


def test_docker_detection_with_a_spaced_display_name(monkeypatch, display_name_with_a_space):
    monkeypatch.setenv(ih.IRONHAND_MODE_ENV, "local")
    ran = []

    class _Container:
        def exec_run(self, argv, demux=True):
            ran.append(argv[-1])
            out = SPIRE_OWN.format(td=ih.TRUST_DOMAIN) if argv[-1].endswith("/service/registry") else "Found 0 entries\n"
            return 0, (out.encode(), b"")

    class _Client:
        containers = type("C", (), {"get": staticmethod(lambda name: _Container())})
    monkeypatch.setattr(ih, "_get_docker_client", lambda: _Client())
    assert ih._autodetect_local_fingerprint() == NODE_FP
    assert ran and not any(" " in sid for sid in ran)


def test_a_runner_mode_enrollment_needs_no_fingerprint_override(monkeypatch, display_name_with_a_space, runner_ops, no_docker):
    calls, answers = runner_ops
    monkeypatch.setenv(ih.IRONHAND_MODE_ENV, "runner")
    answers["spire_agent_list"] = {"rc": 0, "stdout": f"SPIFFE ID : {NODE}\n", "stderr": ""}
    answers["spire_entry_show"] = lambda f: ({"rc": 0, "stdout": SPIRE_OWN.format(td=ih.TRUST_DOMAIN), "stderr": ""}
                                             if f.get("spiffe_id", "").endswith("/service/registry") else
                                             {"rc": 0, "stdout": "Found 0 entries\n", "stderr": ""})
    sid = ih.register_agent_spire_entry("did:theprotocol:4c783710-64d5")
    op, f = calls[-1]
    assert op == "spire_entry_create" and f["parent_id"] == NODE and sid.endswith("/agent/did-theprotocol-4c783710-64d5")
