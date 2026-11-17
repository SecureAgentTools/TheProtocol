"""§FRAMEPROV P1 (2026-09-13): a frame's nine ports (seven, plus grafana and the auditor since §SOVKIT) come from the host, never from a default two frames share.

Pinned on fixtures and fake command output; the live allocation is a read-only call made by the proof, not here.
"""
import importlib.util
import json
import os
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("frame_ports", os.path.join(os.path.dirname(HERE), "frame_ports.py"))
fp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fp)


def test_the_layout_is_the_proof_pairs_shape():
    assert fp.layout(8750) == {"registry": 8750, "es": 8761, "teg": 8762, "spire_bundle": 8765, "grafana": 8801, "auditor": 8802,
                               "spire_grpc": 8791, "push": 8799, "nginx_fed": 30763}


def test_every_port_has_its_env_name():
    assert set(fp.ENV_NAMES) == set(fp.layout(8500))


def test_the_first_free_block_wins():
    assert fp.allocate(set(), bases=[8500, 8600])["registry"] == 8500


@pytest.mark.parametrize("key", sorted(fp.layout(8500)))
def test_one_taken_port_moves_the_whole_block(key):
    taken = {fp.layout(8500)[key]}
    assert fp.allocate(taken, bases=[8500, 8600])["registry"] == 8600


def test_no_free_block_refuses_with_a_sentence():
    taken = set(fp.layout(8500).values()) | set(fp.layout(8600).values())
    with pytest.raises(fp.NoFreePorts, match="has all nine ports free"):
        fp.allocate(taken, bases=[8500, 8600])


def test_a_stack_that_recorded_ports_holds_them_while_nothing_listens(tmp_path):
    d = tmp_path / "juice-1788000000"
    d.mkdir()
    (d / "hetzner-demo-run.json").write_text(json.dumps({"ports": {"registry": 8500, "teg": 8512}, "port_push": 8549}))
    (tmp_path / "broken-1").mkdir()
    (tmp_path / "broken-1" / "hetzner-demo-run.json").write_text("{not json")
    assert fp.recorded_stack_ports(str(tmp_path)) == {8500, 8512, 8549}


def test_stopped_containers_hold_their_bindings(monkeypatch):
    def fake_run(cmd, **kw):
        if cmd[:3] == ["docker", "ps", "-aq"]:
            return subprocess.CompletedProcess(cmd, 0, "aaa\nbbb\nccc\nddd\n", "")
        if cmd[:2] == ["docker", "inspect"]:
            out = ('{"8000/tcp":[{"HostIp":"127.0.0.1","HostPort":"8350"}]}\n'
                   'null\n{}\n{"8081/tcp":[{"HostIp":"","HostPort":"8391"}]}\n')
            return subprocess.CompletedProcess(cmd, 0, out, "")
        raise AssertionError(cmd)
    monkeypatch.setattr(fp.subprocess, "run", fake_run)
    assert fp.container_bindings() == {8350, 8391}


def test_host_listeners_are_parsed(monkeypatch):
    out = ("LISTEN 0 4096 127.0.0.1:8350 0.0.0.0:*\n"
           "LISTEN 0 511 [::]:8443 [::]:*\n"
           "LISTEN 0 4096 *:30663 *:*\n")
    monkeypatch.setattr(fp.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, out, ""))
    assert fp.host_listeners() == {8350, 8443, 30663}


# §PAIRPORTS (2026-11-16, V0666's pair proof): three pairs failed on "failed to bind host port 127.0.0.1:8552" while nothing
# LISTENED there: edge-nginx held 8552 as the SOURCE port of an established connection (this host's ephemeral range is
# 1024-65535). A port the kernel holds in ANY state is taken, not only a listener.
SS_ALL = (
    "LISTEN     0 4096  127.0.0.1:8350      0.0.0.0:*\n"
    "ESTAB      0 0     127.0.0.1:8552      127.0.0.1:8461\n"
    "ESTAB      0 0     127.0.0.1:8461      127.0.0.1:8552\n"
    "TIME-WAIT  0 0     127.0.0.1:8510      127.0.0.1:8250\n"
    "ESTAB      0 0     [::1]:8612          [::1]:8461\n"
)


def _ss(cmd):
    """`ss -Hltn` lists listeners only; `ss -Hatn` lists every state: the fake answers each as ss does."""
    if "-Hltn" in cmd:
        return "".join(l + "\n" for l in SS_ALL.splitlines() if l.startswith("LISTEN"))
    return SS_ALL


def test_a_port_held_in_any_state_is_taken(monkeypatch):
    monkeypatch.setattr(fp.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, _ss(cmd), ""))
    held = fp.host_local_ports()
    assert {8350, 8552, 8461, 8510, 8612} <= held
    assert 8250 not in held   # a REMOTE port is someone else's


def test_taken_ports_counts_a_borrowed_source_port(monkeypatch, tmp_path):
    def fake_run(cmd, **kw):
        if cmd[:1] == ["ss"]:
            return subprocess.CompletedProcess(cmd, 0, _ss(cmd), "")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(fp.subprocess, "run", fake_run)
    taken = fp.taken_ports(str(tmp_path))
    assert 8552 in taken                       # the auditor port of the 8500 block, borrowed: not free
    assert fp.allocate(taken)["registry"] != 8500
