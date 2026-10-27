"""§NIGHTPROV (2026-09-27, his words "the frame runner may build sandbox-posture frames at night"): `--wire-only`.

A nightly sandbox pair must federate through this host's stream SNI map and have its roots in the ES vhosts' bundle
refresh, and nothing else of the host: no Prometheus job, no host auditor slot (the public auditor page), no apex
vhost route and no FRESH_NETWORK_JSON tile in the production compose. `--wire-prod` writes all six pieces;
`--wire-only sni,bundle` writes the two. The fleet's frames keep `--wire-prod` byte for byte: the controls below pin
that the old flag still asks every question and writes every piece.
"""
import importlib.util
import json
import os
import pathlib
import stat

import pytest

HERE = pathlib.Path(__file__).resolve().parent


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE.parent / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


drv = _load("standup_driver_wire_only", "standup_driver.py")
sc = _load("sidecars_wire_only", "sidecars.py")
plan_tests = _load("test_standup_plan_for_wire_only", "tests/test_standup_plan.py")

BASE_ARGV = plan_tests.BASE_ARGV


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(drv, "LOG_TO_STDERR", False)
    monkeypatch.setattr(drv, "PORTS", dict(drv.PORTS))
    monkeypatch.setattr(drv, "PROGRESS", None)
    for name in drv.frame_ports.ENV_NAMES.values():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("FRAME_MAIL_SERVER", raising=False)


def _args(*extra):
    return drv.build_parser().parse_args(BASE_ARGV + list(extra))


def test_wire_prod_is_every_piece_and_wire_only_the_named_ones():
    wp = _args("--wire-prod")
    assert drv.wiring(wp) == (True, None)
    assert all(drv.wires(wp, p) for p in drv.WIRE_PIECES)
    wo = _args("--wire-only", "sni, bundle")
    assert drv.wiring(wo) == (True, {"sni", "bundle"})
    assert drv.wires(wo, "sni") and drv.wires(wo, "bundle")
    assert not any(drv.wires(wo, p) for p in ("prometheus", "auditor", "apex", "directory"))
    none = _args()
    assert drv.wiring(none) == (False, None) and not any(drv.wires(none, p) for p in drv.WIRE_PIECES)


def test_an_unknown_piece_and_two_wirings_are_refused():
    joined = "\n".join(drv.validate_args(_args("--wire-only", "sni,auditors")))
    assert "--wire-only 'sni,auditors': unknown piece(s) auditors" in joined
    joined = "\n".join(drv.validate_args(_args("--wire-only", "sni", "--wire-prod")))
    assert "--wire-prod and --wire-only name two wirings for one frame" in joined
    # control: the pair's pieces pass the check, and a frame without the flag is not refused over it
    assert not any("wire" in r for r in drv.validate_args(_args("--wire-only", "sni,bundle")))
    assert not any("wire" in r for r in drv.validate_args(_args()))


def _manifest(tmp_path):
    """A host whose SNI script, stream map and bundle refresh are there, and whose auditor and Prometheus are not."""
    sni = tmp_path / "extend_stream_sni_map.sh"
    sni.write_text("#!/bin/sh\nexit 0\n")
    conf = tmp_path / "federation-mtls.conf"
    conf.write_text("")
    refresh = tmp_path / "frame-spire-bundle.sh"
    refresh.write_text("#!/bin/sh\nexit 0\n")
    refresh.chmod(refresh.stat().st_mode | stat.S_IXUSR)
    m = {"auditor": {"env": str(tmp_path / "no-auditor.env"), "compose": str(tmp_path / "no-auditor.yml")},
         "prometheus": {"mode": "static-yml", "config": str(tmp_path / "no-prometheus.yml")},
         "bundles": {"refresh": str(refresh)}, "sni": {"script": str(sni), "conf": str(conf)}}
    path = tmp_path / "sidecars.json"
    path.write_text(json.dumps(m))
    return m, str(path)


def test_require_asks_only_about_the_named_pieces(tmp_path):
    m, _ = _manifest(tmp_path)
    assert sc.require(m, only={"sni", "bundle"}) == []
    # control: the same host fails every question --wire-prod asks (the auditor's files, the Prometheus config)
    full = sc.require(m)
    assert any("auditor" in x for x in full) and any("Prometheus" in x for x in full)
    # and the named piece is still asked: a missing SNI script is a sentence under only={"sni"}
    os.remove(m["sni"]["script"])
    assert any("SNI map script" in x for x in sc.require(m, only={"sni"}))


def test_a_plan_under_wire_only_passes_where_wire_prod_refuses(monkeypatch, capsys, tmp_path):
    _, path = _manifest(tmp_path)
    monkeypatch.setenv("FRAME_SIDECARS_MANIFEST", path)
    code, doc, _, fake = plan_tests._plan(BASE_ARGV + ["--wire-only", "sni,bundle"], monkeypatch, capsys)
    assert code == 0 and doc["ok"] is True, doc["refusals"]
    assert doc["derived"]["wire_only"] == ["bundle", "sni"] and doc["derived"]["wire_prod"] is False
    assert fake.writes == [] and fake.mutating_commands() == []
    # control: the same host under --wire-prod is refused for the auditor it lacks, with the old sentence prefix
    code, doc, _, _ = plan_tests._plan(BASE_ARGV + ["--wire-prod"], monkeypatch, capsys)
    assert code == 2 and any(r.startswith("--wire-prod: the auditor's") for r in doc["refusals"]), doc["refusals"]


def test_wire_under_only_writes_no_auditor_prometheus_or_apex(tmp_path, monkeypatch):
    """The writer half: sidecars.wire(only={"sni","bundle"}) calls the SNI and bundle writers and nothing else."""
    touched = []
    monkeypatch.setattr(sc.extras, "sni_route", lambda name, port: touched.append(("sni", name, port)) or 0)
    monkeypatch.setattr(sc.extras, "identity_nets_append", lambda net, path=None: touched.append(("net", net)) or True)
    monkeypatch.setattr(sc, "register_bundle", lambda m, name, net, log=None: touched.append(("bundle", name, net)) or {})
    for fn in ("auditor_slot", "prometheus_jobs", "apex_ws_routes", "fresh_network_upsert"):
        monkeypatch.setattr(sc.extras, fn, lambda *a, _fn=fn, **k: (_ for _ in ()).throw(AssertionError(f"{_fn} touched")))
    monkeypatch.setattr(sc, "_prom_reload", lambda m: (_ for _ in ()).throw(AssertionError("prometheus reloaded")))
    m = {"prometheus": {"mode": "static-yml", "config": str(tmp_path / "p.yml")}, "auditor": {"compose": str(tmp_path / "c.yml")},
         "apex": {"vhosts": ["theprotocol-apex"]}, "bundles": {}, "sni": {}}
    f = {"name": "nt260927x1a", "frame_label": "Nightly A", "env_label": "sandbox", "ticker": "NTA", "fed_port": 30901,
         "identity_net": "nt260927x1-identity", "operators": [], "public_url": "https://nt260927x1a.theprotocol.cloud",
         "es_public_url": "https://nt260927x1a-es.theprotocol.cloud", "es_port": 30902}
    done = sc.wire(m, f, only={"sni", "bundle"}, log=lambda *_: None)
    assert ("sni", "nt260927x1a", 30901) in touched and ("bundle", "nt260927x1a", "nt260927x1-identity") in touched
    assert set(done) == {"sni", "identity_net", "bundle"}, done
