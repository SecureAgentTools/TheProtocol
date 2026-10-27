"""§PROVSHOW (2026-09-15) — a resume restores the kit's loopback ports, never the provisioner's defaults in silence.

The first resume of lantern (from EU's Frame Management) died on "kit: grafana never answered on 127.0.0.1:8201". The run
meta recorded the base ports and the push port, never grafana (8551) or the solo auditor (8552), so the resumed process
built its context from FRAME_TEST_PORT_GRAFANA's default and probed Frame B's store port, which answered 404."""
from __future__ import annotations

import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("standup_driver_kitports", os.path.join(os.path.dirname(HERE), "standup_driver.py"))
drv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drv)


def _isolate(monkeypatch):
    monkeypatch.setattr(os, "environ", {k: v for k, v in os.environ.items() if not k.startswith("FRAME_TEST_PORT_")})
    monkeypatch.setattr(drv, "PORTS", dict(drv.PORTS))


def test_the_run_meta_kit_ports_reach_the_environment_without_asking_docker(monkeypatch):
    _isolate(monkeypatch)
    def refuse(container):
        raise AssertionError("asked docker although the meta had the port")
    monkeypatch.setattr(drv, "_published_port", refuse)
    drv._restore_ports_from_meta({"name": "lantern", "ports": {"registry": 8500}, "port_push": 8549, "port_grafana": 8551, "port_auditor": 8552})
    assert os.environ["FRAME_TEST_PORT_GRAFANA"] == "8551" and os.environ["FRAME_TEST_PORT_AUDITOR"] == "8552"


def test_a_meta_without_kit_ports_reads_the_running_containers_and_records_them(monkeypatch):
    _isolate(monkeypatch)
    monkeypatch.setattr(drv, "_published_port", {"lantern-grafana": 8551, "lantern-auditor": 8552}.get)
    meta = {"name": "lantern", "ports": {"registry": 8500}, "port_push": 8549}
    drv._restore_ports_from_meta(meta)
    assert os.environ["FRAME_TEST_PORT_GRAFANA"] == "8551" and os.environ["FRAME_TEST_PORT_AUDITOR"] == "8552"
    assert meta["port_grafana"] == 8551 and meta["port_auditor"] == 8552


def test_an_unknown_kit_port_leaves_the_environment_alone(monkeypatch):
    _isolate(monkeypatch)
    monkeypatch.setattr(drv, "_published_port", lambda container: None)
    drv._restore_ports_from_meta({"name": "lantern", "ports": {}})
    assert "FRAME_TEST_PORT_GRAFANA" not in os.environ and "FRAME_TEST_PORT_AUDITOR" not in os.environ


def test_published_port_reads_the_first_mapping_of_docker_port(monkeypatch):
    class Done:
        stdout = "3000/tcp -> 127.0.0.1:8551\n3000/tcp -> [::1]:8551\n"
        returncode = 0
    monkeypatch.setattr(drv.subprocess, "run", lambda *a, **k: Done())
    assert drv._published_port("lantern-grafana") == 8551
