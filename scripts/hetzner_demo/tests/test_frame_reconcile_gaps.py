"""§PROVSHOW (2026-09-15) — the frame reconcile asks the rendered compose which services must be up, never a count.

The first standup since the kit and K1 (lantern, from EU's Frame Management) aborted on "dependency failed to start:
container lantern-redpanda is unhealthy" and left five dependents Created while 20 other containers ran. The old loop
compared the running count to a literal 13, judged the stack complete, never re-issued `compose up -d`, and the Directory
gate timed out blaming SPIRE."""
from __future__ import annotations

import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("standup_driver_reconcile", os.path.join(os.path.dirname(HERE), "standup_driver.py"))
drv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drv)

EXPECTED = ["lantern-registry", "lantern-redpanda", "lantern-redpanda-init", "lantern-event-store",
            "lantern-nginx-event-store", "lantern-directory", "lantern-directory-nginx"]


def ps(*rows):
    return "\n".join("\t".join(r) for r in rows)


def test_the_lantern_state_names_the_five_created_services():
    text = ps(("lantern-registry", "running", "Up 3 minutes (healthy)"), ("lantern-redpanda", "running", "Up 3 minutes (healthy)"),
              ("lantern-redpanda-init", "created", "Created"), ("lantern-event-store", "created", "Created"),
              ("lantern-nginx-event-store", "created", "Created"), ("lantern-directory", "created", "Created"),
              ("lantern-directory-nginx", "created", "Created"))
    gaps = drv.frame_stack_gaps(EXPECTED, drv.parse_container_states(text, "lantern"))
    assert gaps == [("lantern-redpanda-init", "created"), ("lantern-event-store", "created"), ("lantern-nginx-event-store", "created"),
                    ("lantern-directory", "created"), ("lantern-directory-nginx", "created")]


def test_running_services_and_an_init_that_exited_0_are_complete():
    text = ps(*[(s, "running", "Up 2 minutes") for s in EXPECTED if not s.endswith("-init")],
              ("lantern-redpanda-init", "exited", "Exited (0) 2 minutes ago"))
    assert drv.frame_stack_gaps(EXPECTED, drv.parse_container_states(text, "lantern")) == []


def test_an_init_that_failed_and_a_service_that_exited_0_are_gaps():
    text = ps(*[(s, "running", "Up 2 minutes") for s in EXPECTED if s not in ("lantern-redpanda-init", "lantern-registry")],
              ("lantern-redpanda-init", "exited", "Exited (1) 2 minutes ago"), ("lantern-registry", "exited", "Exited (0) 1 minute ago"))
    assert drv.frame_stack_gaps(EXPECTED, drv.parse_container_states(text, "lantern")) == [
        ("lantern-registry", "exited(0)"), ("lantern-redpanda-init", "exited(1)")]


def test_missing_and_restarting_are_gaps_and_another_frames_names_are_not_read():
    text = ps(*[(s, "running", "Up 2 minutes") for s in EXPECTED if s not in ("lantern-redpanda", "lantern-directory")],
              ("lantern-redpanda", "restarting", "Restarting (1) 3 seconds ago"), ("old-lantern-directory", "running", "Up 1 hour"),
              ("lanternish-directory", "running", "Up 1 hour"))
    states = drv.parse_container_states(text, "lantern")
    assert "old-lantern-directory" not in states and "lanternish-directory" not in states
    assert drv.frame_stack_gaps(EXPECTED, states) == [("lantern-redpanda", "restarting"), ("lantern-directory", "missing")]


# §TESTBED (2026-09-19): the fields of three real containers, read from `docker inspect` on the host the moment the
# failure was found: larchsbx-nginx-edge ran with no network after 127.0.0.1:8752 was taken for an instant at its start,
# beside the sandbox's healthy registry and the parent frame's edge (the same service, published).
BINDS = {"3000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8751"}], "80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8749"}],
         "8045/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8752"}], "8200/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8711"}]}


def _inspect(state="running", mode="larchsbx_network_edge", binds=None, ports=None, nets=None):
    return {"Name": "/larchsbx-nginx-edge", "State": {"Status": state},
            "HostConfig": {"NetworkMode": mode, "PortBindings": binds if binds is not None else BINDS},
            "NetworkSettings": {"Ports": ports if ports is not None else {}, "Networks": nets if nets is not None else {}}}


def test_the_measured_edge_runs_with_no_network():
    assert drv.detachment_of(_inspect()) == "running with no network"


def test_a_healthy_container_and_the_parents_edge_are_up():
    reg = {"State": {"Status": "running"}, "HostConfig": {"NetworkMode": "larchsbx_network",
           "PortBindings": {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8700"}]}},
           "NetworkSettings": {"Ports": {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8700"}]},
                               "Networks": {"larchsbx_network": {}, "larchsbx_network_identity": {}}}}
    assert drv.detachment_of(reg) is None
    assert drv.detachment_of(_inspect(mode="larch_network_edge", ports=BINDS, nets={"larch_network_edge": {}})) is None


def test_a_port_that_did_not_publish_is_named_and_other_modes_are_not_judged():
    ports = {k: v for k, v in BINDS.items() if k != "8045/tcp"}
    assert drv.detachment_of(_inspect(ports=ports, nets={"larchsbx_network_edge": {}})) == "running with 127.0.0.1:8752 unpublished"
    for mode in ("host", "none", "container:abc"):
        assert drv.detachment_of(_inspect(mode=mode)) is None
    assert drv.detachment_of(_inspect(state="created")) is None      # a created container is frame_stack_gaps' to name


def test_the_reconcile_recreates_exactly_the_detached_services():
    assert drv.reconcile_command([]) == "docker compose -f docker-compose.frame-test.yml --env-file .env.frame-test up -d"
    cmd = drv.reconcile_command(["larchsbx-nginx-edge"])
    assert cmd.endswith("up -d --no-deps --force-recreate larchsbx-nginx-edge") and cmd.count("up -d") == 2
