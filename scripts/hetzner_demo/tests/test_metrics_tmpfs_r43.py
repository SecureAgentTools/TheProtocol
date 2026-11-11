"""V0657 (c), session-code 2026-11-06 (his approval, room seq 1409 and 1416): every service of the frame template and
of the operators' compose that sets PROMETHEUS_MULTIPROC_DIR mounts it as a tmpfs of at least 128m (contract rule R43).

sbx-alpha's registry was wedged for 11 hours: its 16m metrics tmpfs was full (212,109 counter files, the dead workers'),
so every new worker died of SIGBUS at its first write into its mmap. The operators' directory sat in the container's
layer, with no size of its own and no fill the registry can report. The registry and the TEG now fold a dead worker's
files and report the fill (AgentVault v0657/c-metrics-tmpfs); this pins the headroom into every frame and operator the
templates build. Every control below builds a compose that must fail, and fails for the reason it names.
RED on origin/master (2786ff0c): the template's three services at 16m, the operators' registry and TEG with no tmpfs.
"""
from __future__ import annotations

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("frame_template_contract_r43",
                                               ROOT / ".forgejo" / "checks" / "frame_template_contract.py")
contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(contract)

TPL = (ROOT / "templates" / "frame-test" / "docker-compose.frame-test.yml.tmpl").read_text(encoding="utf-8")
ENV = (ROOT / "templates" / "frame-test" / "frame-test.env.tmpl").read_text(encoding="utf-8")
OPS = (ROOT / "scripts" / "distribution" / "nginx-templates" / "docker-compose.operator.yml").read_text(encoding="utf-8")


def test_the_frame_template_and_the_operators_compose_have_room():
    assert contract.metrics_tmpfs_contract(TPL, ENV) == []
    assert contract.metrics_tmpfs_contract(OPS) == []


def test_it_reads_every_service_that_writes_metrics():
    """The rule's population: the store, the TEG and the registry of a frame; the registry and the TEG of an operator."""
    def writers(text):
        return sorted(n for n, b in contract._compose_blocks(text) if contract._MULTIPROC_LINE.search(b))
    assert writers(TPL) == ["{{REGISTRY_NAME}}-event-store", "{{REGISTRY_NAME}}-registry", "{{REGISTRY_NAME}}-teg"]
    assert writers(OPS) == ["registry", "teg-layer"]


def test_control_a_16m_tmpfs_fails_naming_its_service():
    old = "/tmp/prom_multiproc_reg:size=128m,mode=1777"
    assert TPL.count(old) == 1
    out = contract.metrics_tmpfs_contract(TPL.replace(old, "/tmp/prom_multiproc_reg:size=16m,mode=1777"), ENV)
    assert len(out) == 1 and out[0].startswith("{{REGISTRY_NAME}}-registry: the tmpfs at /tmp/prom_multiproc_reg"), out


def test_control_a_directory_with_no_tmpfs_fails():
    line = "      - /tmp/prom_multiproc:size=128m,mode=1777\n"
    assert OPS.count(line) == 2
    out = contract.metrics_tmpfs_contract(OPS.replace(line, "", 1))
    assert len(out) == 1 and out[0].startswith("registry: /tmp/prom_multiproc is no tmpfs of its own"), out


def test_control_the_env_template_decides_the_directory():
    """The template names its directories through the env template: a value pointing elsewhere is a directory unmounted."""
    env = ENV.replace("FT_TEG_PROMETHEUS_MULTIPROC_DIR=/tmp/prom_multiproc_teg", "FT_TEG_PROMETHEUS_MULTIPROC_DIR=/tmp/x")
    assert env != ENV
    out = contract.metrics_tmpfs_contract(TPL, env)
    assert out == ["{{REGISTRY_NAME}}-teg: /tmp/x is no tmpfs of its own (it fills the container's layer, and no fill can "
                   "be reported); mount it as `- /tmp/x:size=128m,mode=1777`"], out


def test_control_a_compose_with_no_metrics_directory_cannot_pass_quietly():
    assert contract.metrics_tmpfs_contract("services:\n  web:\n    image: nginx\n") == [
        "no service sets PROMETHEUS_MULTIPROC_DIR, so the rule cannot see its subject"]


def test_sizes_read_in_any_unit():
    assert [contract._size_mb(o) for o in ("size=128m,mode=1777", "mode=1777,size=131072k", "size=1g", "size=16m",
                                           "size=134217728", "mode=1777")] == [128.0, 128.0, 1024.0, 16.0, 128.0, None]
