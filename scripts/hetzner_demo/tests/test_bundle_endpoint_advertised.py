"""§F6 WP6.5/A4 (2026-09-27): a frame ADVERTISES a bundle endpoint a peer can reach.

Measured: every runner-built frame and sbx-beta advertised https://<name>-spire-server:8443/, a name on the frame's own
compose network that no peer frame resolves (the throwaways' endpoint was set by hand), while
https://sandbox-b.theprotocol.cloud:8565/ (the public host with the published bundle port) served sbx-beta's bundle to a
container on sbx-alpha's network. The driver now derives that shape when the caller names none, a resume keeps what the
frame was born with, and the federate step reads what the frame advertises instead of composing the internal name.
"""
import importlib.util
import inspect
import json
import os
import types

HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER_DIR = os.path.dirname(HERE)


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(DRIVER_DIR, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


drv = _load("standup_driver")
fed = _load("standup_federate")


def _args(**kw):
    return types.SimpleNamespace(**{"bundle_public_url": "", "public_url": "", **kw})


def test_a_named_endpoint_wins(monkeypatch):
    monkeypatch.setitem(drv.PORTS, "spire_bundle", 8765)
    a = _args(bundle_public_url=" https://bundle.example.org:9443/ ", public_url="https://lantern.theprotocol.cloud")
    assert drv.default_bundle_public_url(a) == "https://bundle.example.org:9443/"


def test_the_public_host_with_the_published_bundle_port(monkeypatch):
    monkeypatch.setitem(drv.PORTS, "spire_bundle", 8765)
    a = _args(public_url="https://lantern.theprotocol.cloud")
    assert drv.default_bundle_public_url(a) == "https://lantern.theprotocol.cloud:8765/"


def test_only_the_host_of_a_public_url_with_a_port_and_a_path(monkeypatch):
    monkeypatch.setitem(drv.PORTS, "spire_bundle", 8765)
    a = _args(public_url="https://lantern.theprotocol.cloud:443/ui/")
    assert drv.default_bundle_public_url(a) == "https://lantern.theprotocol.cloud:8765/"


def test_no_public_host_keeps_the_old_fallback(monkeypatch):
    monkeypatch.setitem(drv.PORTS, "spire_bundle", 8765)
    assert drv.default_bundle_public_url(_args(public_url="")) == ""
    assert drv.default_bundle_public_url(_args(public_url="not a url")) == ""


def test_a_new_standup_derives_it_once_the_ports_are_final_and_a_resume_keeps_its_birth_value():
    resume, fresh = inspect.getsource(drv.main).split('_pre("preflight")', 1)
    assert 'args.bundle_public_url = _e.get("FRAME_LOCAL_BUNDLE_ENDPOINT_URL", "")' in resume
    assert "default_bundle_public_url" not in resume   # a resume never takes a new default
    order = [fresh.index(s) for s in ("_apply_allocated_ports(args)", "default_bundle_public_url(args)",
                                      "preflight(args)", "build_ctx(")]
    assert order == sorted(order)
    assert "default_bundle_public_url(args)" in inspect.getsource(drv.plan)


def _stack(tmp_path, env_lines):
    sd = tmp_path / "f1-1"
    sd.mkdir()
    (sd / "hetzner-demo-run.json").write_text(json.dumps({"name": "f1", "ts": 1, "public_url": "https://f1.theprotocol.cloud"}))
    (sd / ".env.frame-test").write_text("\n".join(env_lines) + "\n")
    (sd / "docker-compose.frame-test.yml").write_text("services: {}\n")
    return str(sd)


def test_the_federate_step_hands_a_peer_what_the_frame_advertises(tmp_path):
    sd = _stack(tmp_path, ["FRAME_LOCAL_BUNDLE_ENDPOINT_URL=https://f1.theprotocol.cloud:8765/"])
    assert fed.frame_facts(sd)["bundle_url"] == "https://f1.theprotocol.cloud:8765/"


def test_a_frame_born_before_keeps_its_internal_name(tmp_path):
    sd = _stack(tmp_path, ["FRAME_CURRENCY=F1C"])
    assert fed.frame_facts(sd)["bundle_url"] == "https://f1-spire-server:8443/"
