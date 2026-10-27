"""§HELLOFRAME lane 6 (2026-09-18): a cloud operator on a frame that lives on a stranger's host.

Four things the provisioner used to assume about the host it runs on, each measured on the sandbox pair and each a
parameter now: the operator's public names (three literals naming op.theprotocol.cloud), the image host in the
compose (images.theprotocol.cloud, so a host whose images are local tags had to invent a pull token), the edge (a
host nginx vhost plus an SNI line, which a frame-up host does not have), and the port binds (every interface, which
on a stranger's host publishes an operator's plain-http registry to the internet). The network's own host must come
out byte-identical from every change here: the first assertion of every block is that control.
"""
import json
import sys
import types

import pytest

from agentvault_registry import host_work
from agentvault_registry.core import host_reach
from agentvault_registry.core.operator_compose import (adapt_operator_compose, images_prefix_is_local,
                                                       operator_public_urls)
from agentvault_registry.services import operator_provision_client as opc

# the shape of scripts/distribution/nginx-templates/docker-compose.operator.yml around the three port placeholders,
# with the image lines the way the template writes them since lane 6 (`${IMAGES_PREFIX:-images.theprotocol.cloud}`)
TEMPLATE = (
    "services:\n"
    "  nginx-federation:\n"
    "    image: nginx:1.25-alpine\n"
    "    container_name: ${REGISTRY_NAME:-operator}-nginx-federation\n"
    "    ports:\n"
    '      - "12443:8443"\n'
    "  registry:\n"
    "    image: ${IMAGES_PREFIX:-images.theprotocol.cloud}/registry:${VERSION:-stable}\n"
    "    ports:\n"
    '      - "12000:8000"\n'
    "  teg-layer:\n"
    "    image: ${IMAGES_PREFIX:-images.theprotocol.cloud}/teg-layer:${VERSION:-stable}\n"
    "    container_name: ${REGISTRY_NAME:-operator}-teg\n"
    "    restart: unless-stopped\n"
)
OLD_TEMPLATE = TEMPLATE.replace("${IMAGES_PREFIX:-images.theprotocol.cloud}/", "images.theprotocol.cloud/")


def _adapt(text, **over):
    kw = dict(safe="harborop", domain="harborop.harbor.example", reg_port=31600, fed_port=31643, teg_port=31680,
              worker_count=4, identity_network="harbor_network_identity")
    kw.update(over)
    out, _notes = adapt_operator_compose(text, **kw)
    return out


# ---- the port binds ---------------------------------------------------------------------------------------------

def test_without_a_bind_address_the_three_port_lines_are_what_they_always_were():
    out = _adapt(TEMPLATE)
    assert '"31643:8443"' in out and '"31600:8000"' in out and '      - "31680:8080"\n' in out
    assert "172.17.0.1" not in out


def test_a_bind_address_binds_the_registry_and_teg_ports_and_leaves_the_federation_lane_public():
    out = _adapt(TEMPLATE, bind_address="172.17.0.1")
    assert '"172.17.0.1:31600:8000"' in out
    assert '      - "172.17.0.1:31680:8080"\n' in out, out
    assert '"31643:8443"' in out and '"172.17.0.1:31643' not in out, "peers dial the mTLS lane: it stays public"
    assert '"31600:8000"' not in out


def test_the_teg_placeholder_form_takes_the_bind_too():
    text = TEMPLATE.replace("    restart: unless-stopped\n", '    restart: unless-stopped\n    ports:\n      - "12080:8080"\n')
    assert '"172.17.0.1:31680:8080"' in _adapt(text, bind_address="172.17.0.1")
    assert '"31680:8080"' in _adapt(text)


def test_the_teg_fallback_matches_the_new_image_line_and_still_the_old_literal():
    assert '      - "31680:8080"\n' in _adapt(TEMPLATE), "the ${IMAGES_PREFIX:-...} line"
    assert '      - "31680:8080"\n' in _adapt(OLD_TEMPLATE), "the pre-lane-6 literal (an older bundle)"
    # a template without the teg-layer block at all is a note, never an exception (the caller reads the notes)
    out, notes = adapt_operator_compose(TEMPLATE.split("  teg-layer:")[0], safe="x", domain="x.y", reg_port=1,
                                        fed_port=2, teg_port=3, worker_count=1, identity_network="n")
    assert "8080" not in out and any("teg-layer" in n for n in notes)


# ---- the public names --------------------------------------------------------------------------------------------

def test_the_networks_own_host_gets_the_three_literals_it_always_wrote():
    urls = operator_public_urls(safe="jelgava", suffix="op.theprotocol.cloud")
    assert urls == {"PUBLIC_URL": "https://jelgava.op.theprotocol.cloud",
                    "BILATERAL_PEER_URL": "https://jelgava.op.theprotocol.cloud:8443",
                    "PUBLIC_UI_URL": "https://jelgava.op.theprotocol.cloud"}


def test_a_foreign_frame_names_the_operator_under_its_own_name_on_its_own_lane_port():
    urls = operator_public_urls(safe="harborop", suffix="harbor.example", lane_port=31643)
    assert urls == {"PUBLIC_URL": "https://harborop.harbor.example",
                    "BILATERAL_PEER_URL": "https://harborop.harbor.example:31643",
                    "PUBLIC_UI_URL": "https://harborop.harbor.example"}
    assert operator_public_urls(safe="a", suffix=".b.example.")["PUBLIC_URL"] == "https://a.b.example"


# ---- local images -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("prefix,local", [
    ("agentvault2", True), ("agentvault2/", True), ("theprotocol", True),
    ("images.theprotocol.cloud", False), ("registry:5000/tp", False), ("localhost/tp", False),
    ("ghcr.io/theprotocol", False), ("", False),
])
def test_a_prefix_is_local_by_dockers_own_rule(prefix, local):
    assert images_prefix_is_local(prefix) is local


def _secrets():
    return {k: "s" * 40 for k in opc.SECRET_KEYS}


def test_the_spec_still_refuses_to_leave_without_a_pull_token_by_default(monkeypatch):
    monkeypatch.setenv("SPIRE_CONTAINER", "harbor-spire-server")
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "harbor.example")
    with pytest.raises(opc.SpecIncomplete) as e:
        opc.build_operator_spec(operator_name="Harbor Op", safe_name="harborop",
                                operator_did="did:theprotocol:operator:harborop", frame="harbor",
                                docker_pull_token="", operator_secrets=_secrets(), phase="stack", env={"A": "b"})
    assert "docker_pull_token" in str(e.value)
    spec = opc.build_operator_spec(operator_name="Harbor Op", safe_name="harborop",
                                   operator_did="did:theprotocol:operator:harborop", frame="harbor",
                                   docker_pull_token="tok", operator_secrets=_secrets(), phase="stack", env={})
    assert spec["docker_pull_token"] == "tok" and "images_local" not in spec


def test_local_images_send_no_token_and_say_so_with_an_absent_key(monkeypatch):
    monkeypatch.setenv("SPIRE_CONTAINER", "harbor-spire-server")
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "harbor.example")
    spec = opc.build_operator_spec(operator_name="Harbor Op", safe_name="harborop",
                                   operator_did="did:theprotocol:operator:harborop", frame="harbor",
                                   docker_pull_token="", operator_secrets=_secrets(), phase="stack", env={},
                                   local_images=True)
    assert "docker_pull_token" not in spec, "absent, not empty: an empty field claims it applies"
    assert spec["images_local"] is True
    assert spec["operator_secrets"] == _secrets() and spec["phase"] == "stack"


def _spec_file(tmp_path, **over):
    spec = {"phase": "stack", "operator_name": "Harbor Op", "safe_name": "harborop",
            "operator_did": "did:theprotocol:operator:harborop", "frame": "harbor", "stack_root": "/srv/frames",
            "job_id": "job1", "bundle_filename": "harborop.tar.gz", "operator_secrets": _secrets(),
            "compose": {"domain": "harborop.harbor.example"}, "spire_container": "harbor-spire-server",
            "spire_trust_domain": "harbor.example"}
    spec.update(over)
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(spec))
    return str(p)


def test_the_one_shot_requires_the_pull_token_unless_the_images_are_local(tmp_path):
    with pytest.raises(host_work.HostWorkRefused) as e:
        host_work.read_spec(_spec_file(tmp_path))
    assert "docker_pull_token" in str(e.value)
    spec = host_work.read_spec(_spec_file(tmp_path, images_local=True))
    assert spec["images_local"] is True and "docker_pull_token" not in spec
    # a string "true" is not the flag: only the boolean the builder writes lifts the requirement
    with pytest.raises(host_work.HostWorkRefused):
        host_work.read_spec(_spec_file(tmp_path, images_local="true"))
    assert host_work.read_spec(_spec_file(tmp_path, docker_pull_token="tok"))["docker_pull_token"] == "tok"


def test_the_one_shot_passes_the_bind_address_to_the_one_adapter():
    """The socket path and the one-shot adapt through ONE function; the one-shot must hand it the bind it was sent."""
    src = open(host_work.__file__).read()
    assert 'bind_address=str(c.get("bind_address") or "")' in src
    assert 'if spec.get("images_local") is True:' in src


# ---- the edge posture, as the registry learns it ----------------------------------------------------------------

def _frc(monkeypatch, tmp_path, *, envelope=None, raise_exc=False, socket_exists=True):
    mod = types.ModuleType("agentvault_registry.services.frame_runner_client")
    sock = tmp_path / "operator.sock"
    if socket_exists:
        sock.write_text("")
    mod.socket_path = lambda: str(sock)
    mod.operator_socket_path = mod.socket_path   # the stand-in's one socket is its operator socket

    def _exchange(path, request, timeout):
        assert request == {"op": "operator_ping"} and path == str(sock)
        if raise_exc:
            raise OSError("no runner")
        return envelope

    mod._exchange = _exchange
    # the way the sibling tests fake it: `from agentvault_registry.services import frame_runner_client` resolves
    # the PACKAGE attribute first, so sys.modules alone would leave the real module in place
    import agentvault_registry.services as pkg
    monkeypatch.setattr(pkg, "frame_runner_client", mod, raising=False)
    monkeypatch.setitem(sys.modules, "agentvault_registry.services.frame_runner_client", mod)


def test_the_edge_is_nginx_unless_the_runner_answers_caddy(monkeypatch, tmp_path):
    _frc(monkeypatch, tmp_path, envelope={"ok": True, "result": {"edge": "caddy", "socket": "operator"}})
    assert host_reach.runner_edge() == "caddy"
    _frc(monkeypatch, tmp_path, envelope={"ok": True, "result": {"socket": "operator"}})
    assert host_reach.runner_edge() == "nginx", "a runner too old to answer the field"
    _frc(monkeypatch, tmp_path, envelope={"ok": True, "result": {"edge": "traefik"}})
    assert host_reach.runner_edge() == "nginx", "an edge this registry does not know is not guessed"
    _frc(monkeypatch, tmp_path, envelope={"ok": False, "refused": "not on this socket"})
    assert host_reach.runner_edge() == "nginx"
    _frc(monkeypatch, tmp_path, raise_exc=True)
    assert host_reach.runner_edge() == "nginx"
    _frc(monkeypatch, tmp_path, socket_exists=False)
    assert host_reach.runner_edge() == "nginx"


def test_the_provisioner_derives_the_edge_the_binds_and_the_names_from_the_route_decision():
    """Pinned on the source: the four decisions sit together right after the socket-or-runner decision, so a fifth
    literal about the host cannot be added far from where the host is asked what it is."""
    from agentvault_registry.services import cloud_provisioner as cp
    src = open(cp.__file__).read()
    assert '_edge_mode = runner_edge() if _through_runner else "nginx"' in src
    assert ('_bind_address = plain_port_bind(_edge_mode, os.getenv("DOCKER_BRIDGE_GATEWAY", "172.17.0.1"), '
            'os.getenv("OPERATOR_PLAIN_PORT_BIND"))') in src
    assert "_images_local = images_prefix_is_local(IMAGES_PREFIX)" in src
    assert 'lane_port=(fed_port if _edge_mode == "caddy" else 8443)' in src
    assert 'f.write(f"PUBLIC_URL={_public[\'PUBLIC_URL\']}\\n")' in src
    assert 'f.write(f"IMAGES_PREFIX={IMAGES_PREFIX}\\n")' in src
    assert '"https://{safe}.op.theprotocol.cloud' not in src, "no operator name literal survives in the provisioner"
    assert "commander:" not in src, "no monitoring credential literal survives in the provisioner"
    # the Prometheus the operators read: unset = the network's own, set and EMPTY = no line at all
    assert 'if "OPERATOR_PROMETHEUS_URL" in os.environ:' in src and "if _prom_url:" in src
    assert 'if _edge_mode != "caddy":' in src and '"mode": _edge_mode, "bind_address": _bind_address' in src
    assert cp.IMAGES_PREFIX == "images.theprotocol.cloud" or images_prefix_is_local(cp.IMAGES_PREFIX) in (True, False)


def test_the_operators_list_says_unknown_when_it_cannot_measure_health():
    from agentvault_registry.routers import cloud_operators as rco
    src = open(rco.__file__).read()
    assert 'health_note = "not measurable here: CLOUD_OP_HEALTH_HOST_IP is unset on this frame"' in src
    assert 'raise RuntimeError("CLOUD_OP_HEALTH_HOST_IP unset")' not in src, "unset used to read as unhealthy"
    assert '"health_note": health_note,' in src
    # the census asks the READ question (docker_daemon_available), never the host-work one (§TESTBED narrowed that)
    assert "_sock_ok, _sock_why = docker_daemon_available()" in src
    assert "_sock_ok, _sock_why = docker_socket_available()" not in src
    # the health probe goes to the gateway on every frame: a registry's loopback is its own container
    assert '_probe_host = os.getenv("DOCKER_BRIDGE_GATEWAY", "172.17.0.1")' in src
    assert '"127.0.0.1" if _sock_ok' not in src
    assert 'containers = {} if _sock_ok else {"note": f"not measurable here: {_sock_why}"}' in src



def test_an_operator_under_a_local_prefix_pulls_the_frames_own_docker_tag(monkeypatch):
    """§HELLOFRAME: the export tags images by release while the card keeps the constant; the operator's compose must
    name the tag that exists. The network's host (a registry-host prefix) keeps the card chain unchanged."""
    from agentvault_registry.services import cloud_provisioner as cp
    monkeypatch.setenv("OPERATOR_IMAGES_PREFIX", "theprotocol"); monkeypatch.setenv("VERSION", "1.0.0-beta.4")
    assert cp.operator_image_version("MoreCompliantThenYourWholeComplianceFrameworkV0397") == "1.0.0-beta.4"
    monkeypatch.setenv("OPERATOR_IMAGES_PREFIX", "images.theprotocol.cloud")
    assert cp.operator_image_version("MoreCompliantThenYourWholeComplianceFrameworkV0397") == "MoreCompliantThenYourWholeComplianceFrameworkV0397"
    monkeypatch.setenv("OPERATOR_IMAGES_PREFIX", "theprotocol"); monkeypatch.delenv("VERSION", raising=False)
    assert cp.operator_image_version("X") == "X"   # no own tag known: the chain stays


# ---- the two docker questions (§TESTBED narrowed host work; the census only reads) --------------------------------

def _fake_docker(monkeypatch, *, answers=True):
    class _Client:
        def __init__(self, *a, **kw):
            pass

        def ping(self):
            if not answers:
                raise ConnectionError("daemon down")
            return True

    fake = types.ModuleType("docker")
    fake.DockerClient = _Client
    monkeypatch.setitem(sys.modules, "docker", fake)


def test_a_sandbox_socket_answers_the_read_question_and_not_the_host_work_one(monkeypatch):
    """The shape §TESTBED measured on larchsbx: the socket, no /host-stack. Host work goes to the runner; a container
    census through the same socket still works, so the detail route keeps its census there."""
    monkeypatch.setattr(host_reach.os.path, "exists", lambda p: p == "/var/run/docker.sock")
    monkeypatch.setattr(host_reach.os.path, "isdir", lambda p: False)
    _fake_docker(monkeypatch)
    read_ok, read_why = host_reach.docker_daemon_available()
    work_ok, work_why = host_reach.docker_socket_available()
    assert read_ok is True and "answers" in read_why
    assert work_ok is False and "/host-stack" in work_why


def test_the_read_question_is_false_without_a_socket_or_a_daemon(monkeypatch):
    monkeypatch.setattr(host_reach.os.path, "exists", lambda p: False)
    _fake_docker(monkeypatch)
    ok, why = host_reach.docker_daemon_available()
    assert ok is False and "docker.sock" in why
    monkeypatch.setattr(host_reach.os.path, "exists", lambda p: p == "/var/run/docker.sock")
    _fake_docker(monkeypatch, answers=False)
    ok, why = host_reach.docker_daemon_available()
    assert ok is False and "ConnectionError" in why


def test_full_host_reach_answers_both_questions(monkeypatch):
    """EU, ASIA, the sandbox pair and the three mainframes today: the socket AND /host-stack (measured 2026-09-19)."""
    monkeypatch.setattr(host_reach.os.path, "exists", lambda p: p == "/var/run/docker.sock")
    monkeypatch.setattr(host_reach.os.path, "isdir", lambda p: p == "/host-stack")
    _fake_docker(monkeypatch)
    assert host_reach.docker_daemon_available()[0] is True
    assert host_reach.docker_socket_available()[0] is True

