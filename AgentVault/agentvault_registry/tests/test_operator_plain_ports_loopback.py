"""§SECFIX-8 (2026-09-25): an operator provisioned under this host's nginx edge binds its plain registry and TEG
ports to loopback.

Measured before: every operator on the network published its plain-http registry and TEG on 0.0.0.0 and [::], and the
DOCKER-USER chain is empty, so Docker's published ports bypass ufw: nothing on the host filtered them, and anything that
could route to the host reached them around host nginx, its vhost rules and CrowdSec (not tested from outside). Host nginx proxies to 127.0.0.1:<reg_port>, Prometheus reaches the containers by
name, and no peer row or environment value dials those ports, so loopback loses nothing. The federation lane (mTLS)
stays public. A Caddy edge keeps the bridge gateway it needs.

RED on the pre-change tree: all six (measured; the helpers do not exist there, and the direct provisioning path passed
no bind address at all). The control's claim, that an unbound line is the old line, holds before and after.
"""
from __future__ import annotations

from agentvault_registry.core import operator_compose as oc
from agentvault_registry.services import cloud_provisioner as cp

TEMPLATE = '''services:
  registry:
    ports:
      - "12000:8000"
  nginx-federation:
    ports:
      - "12443:8443"
  teg-layer:
    ports:
      - "12080:8080"
'''


def _adapt(bind):
    out, _notes = oc.adapt_operator_compose(
        TEMPLATE, safe="probeop", domain="probeop.example", reg_port=31600, fed_port=31643, teg_port=31680,
        worker_count=4, identity_network="probe_identity", bind_address=bind)
    return out


def test_this_hosts_nginx_edge_binds_loopback_by_default():
    assert oc.plain_port_bind("nginx", "172.17.0.1", None) == "127.0.0.1"


def test_a_caddy_edge_keeps_the_bridge_gateway():
    assert oc.plain_port_bind("caddy", "172.17.0.1", None) == "172.17.0.1"
    assert oc.plain_port_bind("caddy", "172.17.0.1", "127.0.0.1") == "172.17.0.1"


def test_the_override_names_an_address_and_empty_restores_every_interface():
    assert oc.plain_port_bind("nginx", "172.17.0.1", " 10.0.0.5 ") == "10.0.0.5"
    assert oc.plain_port_bind("nginx", "172.17.0.1", "") == ""


def test_loopback_binds_the_registry_and_teg_and_leaves_the_federation_lane_public():
    out = _adapt("127.0.0.1")
    assert oc.port_line("127.0.0.1", 31600, 8000) in out and '"127.0.0.1:31600:8000"' in out
    assert '"127.0.0.1:31680:8080"' in out
    assert '"31643:8443"' in out and '"127.0.0.1:31643:8443"' not in out


def test_the_direct_path_passes_the_bind_and_verifies_the_line_it_wrote():
    src = open(cp.__file__).read()
    call = src[src.index("compose, _adapt_notes = adapt_operator_compose("):]
    call = call[:call.index(")")]
    assert "bind_address=_bind_address" in call, "the direct provisioning path must pass the bind address"
    assert 'port_line(_bind_address, reg_port, 8000) in _written' in src
    assert """f'"{reg_port}:8000"' in _written""" not in src, "the old check cannot see a bound line"


def test_control_the_port_line_without_a_bind_is_the_old_line():
    assert oc.port_line("", 31600, 8000) == '"31600:8000"'
    assert '"31600:8000"' in _adapt("")
