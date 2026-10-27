"""§SOVKIT K2 (2026-09-14, his word "4 sidecars only") — the store-sidecar retrofit renders from the TEMPLATE and derives
everything else from the frame's own stack: the certs volume and the two networks from the nginx-teg block, the stack dir
from its conf mount, the proxy marker from the env; the SPIRE entry update re-passes everything and appends the one SAN.
Pure parts only here (no docker): derive, the block, the conf, the env lines, the entry parser and its argv.
"""
from __future__ import annotations

import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import retrofit_es_sidecar as rf  # noqa: E402

MARKER = "m" * 64
SHOW = """Found 1 entry
Entry ID         : a8cc72eb-0cb9-4cf0-bc68-155807c7be57
SPIFFE ID        : spiffe://sandbox-a.theprotocol.cloud/service/sbx-alpha-registry
Parent ID        : spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/dae5b651
Revision         : 3
X509-SVID TTL    : 14400
JWT-SVID TTL     : default
Selector         : docker:label:com.agentvault.service:svid-writer-sbx-alpha
FederatesWith    : sandbox-b.theprotocol.cloud
DNS name         : sbx-alpha-nginx-federation
DNS name         : sbx-alpha-nginx-teg
DNS name         : sandbox-a.theprotocol.cloud
"""


def _stack(tmp_path, name="sbx-alpha", marker=MARKER, with_es_block=False, mtls="${FT_ES_EVENTSTORE_MTLS_REQUIRED}"):
    host = f"/opt/theprotocol/stack/{name}-1788462456"
    compose = f"""services:
  {name}-event-store:
    image: agentvault2-event-store:sovkit1
    environment:
      EVENTSTORE_MTLS_REQUIRED: {mtls}
  {name}-nginx-teg:
    image: nginx:1.25-alpine
    volumes:
      - {host}/nginx-teg-frame-test.conf:/etc/nginx/conf.d/default.conf:ro
      - {host}/nginx-entrypoint.sh:/opt/nginx-entrypoint.sh:ro
      - {name.replace('-', '_')}_svid_certs_1788462456:/certs:ro
    networks:
      - {name.replace('-', '_')}_network
      - sandbox-federation-identity
    depends_on:
      {name}-cert-writer:
        condition: service_started
"""
    if with_es_block:
        compose += f"  {name}-nginx-event-store:\n    image: nginx:1.25-alpine\n"
    compose += f"volumes:\n  {name.replace('-', '_')}_svid_certs_1788462456:\n"
    (tmp_path / "docker-compose.frame-test.yml").write_text(compose)
    env = f"SPIRE_TRUST_DOMAIN=sandbox-a.theprotocol.cloud\nFT_CERT_DIR=/certs\n"
    if marker:
        env += f"ES_PROXY_TRUST_SECRET={marker}\n"
    (tmp_path / ".env.frame-test").write_text(env)
    return str(tmp_path)


def test_derive_reads_the_frames_own_shape(tmp_path):
    d = rf.derive(_stack(tmp_path))
    assert d["name"] == "sbx-alpha" and d["certs_volume"] == "sbx_alpha_svid_certs_1788462456"
    assert d["host_stack_dir"] == "/opt/theprotocol/stack/sbx-alpha-1788462456"
    assert (d["net"], d["identity_net"]) == ("sbx_alpha_network", "sandbox-federation-identity")
    assert d["marker"] == MARKER and d["env_present"]["FT_CERT_DIR"] is True and d["env_present"]["FT_NGES_SERVICE_NAME"] is False


def test_a_socket_shaped_template_is_refused_for_a_tcp_frame(tmp_path):
    """§MTLSHOPS T2 (S4): the template's store sidecar reaches the store through a unix socket, which a frame whose store
    listens on TCP does not have; rendering it would give that frame a gateway to nothing, so both renders refuse."""
    d = rf.derive(_stack(tmp_path))
    with pytest.raises(rf.Refused) as e:
        rf.render_block(d)
    assert "mounts the store's socket" in str(e.value) and "listens on TCP" in str(e.value)
    with pytest.raises(rf.Refused) as e:
        rf.render_conf(d)
    assert "proxies to a unix socket" in str(e.value)


def test_env_lines_add_only_what_is_missing_and_copy_the_frames_marker(tmp_path):
    d = rf.derive(_stack(tmp_path)); lines = rf.env_lines(d)
    keys = [l.split("=", 1)[0] for l in lines]
    assert keys == ["FT_NGES_RELOAD_SEC", "FT_NGES_SERVICE_NAME", "FT_NGES_PROXY_TRUST_SECRET", "FT_EVENT_STORE_MTLS_URL"], keys
    assert f"FT_NGES_PROXY_TRUST_SECRET={MARKER}" in lines and "FT_EVENT_STORE_MTLS_URL=https://sbx-alpha-nginx-event-store:8443" in lines


def test_entry_update_re_passes_everything_and_appends_the_san_once():
    e = rf.parse_entry_show(SHOW)
    argv = rf.entry_update_argv(e, "sbx-alpha-nginx-event-store")
    assert argv[:5] == ["/opt/spire/bin/spire-server", "entry", "update", "-entryID", "a8cc72eb-0cb9-4cf0-bc68-155807c7be57"]
    assert argv[argv.index("-selector") + 1] == "docker:label:com.agentvault.service:svid-writer-sbx-alpha"
    dns = [argv[i + 1] for i, a in enumerate(argv) if a == "-dns"]
    assert dns == ["sbx-alpha-nginx-federation", "sbx-alpha-nginx-teg", "sandbox-a.theprotocol.cloud", "sbx-alpha-nginx-event-store"]
    assert argv[argv.index("-x509SVIDTTL") + 1] == "14400"
    assert argv[argv.index("-federatesWith") + 1] == "spiffe://sandbox-b.theprotocol.cloud"
    again = rf.entry_update_argv(rf.parse_entry_show(SHOW.replace("DNS name         : sandbox-a.theprotocol.cloud", "DNS name         : sandbox-a.theprotocol.cloud\nDNS name         : sbx-alpha-nginx-event-store")), "sbx-alpha-nginx-event-store")
    assert again.count("sbx-alpha-nginx-event-store") == 1, "a SAN already there is not repeated (SPIRE refuses a duplicate)"


@pytest.mark.parametrize("kw,why", [({"with_es_block": True}, "already exists"), ({"marker": ""}, "no proxy marker"), ({"mtls": '"false"'}, "mTLS-required posture")])
def test_refusals_name_their_reason(tmp_path, kw, why):
    with pytest.raises(rf.Refused) as e:
        rf.derive(_stack(tmp_path, **kw))
    assert why in str(e.value)


def test_a_stack_without_the_teg_block_is_refused(tmp_path):
    (tmp_path / "docker-compose.frame-test.yml").write_text("services:\n  x-registry:\n    image: a\nvolumes:\n")
    (tmp_path / ".env.frame-test").write_text(f"ES_PROXY_TRUST_SECRET={MARKER}\n")
    with pytest.raises(rf.Refused) as e:
        rf.derive(str(tmp_path))
    assert "nginx-teg" in str(e.value)
