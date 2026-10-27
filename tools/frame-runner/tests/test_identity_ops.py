"""§F6 WP6.1 (2026-09-26): the identity ops act on the CALLER's own SPIRE server, with every argument in its one shape.

A runner op with a too-wide argument is the docker socket by another name. So every rule here has a planted bad argument
that must be refused BEFORE anything runs (the recorder below sees no call), and a good request whose exact argv is
pinned. The SPIRE server is a recorder: nothing here touches docker, a SPIRE server or the host.
"""
import base64
import importlib.util
import json
import os
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("frame_runner_identity", HERE.parent / "frame_runner.py")
fr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fr)

TD = "sbx.example.org"
PEER = "peer.example.org"
NODE = f"spiffe://{TD}/spire/agent/x509pop/0a1b2c3d4e5f"
AGENT = f"spiffe://{TD}/agent/did-theprotocol-4c783710-64d5"
SERVICE = f"spiffe://{TD}/service/sbx-registry"
DER = base64.b64encode(bytes([0x30, 0x82]) + b"\x01" * 40).decode()
PEM = f"-----BEGIN CERTIFICATE-----\n{DER}\n-----END CERTIFICATE-----\n"
JWKS = json.dumps({"keys": [{"kty": "EC", "use": "x509-svid", "crv": "P-256", "x": "a", "y": "b", "x5c": [DER]}]})
AGENT_LIST = f"Found 1 attested agent:\n\nSPIFFE ID         : {NODE}\nAttestation type  : x509pop\n"
ENTRY_SERVICE = (f"Found 1 entry\nEntry ID         : e-service-1\nSPIFFE ID        : {SERVICE}\nParent ID        : {NODE}\n"
                 f"Revision         : 0\nX509-SVID TTL    : 14400\nSelector         : docker:label:com.agentvault.service:registry-sbx\n"
                 f"DNS name         : sbx-registry\nFederatesWith    : spiffe://old.example.org\n")
ENTRY_AGENT = (f"Found 1 entry\nEntry ID         : e-agent-1\nSPIFFE ID        : {AGENT}\nParent ID        : {NODE}\n"
               f"Selector         : docker:label:com.theprotocol.agent-did:did-theprotocol-4c783710-64d5\n")
ENTRY_FOREIGN = (f"Found 1 entry\nEntry ID         : e-foreign-1\nSPIFFE ID        : spiffe://other.example.org/service/x\n"
                 f"Parent ID        : {NODE}\n")


@pytest.fixture
def rig(tmp_path, monkeypatch):
    cfg = fr.Config(conf={"images": {"registry": ["agentvault2-registry-a:v0457"]}, "allowed_uids": [0, 1000],
                          "min_free_gb": 0, "max_load": 10 ** 6, "min_mem_gib": 0},
                    socket=str(tmp_path / "run" / "fr.sock"), state=str(tmp_path / "state"),
                    driver=str(tmp_path / "driver.py"), teardown=str(tmp_path / "td.sh"), python=sys.executable,
                    stack_root=str(tmp_path / "stack"), protected_list=str(tmp_path / "protected.list"),
                    template=str(tmp_path / "template.yml.tmpl"))
    os.makedirs(cfg.state, exist_ok=True)
    runner = fr.Runner(cfg)
    calls = []
    outputs = {("agent", "list"): AGENT_LIST}

    def spire_exec(spire, argv, stdin=None, timeout=30):
        calls.append({"spire": spire, "argv": list(argv), "stdin": stdin})
        if argv[:2] == ["entry", "show"] and "-entryID" in argv:
            eid = argv[argv.index("-entryID") + 1]
            text = {"e-service-1": ENTRY_SERVICE, "e-agent-1": ENTRY_AGENT, "e-foreign-1": ENTRY_FOREIGN}.get(eid, "Found 0 entries\n")
            return {"rc": 0, "stdout": text, "stderr": ""}
        return {"rc": 0, "stdout": outputs.get(tuple(argv[:2]), "ok\n"), "stderr": ""}

    monkeypatch.setattr(runner, "_spire_exec", spire_exec)
    monkeypatch.setattr(runner, "_frame_spire", lambda project: ("sbx-spire-server", TD))
    # the caller: pid 4242 runs in container "c" of compose project sbx-1788464843 (frame "sbx")
    monkeypatch.setattr(fr, "container_of_pid", lambda pid: "c" if pid == 4242 else None)
    monkeypatch.setattr(runner, "_project_of_container", lambda cid: "sbx-1788464843" if cid == "c" else "")
    return runner, calls, cfg


def call(runner, op, uid=1000, pid=4242, allowed=None, **fields):
    return runner.handle({"op": op, **fields}, uid, fr.OPERATOR_OPS if allowed is None else allowed, pid=pid)


def refused(runner, calls, op, match, **kw):
    before = len([c for c in calls if c["argv"][:2] != ["agent", "list"] and not (c["argv"][:2] == ["entry", "show"])])
    with pytest.raises(fr.Refused) as exc:
        call(runner, op, **kw)
    assert match in str(exc.value), str(exc.value)
    writes = [c for c in calls if c["argv"][:2] not in (["agent", "list"], ["entry", "show"])]
    assert len(writes) == before, f"{op} ran SPIRE before refusing: {writes[before:]}"


# ── binding: the caller's own frame, never a claim ───────────────────────────────────────────────────────────────

def test_a_caller_is_bound_to_its_own_frame(rig):
    runner, calls, _ = rig
    out = call(runner, "spire_entry_count")
    assert out["frame"] == "sbx" and out["trust_domain"] == TD and calls[-1]["argv"] == ["entry", "count"]
    refused(runner, calls, "spire_entry_count", "not the calling frame", frame="asia")
    refused(runner, calls, "spire_entry_count", "runs in no container", pid=999)
    refused(runner, calls, "spire_entry_count", "runs in no container", pid=None)


def test_a_project_that_is_not_a_frame_is_refused(rig, monkeypatch):
    runner, calls, _ = rig
    monkeypatch.setattr(runner, "_project_of_container", lambda cid: "forgejo")
    refused(runner, calls, "spire_entry_count", "is not a frame")


def test_the_host_names_a_project_and_only_a_plain_one(rig):
    runner, calls, _ = rig
    assert call(runner, "spire_entry_count", uid=0, pid=None, project="sbx-1788464843")["frame"] == "sbx"
    refused(runner, calls, "spire_entry_count", "project:", uid=0, pid=None, project="../etc")


def test_the_identity_ops_live_on_the_operator_socket_only(rig):
    runner, calls, _ = rig
    for op in fr.IDENTITY_OPS:
        assert op in fr.OPERATOR_OPS and op not in fr.OPS
    with pytest.raises(fr.Refused) as exc:
        call(runner, "spire_entry_count", allowed=fr.OPS)
    assert "not served on this socket" in str(exc.value)


# ── trust domains and SPIFFE ids ─────────────────────────────────────────────────────────────────────────────────

def test_a_peer_trust_domain_is_a_dns_name_and_never_our_own(rig):
    runner, calls, _ = rig
    for bad, why in ((TD, "this frame's own"), ("localhost", "not a DNS name"), ("a..b.org", "not a DNS name"),
                     ("peer.example.org;rm", "not a DNS name"), ("", "not a DNS name")):
        refused(runner, calls, "spire_bundle_delete", why, trust_domain=bad)
    call(runner, "spire_bundle_delete", trust_domain="spiffe://PEER.example.org/")
    assert calls[-1]["argv"] == ["bundle", "delete", "-mode", "dissociate", "-id", f"spiffe://{PEER}"]
    refused(runner, calls, "spire_bundle_delete", "mode:", trust_domain=PEER, mode="nuke")


def test_a_spiffe_id_lies_under_our_domain_and_a_known_kind(rig):
    runner, calls, _ = rig
    base = dict(parent_id=NODE, selectors=["docker:label:com.agentvault.service:registry-sbx"], ttl=1800)
    for bad, why in ((f"spiffe://{PEER}/service/x", "not under this frame's trust domain"),
                     (f"spiffe://{TD}/spire/agent/x509pop/ff", "is not under"),
                     (f"spiffe://{TD}/service", "names no workload"),
                     (f"spiffe://{TD}/operator/amsterdam", "names no workload"),
                     (f"spiffe://{TD}/service/../x", "unusual path segment"),
                     (f"spiffe://{TD}/service/a b", "unusual path segment"),
                     ("https://sbx.example.org/service/x", "not a SPIFFE ID")):
        refused(runner, calls, "spire_entry_create", why, spiffe_id=bad, **base)


# ── entry create: selectors, parent, DNS, TTL, federation ───────────────────────────────────────────────────────

def test_entry_create_runs_one_exact_argv(rig):
    runner, calls, _ = rig
    call(runner, "spire_entry_create", spiffe_id=SERVICE, parent_id=NODE,
         selectors=["docker:label:com.agentvault.service:registry-sbx"], dns=["sbx-registry", "SBX-Registry"], ttl=14400,
         federates_with=[PEER])
    assert calls[-1]["argv"] == ["entry", "create", "-parentID", NODE, "-spiffeID", SERVICE,
                                 "-selector", "docker:label:com.agentvault.service:registry-sbx", "-x509SVIDTTL", "14400",
                                 "-dns", "sbx-registry", "-federatesWith", f"spiffe://{PEER}"]


def test_selectors_are_the_label_key_of_the_identity_kind(rig):
    runner, calls, _ = rig
    for sid, sels, why in ((AGENT, ["docker:label:com.agentvault.service:registry-sbx"], "com.theprotocol.agent-did"),
                           (SERVICE, ["docker:label:com.theprotocol.agent-did:x"], "com.agentvault.service"),
                           (SERVICE, ["unix:uid:0"], "is not docker:label"),
                           (SERVICE, ["docker:label:com.agentvault.service:a b"], "is not docker:label"),
                           (SERVICE, [], "a list of 1 to"),
                           (SERVICE, ["docker:label:com.agentvault.service:x"] * 5, "a list of 1 to")):
        refused(runner, calls, "spire_entry_create", why, spiffe_id=sid, parent_id=NODE, selectors=sels, ttl=1800)


def test_the_parent_is_a_live_node_of_this_frame(rig):
    runner, calls, _ = rig
    sel = ["docker:label:com.agentvault.service:registry-sbx"]
    refused(runner, calls, "spire_entry_create", "not a SPIRE agent node", spiffe_id=SERVICE,
            parent_id=f"spiffe://{PEER}/spire/agent/x509pop/ab", selectors=sel, ttl=1800)
    refused(runner, calls, "spire_entry_create", "not a live node", spiffe_id=SERVICE,
            parent_id=f"spiffe://{TD}/spire/agent/x509pop/deadbeef", selectors=sel, ttl=1800)


def test_dns_names_and_ttls_are_bounded(rig):
    runner, calls, _ = rig
    base = dict(spiffe_id=SERVICE, parent_id=NODE, selectors=["docker:label:com.agentvault.service:registry-sbx"])
    refused(runner, calls, "spire_entry_create", "not a DNS name", dns=["bad_name"], ttl=1800, **base)
    refused(runner, calls, "spire_entry_create", "at most 16", dns=[f"n{i}" for i in range(17)], ttl=1800, **base)
    for ttl, why in ((10, "outside"), (86401, "outside"), ("abc", "not a number")):
        refused(runner, calls, "spire_entry_create", why, ttl=ttl, **base)
    refused(runner, calls, "spire_entry_create", "this frame's own", ttl=1800, federates_with=[TD], **base)


# ── bundles ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_bundle_is_certificates_or_public_keys_and_nothing_else(rig):
    runner, calls, _ = rig
    call(runner, "spire_bundle_set", trust_domain=PEER, format="pem", bundle=PEM)
    assert calls[-1]["argv"] == ["bundle", "set", "-id", f"spiffe://{PEER}", "-format", "pem"] and calls[-1]["stdin"] == PEM
    call(runner, "spire_bundle_set", trust_domain=PEER, format="spiffe", bundle=JWKS)
    key = "-----BEGIN " + "PRIVATE KEY-----\n" + DER + "\n-----END " + "PRIVATE KEY-----\n"   # built, never a literal header
    jwk_private = json.dumps({"keys": [{"kty": "EC", "use": "x509-svid", "d": "secret", "x5c": [DER]}]})
    for fmt, body, why in (("pem", PEM + key, "PEM certificates alone"), ("pem", "hello\n" + PEM, "PEM certificates alone"),
                           ("pem", "-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n", "PEM certificates alone"),
                           ("spiffe", jwk_private, "private part"), ("spiffe", '{"keys": []}', "at least one key"),
                           ("spiffe", json.dumps({"keys": [{"kty": "EC", "use": "x509-svid"}]}), "x5c"),
                           ("spiffe", "not json", "JSON JWK set"), ("jwks", JWKS, "format:"),
                           ("pem", PEM * (fr.MAX_BUNDLE_BYTES // len(PEM) + 1), "over")):
        refused(runner, calls, "spire_bundle_set", why, trust_domain=PEER, format=fmt, bundle=body)


# ── federation relationships ────────────────────────────────────────────────────────────────────────────────────

def test_a_federation_relationship_names_a_bundle_endpoint_and_nothing_more(rig):
    runner, calls, _ = rig
    call(runner, "spire_federation_create", trust_domain=PEER, bundle_endpoint_url="https://spire.peer.example.org:8443/")
    assert calls[-1]["argv"] == ["federation", "create", "-trustDomain", PEER, "-bundleEndpointURL",
                                 "https://spire.peer.example.org:8443", "-bundleEndpointProfile", "https_spiffe",
                                 "-endpointSpiffeID", f"spiffe://{PEER}/spire/server"]
    for url, why in (("http://spire.peer.example.org", "is not https://"), ("https://u:p@spire.peer.example.org", "is not https://"),
                     ("https://spire.peer.example.org/.well-known/x", "is not https://"), ("https://h?x=1", "is not https://"),
                     ("https://bad_host", "not a host name"), ("https://h:99999", "not a URL")):
        refused(runner, calls, "spire_federation_update", why, trust_domain=PEER, bundle_endpoint_url=url)
    refused(runner, calls, "spire_federation_create", "profile:", trust_domain=PEER,
            bundle_endpoint_url="https://spire.peer.example.org", profile="http")
    refused(runner, calls, "spire_federation_create", "not under the peer's trust domain", trust_domain=PEER,
            bundle_endpoint_url="https://spire.peer.example.org", endpoint_spiffe_id=f"spiffe://{TD}/spire/server")


# ── entries: update federates, delete ───────────────────────────────────────────────────────────────────────────

def test_update_federates_re_passes_the_whole_entry_and_adds_only(rig):
    runner, calls, _ = rig
    out = call(runner, "spire_entry_update_federates", entry_id="e-service-1", add=[PEER])
    assert out["already"] is False
    assert calls[-1]["argv"] == ["entry", "update", "-entryID", "e-service-1", "-spiffeID", SERVICE, "-parentID", NODE,
                                 "-selector", "docker:label:com.agentvault.service:registry-sbx", "-x509SVIDTTL", "14400",
                                 "-dns", "sbx-registry", "-federatesWith", "spiffe://old.example.org",
                                 "-federatesWith", f"spiffe://{PEER}"]
    n = len(calls)
    assert call(runner, "spire_entry_update_federates", entry_id="e-service-1", add=["old.example.org"])["already"] is True
    assert all(c["argv"][:2] == ["entry", "show"] for c in calls[n:])          # nothing but the read
    refused(runner, calls, "spire_entry_update_federates", "is not under /service/ or /operator/", entry_id="e-agent-1", add=[PEER])
    refused(runner, calls, "spire_entry_update_federates", "is not one entry", entry_id="e-missing", add=[PEER])
    refused(runner, calls, "spire_entry_update_federates", "at least one", entry_id="e-service-1", add=[])
    refused(runner, calls, "spire_entry_update_federates", "not a SPIRE entry ID", entry_id="e 1; ls", add=[PEER])


def test_delete_only_an_entry_of_this_frame(rig):
    runner, calls, _ = rig
    call(runner, "spire_entry_delete", entry_id="e-agent-1")
    assert calls[-1]["argv"] == ["entry", "delete", "-entryID", "e-agent-1"]
    refused(runner, calls, "spire_entry_delete", "not under this frame's trust domain", entry_id="e-foreign-1")


def test_show_filters_are_ours(rig):
    runner, calls, _ = rig
    call(runner, "spire_entry_show", spiffe_id=AGENT)
    assert calls[-1]["argv"] == ["entry", "show", "-spiffeID", AGENT]
    refused(runner, calls, "spire_entry_show", "not under this frame's trust domain", spiffe_id=f"spiffe://{PEER}/agent/x")


# ── issuance and nodes ───────────────────────────────────────────────────────────────────────────────────────────────

def test_mint_is_for_an_agent_and_its_key_never_reaches_the_audit(rig):
    runner, calls, cfg = rig
    secret = "ZmFrZS1wcml2YXRlLWtleS1ib2R5"
    runner._spire_exec = lambda spire, argv, stdin=None, timeout=30: (
        calls.append({"argv": list(argv), "stdin": stdin}) or {"rc": 0, "stdout": json.dumps([{"private_key": secret}]), "stderr": ""})
    out = call(runner, "spire_x509_mint", spiffe_id=AGENT, ttl=3600, dns=["agent.example.org"])
    assert calls[-1]["argv"] == ["x509", "mint", "-spiffeID", AGENT, "-ttl", "3600s", "-output", "json", "-dns", "agent.example.org"]
    assert secret in out["stdout"]                                             # to the caller
    audit = open(os.path.join(cfg.state, "audit.jsonl")).read()
    assert secret not in audit and "spire_x509_mint" in audit                  # never to the audit
    refused(runner, calls, "spire_x509_mint", "is not under /agent/", spiffe_id=SERVICE, ttl=3600)
    refused(runner, calls, "spire_x509_mint", "outside", spiffe_id=AGENT, ttl=10 ** 7)


def test_ban_and_evict_only_a_live_node_of_this_frame(rig):
    runner, calls, _ = rig
    call(runner, "spire_agent_ban", spiffe_id=NODE)
    assert calls[-1]["argv"] == ["agent", "ban", "-spiffeID", NODE]
    call(runner, "spire_agent_evict", spiffe_id=NODE)
    assert calls[-1]["argv"] == ["agent", "evict", "-spiffeID", NODE]
    refused(runner, calls, "spire_agent_ban", "not a live node", spiffe_id=f"spiffe://{TD}/spire/agent/x509pop/ffff")
    refused(runner, calls, "spire_agent_evict", "not a SPIRE agent node", spiffe_id=SERVICE)


# ── the exec itself: an argument list, never a shell ─────────────────────────────────────────────────────────────

def test_the_exec_is_an_argument_list_into_the_frames_own_server(tmp_path, monkeypatch):
    cfg = fr.Config(conf={"images": {}, "allowed_uids": [os.getuid()], "min_free_gb": 0, "max_load": 10 ** 6, "min_mem_gib": 0},
                    socket=str(tmp_path / "s.sock"), state=str(tmp_path / "state"), driver="d", teardown="t",
                    python=sys.executable, stack_root=str(tmp_path), protected_list=str(tmp_path / "p"), template=str(tmp_path / "t"))
    runner = fr.Runner(cfg)
    seen = []

    class R:
        returncode, stdout, stderr = 0, b"ok", b""

    def fake_run(cmd, **kw):
        seen.append((cmd, kw))
        return R()
    monkeypatch.setattr(fr.subprocess, "run", fake_run)
    runner._spire_exec("sbx-spire-server", ["bundle", "set", "-id", "spiffe://p.example.org", "-format", "pem"], stdin=PEM)
    cmd, kw = seen[-1]
    assert cmd == ["docker", "exec", "-i", "sbx-spire-server", fr.SPIRE_BIN, "bundle", "set", "-id", "spiffe://p.example.org",
                   "-format", "pem"]
    assert kw["input"] == PEM.encode() and not kw.get("shell")
    runner._spire_exec("sbx-spire-server", ["entry", "count"])
    cmd, kw = seen[-1]
    assert cmd == ["docker", "exec", "sbx-spire-server", fr.SPIRE_BIN, "entry", "count"]
    assert kw["stdin"] is fr.subprocess.DEVNULL and not kw.get("shell")
