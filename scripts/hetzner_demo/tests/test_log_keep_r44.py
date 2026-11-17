"""V0667 (order gwo_4d55fcc1535962f55866740c, session-volume): the registry and the TEG of every frame and every operator keep 5 x 50 MB of logs, WRITTEN in the compose (contract rule R44).

V0666's console proof lost the award 500's traceback to log rotation: the frame template wrote `max-size: 10m, max-file: 3` for every service (30 MB of a registry's log), and a flood of
worker lines pushed the one traceback out in minutes. The operators' compose wrote nothing, so their registries kept what the HOST's daemon default happens to be (50m x 5 today): true only
while nobody edits /etc/docker/daemon.json, and invisible to a template reader. The rule: the registry and the TEG services carry an explicit `logging:` of at least 50m x 5, inline or through an
anchor the compose declares; a service with none, a smaller one, or an alias to an anchor that is not there, fails naming the service. Every control builds a compose that must fail, and fails for
the reason it names.
RED on master: the frame template's registry and TEG use the 10m x 3 anchor; the operators' registry and TEG write nothing.
"""
from __future__ import annotations

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("frame_template_contract_r44", ROOT / ".forgejo" / "checks" / "frame_template_contract.py")
contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(contract)

TPL = (ROOT / "templates" / "frame-test" / "docker-compose.frame-test.yml.tmpl").read_text(encoding="utf-8")
OPS = (ROOT / "scripts" / "distribution" / "nginx-templates" / "docker-compose.operator.yml").read_text(encoding="utf-8")
FRAME = contract.LOG_KEEP_FRAME_SERVICES
OPERATOR = contract.LOG_KEEP_OPERATOR_SERVICES

SMALL = """x-logging: &default-logging
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"
x-logging-keep: &keep-logging
  driver: json-file
  options:
    max-size: "50m"
    max-file: "5"

services:
  reg:
    image: x
    logging: *keep-logging
  teg:
    image: x
    logging: *default-logging
"""


def test_the_frame_template_and_the_operators_compose_keep_five_times_fifty():
    assert contract.log_keep_contract(TPL, FRAME) == []
    assert contract.log_keep_contract(OPS, OPERATOR) == []


def test_the_population_is_the_registry_and_the_teg_of_each_and_only_those():
    assert FRAME == ("{{REGISTRY_NAME}}-registry", "{{REGISTRY_NAME}}-teg")
    assert OPERATOR == ("registry", "teg-layer")
    names = [n for n, _b in contract._compose_blocks(TPL)]
    assert all(s in names for s in FRAME), "the frame template has both"
    assert "{{REGISTRY_NAME}}-nginx-teg" in names and "{{REGISTRY_NAME}}-nginx-teg" not in FRAME, "a service whose name merely ends in -teg is not the TEG"
    assert all(s in [n for n, _b in contract._compose_blocks(OPS)] for s in OPERATOR)


def test_the_services_that_do_not_hold_a_ledger_or_a_register_keep_what_they_kept():
    """The other services of the frame (databases, nginx, cert writers) stay on the 10m x 3 anchor: the rule is for the two whose logs are evidence."""
    for name, block in contract._compose_blocks(TPL):
        if name in FRAME or "logging:" not in block:
            continue
        assert "logging: *default-logging" in block, name


def test_control_a_10m_by_3_registry_fails_naming_it_and_the_size():
    out = contract.log_keep_contract(SMALL, ("teg",))
    assert out == ["teg: logs rotate at 10m x 3, below the 50m x 5 a registry or a TEG keeps"], out


def test_control_a_service_with_no_logging_fails_because_a_hosts_default_is_not_written():
    out = contract.log_keep_contract("services:\n  registry:\n    image: x\n    restart: unless-stopped\n", ("registry",))
    assert out == ["registry: no logging is written (the host's daemon default is not in the compose: write max-size 50m and max-file 5)"], out


def test_control_an_alias_to_an_anchor_that_is_not_declared_fails():
    out = contract.log_keep_contract("services:\n  registry:\n    image: x\n    logging: *keep-logging\n", ("registry",))
    assert out == ["registry: logging names the anchor keep-logging, which the compose does not declare"], out


def test_control_an_inline_block_is_read_as_written():
    inline = 'services:\n  registry:\n    image: x\n    logging:\n      driver: json-file\n      options:\n        max-size: "{s}"\n        max-file: "{f}"\n'
    assert contract.log_keep_contract(inline.format(s="50m", f="5"), ("registry",)) == []
    assert contract.log_keep_contract(inline.format(s="200m", f="10"), ("registry",)) == []
    assert contract.log_keep_contract(inline.format(s="50m", f="3"), ("registry",)) == ["registry: logs rotate at 50m x 3, below the 50m x 5 a registry or a TEG keeps"]
    assert contract.log_keep_contract(inline.format(s="1g", f="5"), ("registry",)) == []
    assert contract.log_keep_contract(inline.format(s="49m", f="5"), ("registry",)) == ["registry: logs rotate at 49m x 5, below the 50m x 5 a registry or a TEG keeps"]


def test_control_a_compose_without_the_service_cannot_pass_quietly():
    out = contract.log_keep_contract("services:\n  web:\n    image: nginx\n", ("registry", "teg-layer"))
    assert out == ["registry: not in the compose, so the rule cannot see its subject", "teg-layer: not in the compose, so the rule cannot see its subject"], out


def test_sizes_read_in_any_unit():
    assert [contract._log_bytes(v) for v in ("50m", "50M", "51200k", "1g", "52428800", "50mb")] == [52428800, 52428800, 52428800, 1073741824, 52428800, None]
