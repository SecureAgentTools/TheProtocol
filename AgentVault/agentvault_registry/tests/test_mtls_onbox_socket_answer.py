"""V0650 (j) (2026-10-31, agentvault2-14): the on-box enable-mtls answer names the socket volume and path.

Order gwo_d3ef2780729cd6d6d0a74c49. The on-box answer of POST /api/v1/agent/enable-mtls told an agent to "mount the
spire-agent-socket volume": Frame A's compose KEY, not a docker volume name on any frame (Frame A's volume is
agentvault_spire_agent_socket; a template-born frame's is <prefix>_spire_socket_<ts>), and it named no socket path. The
answer now names the label in docker run form, the volume this registry itself mounts at the socket's directory (read
from /proc/self/mountinfo, never invented), the Workload API socket path from the registry's own SPIFFE_ENDPOINT_SOCKET,
and the mount line. Cases marked BASE fail on 6c1f036b (V0649).
"""
from __future__ import annotations

import pytest

from agentvault_registry.routers import agent_mtls

DID = "did:theprotocol:eu.theprotocol.cloud:00000000-0000-4000-8000-0000000000aa"
SAN = agent_mtls.sanitize_did_for_spiffe(DID)
VOL = "devframe_spire_socket_1793000000"
LINE = (f"2101 2050 9:2 /var/lib/docker/volumes/{VOL}/_data /opt/spire/sockets ro,relatime master:1 - ext4 /dev/md2 rw")


def _onbox(monkeypatch, mountinfo: str, socket_env=None, response=None) -> dict:
    monkeypatch.setattr(agent_mtls, "_read_mountinfo", lambda: mountinfo, raising=False)
    if socket_env is None:
        monkeypatch.delenv("SPIFFE_ENDPOINT_SOCKET", raising=False)
    else:
        monkeypatch.setenv("SPIFFE_ENDPOINT_SOCKET", socket_env)
    return agent_mtls._attach_delivery(dict(response or {"status": "enrolled"}), None, DID, SAN,
                                       deployment="onbox", signal="internal_network_source")


def test_the_onbox_answer_names_the_volume_the_socket_and_the_label(monkeypatch):
    # BASE: the old sentence names "the spire-agent-socket volume" and no path
    out = _onbox(monkeypatch, LINE, "unix:///opt/spire/sockets/agent.sock")
    text = out["instructions"]
    assert out["delivery"] == "workload_api"
    assert VOL in text and "/opt/spire/sockets/agent.sock" in text
    assert f"com.theprotocol.agent-did={SAN}" in text
    assert f"-v {VOL}:/opt/spire/sockets:ro" in text
    assert "spire-agent-socket volume" not in text
    assert out["socket_volume"] == VOL and out["socket_path"] == "/opt/spire/sockets/agent.sock"


@pytest.mark.parametrize("env,path", [
    ("unix:/opt/spire/sockets/agent.sock", "/opt/spire/sockets/agent.sock"),      # what svid_client writes at boot
    ("/opt/spire/sockets/agent.sock", "/opt/spire/sockets/agent.sock"),           # a plain path
    ("unix:///run/spire/sockets/agent.sock", "/run/spire/sockets/agent.sock"),    # a non-default directory
    (None, "/opt/spire/sockets/agent.sock"),                                      # unset: the default
])
def test_the_socket_path_follows_the_registrys_own_spiffe_endpoint(monkeypatch, env, path):
    # BASE: no socket_path key
    mount_dir = path.rsplit("/", 1)[0]
    line = f"2101 2050 9:2 /var/lib/docker/volumes/{VOL}/_data {mount_dir} ro,relatime - ext4 /dev/md2 rw"
    out = _onbox(monkeypatch, line, env)
    assert out["socket_path"] == path and path in out["instructions"]
    assert out["socket_volume"] == VOL and f"-v {VOL}:{mount_dir}:ro" in out["instructions"]


@pytest.mark.parametrize("mountinfo", [
    "",                                                                                  # unreadable
    "2101 2050 9:2 / /etc/hosts rw - ext4 /dev/md2 rw",                                 # no socket mount
    "2101 2050 9:2 /run/spire/sockets /opt/spire/sockets ro - tmpfs tmpfs rw",          # a host-path bind
])
def test_an_unreadable_volume_is_said_never_guessed(monkeypatch, mountinfo):
    # BASE: no socket_volume key, the guessed name in the text
    out = _onbox(monkeypatch, mountinfo, "unix:///opt/spire/sockets/agent.sock")
    text = out["instructions"]
    assert out["socket_volume"] is None and "could not read its name" in text
    assert "/opt/spire/sockets/agent.sock" in text and f"com.theprotocol.agent-did={SAN}" in text
    assert "spire-agent-socket" not in text


@pytest.mark.parametrize("root,name", [
    ("/var/lib/docker/volumes/a/_data", "a"),
    ("/volumes/b/_data", "b"),                                         # Docker Desktop's VM view
    ("/home/u/.local/share/docker/volumes/c/_data", "c"),             # rootless docker
    ("/var/lib/containers/storage/volumes/d/_data", "d"),             # podman
    ("/var/lib/docker/volumes/e/_data/sub", None),                    # a sub-directory of a volume: not the volume
])
def test_the_volume_parser_reads_docker_podman_rootless_and_desktop_roots(root, name):
    # BASE: AttributeError (no _socket_volume)
    line = f"1 2 9:2 {root} /opt/spire/sockets ro - ext4 /dev/md2 rw"
    assert agent_mtls._socket_volume("/opt/spire/sockets", line) == name


def test_the_last_mount_on_the_socket_directory_wins():
    text = "\n".join([
        "1 2 9:2 /var/lib/docker/volumes/first/_data /opt/spire/sockets ro - ext4 /dev/md2 rw",
        "3 4 9:2 /var/lib/docker/volumes/second/_data /opt/spire/sockets ro - ext4 /dev/md2 rw",
    ])
    assert agent_mtls._socket_volume("/opt/spire/sockets", text) == "second"


def test_the_already_enrolled_answer_carries_the_label(monkeypatch):
    # BASE: no docker_label on already_enrolled
    out = _onbox(monkeypatch, LINE, None, response={"status": "already_enrolled"})
    assert out["docker_label"] == f"com.theprotocol.agent-did:{SAN}"
    fresh = _onbox(monkeypatch, LINE, None, response={"status": "enrolled",
                                                       "docker_label": f"com.theprotocol.agent-did:{SAN}"})
    assert fresh["docker_label"] == f"com.theprotocol.agent-did:{SAN}"


def test_the_external_answers_are_unchanged(monkeypatch):
    # control: passes on both trees
    monkeypatch.setenv("IRONHAND_INLINE_SVID_ENABLED", "false")
    out = agent_mtls._attach_delivery({"status": "enrolled"}, None, DID, SAN,
                                      deployment="external", signal="public_source")
    assert out["delivery"] == "unavailable" and "socket_volume" not in out
