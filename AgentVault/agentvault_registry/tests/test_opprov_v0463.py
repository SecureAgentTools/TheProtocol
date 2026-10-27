"""§OPPROV (2026-09-27, his words "keep testing and fixing this stuff on sandbox ... fix operators provisioning"): the
socket route's operator lifecycle, brought to the rules the runner route already keeps. Each defect was measured on
sbx-beta during §F6 WP6.2 slice 2 (FINDINGS_2026-09-26_F6_WP62.md, D2-D6) or named by agentvault2-a1's review:

  D2  the socket route never chowned the operator's Redis ACL, so its Redis could not open it and the operator reconciled
      to 0/9 (host_work._fix_redis_acl_owner, with the file's HOST directory as the bind source);
  D3  an operator whose images are neither on this host nor pullable failed at `compose up`, after the ports, the SPIRE
      entries, the licence and the stack dir were spent (operator_images_preflight, before any of it);
  D5  the provision held one transaction idle through compose up, the idle-transaction reaper killed it at 120 s, and the
      route answered 500 after the operator was up (a commit right after the licence);
      the socket route rebuilds a missing bundle as the runner route does (activation's failed bundle was final there);
  D6  the socket revoke evicted after banning, which erased the ban (the runner's rule: ban, delete, never evict), and
      the revoke route skipped SPIRE whole when the row carried no fingerprint;
      the bind probe left a Created container behind for every refused port block;
      activation used a second slug rule, and a second live application could share a name's SPIFFE path;
  review 3: a retried purge trusted a zero after a drain the parent never confirmed (services/operator_drain.py), and the
      socket purge's drain read with a key every operator TEG refuses since §SECFIX, parsed the 403 as zero, and went on.
"""
import ast
import json
import pathlib
import re
import sys
import types

import pytest

from agentvault_registry.services import cloud_provisioner as cp
from agentvault_registry.services import operator_drain as od
from agentvault_registry.services import operator_revoker as orv

SRC = pathlib.Path(cp.__file__).resolve().parents[1]
OP = "sbxop"
TD = "sbx.example.org"


# ── the socket purge's drain (services/operator_drain.py) ────────────────────────────────────────────────────────────

class _Container:
    def __init__(self, name, env=(), created="2026-09-27T07:00:00Z"):
        self.name = name
        self.attrs = {"Config": {"Env": list(env)}, "Created": created}


class _FakeDocker:
    """The drain's four questions of Docker, answered from a small world the test controls."""

    def __init__(self, world):
        self.w = world

    def containers(self, slug, service):
        if self.w.get("list_raises"):
            raise RuntimeError("docker did not answer")
        return list(self.w["containers"].get(service, []))

    def ledger_volumes(self, slug):
        return list(self.w.get("ledger", []))

    def registry_python(self, container, code, body=None):
        self.w["calls"].append(("send" if "cross-teg-fund-send" in code else "read", body))
        if "cross-teg-fund-send" in code:
            http, status = (self.w["send_answers"].pop(0) if self.w.get("send_answers")
                            else (self.w["send_http"], self.w["send_status"]))
            if http in (200, 201) and status == "completed" and not self.w.get("send_moves_nothing"):
                self.w["balance"] = "0"   # a completed send took the whole balance (a replayed id moves nothing)
            return {"status": http, "result": status}
        if self.w.get("read_answers"):
            http, balance = self.w["read_answers"].pop(0)
            return {"status": http, "treasury_balance": balance}
        return {"status": self.w["info_status"], "treasury_balance": self.w["balance"]}


@pytest.fixture
def drain(tmp_path):
    stack = tmp_path / f"cloud-op-{OP}"
    stack.mkdir()
    world = {
        "containers": {"teg-layer": [_Container(f"cloud-op-{OP}-teg", ['PARTNER_TEGS={"teg-layer-test": {}}'])],
                       "registry": [_Container(f"cloud-op-{OP}-registry")]},
        "balance": "0", "info_status": 200, "send_http": 200, "send_status": "completed", "calls": [],
    }
    return world, stack, _FakeDocker(world)


def _run(world, stack, dk):
    return od.drain_operator_treasury(OP, str(stack), docker=dk)


def _record(stack):
    return json.loads((stack / od.DRAIN_RECORD).read_text())["drains"]


def _sends(world):
    return [json.loads(b) for kind, b in world["calls"] if kind == "send"]


def test_the_socket_drain_reads_and_sends_through_the_operators_registry_never_with_the_key():
    for code in (od.DRAIN_PY_READ, od.DRAIN_PY_SEND):
        assert "get_httpx_verify" in code and "TEG_API_BASE_URL" in code and "TEG_ADMIN_API_KEY" not in code
    src = (SRC / "services" / "cloud_provisioner.py").read_text()
    assert "def _drain_op_genesis" not in src, "the key-era drain (a 403 read as a zero) must be gone"


def test_a_treasury_the_teg_will_not_show_refuses_instead_of_reading_as_zero(drain):
    world, stack, dk = drain
    world["info_status"], world["balance"] = 403, ""
    out = _run(world, stack, dk)
    assert out["ok"] is False and "answered 403" in out["note"] and _sends(world) == []


def test_a_funded_treasury_is_sent_to_the_one_partner_under_a_numbered_incarnation_id(drain):
    world, stack, dk = drain
    world["balance"] = "1.25E+1"
    out = _run(world, stack, dk)
    sent = _sends(world)
    assert out["ok"] and out["drained"] is True and len(sent) == 1
    assert {k: sent[0][k] for k in ("amount", "target_teg_id", "reason")} == {
        "amount": "12.5", "target_teg_id": "teg-layer-test", "reason": "teardown_genesis_drain"}
    assert re.fullmatch(rf"td-{OP}-[0-9a-f]{{8}}-1", sent[0]["correlation_id"]) and len(sent[0]["correlation_id"]) <= 36
    assert sent[0]["correlation_id"] == od.next_correlation_id({"drains": []}, OP, od.incarnation_of(
        OP, "2026-09-27T07:00:00Z")), "the same id the runner derives for the same container"
    assert _record(stack)[0]["state"] == "completed"


def test_a_completed_answer_with_the_value_still_there_is_not_a_drain(drain):
    # §OPPROV: the TEG answers a correlation id it already completed with that success and moves nothing; a drain whose
    # record was lost could reuse an id at the same amount. Only a treasury that READS empty after the send is drained.
    world, stack, dk = drain
    world["balance"], world["send_moves_nothing"] = "12.5", True
    out = _run(world, stack, dk)
    assert out["ok"] is False and out["drained"] is False and "still reads 12.5" in out["note"] and out["after"] == "12.5"
    assert _record(stack)[0]["state"] == "completed", "the record keeps what the TEG answered"
    world["send_moves_nothing"] = False                          # a retried purge: a NEW id, and this one moves the value
    out = _run(world, stack, dk)
    ids = [x["correlation_id"] for x in _sends(world)]
    assert out["ok"] and out["drained"] is True and ids[0].endswith("-1") and ids[1].endswith("-2")


def test_a_completed_drain_whose_treasury_cannot_be_reread_removes_nothing(drain):
    world, stack, dk = drain
    world["balance"] = "3"
    world["read_answers"] = [(200, "3"), (503, "")]              # the read before the send, then the re-read after it
    out = _run(world, stack, dk)
    assert out["ok"] is False and "could not be re-read" in out["note"] and len(_sends(world)) == 1


def test_an_unconfirmed_drain_is_resent_first_and_the_zero_behind_it_is_never_trusted(drain):
    world, stack, dk = drain
    world["balance"], world["send_answers"] = "12.5", [(503, "")]
    out = _run(world, stack, dk)
    assert out["ok"] is False and "not confirmed" in out["note"]
    cid = _record(stack)[0]["correlation_id"]
    assert _record(stack)[0]["state"] == "uncertain"
    world["balance"] = "0"                                       # the TEG kept the debit; the row is pending
    world["calls"].clear()
    world["send_answers"] = [(503, "")]
    out = _run(world, stack, dk)
    assert out["ok"] is False and cid in out["note"] and "still unconfirmed" in out["note"]
    assert [k for k, _ in world["calls"]] == ["send"], "refused before the balance is even read"
    world["send_answers"] = [(400, "")]                          # an older TEG's balance pre-flight refuses the resume
    assert _run(world, stack, dk)["ok"] is False and _record(stack)[0]["state"] == "uncertain"
    world["send_answers"] = [(200, "completed")]
    out = _run(world, stack, dk)
    assert out["ok"] and out["drained"] is True and out["resumed"] == [cid]
    assert all(s["correlation_id"] == cid and s["amount"] == "12.5" for s in _sends(world))


def test_a_completed_id_is_never_sent_again_and_a_reversal_is_drained_under_the_next(drain):
    world, stack, dk = drain
    (stack / od.DRAIN_RECORD).write_text(json.dumps({"drains": [
        {"correlation_id": od.drain_id(OP, od.incarnation_of(OP, "2026-09-27T07:00:00Z"), 1), "amount": "10",
         "target": "teg-layer-test", "state": "completed"}]}))
    world["balance"], world["send_answers"] = "2.5", [(502, "")]
    out = _run(world, stack, dk)
    assert out["ok"] is False and "re-credited" in out["note"]
    assert _sends(world)[0]["correlation_id"].endswith("-2") and _record(stack)[1]["state"] == "reversed"
    out = _run(world, stack, dk)
    assert out["ok"] and _sends(world)[1]["correlation_id"].endswith("-3")


def test_a_record_that_cannot_be_read_or_names_another_target_is_refused_with_nothing_sent(drain):
    world, stack, dk = drain
    world["balance"] = "3"
    (stack / od.DRAIN_RECORD).write_text("{broken")
    assert "cannot be read" in _run(world, stack, dk)["note"]
    own = od.drain_id(OP, od.incarnation_of(OP, "2026-09-27T07:00:00Z"), 1)
    for bad in ({"correlation_id": "td-other-aaaaaaaa-1", "amount": "3", "target": "teg-layer-test"},
                {"correlation_id": f"td-{OP}-bbbbbbbb-1", "amount": "3", "target": "teg-layer-test"},
                {"correlation_id": own, "amount": "3", "target": "teg-elsewhere"},
                {"correlation_id": own, "amount": "1e3", "target": "teg-layer-test"}):
        (stack / od.DRAIN_RECORD).write_text(json.dumps({"drains": [dict(bad, state="uncertain")]}))
        assert "was not re-sent" in _run(world, stack, dk)["note"]
    assert _sends(world) == []


def test_no_teg_is_nothing_to_drain_only_without_a_ledger_and_two_are_refused(drain):
    world, stack, dk = drain
    teg = world["containers"].pop("teg-layer")
    world["ledger"] = [f"cloud-op-{OP}_teg-data"]
    assert "ledger volume remains" in _run(world, stack, dk)["note"]
    world["ledger"] = []
    assert _run(world, stack, dk) == {"ok": True, "drained": False, "note": "nothing to drain: the operator runs 0 TEG "
                                                                             "container(s), not one, and no TEG ledger volume"}
    world["containers"]["teg-layer"] = teg * 2
    assert "2 TEG container(s)" in _run(world, stack, dk)["note"]
    world["list_raises"] = True
    assert _run(world, stack, dk)["ok"] is False


def test_an_operator_with_no_partner_teg_is_drained_to_its_parent_by_its_own_registrys_address(drain):
    # measured on sbx-beta: PARTNER_TEGS=[] on every socket-route operator since §REDERIVE; the purge refused at the drain
    world, stack, dk = drain
    world["containers"]["teg-layer"] = [_Container("t", ["PARTNER_TEGS=[]"])]
    world["balance"] = "1"
    out = _run(world, stack, dk)
    assert out["ok"] and _sends(world)[0]["target_teg_id"] == od.PARENT_LABEL and "target_url" not in _sends(world)[0]
    compile(od.DRAIN_PY_SEND, "send", "exec")
    assert "MAINFRAME_PUBLIC_URL" in od.DRAIN_PY_SEND and "_teg_dial_url" in od.DRAIN_PY_SEND
    assert "if m and not body.get('target_url')" in od.DRAIN_PY_SEND


def test_every_drain_id_fits_the_tegs_transaction_id_column():
    longest = od.drain_id("a" * 40, "f" * 64, 9999)
    assert len(longest) <= od.DRAIN_ID_MAX == 36 and od.DRAIN_ID_RE.fullmatch(longest)
    assert od.drain_id("sbxbetaop", "0123456789abcdef" * 4, 1) == "td-sbxbetaop-01234567-1"


def test_a_partner_that_is_not_unique_refuses_a_funded_drain(drain):
    world, stack, dk = drain
    world["containers"]["teg-layer"] = [_Container("t", ['PARTNER_TEGS={"teg-a": {}, "teg-b": {}}'])]
    world["balance"] = "3"
    assert "not unique" in _run(world, stack, dk)["note"] and _sends(world) == []
    world["balance"] = "0"                                      # nothing to send: no target needed
    assert _run(world, stack, dk)["ok"] is True


# ── the images, before anything is spent (D3) ──────────────────────────────────────────────────────────────────────

def _fake_docker_module(monkeypatch, *, local=(), registry_ok=(), registry_error="denied: requested access to the "
                                                                                "resource is denied dpt_0123abcd"):
    mod = types.ModuleType("docker")

    class ImageNotFound(Exception):
        pass
    mod.errors = types.SimpleNamespace(ImageNotFound=ImageNotFound)
    asked = []

    class Images:
        def get(self, ref):
            if ref in local:
                return object()
            raise ImageNotFound(ref)

        def get_registry_data(self, ref, auth_config=None):
            asked.append((ref, dict(auth_config or {})))
            if ref in registry_ok:
                return object()
            raise RuntimeError(registry_error)

    mod.from_env = lambda: types.SimpleNamespace(images=Images())
    monkeypatch.setitem(sys.modules, "docker", mod)
    from agentvault_registry.core import registry_identity
    monkeypatch.setattr(registry_identity, "get_software_version", lambda: "VTEST")
    monkeypatch.setattr(cp, "operator_image_version", lambda v: v)
    return asked


def test_the_images_preflight_names_every_image_this_host_cannot_have(monkeypatch):
    refs = [f"{cp.IMAGES_PREFIX}/{n}:VTEST" for n in cp.OPERATOR_IMAGE_NAMES]
    _fake_docker_module(monkeypatch, local=refs)
    assert cp.operator_images_preflight("operator-x", "dpt_" + "0" * 64) == []
    asked = _fake_docker_module(monkeypatch, local=refs[:1], registry_ok=refs[1:2])
    missing = cp.operator_images_preflight("operator-x", "dpt_" + "0" * 64)
    assert len(missing) == 1 and missing[0].startswith(refs[2]) and "refused it" in missing[0]
    assert "dpt_0123abcd" not in missing[0] and "dpt_<redacted>" in missing[0], "a token in an error is never repeated"
    assert [a[1]["username"] for a in asked] == ["operator-x", "operator-x"]
    _fake_docker_module(monkeypatch)
    missing = cp.operator_images_preflight("", "")
    assert len(missing) == 3 and all("no pull credential" in m for m in missing)


def _fn(relpath, name):
    tree = ast.parse((SRC / relpath).read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def _first_line(fn, pred):
    lines = [n.lineno for n in ast.walk(fn) if pred(n)]
    return min(lines) if lines else None


def _calls(name):
    return lambda n: isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", None)) == name


def test_the_provision_refuses_missing_images_before_it_spends_anything():
    fn = _fn("services/cloud_provisioner.py", "provision_cloud_operator")
    pre = _first_line(fn, lambda n: isinstance(n, ast.Name) and n.id == "operator_images_preflight")
    assert pre is not None, "the socket route must ask for its images"
    for spent in ("provision_operator", "bundle_through_runner", "_delete_op_spire_entries", "FederationLicense",
                  "_compose_up_blocking"):
        at = _first_line(fn, lambda n, s=spent: (isinstance(n, ast.Attribute) and n.attr == s)
                         or (isinstance(n, ast.Name) and n.id == s))
        assert at is None or pre < at, f"{spent} (line {at}) runs before the images are known (line {pre})"


def test_the_provision_commits_after_the_licence_and_before_the_long_host_work():
    fn = _fn("services/cloud_provisioner.py", "provision_cloud_operator")
    lic = _first_line(fn, lambda n: isinstance(n, ast.Attribute) and n.attr == "FederationLicense")
    commits = sorted(n.lineno for n in ast.walk(fn) if _calls("commit")(n))
    up = _first_line(fn, lambda n: isinstance(n, ast.Name) and n.id == "_compose_up_blocking")
    key = _first_line(fn, lambda n: isinstance(n, ast.Constant) and isinstance(n.value, str)
                      and n.value.startswith("FEDERATION_LICENSE_KEY="))
    between = [c for c in commits if lic < c < up]
    assert between, "no commit between the licence and compose up: the reaper kills the idle transaction"
    assert key is None or between[0] < key, "the licence must be durable before its key is written anywhere"


def test_the_socket_route_rebuilds_a_missing_bundle_as_the_runner_route_does():
    fn = _fn("services/cloud_provisioner.py", "provision_cloud_operator")
    src = ast.unparse(fn)
    assert "if not bundle_path or not os.path.exists(bundle_path):" in src
    assert "(not bundle_path or not os.path.exists(bundle_path)) and _through_runner" not in src
    sweep = _first_line(fn, lambda n: isinstance(n, ast.Name) and n.id == "_delete_op_spire_entries")
    build = _first_line(fn, lambda n: isinstance(n, ast.Attribute) and n.attr == "provision_operator")
    assert sweep and build and sweep < build, "the failed attempt's entries are swept before new ones are registered"


def test_the_socket_route_gives_the_acl_to_redis_before_up_and_refuses_when_it_cannot():
    fn = _fn("services/cloud_provisioner.py", "provision_cloud_operator")
    fix = next(n for n in ast.walk(fn) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "_fix_redis_acl_owner")
    assert [k.arg for k in fix.keywords] == ["host_dir"] and ast.unparse(fix.keywords[0].value) == "stack_dir_host"
    up = _first_line(fn, lambda n: isinstance(n, ast.Name) and n.id == "_compose_up_blocking")
    assert fix.lineno < up
    assert "redis_acl_chown_needed" in ast.unparse(fn)


def test_the_acl_chown_binds_the_hosts_directory_not_this_containers(monkeypatch, tmp_path):
    from agentvault_registry import host_work as hw
    acl = tmp_path / "redis-users.acl"
    acl.write_text("user default off\n")
    uids = iter([1000, 999])
    monkeypatch.setattr(hw.os, "stat", lambda p: types.SimpleNamespace(st_uid=next(uids)))
    ran = []
    monkeypatch.setattr(hw.subprocess, "run", lambda argv, **k: ran.append(argv) or types.SimpleNamespace(
        returncode=0, stderr=""))
    notes = []
    out = hw._fix_redis_acl_owner(str(acl), notes, host_dir="/opt/theprotocol/stack/cloud-op-x")
    assert out["redis_acl_chown_needed"] is False and "-v" in ran[0]
    assert ran[0][ran[0].index("-v") + 1] == "/opt/theprotocol/stack/cloud-op-x:/w"


def test_the_bind_probe_removes_its_container_whatever_the_start_did():
    fn = _fn("services/cloud_provisioner.py", "allocate_port_block")
    src = ast.unparse(fn)
    assert "containers.run(" not in src, "run() raises on a refused start with its created container left behind"
    tries = [n for n in ast.walk(fn) if isinstance(n, ast.Try) and n.finalbody]
    assert any("remove(force=True)" in ast.unparse(t.finalbody[0]) for t in tries if t.finalbody)
    assert "operator-port-bind-probe" in src


# ── the revoke (D6) ─────────────────────────────────────────────────────────────────────────────────────────────────

def _entry(eid, sid, parent):
    return f"Entry ID         : {eid}\nSPIFFE ID        : {sid}\nParent ID        : {parent}\nRevision         : 0\n\n"


NODE = f"spiffe://{TD}/spire/agent/x509pop/{'a' * 40}"
LISTING = (_entry("e-reg", f"spiffe://{TD}/operator/{OP}/registry", NODE)
           + _entry("e-teg", f"spiffe://{TD}/operator/{OP}/teg", NODE)
           + _entry("e-agent", f"spiffe://{TD}/agent/did:theprotocol:x", NODE)
           + _entry("e-orphan", f"spiffe://{TD}/operator/{OP}/svid-writer", f"spiffe://{TD}/spire/agent/x509pop/{'c' * 40}")
           + _entry("e-other", f"spiffe://{TD}/operator/{OP}x/registry", f"spiffe://{TD}/spire/agent/x509pop/{'d' * 40}")
           + _entry("e-frame", f"spiffe://{TD}/service/registry", f"spiffe://{TD}/spire/agent/x509pop/{'b' * 40}"))


@pytest.fixture
def spire(monkeypatch):
    world = {"listing": LISTING, "agents": f"SPIFFE ID         : {NODE}\n", "ran": []}

    class _Spire:
        def exec_run(self, argv, demux=True):
            world["ran"].append(argv[1:])
            if argv[1:3] == ["entry", "show"]:
                return 0, (world["listing"].encode(), b"")
            if argv[1:3] == ["agent", "list"]:
                return 0, (world["agents"].encode(), b"")
            return 0, (b"ok\n", b"")

    monkeypatch.setattr(orv, "TRUST_DOMAIN", TD)
    monkeypatch.setattr(orv, "_get_docker_client",
                        lambda: types.SimpleNamespace(containers=types.SimpleNamespace(get=lambda name: _Spire())))
    monkeypatch.setenv("OPERATOR_LIFECYCLE_VIA", "local")
    return world


def _writes(world):
    return [a for a in world["ran"] if a[:2] in (["agent", "ban"], ["agent", "evict"], ["entry", "delete"])]


def test_the_socket_revoke_bans_the_node_deletes_its_entries_and_never_evicts(spire):
    res = orv.revoke_operator_spire(OP, "a" * 40)
    assert res.spire_agent_banned is True and res.spire_agent_evicted is False and res.node_listed is True
    assert ["agent", "ban", "-spiffeID", NODE] in spire["ran"]
    assert not any(a[:2] == ["agent", "evict"] for a in spire["ran"]), "an evict erases the ban on SPIRE 1.10"
    deleted = sorted(a[3] for a in _writes(spire) if a[:2] == ["entry", "delete"])
    assert deleted == ["e-agent", "e-orphan", "e-reg", "e-teg"] and res.agent_entries == 1 and not res.errors


def test_without_a_fingerprint_the_operators_path_is_still_swept_and_nothing_is_banned(spire):
    res = orv.revoke_operator_spire(OP, "")
    assert res.spire_agent_banned is False and res.node_listed is None
    assert sorted(a[3] for a in _writes(spire)) == ["e-orphan", "e-reg", "e-teg"], "e-other is another operator's"


def test_a_node_that_parents_anything_else_or_only_agents_is_refused_with_nothing_changed(spire):
    spire["listing"] = LISTING + _entry("e-svc", f"spiffe://{TD}/service/teg-layer", NODE)
    res = orv.revoke_operator_spire(OP, "a" * 40)
    assert _writes(spire) == [] and "nothing was changed" in res.errors[0]
    spire["ran"].clear()
    spire["listing"] = _entry("e-stale", f"spiffe://{TD}/agent/did:theprotocol:old", NODE)
    res = orv.revoke_operator_spire(OP, "a" * 40)
    assert _writes(spire) == [] and "cannot be attributed" in res.errors[0]


def test_an_unattested_node_is_a_fact_not_an_error_and_its_path_is_still_swept(spire):
    spire["agents"] = ""
    res = orv.revoke_operator_spire(OP, "a" * 40)
    assert res.node_listed is False and res.spire_agent_banned is False and res.errors == []
    assert not any(a[:2] == ["agent", "ban"] for a in spire["ran"]) and res.spire_entries_deleted == 4


def test_the_runner_half_passes_an_empty_fingerprint_through_and_reports_the_same_facts(monkeypatch):
    from agentvault_registry.services import spire_ops_client as soc
    asked = []
    monkeypatch.setenv("OPERATOR_LIFECYCLE_VIA", "runner")
    monkeypatch.setattr(soc, "call", lambda op, timeout=None, **f: asked.append((op, f)) or {
        "banned": False, "entries_found": 3, "entries_deleted": 3, "evicted": False, "errors": [], "node_listed": None,
        "agent_entries": 0})
    res = orv.revoke_operator_spire(OP, "")
    assert asked == [("operator_revoke_spire", {"operator": OP, "fingerprint": ""})]
    assert res.spire_entries_deleted == 3 and res.errors == [] and res.node_listed is None


def test_a_withheld_sweep_takes_only_the_nodes_own_children(spire):
    # a second application under a live operator's name: its node's entries go, the live operator's path stays
    res = orv.revoke_operator_spire(OP, "a" * 40, sweep_path=False)
    assert sorted(a[3] for a in _writes(spire) if a[:2] == ["entry", "delete"]) == ["e-agent", "e-reg", "e-teg"]
    assert "e-orphan" not in str(spire["ran"]) and res.spire_agent_banned is True
    spire["ran"].clear()
    res = orv.revoke_operator_spire(OP, "", sweep_path=False)
    assert _writes(spire) == [] and "nothing was changed" in res.errors[0]


def test_the_runner_half_asks_to_withhold_the_sweep_and_flags_a_runner_that_did_not(monkeypatch):
    from agentvault_registry.services import spire_ops_client as soc
    asked = []
    monkeypatch.setenv("OPERATOR_LIFECYCLE_VIA", "runner")
    answer = {"banned": True, "entries_found": 2, "entries_deleted": 2, "evicted": False, "errors": [],
              "node_listed": True, "agent_entries": 0, "sweep_path": False}
    monkeypatch.setattr(soc, "call", lambda op, timeout=None, **f: asked.append(f) or dict(answer))
    res = orv.revoke_operator_spire(OP, "a" * 40, sweep_path=False)
    assert asked[-1] == {"operator": OP, "fingerprint": "a" * 40, "sweep_path": False} and res.errors == []
    answer.pop("sweep_path")                                     # a runner older than §OPPROV ignores the field
    res = orv.revoke_operator_spire(OP, "a" * 40, sweep_path=False)
    assert any("did not confirm it withheld the path sweep" in e for e in res.errors)
    orv.revoke_operator_spire(OP, "a" * 40)
    assert "sweep_path" not in asked[-1], "the default asks exactly what it asked before"


def test_the_revoke_route_acts_on_the_name_only_as_its_holder():
    fn = _fn("routers/operator_applications.py", "revoke_operator_access")
    src = ast.unparse(fn)
    assert "name_holder = app_record.activated_at is not None and (not _namesakes)" in src
    call = next(n for n in ast.walk(fn) if _calls("to_thread")(n))
    assert ast.unparse(call.args[-1]) == "name_holder", "the path sweep follows the holding"
    holder = _first_line(fn, lambda n: isinstance(n, ast.Name) and n.id == "name_holder" and isinstance(n.ctx, ast.Store))
    first_write = _first_line(fn, lambda n: isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store)
                              and n.attr in ("status", "is_federation_operator", "revoked_at"))
    assert holder < first_write, "whose name it is is read before anything is changed"
    assert "if app_record.developer_id and name_holder:" in src, "the licence (keyed by the name's DID) only by its holder"
    assert "'name_holder': name_holder" in src, "the event says so, for the cascade reactor"
    bound = _first_line(fn, lambda n: isinstance(n, ast.Name) and n.id == "fed_license" and isinstance(n.ctx, ast.Store))
    emit = _first_line(fn, lambda n: isinstance(n, ast.Constant) and n.value == "OperatorApplicationRevoked")
    assert bound < emit and "fed_license = None" in src, "bound for a phantom revoke, or the emit raises NameError"


def test_the_cascade_reactor_leaves_a_namesakes_peer_row_alone(monkeypatch):
    import asyncio
    from agentvault_registry.background_tasks import reactor_operator_application_revoked as rr
    opened = []

    class _NoSession:
        async def __aenter__(self):
            opened.append(1)
            raise AssertionError("the database was opened for an application that does not hold its name")

        async def __aexit__(self, *a):
            return False
    monkeypatch.setattr(rr, "AsyncSessionLocal", lambda: _NoSession())
    reactor = rr.OperatorApplicationRevokedReactor.__new__(rr.OperatorApplicationRevokedReactor)
    asyncio.run(reactor.handle_event({"operator_name": OP, "application_id": "a2", "name_holder": False}))
    assert opened == []
    with pytest.raises(AssertionError, match="database was opened"):
        asyncio.run(reactor.handle_event({"operator_name": OP, "application_id": "a1"}))   # an older event cascades


def test_the_revoke_route_runs_the_spire_half_without_a_fingerprint_and_off_the_event_loop():
    fn = _fn("routers/operator_applications.py", "revoke_operator_access")
    src = ast.unparse(fn)
    assert "if fingerprint:" not in src, "SPIRE was skipped whole without a fingerprint"
    call = next(n for n in ast.walk(fn) if _calls("to_thread")(n))
    assert ast.unparse(call.args[0]) == "revoke_operator" and "fingerprint or ''" in ast.unparse(call)


# ── activation's one name (D6) ──────────────────────────────────────────────────────────────────────────────────────

def test_activation_uses_the_one_slug_rule_and_refuses_a_held_name_before_the_code_is_spent():
    fn = _fn("routers/operator_applications.py", "activate_operator")
    src = ast.unparse(fn)
    assert "c if c.isalnum() or c == '-' else '-'" not in src, "activation's second slug rule is gone"
    assert "safe_name = _safe_name(app_record.name or '') or f'operator-{developer.id}'" in src
    held = _first_line(fn, lambda n: isinstance(n, ast.Constant) and isinstance(n.value, str)
                       and "is already active on this frame" in n.value)
    spent = _first_line(fn, lambda n: isinstance(n, ast.Attribute) and n.attr == "is_federation_operator"
                        and isinstance(getattr(n, "ctx", None), ast.Store))
    first_commit = _first_line(fn, _calls("commit"))
    assert held and spent and held < spent and held < first_commit
    assert cp._safe_name("Acme Corp") == "acmecorp" and cp._safe_name("op_test") == "optest"
