"""§F6 WP6.2 slice 2 (2026-09-26, his words "continue with wp6.2 slice 2 on the sandbox pair"): the SPIRE half of an
operator's revoke and purge, the host half of a purge, and the read-only census and stats of what the caller owns.

Each rule has a planted bad argument refused BEFORE anything runs, and a good request whose effect is pinned. The SPIRE
server, docker and nginx are recorders: nothing here touches the host.
"""
import importlib.util
import json
import re
import os
import pathlib
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("frame_runner_slice2", HERE.parent / "frame_runner.py")
fr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fr)

TD = "sbx.example.org"
OP = "sbxop"
FP_OP = "a" * 40
FP_FRAME = "b" * 40
NODE_OP = f"spiffe://{TD}/spire/agent/x509pop/{FP_OP}"
NODE_FRAME = f"spiffe://{TD}/spire/agent/x509pop/{FP_FRAME}"


def entry(eid, sid, parent):
    return f"Entry ID         : {eid}\nSPIFFE ID        : {sid}\nParent ID        : {parent}\nSelector         : docker:label:x:y\n\n"


LISTING = (entry("e-op-reg", f"spiffe://{TD}/operator/{OP}/registry", NODE_OP)
           + entry("e-op-teg", f"spiffe://{TD}/operator/{OP}/teg", NODE_OP)
           + entry("e-op-data", f"spiffe://{TD}/operator/{OP}/data", NODE_OP)
           + entry("e-frame-reg", f"spiffe://{TD}/service/sbx-registry", NODE_FRAME)
           + entry("e-other-op", f"spiffe://{TD}/operator/{OP}x/registry", NODE_FRAME))
AGENTS = f"SPIFFE ID : {NODE_OP}\nSPIFFE ID : {NODE_FRAME}\n"
FMT_CENSUS = "{{.ID}}\t{{.Names}}\t{{.Label \"com.docker.compose.service\"}}\t{{.State}}\t{{.Status}}\t{{.Image}}"


@pytest.fixture
def rig(tmp_path, monkeypatch):
    stack = tmp_path / "stack"
    cfg = fr.Config(conf={"images": {"registry": ["agentvault2-registry-a:v0462"]}, "allowed_uids": [0, 1000],
                          "min_free_gb": 0, "max_load": 10 ** 6, "min_mem_gib": 0},
                    socket=str(tmp_path / "run" / "fr.sock"), state=str(tmp_path / "state"),
                    driver=str(tmp_path / "driver.py"), teardown=str(tmp_path / "td.sh"), python=sys.executable,
                    stack_root=str(stack), protected_list=str(tmp_path / "protected.list"),
                    template=str(tmp_path / "template.yml.tmpl"))
    os.makedirs(cfg.state, exist_ok=True)
    runner = fr.Runner(cfg)
    wd = stack / f"cloud-op-{OP}"
    wd.mkdir(parents=True)
    (wd / "docker-compose.operator.yml").write_text("services: {}\n")
    (wd / ".env.operator").write_text("X=1\n")
    sites = tmp_path / "sites"
    sites.mkdir()
    (sites / f"cloud-op-{OP}").write_text(f"server {{\n    server_name {OP}.op.example.org;\n}}\n")
    sni = tmp_path / "federation-mtls.conf"
    sni.write_text(f"map $ssl_preread_server_name $b {{\n    {OP}.op.example.org    127.0.0.1:31243;\n    keep.op.example.org    127.0.0.1:31143;\n}}\n")
    monkeypatch.setattr(runner, "NGINX_SITES", str(sites))
    monkeypatch.setattr(runner, "NGINX_SNI_MAP", str(sni))
    monkeypatch.setattr(runner, "NGINX_BACKUPS", str(tmp_path / "vhost-backups"))
    world = {
        "spire": [], "listing": LISTING, "agents": AGENTS, "spire_rc": {},
        "compose": [], "execs": [], "nginx": [],
        "balance": "0", "send_status": "completed", "send_rc": 0, "ledger": "", "ledger_rc": 0,
        "info_status": 200, "send_http": 200,
        "volumes": {}, "volumes_rc": 0,
        "projects": {
            "sbx-1788464843": [
                {"id": "f1", "name": "sbx-registry", "service": "sbx-registry", "state": "running", "status": "Up 2 hours (healthy)", "image": "reg:v1"},
                {"id": "f2", "name": "sbx-db", "service": "sbx-db", "state": "running", "status": "Up 2 hours", "image": "pg:16"}],
            f"cloud-op-{OP}": [
                {"id": "opreg1", "name": f"cloud-op-{OP}-registry", "service": "registry", "state": "running", "status": "Up 1 hour", "image": "reg:v1"},
                {"id": "opteg1", "name": f"cloud-op-{OP}-teg", "service": "teg-layer", "state": "running", "status": "Up 1 hour", "image": "teg:v1"},
                {"id": "opdb1", "name": f"cloud-op-{OP}-db", "service": "db", "state": "exited", "status": "Exited (0)", "image": "pg:16"}],
        },
        "inspect": {
            "opreg1": {"Config": {"Labels": {"com.docker.compose.project": f"cloud-op-{OP}",
                                             "com.docker.compose.project.working_dir": str(wd),
                                             "com.docker.compose.project.config_files": str(wd / "docker-compose.operator.yml"),
                                             "com.docker.compose.project.environment_file": str(wd / ".env.operator")},
                                  "Env": [f"SPIRE_TRUST_DOMAIN={TD}", f"REGISTRY_SAFE_NAME={OP}", "DB_PASSWORD=not-for-any-answer"]}},
            f"cloud-op-{OP}-teg": {"Config": {"Env": ['PARTNER_TEGS={"teg-layer-test": {"url": "https://parent:8443"}}',
                                                        "TEG_ADMIN_API_KEY=not-for-any-answer"]}},
        },
        "api": {},
    }

    def fake_run(cmd, **kw):
        if cmd[:2] == ["docker", "ps"]:
            project = next((a[len("label=com.docker.compose.project="):] for a in cmd if a.startswith("label=com.docker.compose.project=")), None)
            service = next((a[len("label=com.docker.compose.service="):] for a in cmd if a.startswith("label=com.docker.compose.service=")), None)
            fmt = cmd[cmd.index("--format") + 1] if "--format" in cmd else None
            rows = [r for r in world["projects"].get(project, []) if service is None or r["service"] == service]
            if "-aq" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "", "")
            if fmt == "{{.ID}}":
                out = "".join(r["id"] + "\n" for r in rows)
            elif fmt == "{{.Names}}":
                out = "".join(r["name"] + "\n" for r in rows) if project else ""
            elif fmt == FMT_CENSUS:
                out = "".join("\t".join(r[k] for k in ("id", "name", "service", "state", "status", "image")) + "\n" for r in rows)
            else:
                out = ""
            return subprocess.CompletedProcess(cmd, 0, out, "")
        if cmd[:3] == ["docker", "volume", "ls"] and "label=com.docker.compose.volume=teg-data" in cmd:
            return subprocess.CompletedProcess(cmd, world["ledger_rc"], world["ledger"], "")
        if cmd[:3] == ["docker", "volume", "ls"] and "--filter" in cmd and "-q" in cmd:
            project = next((a[len("label=com.docker.compose.project="):] for a in cmd if a.startswith("label=com.docker.compose.project=")), None)
            return subprocess.CompletedProcess(cmd, world["volumes_rc"], "".join(v + "\n" for v in world["volumes"].get(project, [])), "")
        if cmd[:3] in (["docker", "volume", "ls"], ["docker", "network", "ls"]):
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:2] == ["docker", "compose"]:
            world["compose"].append(cmd)
            return subprocess.CompletedProcess(cmd, 0, b"down\n", b"")
        if cmd[:2] == ["docker", "exec"]:
            world["execs"].append((cmd, kw.get("input")))
            if "treasury/info" in cmd[-1]:      # the app's import noise, then the one marked line
                if world.get("read_answers"):
                    http, balance = world["read_answers"].pop(0)
                    out = "INFO svid loaded\nDRAIN-JSON " + json.dumps({"status": http, "treasury_balance": balance})
                    return subprocess.CompletedProcess(cmd, 0, out, "")
                out = "INFO svid loaded\nDRAIN-JSON " + json.dumps({"status": world["info_status"], "treasury_balance": world["balance"]})
                return subprocess.CompletedProcess(cmd, 0, out, "")
            if "cross-teg-fund-send" in cmd[-1]:
                http, st = (world["send_answers"].pop(0) if world.get("send_answers")
                            else (world["send_http"], world["send_status"]))
                if http in (200, 201) and st == "completed" and not world.get("send_moves_nothing"):
                    world["balance"] = "0"   # a completed send took the whole balance (a replayed id moves nothing)
                out = "DRAIN-JSON " + json.dumps({"status": http, "result": st})
                return subprocess.CompletedProcess(cmd, world["send_rc"], out, "")
        if cmd[:1] == ["nginx"]:
            world["nginx"].append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(f"unexpected command: {cmd}")

    def spire_exec(spire, argv, stdin=None, timeout=30):
        world["spire"].append(list(argv))
        rc = world["spire_rc"].get(tuple(argv[:2]), 0)
        if argv[:2] == ["entry", "show"]:
            return {"rc": rc, "stdout": world["listing"], "stderr": "" if rc == 0 else "boom"}
        if argv[:2] == ["agent", "list"]:
            return {"rc": 0, "stdout": world["agents"], "stderr": ""}
        return {"rc": rc, "stdout": "ok\n", "stderr": "" if rc == 0 else "refused by spire"}

    monkeypatch.setattr(fr.subprocess, "run", fake_run)
    monkeypatch.setattr(runner, "_docker_inspect", lambda name: json.loads(json.dumps(world["inspect"].get(name))))
    monkeypatch.setattr(runner, "_spire_exec", spire_exec)
    monkeypatch.setattr(runner, "_frame_spire", lambda project: ("sbx-spire-server", TD))
    monkeypatch.setattr(fr, "container_of_pid", lambda pid: "c" if pid == 4242 else None)
    monkeypatch.setattr(runner, "_project_of_container", lambda cid: "sbx-1788464843" if cid == "c" else "")
    monkeypatch.setattr(runner, "_docker_api_json", lambda route, timeout=30: world["api"].get(route) or _stats_doc())
    return runner, world, wd, cfg, sites, sni, stack


def _stats_doc():
    return {"cpu_stats": {"cpu_usage": {"total_usage": 200, "percpu_usage": [1, 2]}, "system_cpu_usage": 1000, "online_cpus": 2},
            "precpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 500},
            "memory_stats": {"usage": 5 * 1024 * 1024, "limit": 100 * 1024 * 1024, "stats": {"secret-ish": 1}},
            "networks": {"eth0": {"rx_bytes": 10, "tx_bytes": 20, "rx_errors": 0}},
            "blkio_stats": {"io_service_bytes_recursive": [{"op": "Read", "value": 7, "major": 8}]},
            "name": "/x", "pids_stats": {"current": 3}}


def call(runner, op, uid=1000, pid=4242, allowed=None, **fields):
    return runner.handle({"op": op, **fields}, uid, fr.OPERATOR_OPS if allowed is None else allowed, pid=pid)


def refused(runner, op, match, **kw):
    with pytest.raises(fr.Refused) as exc:
        call(runner, op, **kw)
    assert match in str(exc.value), str(exc.value)
    return str(exc.value)


def writes(world):
    return [a for a in world["spire"] if a[:2] not in (["entry", "show"], ["agent", "list"])]


# ── where the ops are served ─────────────────────────────────────────────────────────────────────────────────────

def test_the_slice_two_ops_live_on_the_operator_socket_only(rig):
    runner, world, *_ = rig
    for op in ("operator_revoke_spire", "operator_purge", "containers_census", "container_stats"):
        assert op in fr.OPERATOR_OPS and op not in fr.OPS
    refused(runner, "containers_census", "not served on this socket", allowed=fr.OPS)


# ── operator_revoke_spire ────────────────────────────────────────────────────────────────────────────────────────

def test_revoke_with_the_node_bans_it_deletes_its_entries_and_never_evicts(rig):
    # measured 2026-09-27 on sbx-beta: an evict after the ban erased it and the operator's agent re-attested in 30 s
    runner, world, *_ = rig
    out = call(runner, "operator_revoke_spire", operator=OP, fingerprint=FP_OP.upper())
    assert writes(world) == [["agent", "ban", "-spiffeID", NODE_OP],
                             ["entry", "delete", "-entryID", "e-op-data"], ["entry", "delete", "-entryID", "e-op-reg"],
                             ["entry", "delete", "-entryID", "e-op-teg"]]
    assert not any(w[:2] == ["agent", "evict"] for w in writes(world))
    assert out["banned"] and out["evicted"] is False and out["node_listed"] and out["entries_deleted"] == 3
    assert out["agent_entries"] == 0 and not out["errors"]


def test_the_operators_ironhand_agent_entries_go_with_it_and_a_service_entry_still_refuses(rig):
    # agentvault2-a1's review: IRONHAND registers spiffe://<td>/agent/<did> with the operator's node as parent, and the
    # first rule refused the whole revoke for it, leaving the node attested while the registry wrote "revoked"
    runner, world, *_ = rig
    world["listing"] = LISTING + entry("e-agent-1", f"spiffe://{TD}/agent/did:theprotocol:abc", NODE_OP)
    out = call(runner, "operator_revoke_spire", operator=OP, fingerprint=FP_OP)
    assert ["entry", "delete", "-entryID", "e-agent-1"] in writes(world)
    assert out["agent_entries"] == 1 and out["entries_deleted"] == 4 and out["banned"] and not out["errors"]
    world["spire"].clear()
    world["listing"] = LISTING + entry("e-svc", f"spiffe://{TD}/service/sneaky", NODE_OP)
    why = refused(runner, "operator_revoke_spire", "not operator sbxop's alone", operator=OP, fingerprint=FP_OP)
    assert "nothing was changed" in why and writes(world) == []


def test_revoke_without_a_node_sweeps_only_the_operators_path(rig):
    runner, world, *_ = rig
    out = call(runner, "operator_revoke_spire", operator=OP)
    assert writes(world) == [["entry", "delete", "-entryID", e] for e in ("e-op-data", "e-op-reg", "e-op-teg")]
    assert out["node"] is None and out["banned"] is False and out["evicted"] is False
    # the prefix is a PATH: an operator named sbxopx is not operator sbxop's
    assert ["entry", "delete", "-entryID", "e-other-op"] not in world["spire"]


def test_a_withheld_path_sweep_takes_only_the_nodes_children_and_needs_a_node(rig):
    # §OPPROV: revoking a second, never-activated application under a live operator's name must not sweep its path
    runner, world, *_ = rig
    # the live namesake's entry sits under the same path, parented by ITS node, not the one being revoked
    world["listing"] = LISTING + entry("e-namesake", f"spiffe://{TD}/operator/{OP}/registry", NODE_OP.replace("a" * 40, "e" * 40))
    out = call(runner, "operator_revoke_spire", operator=OP, fingerprint=FP_OP, sweep_path=False)
    deleted = [a[3] for a in world["spire"] if a[:2] == ["entry", "delete"]]
    assert out["sweep_path"] is False and out["banned"] is True and "e-namesake" not in deleted
    assert sorted(deleted) == ["e-op-data", "e-op-reg", "e-op-teg"]
    world["spire"].clear()
    call(runner, "operator_revoke_spire", operator=OP, fingerprint=FP_OP)
    assert "e-namesake" in [a[3] for a in world["spire"] if a[:2] == ["entry", "delete"]], "the default sweeps the path"
    refused(runner, "operator_revoke_spire", "nothing would be changed", operator=OP, sweep_path=False)
    refused(runner, "operator_revoke_spire", "true or false", operator=OP, fingerprint=FP_OP, sweep_path="no")


def test_a_node_that_parents_anything_else_is_refused_with_nothing_changed(rig):
    runner, world, *_ = rig
    why = refused(runner, "operator_revoke_spire", "not operator sbxop's alone", operator=OP, fingerprint=FP_FRAME)
    assert "nothing was changed" in why and writes(world) == []


def test_an_unlisted_node_is_not_banned_but_its_path_is_still_swept(rig):
    runner, world, *_ = rig
    world["agents"] = f"SPIFFE ID : {NODE_FRAME}\n"
    out = call(runner, "operator_revoke_spire", operator=OP, fingerprint=FP_OP)
    assert out["node_listed"] is False and not out["banned"] and not out["evicted"] and out["entries_deleted"] == 3
    assert not any(a[:2] in (["agent", "ban"], ["agent", "evict"]) for a in world["spire"])


def test_revoke_arguments_are_refused_before_spire_runs(rig):
    runner, world, *_ = rig
    for fp in ("a" * 39, "g" * 40, "a" * 41, "../x", "a" * 40 + "\nentry delete"):
        refused(runner, "operator_revoke_spire", "fingerprint:", operator=OP, fingerprint=fp)
    for name in ("../x", "O", "x", None):
        refused(runner, "operator_revoke_spire", "operator:", operator=name)
    assert world["spire"] == []
    refused(runner, "operator_revoke_spire", "not the calling frame", operator=OP, frame="asia")


def test_a_failed_step_is_reported_and_the_cascade_goes_on(rig):
    runner, world, *_ = rig
    world["spire_rc"][("agent", "ban")] = 1
    out = call(runner, "operator_revoke_spire", operator=OP, fingerprint=FP_OP)
    assert out["banned"] is False and out["entries_deleted"] == 3 and out["evicted"] is False
    assert len(out["errors"]) == 1 and "agent ban" in out["errors"][0]
    world["spire_rc"][("entry", "show")] = 1
    refused(runner, "operator_revoke_spire", "entry show failed", operator=OP)


# ── operator_purge ───────────────────────────────────────────────────────────────────────────────────────────────

def test_purge_with_nothing_to_drain_takes_the_stack_the_edge_and_the_dirs(rig):
    runner, world, wd, cfg, sites, sni, stack = rig
    arch = stack / f"cloud-op-{OP}-archived-20260101-0101"
    arch.mkdir()
    keep = stack / f"cloud-op-{OP}x-archived-20260101-0101"
    keep.mkdir()
    out = call(runner, "operator_purge", operator=OP)
    assert world["compose"][-1] == ["docker", "compose", "-p", f"cloud-op-{OP}", "-f", str(wd / "docker-compose.operator.yml"),
                                    "--env-file", str(wd / ".env.operator"), "down", "-v", "--remove-orphans"]
    assert out["drain"]["ok"] and out["drain"]["drained"] is False
    assert not (sites / f"cloud-op-{OP}").exists() and f"{OP}.op.example.org" not in sni.read_text()
    assert "keep.op.example.org" in sni.read_text()                     # another host's SNI line is not touched
    assert world["nginx"][0] == ["nginx", "-t"] and ["nginx", "-s", "reload"] in world["nginx"]
    assert not wd.exists() and not arch.exists() and keep.exists()
    assert out["archives_removed"] == [arch.name] and out["edge_names"] == [f"{OP}.op.example.org"]
    assert not any("cross-teg-fund-send" in c[0][-1] for c in world["execs"])


def test_a_funded_treasury_is_drained_to_the_operators_one_partner_before_anything_goes(rig):
    runner, world, wd, *_ = rig
    world["balance"] = "12.5"
    out = call(runner, "operator_purge", operator=OP)
    send = [c for c in world["execs"] if "cross-teg-fund-send" in c[0][-1]]
    assert len(send) == 1
    cmd, body = send[0]
    # through the operator's own REGISTRY (its SVID, its TEG sidecar), never with the TEG admin key (403 since §SECFIX)
    assert cmd[:8] == ["docker", "exec", "-i", "-w", "/app", "-e", "PYTHONPATH=/app/src", "opreg1"]
    assert cmd[8:10] == ["python", "-c"] and "get_httpx_verify" in cmd[-1] and "TEG_ADMIN_API_KEY" not in cmd[-1]
    sent = json.loads(body)
    assert {k: sent[k] for k in ("amount", "target_teg_id", "reason")} == {
        "amount": "12.5", "target_teg_id": "teg-layer-test", "reason": "teardown_genesis_drain"}
    # one id per incarnation of the name (agentvault2-a1's review): a repeat is a replay the parent credits nothing for;
    # and one per drain within it (§OPPROV): a completed id is never sent again
    assert re.fullmatch(rf"td-{OP}-[0-9a-f]{{8}}-1", sent["correlation_id"]) and len(sent["correlation_id"]) <= 36
    assert out["drain"]["drained"] is True and world["compose"], "the drain comes first, then the stack goes"


def test_a_treasury_that_did_not_move_refuses_the_purge_with_nothing_removed(rig):
    runner, world, wd, cfg, sites, sni, stack = rig
    world["balance"] = "12.5"
    world["send_status"] = "failed"
    refused(runner, "operator_purge", "nothing was removed", operator=OP)
    assert world["compose"] == [] and wd.exists() and (sites / f"cloud-op-{OP}").exists()
    (wd / ".teardown-drain.json").unlink()                        # each refusal below on its own, with no drain in flight
    world["balance"] = "not a number"
    refused(runner, "operator_purge", "could not be read", operator=OP)
    world["balance"] = "3"
    world["inspect"][f"cloud-op-{OP}-teg"]["Config"]["Env"][0] = 'PARTNER_TEGS={"teg-a": {}, "teg-b": {}}'
    refused(runner, "operator_purge", "not unique", operator=OP)
    assert world["compose"] == [] and wd.exists()


def test_no_teg_container_is_nothing_to_drain_only_when_no_ledger_volume_remains(rig):
    runner, world, wd, cfg, sites, sni, stack = rig
    teg = [r for r in world["projects"][f"cloud-op-{OP}"] if r["service"] == "teg-layer"]
    world["projects"][f"cloud-op-{OP}"] = [r for r in world["projects"][f"cloud-op-{OP}"] if r["service"] != "teg-layer"]
    world["ledger"] = f"cloud-op-{OP}_teg-data\n"
    refused(runner, "operator_purge", "ledger volume remains", operator=OP)
    assert world["compose"] == [] and wd.exists() and (sites / f"cloud-op-{OP}").exists()
    world["ledger_rc"] = 1                                               # docker could not list the volumes: refused too
    refused(runner, "operator_purge", "nothing was removed", operator=OP)
    assert world["compose"] == []
    world["projects"][f"cloud-op-{OP}"] += teg + [dict(teg[0], id="opteg2", name=f"cloud-op-{OP}-teg-2")]
    refused(runner, "operator_purge", "2 TEG container(s)", operator=OP)
    assert world["compose"] == [] and wd.exists()
    world["projects"][f"cloud-op-{OP}"] = [r for r in world["projects"][f"cloud-op-{OP}"] if r["service"] != "teg-layer"]
    world["ledger"], world["ledger_rc"] = "", 0                         # never had a ledger: the purge goes on
    out = call(runner, "operator_purge", operator=OP)
    assert out["drain"] == {"ok": True, "drained": False,
                            "note": "nothing to drain: the operator runs 0 TEG container(s), not one, and no TEG ledger volume"}
    assert world["compose"] and not wd.exists()


def _never_started(world, wd, sites):
    """The host as a provision that failed before its stack came up leaves it: nothing of the operator at all."""
    import shutil as _sh
    world["projects"].pop(f"cloud-op-{OP}", None)
    _sh.rmtree(wd)
    (sites / f"cloud-op-{OP}").unlink()


def test_a_purge_of_an_operator_that_never_started_removes_nothing_and_answers(rig):
    runner, world, wd, cfg, sites, sni, stack = rig
    _never_started(world, wd, sites)
    before = sni.read_text()
    out = call(runner, "operator_purge", operator=OP)
    assert out["nothing_on_host"] is True and out["operator"] == OP
    assert out["sweep"]["containers"]["left"] == 0 and out["edge"] == [] and out["archives_removed"] == []
    assert world["compose"] == [] and world["nginx"] == [] and world["execs"] == []   # no drain, no down, no reload
    assert sni.read_text() == before


def test_any_trace_of_the_operator_keeps_the_binding_and_its_refusal(rig):
    runner, world, wd, cfg, sites, sni, stack = rig
    _never_started(world, wd, sites)
    wd.mkdir()                                                           # its stack dir alone: cannot be bound, refused
    refused(runner, "operator_purge", "registry container", operator=OP)
    assert world["compose"] == [] and wd.exists()
    wd.rmdir()
    world["volumes"][f"cloud-op-{OP}"] = [f"cloud-op-{OP}_teg-data"]     # a volume alone: refused, not destroyed
    refused(runner, "operator_purge", "registry container", operator=OP)
    world["volumes"] = {}
    world["volumes_rc"] = 1                                              # a listing that failed counts as a trace
    refused(runner, "operator_purge", "registry container", operator=OP)
    world["volumes_rc"] = 0
    (stack / f"cloud-op-{OP}-archived-20260101-0101").mkdir()            # an archive alone: refused too
    refused(runner, "operator_purge", "registry container", operator=OP)
    assert world["compose"] == [] and world["nginx"] == []
    refused(runner, "operator_purge", "not an operator name", operator="Bad Name")


def test_the_drain_reads_through_the_operators_registry_and_takes_the_tegs_notation(rig):
    runner, world, wd, *_ = rig
    world["balance"] = "0E-18"                                   # an empty treasury exactly as the TEG prints it
    out = call(runner, "operator_purge", operator=OP)
    assert out["drain"] == {"ok": True, "drained": False, "amount": "0.000000000000000000",
                            "note": "the operator treasury holds nothing to drain"}
    reads = [c for c, _ in world["execs"] if "treasury/info" in c[-1]]
    assert len(reads) == 1 and reads[0][7] == "opreg1" and "TEG_ADMIN_API_KEY" not in reads[0][-1]
    assert not any("cross-teg-fund-send" in c[-1] for c, _ in world["execs"])


def test_a_treasury_the_teg_will_not_show_or_a_nonsense_balance_refuses_the_purge(rig):
    runner, world, wd, cfg, sites, sni, stack = rig
    world["info_status"] = 403                                    # the key-era read, as every operator TEG answers it now
    refused(runner, "operator_purge", "answered 403", operator=OP)
    world["info_status"] = 200
    for bad in ("NaN", "-1", "Infinity", ""):
        world["balance"] = bad
        refused(runner, "operator_purge", "could not be read", operator=OP)
    assert world["compose"] == [] and wd.exists()
    world["balance"] = "1.25E+1"                                  # notation in, a plain amount out
    out = call(runner, "operator_purge", operator=OP)
    sends = [(c, b) for c, b in world["execs"] if "cross-teg-fund-send" in c[-1]]
    assert len(sends) == 1 and json.loads(sends[0][1])["amount"] == "12.5" and out["drain"]["drained"] is True


def test_a_node_with_agent_entries_and_none_of_the_operators_own_is_refused(rig):
    # the 2026-09-27 02:09Z restart probe: operator "wp62nobody" + the fingerprint of a node that parented only a stale
    # /agent/ entry was NOT refused and deleted it; the node must first be shown to be the operator's
    runner, world, *_ = rig
    world["listing"] = LISTING + entry("e-stale-agent", f"spiffe://{TD}/agent/did:theprotocol:old", NODE_FRAME.replace("b" * 40, "c" * 40))
    why = refused(runner, "operator_revoke_spire", "cannot be attributed", operator="nobody", fingerprint="c" * 40)
    assert "nothing was changed" in why and writes(world) == []
    why = refused(runner, "operator_revoke_spire", "cannot be attributed", operator=OP, fingerprint="c" * 40)
    assert writes(world) == []


def _record(wd):
    return json.loads((wd / ".teardown-drain.json").read_text())["drains"]


def _sends(world):
    return [json.loads(b) for c, b in world["execs"] if "cross-teg-fund-send" in c[-1]]


def test_a_drain_the_parent_did_not_confirm_is_resent_first_and_a_zero_is_never_trusted(rig):
    # agentvault2-a1's review item 3: a 503 leaves the operator TEG's row PENDING with the treasury already debited; the
    # retried purge read the empty treasury, called it drained and destroyed that row with the ledger
    runner, world, wd, cfg, sites, sni, stack = rig
    world["balance"] = "12.5"
    world["send_answers"] = [(503, "")]
    why = refused(runner, "operator_purge", "nothing was removed", operator=OP)
    assert "not confirmed" in why and world["compose"] == [] and wd.exists()
    first = _record(wd)
    assert len(first) == 1 and first[0]["state"] == "uncertain" and first[0]["amount"] == "12.5"
    cid = first[0]["correlation_id"]
    world["balance"] = "0"                                         # what the TEG shows after the debit it kept
    world["send_answers"] = [(503, "")]                            # the parent is still down: refused again
    why = refused(runner, "operator_purge", "still unconfirmed", operator=OP)
    assert cid in why and world["compose"] == [] and wd.exists()
    assert not any("treasury/info" in c[-1] for c, _ in world["execs"][-1:]), "the zero is not even read"
    assert [x["correlation_id"] for x in _sends(world)] == [cid, cid] and _sends(world)[1]["amount"] == "12.5"
    world["send_answers"] = [(400, "")]                            # an older TEG refuses the resume (balance pre-flight)
    refused(runner, "operator_purge", "still unconfirmed", operator=OP)
    assert _record(wd)[0]["state"] == "uncertain" and world["compose"] == []
    world["send_answers"] = [(200, "completed")]                   # delivered at last: then, and only then, the purge goes
    out = call(runner, "operator_purge", operator=OP)
    assert out["drain"]["ok"] and out["drain"]["drained"] is True and out["drain"]["resumed"] == [cid]
    assert [x["correlation_id"] for x in _sends(world)] == [cid] * 4 and world["compose"] and not wd.exists()


def test_a_purge_that_died_mid_send_resends_that_drain_first(rig):
    runner, world, wd, *_ = rig
    cid = runner.drain_id(OP, runner._operator_incarnation({"operator": OP, "registry_container": "opreg1"}), 1)
    (wd / ".teardown-drain.json").write_text(json.dumps({"drains": [
        {"correlation_id": cid, "amount": "7", "target": "teg-layer-test", "state": "sending"}]}))
    world["balance"] = "0"
    out = call(runner, "operator_purge", operator=OP)
    assert [x["correlation_id"] for x in _sends(world)] == [cid] and _sends(world)[0]["amount"] == "7"
    assert out["drain"]["drained"] is True and world["compose"]


def test_a_completed_drains_id_is_never_sent_again_for_a_remainder(rig):
    # the TEG answers a repeated id with the prior success and sends nothing, so the remainder was reported drained
    runner, world, wd, *_ = rig
    done = runner.drain_id(OP, runner._operator_incarnation({"operator": OP, "registry_container": "opreg1"}), 1)
    (wd / ".teardown-drain.json").write_text(json.dumps({"drains": [
        {"correlation_id": done, "amount": "10", "target": "teg-layer-test", "state": "completed"}]}))
    world["balance"] = "2.5"
    out = call(runner, "operator_purge", operator=OP)
    sent = _sends(world)
    assert len(sent) == 1 and sent[0]["amount"] == "2.5" and sent[0]["correlation_id"].endswith("-2")
    assert sent[0]["correlation_id"] != done and out["drain"]["drained"] is True


def test_a_completed_answer_with_the_value_still_there_refuses_the_purge(rig):
    # §OPPROV: the TEG answers a correlation id it already completed with that success and moves nothing; a drain whose
    # record was lost could reuse an id at the same amount. Only a treasury that READS empty after the send is drained.
    runner, world, wd, cfg, sites, sni, stack = rig
    world["balance"], world["send_moves_nothing"] = "12.5", True
    why = refused(runner, "operator_purge", "still reads 12.5", operator=OP)
    assert "nothing was removed" in why and world["compose"] == [] and wd.exists()
    assert _record(wd)[0]["state"] == "completed"
    world["send_moves_nothing"] = False                            # the retried purge drains under a new id
    out = call(runner, "operator_purge", operator=OP)
    ids = [x["correlation_id"] for x in _sends(world)]
    assert ids[0].endswith("-1") and ids[1].endswith("-2") and out["drain"]["drained"] is True and world["compose"]


def test_a_completed_drain_whose_treasury_cannot_be_reread_refuses_the_purge(rig):
    runner, world, wd, cfg, sites, sni, stack = rig
    world["balance"] = "3"
    world["read_answers"] = [(200, "3"), (503, "")]                # the read before the send, then the re-read after it
    refused(runner, "operator_purge", "could not be re-read", operator=OP)
    assert world["compose"] == [] and wd.exists() and len(_sends(world)) == 1


def test_a_parent_refusal_is_recorded_reversed_and_the_next_purge_drains_under_a_new_id(rig):
    runner, world, wd, *_ = rig
    world["balance"] = "4"
    world["send_answers"] = [(502, "")]
    why = refused(runner, "operator_purge", "re-credited", operator=OP)
    assert "nothing was removed" in why and _record(wd)[0]["state"] == "reversed"
    world["send_answers"] = [(200, "completed")]                   # the TEG put the 4 back; a new drain takes it
    out = call(runner, "operator_purge", operator=OP)
    ids = [x["correlation_id"] for x in _sends(world)]
    assert len(ids) == 2 and ids[0].endswith("-1") and ids[1].endswith("-2") and out["drain"]["drained"] is True


def test_an_unreadable_or_foreign_drain_record_refuses_with_nothing_sent_or_removed(rig):
    runner, world, wd, *_ = rig
    world["balance"] = "3"
    (wd / ".teardown-drain.json").write_text("{not json")
    refused(runner, "operator_purge", "cannot be read", operator=OP)
    own = runner.drain_id(OP, runner._operator_incarnation({"operator": OP, "registry_container": "opreg1"}), 1)
    for bad in ({"correlation_id": "td-someoneelse-aaaaaaaa-1", "amount": "3", "target": "teg-layer-test"},
                {"correlation_id": f"td-{OP}-bbbbbbbb-1", "amount": "3", "target": "teg-layer-test"},   # another incarnation
                {"correlation_id": own, "amount": "3", "target": "teg-elsewhere"},
                {"correlation_id": own, "amount": "-3", "target": "teg-layer-test"}):
        (wd / ".teardown-drain.json").write_text(json.dumps({"drains": [dict(bad, state="uncertain")]}))
        refused(runner, "operator_purge", "was not re-sent", operator=OP)
    assert _sends(world) == [] and world["compose"] == [] and wd.exists()


def test_an_operator_with_no_partner_teg_is_drained_to_its_parent_by_its_own_registrys_address(rig):
    # §OPPROV, measured on sbx-beta (opprova): every socket-route operator since §REDERIVE ships PARTNER_TEGS=[], and a
    # funded purge was refused at "0 partner TEG(s)"; the address comes from the operator's own registry now
    runner, world, wd, *_ = rig
    world["inspect"][f"cloud-op-{OP}-teg"]["Config"]["Env"][0] = "PARTNER_TEGS=[]"
    world["balance"] = "1"
    out = call(runner, "operator_purge", operator=OP)
    sent = _sends(world)
    assert len(sent) == 1 and sent[0]["target_teg_id"] == runner.DRAIN_PARENT_LABEL and "target_url" not in sent[0]
    assert out["drain"]["drained"] is True and world["compose"]
    code = runner._DRAIN_PY_SEND
    compile(code, "send", "exec")
    assert "MAINFRAME_PUBLIC_URL" in code and "_teg_dial_url" in code and "body['target_url']" in code
    assert "if m and not body.get('target_url')" in code, "a caller's own target_url is never overwritten"


def test_every_drain_id_fits_the_tegs_transaction_id_column():
    # teg_transactions.transaction_id is VARCHAR(36): measured 2026-09-27, the 37-character id was refused (400) before
    # any debit, and the slice-2 form already overflowed for any operator name of nine characters or more
    longest = fr.Runner.drain_id("a" * 40, "f" * 64, 9999)
    assert len(longest) <= fr.Runner.DRAIN_ID_MAX == 36 and fr.Runner.DRAIN_ID_RE.fullmatch(longest)
    assert fr.Runner.drain_id("sbxbetaop", "0123456789abcdef" * 4, 1) == "td-sbxbetaop-01234567-1"


def test_the_drain_record_lives_only_in_a_real_stack_dir(rig):
    # through the purge a linked or missing stack dir is already refused by the binding; the helper says so on its own
    runner, world, wd, cfg, sites, sni, stack = rig
    assert runner._drain_record({"stack_dir": ""})[:2] == (None, None)
    assert runner._drain_record({"stack_dir": str(stack / "nowhere")})[:2] == (None, None)
    link = stack / "linked"
    link.symlink_to(wd)
    assert runner._drain_record({"stack_dir": str(link)})[:2] == (None, None)
    assert runner._drain_record({"stack_dir": str(wd)}) == (str(wd / ".teardown-drain.json"), {"drains": []}, None)
    (wd / ".teardown-drain.json").write_text("[]")
    path, rec, why = runner._drain_record({"stack_dir": str(wd)})
    assert path and rec is None and "cannot be read" in why


def test_each_incarnation_of_an_operator_name_drains_under_its_own_id(rig):
    runner, world, *_ = rig
    world["inspect"]["opreg1"]["Created"] = "2026-09-27T01:00:00Z"
    a = runner._operator_incarnation({"operator": OP, "registry_container": "opreg1"})
    assert a == runner._operator_incarnation({"operator": OP, "registry_container": "opreg1"})   # stable for a retry
    world["inspect"]["opreg1"]["Created"] = "2026-09-27T02:00:00Z"                               # provisioned again
    assert runner._operator_incarnation({"operator": OP, "registry_container": "opreg1"}) != a


def test_purge_is_bound_to_the_calling_frames_operator(rig):
    runner, world, wd, *_ = rig
    world["inspect"]["opreg1"]["Config"]["Env"][0] = "SPIRE_TRUST_DOMAIN=asia.example.org"
    refused(runner, "operator_purge", "not an operator of the calling frame", operator=OP)
    assert world["compose"] == [] and world["execs"] == [] and wd.exists()


def test_no_answer_or_audit_carries_a_key_or_an_env_value(rig):
    runner, world, wd, cfg, *_ = rig
    world["balance"] = "1"
    out = call(runner, "operator_purge", operator=OP)
    text = open(os.path.join(cfg.state, "audit.jsonl")).read() + json.dumps(out)
    assert "not-for-any-answer" not in text and "https://parent:8443" not in text


# ── containers_census and container_stats ────────────────────────────────────────────────────────────────────────

def test_census_answers_the_callers_own_project_or_one_of_its_operators(rig):
    runner, world, *_ = rig
    out = call(runner, "containers_census")
    assert out["project"] == "sbx-1788464843" and [c["name"] for c in out["containers"]] == ["sbx-db", "sbx-registry"]
    out = call(runner, "containers_census", operator=OP)
    assert out["operator"] == OP and {c["service"] for c in out["containers"]} == {"registry", "teg-layer", "db"}
    world["inspect"]["opreg1"]["Config"]["Env"][0] = "SPIRE_TRUST_DOMAIN=asia.example.org"
    refused(runner, "containers_census", "not an operator of the calling frame", operator=OP)
    refused(runner, "containers_census", "operator:", operator="../x")


def test_census_does_not_wait_on_a_job_but_a_purge_does(rig, monkeypatch):
    runner, world, *_ = rig
    monkeypatch.setattr(runner, "running_jobs", lambda: [{"id": "j1", "op": "operator_teardown", "operator": OP}])
    assert call(runner, "containers_census", operator=OP)["count"] == 3
    refused(runner, "operator_purge", "is running on this operator's stack", operator=OP)


def test_stats_sample_only_running_containers_pruned_to_what_the_views_read(rig):
    runner, world, *_ = rig
    world["api"]["/containers/opteg1/stats?stream=false"] = {"cpu_stats": {}, "memory_stats": {"usage": 1, "limit": 2}}
    out = call(runner, "container_stats", operator=OP)
    assert out["count"] == 2 and {c["id"] for c in out["containers"]} == {"opreg1", "opteg1"}    # the exited db is not sampled
    s = next(c for c in out["containers"] if c["id"] == "opreg1")["stats"]
    assert set(s) == {"cpu_stats", "precpu_stats", "memory_stats", "networks", "blkio_stats"}
    assert s["memory_stats"] == {"usage": 5 * 1024 * 1024, "limit": 100 * 1024 * 1024}
    assert s["networks"] == {"eth0": {"rx_bytes": 10, "tx_bytes": 20}} and s["cpu_stats"]["online_cpus"] == 2
    assert s["blkio_stats"]["io_service_bytes_recursive"] == [{"op": "Read", "value": 7}]


def test_one_containers_stats_failure_is_reported_the_rest_still_answer(rig, monkeypatch):
    runner, world, *_ = rig

    def api(route, timeout=30):
        if "opteg1" in route:
            raise RuntimeError("the daemon said no")
        return _stats_doc()
    monkeypatch.setattr(runner, "_docker_api_json", api)
    out = call(runner, "container_stats", operator=OP)
    bad = [c for c in out["containers"] if c.get("error")]
    assert len(bad) == 1 and bad[0]["id"] == "opteg1" and bad[0]["stats"] is None
