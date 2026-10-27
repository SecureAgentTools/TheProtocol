"""§F6 stage 4 (2026-09-27, runner half; live at the runner restart that goes with stage 4): the one-shot's x509pop CA
when the frame's registry no longer mounts it. The frame's OWN SPIRE server attests with the same CA: its server.conf
(a bind mount) names ca_bundle_path, and its bind at that file's directory is the source. Every link must lie in the
frame's own stack dir, and the directory must hold the key the provisioner signs with (attestation-ca.key); any missing
link refuses, as before, naming the registry's mount. While the registry keeps its /opt/spire-ca mount nothing changes.
docker is a fake here; the files are real."""
import importlib.util
import json
import pathlib
import subprocess

import pytest

HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("frame_runner_spireca", HERE.parent / "frame_runner.py")
fr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fr)


def _runner(tmp_path):
    plist = tmp_path / "protected.list"
    plist.write_text("eu\n")
    (tmp_path / "stack").mkdir(exist_ok=True)
    cfg = fr.Config(conf={"images": {"registry": ["r:1"], "teg": ["t:1"]}, "min_free_gb": 0, "max_load": 10 ** 6,
                          "min_mem_gib": 0}, state=str(tmp_path / "state"), stack_root=str(tmp_path / "stack"),
                    protected_list=str(plist))
    return fr.Runner(cfg)


def _world(tmp_path, *, registry_ca=False, conf_text=None, conf_outside=False, ca_outside=False, key=True):
    sd = tmp_path / "stack" / "beta-1"
    ca = (tmp_path / "elsewhere" / "x509pop-certs") if ca_outside else (sd / "x509pop-certs")
    ca.mkdir(parents=True, exist_ok=True)
    (ca / "attestation-ca.crt").write_text("cert")
    if key:
        (ca / "attestation-ca.key").write_text("key")
    conf = (tmp_path / "elsewhere" / "server.conf") if conf_outside else (sd / "server.conf")
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text(conf_text if conf_text is not None else
                    'plugins {\n  NodeAttestor "x509pop" {\n    plugin_data {\n'
                    '      ca_bundle_path = "/opt/spire/conf/x509pop-certs/attestation-ca.crt"\n    }\n  }\n}\n')
    tpl = tmp_path / "tpl"
    tpl.mkdir(exist_ok=True)
    reg_mounts = [{"Type": "bind", "Source": str(tpl), "Destination": "/app/nginx-templates"}]
    if registry_ca:
        reg_mounts.append({"Type": "bind", "Source": str(sd / "x509pop-certs"), "Destination": "/opt/spire-ca"})
    spire_doc = {"Config": {"Labels": {"com.docker.compose.project.working_dir": str(sd)}},
                 "Mounts": [{"Type": "bind", "Source": str(conf), "Destination": "/opt/spire/conf/server.conf"},
                            {"Type": "bind", "Source": str(ca), "Destination": "/opt/spire/conf/x509pop-certs"}]}

    def fake_run(argv, **kw):
        if argv[:3] == ["docker", "inspect", "beta-registry"]:
            env = ["SPIRE_CONTAINER=beta-spire-server", "SPIRE_TRUST_DOMAIN=beta.theprotocol.cloud"]
            return subprocess.CompletedProcess(argv, 0, json.dumps([{"Config": {"Env": env}, "Mounts": reg_mounts}]), "")
        if argv[:3] == ["docker", "inspect", "beta-spire-server"]:
            return subprocess.CompletedProcess(argv, 0, json.dumps([spire_doc]), "")
        return subprocess.CompletedProcess(argv, 1, "", "no such object")
    return {"name": "beta", "stack_dir": str(sd)}, fake_run, str(ca)


def test_a_registry_without_the_ca_mount_takes_the_ca_its_spire_server_attests_with(tmp_path, monkeypatch):
    runner = _runner(tmp_path)
    frame, fake_run, ca = _world(tmp_path)
    monkeypatch.setattr(fr.subprocess, "run", fake_run)
    binds = runner._frame_provisioner_inputs(frame)["binds"]
    assert (ca, "/opt/spire-ca") in binds


def test_control_a_registry_that_mounts_the_ca_is_read_as_before(tmp_path, monkeypatch):
    runner = _runner(tmp_path)
    frame, fake_run, ca = _world(tmp_path, registry_ca=True, key=False)   # no key: the fallback would refuse
    monkeypatch.setattr(fr.subprocess, "run", fake_run)
    assert (ca, "/opt/spire-ca") in runner._frame_provisioner_inputs(frame)["binds"]


@pytest.mark.parametrize("world", [
    dict(conf_outside=True),                                    # the server.conf is not the frame's own file
    dict(ca_outside=True),                                      # the CA directory lies outside the frame's stack
    dict(key=False),                                            # no key to sign with
    dict(conf_text="plugins {}\n"),                             # the server names no x509pop CA
])
def test_RED_a_missing_or_foreign_link_refuses_naming_the_registrys_mount(tmp_path, monkeypatch, world):
    runner = _runner(tmp_path)
    frame, fake_run, _ca = _world(tmp_path, **world)
    monkeypatch.setattr(fr.subprocess, "run", fake_run)
    with pytest.raises(fr.Refused, match="no bind mount at /opt/spire-ca"):
        runner._frame_provisioner_inputs(frame)
