"""§NIGHTPROV (2026-09-27): `--registry-workers`. The nightly pair is the MCP tester's second target, and its posture follows
the standing one's (sbx-alpha) wherever the suites measured a difference. sbx-alpha's registry runs 8 gunicorn workers; a
runner-built frame takes the provisioner's default, 4. On nt260927x3 (the tester at sbx-alpha's concurrency 10) two
RFC 7807 probes each spent their whole 20 s budget on one attempt while the probe between them passed, on x2 (concurrency
4) neither did. The runner passes the count from its policy; 0 keeps the provisioner's default, byte for byte.
"""
import importlib.util
import pathlib

import pytest

HERE = pathlib.Path(__file__).resolve().parent


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE.parent / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


drv = _load("standup_driver_registry_workers", "standup_driver.py")
plan_tests = _load("test_standup_plan_for_registry_workers", "tests/test_standup_plan.py")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(drv, "LOG_TO_STDERR", False)
    monkeypatch.setattr(drv, "PORTS", dict(drv.PORTS))
    monkeypatch.setattr(drv, "PROGRESS", None)
    for name in drv.frame_ports.ENV_NAMES.values():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("FRAME_MAIL_SERVER", raising=False)


def _rendered_workers(monkeypatch, *extra):
    plan_tests.HostFake(monkeypatch)
    args = drv.build_parser().parse_args(list(plan_tests.BASE_ARGV) + list(extra))
    assert drv.validate_args(args) == []
    prov = drv.load_provisioner()
    return prov, prov._template_values(drv.build_ctx(args, 1789290319, prov))["WORKERS_REG"]


def test_the_count_reaches_the_registrys_command_line(monkeypatch):
    _prov, workers = _rendered_workers(monkeypatch, "--registry-workers", "8")
    assert workers == 8


def test_no_flag_keeps_the_provisioners_default(monkeypatch):
    prov, workers = _rendered_workers(monkeypatch)
    assert workers == prov.DEFAULT_WORKERS_REG, "the fleet's frames render exactly what they rendered before"
    _prov, zero = _rendered_workers(monkeypatch, "--registry-workers", "0")
    assert zero == prov.DEFAULT_WORKERS_REG


@pytest.mark.parametrize("bad", ["17", "-1", "64"])
def test_a_count_outside_1_to_16_is_refused(bad):
    args = drv.build_parser().parse_args(list(plan_tests.BASE_ARGV) + ["--registry-workers", bad])
    assert any("--registry-workers" in r for r in drv.validate_args(args))
