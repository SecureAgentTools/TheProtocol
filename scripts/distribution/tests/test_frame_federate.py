"""frame-federate.py (§HELLOFRAME D2): the argv builders and parsers mirror the registry's own
(services/frame_trust_manager.py, services/frame_test_provisioner.py); the fact readers, the endpoint refusals, the
root counting and the waits are exercised with fakes. No docker, no network."""
import importlib.util
import json
import os
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("frame_federate", HERE.parent / "frame-federate.py")
ff = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ff          # dataclasses resolve postponed annotations through sys.modules[cls.__module__]
SPEC.loader.exec_module(ff)


# ── the frame's facts ──────────────────────────────────────────────────────────────────────────────────────────────

ENV = """# rendered
REGISTRY_NAME=lantern
SPIRE_TRUST_DOMAIN=lantern.example.org
FT_REG_SPIRE_CONTAINER=lantern-spire-server
FT_CW_REFRESH_SEC=120
FT_CERT_DIR=/certs
ADMIN_PASSWORD="not-read-by-the-program"
"""
COMPOSE = """services:
  lantern-spire-server:
    container_name: lantern-spire-server
  lantern-nginx-federation:
    container_name: lantern-nginx-federation
  lantern-nginx-teg:
    container_name: lantern-nginx-teg
  lantern-registry:
    container_name: lantern-registry
    ports:
      - "127.0.0.1:8150:8000"
  lantern-nginx-event-store:
    container_name: lantern-nginx-event-store
"""


def test_parse_env_strips_quotes_and_ignores_comments():
    env = ff.parse_env(ENV)
    assert env["REGISTRY_NAME"] == "lantern"
    assert env["ADMIN_PASSWORD"] == "not-read-by-the-program"
    assert "# rendered" not in env


def test_frame_facts_reads_name_domain_spire_port_refresh_and_terminators():
    f = ff.frame_facts("/stack", ENV, COMPOSE)
    assert (f.name, f.trust_domain, f.spire_container, f.registry_port, f.refresh_sec, f.cert_dir) == \
        ("lantern", "lantern.example.org", "lantern-spire-server", 8150, 120, "/certs")
    assert f.terminators == ["lantern-nginx-federation", "lantern-nginx-teg", "lantern-nginx-event-store", "lantern-registry"]
    assert f.missing == []


def test_frame_facts_refuses_with_a_sentence_when_the_port_or_domain_is_missing():
    with pytest.raises(ff.Refused, match="publishes no registry port"):
        ff.frame_facts("/stack", ENV, COMPOSE.replace('"127.0.0.1:8150:8000"', '"8150:8000"'))
    with pytest.raises(ff.Refused, match="SPIRE_TRUST_DOMAIN"):
        ff.frame_facts("/stack", ENV.replace("SPIRE_TRUST_DOMAIN=lantern.example.org\n", ""), COMPOSE)
    with pytest.raises(ff.Refused, match="names no container"):
        ff.frame_facts("/stack", ENV, COMPOSE.replace("container_name: lantern-spire-server\n", ""))


def test_load_facts_names_the_missing_file(tmp_path):
    with pytest.raises(ff.Refused, match=r"\.env\.frame-test does not exist"):
        ff.load_facts(str(tmp_path))
    (tmp_path / ".env.frame-test").write_text(ENV)
    (tmp_path / "docker-compose.frame-test.yml").write_text(COMPOSE)
    assert ff.load_facts(str(tmp_path)).name == "lantern"


# ── mirrors of the registry's builders ───────────────────────────────────────────────────────────────────────────

def test_spire_endpoint_from_url_drops_the_path_and_keeps_the_port():
    assert ff.spire_endpoint_from_url("https://peer.example:8443/.well-known/spire-bundle") == "https://peer.example:8443"
    assert ff.spire_endpoint_from_url("https://peer-spire.example/") == "https://peer-spire.example"
    assert ff.spire_endpoint_from_url("peer.example:8465") == "https://peer.example:8465"
    assert ff.spire_endpoint_from_url("") == ""


def test_federation_create_argv_is_the_registrys():
    assert ff.federation_create_argv("peer.example", "https://peer.example:8465") == [
        "/opt/spire/bin/spire-server", "federation", "create",
        "-trustDomain", "peer.example",
        "-bundleEndpointURL", "https://peer.example:8465",
        "-bundleEndpointProfile", "https_spiffe",
        "-endpointSpiffeID", "spiffe://peer.example/spire/server"]


def test_plan_relationship_already_create_skip():
    listing = "Found 1 federation relationship\n\nTrust domain              : peer.example\nBundle endpoint URL       : https://old:8443\nBundle endpoint profile   : https_spiffe\nEndpoint SPIFFE ID        : spiffe://peer.example/spire/server\n"
    existing = ff.parse_federation_list(listing)
    assert existing == {"peer.example": {"url": "https://old:8443", "profile": "https_spiffe",
                                         "endpoint_spiffe_id": "spiffe://peer.example/spire/server"}}
    d, argv, detail = ff.plan_relationship(existing, "PEER.example", "https://peer-spire.example/")
    assert d == "already" and argv is None and detail["url"] == "https://old:8443"   # an existing one is never touched
    d, argv, detail = ff.plan_relationship({}, "other.example", "https://other-spire.example/")
    assert d == "create" and argv[2] == "create" and detail["endpoint_spiffe_id"] == "spiffe://other.example/spire/server"
    d, argv, _ = ff.plan_relationship({}, "other.example", "")
    assert d == "skip" and argv is None


def test_parse_bundle_list_reads_the_star_lines():
    text = "****************************************\n* peer.example\n****************************************\n-----BEGIN CERTIFICATE-----\nAAA\n-----END CERTIFICATE-----\n"
    assert ff.parse_bundle_list(text) == ["peer.example"]
    assert ff.parse_bundle_list("") == []


ENTRY_SHOW = """Found 3 entries

Entry ID         : e1
SPIFFE ID        : spiffe://lantern.example.org/service/lantern-registry
Parent ID        : spiffe://lantern.example.org/spire/agent/x509pop/abc
Revision         : 2
X509-SVID TTL    : 14400
JWT-SVID TTL     : default
Selector         : docker:label:com.agentvault.service:registry-lantern
DNS name         : lantern-nginx-federation
DNS name         : lantern.example.org
FederatesWith    : spiffe://old.example

Entry ID         : e2
SPIFFE ID        : spiffe://lantern.example.org/service/teg-layer
Parent ID        : spiffe://lantern.example.org/spire/agent/x509pop/abc
X509-SVID TTL    : default
Selector         : docker:label:com.agentvault.service:teg-core-lantern
FederatesWith    : spiffe://peer.example

Entry ID         : e3
SPIFFE ID        : spiffe://lantern.example.org/service/data
Parent ID        : spiffe://lantern.example.org/spire/agent/x509pop/abc
Selector         : docker:label:com.agentvault.service:svid-writer-data-lantern

Entry ID         : e4
SPIFFE ID        : spiffe://lantern.example.org/agent/some-agent
Parent ID        : spiffe://lantern.example.org/spire/agent/x509pop/abc
Selector         : unix:uid:1000
"""


def test_parse_entry_show_matches_the_provisioners_fields():
    es = ff.parse_entry_show(ENTRY_SHOW)
    assert [e["entry_id"] for e in es] == ["e1", "e2", "e3", "e4"]
    e1 = es[0]
    assert e1["dns"] == ["lantern-nginx-federation", "lantern.example.org"]
    assert e1["federates_with"] == ["old.example"] and e1["ttl"] == "14400"
    assert es[1]["ttl"] is None                        # `default` reads as None, the way the provisioner reads it


def test_entry_update_argv_is_a_replace_that_keeps_everything_and_adds_the_peer():
    e = ff.parse_entry_show(ENTRY_SHOW)[0]
    argv = ff.entry_update_argv(e, ff.merge_federates_with(e["federates_with"], ["PEER.example"]))
    assert argv[:5] == ["/opt/spire/bin/spire-server", "entry", "update", "-entryID", "e1"]
    assert argv[5:9] == ["-spiffeID", "spiffe://lantern.example.org/service/lantern-registry",
                         "-parentID", "spiffe://lantern.example.org/spire/agent/x509pop/abc"]
    assert argv.count("-dns") == 2 and argv.count("-selector") == 1
    assert "-x509SVIDTTL" in argv and argv[argv.index("-x509SVIDTTL") + 1] == "14400"
    fw = [argv[i + 1] for i, a in enumerate(argv) if a == "-federatesWith"]
    assert fw == ["spiffe://old.example", "spiffe://peer.example"]     # existing first, the new one appended, lowercased


def test_federate_entries_updates_services_skips_data_and_agents_counts_already():
    calls = []

    def exec_fn(argv):
        calls.append(argv)
        if argv[1:3] == ["entry", "show"]:
            return 0, ENTRY_SHOW
        return 0, "Entry updated"

    d = ff.federate_entries(exec_fn, "peer.example")
    assert d == {"peer": "peer.example", "updated": 1, "already": 1, "failed": [], "skipped": 2}
    updates = [c for c in calls if c[1:3] == ["entry", "update"]]
    assert len(updates) == 1 and updates[0][4] == "e1"


def test_federate_entries_reports_a_failed_update_and_a_failed_show():
    def failing(argv):
        if argv[1:3] == ["entry", "show"]:
            return 0, ENTRY_SHOW
        return 1, "rpc error: unique dns"

    d = ff.federate_entries(failing, "peer.example")
    assert d["updated"] == 0 and len(d["failed"]) == 1 and "e1" not in d["failed"][0] and "service/lantern-registry" in d["failed"][0]
    with pytest.raises(ff.StepFailed, match="entry show"):
        ff.federate_entries(lambda argv: (1, "boom"), "peer.example")


def test_bundle_set_argv_stage_path_and_format_detection():
    assert ff.bundle_set_argv("PEER.example", "/tmp/frame_bundle_peer.example.spiffe", "spiffe") == [
        "/opt/spire/bin/spire-server", "bundle", "set", "-id", "spiffe://peer.example",
        "-path", "/tmp/frame_bundle_peer.example.spiffe", "-format", "spiffe"]
    assert ff.bundle_stage_path("peer.example", "pem") == "/tmp/frame_bundle_peer.example.pem"
    assert ff.bundle_stage_path("a b/c", "spiffe") == "/tmp/frame_bundle_a_b_c.spiffe"
    assert ff.detect_bundle_format('{"keys": []}') == "spiffe"
    assert ff.detect_bundle_format("\n-----BEGIN CERTIFICATE-----\n") == "pem"


# ── the peer's card and the endpoint refusals ─────────────────────────────────────────────────────────────────────

def test_card_facts_reads_trust_domain_and_bundle_endpoint():
    card = {"identity": {"trust_domain": "Peer.Example"}, "federation": {"spire_bundle_endpoint": "https://peer-spire.example/"}}
    assert ff.card_facts(card) == ("peer.example", "https://peer-spire.example/")
    with pytest.raises(ff.Refused, match="identity.trust_domain"):
        ff.card_facts({"federation": {}})


def _resolver(answers):
    def resolve(host, port):
        if host not in answers:
            raise socket_error()
        return [(None, None, None, None, (a, 0)) for a in answers[host]]
    return resolve


def socket_error():
    return OSError("[Errno -2] Name or service not known")


def test_endpoint_refusal_names_docker_internal_unresolvable_and_loopback_addresses():
    r = _resolver({"peer-spire.example": ["203.0.113.5"], "self.example": ["127.0.0.1"]})
    assert ff.endpoint_refusal("https://peer-spire.example/", resolve=r) is None
    assert "docker-internal" in ff.endpoint_refusal("https://sbx-beta-spire-server:8443/", resolve=r)
    assert "does not resolve" in ff.endpoint_refusal("https://nowhere.example/", resolve=r)
    assert "only to loopback" in ff.endpoint_refusal("https://self.example:8465/", resolve=r)
    assert "not https" in ff.endpoint_refusal("http://peer-spire.example/", resolve=r)
    assert "names no federation.spire_bundle_endpoint" in ff.endpoint_refusal("", resolve=r)


def test_licence_prefix_reads_the_finalize_note():
    assert ff.licence_prefix("approved\n[framelic] licence issued by approver, prefix tp_fed_0123abcd") == "tp_fed_0123abcd"
    assert ff.licence_prefix("nothing here") is None
    assert ff.licence_prefix(None) is None


# ── the admin secret, by shape, never printed ─────────────────────────────────────────────────────────────────────

def test_read_admin_secret_by_shape(tmp_path):
    p = tmp_path / ".lantern_frame_admin.secret.json"
    p.write_text(json.dumps({"admin_email": "admin@lantern.example.org", "admin_password": "s3cr3t-value-never-shown",
                             "registry_port": 8150, "note": "seeded"}))
    assert ff.read_admin_secret(str(p)) == ("admin@lantern.example.org", "s3cr3t-value-never-shown")
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"frames": {"x": {"password": "s3cr3t-value-never-shown"}}}))
    with pytest.raises(ff.Refused) as ei:
        ff.read_admin_secret(str(other))
    assert "admin_email and admin_password" in str(ei.value) and "s3cr3t-value-never-shown" not in str(ei.value)
    with pytest.raises(ff.Refused, match="does not exist"):
        ff.read_admin_secret(str(tmp_path / "missing.json"))


# ── the root counting and the waits, with fakes ──────────────────────────────────────────────────────────────────

def test_root_counts_reads_grep_c_and_tolerates_a_silent_container():
    def exec_in(container, argv):
        assert argv == ["grep", "-c", "BEGIN CERT", "/certs/bundle.0.pem"]
        return {"a": (0, "5\n"), "b": (0, "6\n"), "c": (1, "")}.get(container, (125, "no such container"))
    assert ff.root_counts(exec_in, ["a", "b", "c", "d"], "/certs") == {"a": 5, "b": 6, "c": 0, "d": None}
    assert ff.count_roots("-----BEGIN CERTIFICATE-----\nx\n-----BEGIN CERTIFICATE-----") == 2


def test_wait_for_roots_returns_when_every_terminator_gained_a_root():
    polls = {"n": 0}

    def exec_in(container, argv):
        polls["n"] += 1
        late = {"fed": 6 if polls["n"] > 2 else 5, "teg": 6}
        return 0, f"{late[container]}\n"

    clock = iter(range(0, 10_000, 5)).__next__
    logged = []
    now = ff.wait_for_roots(exec_in, ["fed", "teg"], "/certs", {"fed": 5, "teg": 5}, 120,
                            clock=clock, sleep=lambda s: None, log=logged.append)
    assert now == {"fed": 6, "teg": 6}
    assert any("waiting: fed=5" in l for l in logged)


def test_wait_for_roots_times_out_naming_the_refresh_clock():
    def exec_in(container, argv):
        return 0, "5\n"
    t = {"now": 0.0}

    def clock():
        t["now"] += 100.0
        return t["now"]

    with pytest.raises(ff.TimedOut) as ei:
        ff.wait_for_roots(exec_in, ["lantern-nginx-federation"], "/certs", {"lantern-nginx-federation": 5}, 120,
                          clock=clock, sleep=lambda s: None, log=lambda *_: None)
    msg = str(ei.value)
    assert "FT_CW_REFRESH_SEC=120" in msg and "lantern-cert-writer" in msg and "270 s" in msg


# ── the steps with fake transports ───────────────────────────────────────────────────────────────────────────────

def _facts():
    return ff.frame_facts("/stack", ENV, COMPOSE)


def test_step3_import_runs_cp_set_create_and_entries_in_order(monkeypatch):
    ran = []

    def exec_in(container, argv):
        ran.append((container, argv))
        if argv[1:3] == ["bundle", "list"]:
            return 0, "****\n* someone.else\n****\n"
        if argv[1:3] == ["federation", "list"]:
            return 0, "Found 0 federation relationships\n"
        if argv[1:3] == ["entry", "show"]:
            return 0, ENTRY_SHOW
        return 0, "ok"

    copied = []

    def cp(src, container, dest):
        copied.append((os.path.exists(src), container, dest))

    def fetch(method, url, **kw):
        assert kw.get("verify") is False and url == "https://peer-spire.example/"
        return 200, json.dumps({"keys": [{"use": "x509-svid"}]})

    out = ff.step3_import(_facts(), "peer.example", "https://peer-spire.example/", exec_in=exec_in, cp=cp, fetch=fetch,
                          log=lambda *_: None)
    assert out["format"] == "spiffe" and out["already_held"] is False and out["relationship"] == "create"
    assert copied == [(True, "lantern-spire-server", "/tmp/frame_bundle_peer.example.spiffe")]
    kinds = [tuple(a[1][1:3]) for a in ran]
    assert kinds[:4] == [("bundle", "list"), ("bundle", "set"), ("federation", "list"), ("federation", "create")]
    assert ("entry", "show") in kinds and ("entry", "update") in kinds
    create = [a for c, a in ran if a[1:3] == ["federation", "create"]][0]
    assert create[create.index("-bundleEndpointURL") + 1] == "https://peer-spire.example"


def test_step3_import_refuses_a_console_answer_and_a_bad_status():
    facts = _facts()
    with pytest.raises(ff.StepFailed, match="not a SPIFFE bundle"):
        ff.step3_import(facts, "peer.example", "https://peer.example/", exec_in=lambda c, a: (0, ""), cp=lambda *a: None,
                        fetch=lambda m, u, **kw: (200, "<html>console</html>"), log=lambda *_: None)
    with pytest.raises(ff.StepFailed, match="answered 400"):
        ff.step3_import(facts, "peer.example", "https://peer.example:8443/", exec_in=lambda c, a: (0, ""),
                        cp=lambda *a: None, fetch=lambda m, u, **kw: (400, "No required SSL certificate"), log=lambda *_: None)
    # §EXTREACH: a terminator behind a client certificate names the way out, and a plain bad status does not claim one
    with pytest.raises(ff.StepFailed, match="--peer-bundle-endpoint"):
        ff.step3_import(facts, "peer.example", "https://peer.example:8443/", exec_in=lambda c, a: (0, ""),
                        cp=lambda *a: None, fetch=lambda m, u, **kw: (400, "No required SSL certificate"), log=lambda *_: None)
    with pytest.raises(ff.StepFailed) as plain:
        ff.step3_import(facts, "peer.example", "https://peer.example:8444/", exec_in=lambda c, a: (0, ""),
                        cp=lambda *a: None, fetch=lambda m, u, **kw: (502, "Bad Gateway"), log=lambda *_: None)
    assert "--peer-bundle-endpoint" not in str(plain.value)


def test_step5_outbound_logs_in_with_the_form_and_posts_the_body_without_printing_the_password():
    seen = []

    def post(method, url, **kw):
        seen.append((method, url, kw))
        if url.endswith("/auth/login"):
            assert kw["form"] == {"username": "admin@lantern.example.org", "password": "pw-never-printed"}
            return 200, {"access_token": "tok"}
        assert kw["headers"] == {"Authorization": "Bearer tok"}
        assert kw["body"] == {"target_registry_url": "https://peer.example", "contact_email": "admin@lantern.example.org",
                              "description": "hello", "spire_bundle_imported": True}
        return 201, {"id": "abc-123", "status": "pending"}

    logged = []
    token = ff.admin_login(_facts(), "admin@lantern.example.org", "pw-never-printed", post=post)
    inv_id = ff.step5_outbound(_facts(), "https://peer.example", token, "admin@lantern.example.org", "hello", post=post, log=logged.append)
    assert (inv_id, token) == ("abc-123", "tok")
    assert seen[0][1] == "http://127.0.0.1:8150/api/v1/auth/login"
    assert "pw-never-printed" not in " ".join(logged)


def test_existing_outbound_asks_for_every_status():
    asked = []

    def get(method, url, **kw):
        asked.append(url); return 200, {"items": []}
    assert ff.existing_outbound(_facts(), "https://peer.example", "tok", get=get) is None
    assert "status=all" in asked[0]


def test_step5_outbound_names_a_missing_endpoint_and_a_bad_login():
    with pytest.raises(ff.StepFailed, match="predates it"):
        ff.step5_outbound(_facts(), "https://peer.example", "tok", "a@b", "d", post=lambda m, u, **kw: (404, {"detail": "Not Found"}), log=lambda *_: None)
    with pytest.raises(ff.StepFailed, match="do not log in"):
        ff.admin_login(_facts(), "a@b", "pw", post=lambda m, u, **kw: (401, {"detail": "bad"}))


def test_step6_wait_polls_to_completed_and_times_out_with_a_sentence():
    answers = iter([(200, {"status": "pending"}), (200, {"status": "approved"}),
                    (200, {"status": "completed", "completed_at": "t", "peer_registry_id": 7,
                           "review_notes": "[framelic] licence issued by approver, prefix tp_fed_ab"})])
    clock = iter(range(0, 100_000, 5)).__next__
    inv = ff.step6_wait(_facts(), "abc", "tok", 20, get=lambda m, u, **kw: next(answers), clock=clock,
                        sleep=lambda s: None, log=lambda *_: None)
    assert inv["peer_registry_id"] == 7 and ff.licence_prefix(inv["review_notes"]) == "tp_fed_ab"
    t = {"now": 0.0}

    def slow_clock():
        t["now"] += 600.0
        return t["now"]

    with pytest.raises(ff.TimedOut, match="20 minutes"):
        ff.step6_wait(_facts(), "abc", "tok", 20, get=lambda m, u, **kw: (200, {"status": "pending"}), clock=slow_clock,
                      sleep=lambda s: None, log=lambda *_: None)
    with pytest.raises(ff.StepFailed, match="rejected"):
        ff.step6_wait(_facts(), "abc", "tok", 20, get=lambda m, u, **kw: (200, {"status": "rejected", "rejection_reason": "no"}),
                      clock=clock, sleep=lambda s: None, log=lambda *_: None)


# ---- step 7: the delivered licence key is applied to the frame, never printed --------------------------------------

def test_step7_takes_the_key_once_writes_the_env_line_recreates_the_registry_alone_and_reads_it_back(tmp_path):
    stack = tmp_path / "hello-1"; stack.mkdir()
    env = stack / ".env.frame-test"; env.write_text("REGISTRY_NAME=hello\nFEDERATION_LICENSE_KEY=old\n"); env.chmod(0o600)
    (stack / "docker-compose.frame-test.yml").write_text("services: {}\n")
    facts = ff.Facts(stack_dir=str(stack), name="hello", trust_domain="hello.example", spire_container="hello-spire-server",
                     registry_port=8500, refresh_sec=300, cert_dir="/certs")
    calls, logs = [], []
    key = "tp_fed_" + "e" * 64

    def get(method, url, headers=None, **kw):
        calls.append(("http", method, url)); return 200, {"federation_license_key": key, "prefix": key[:12]}

    def run_fn(argv, timeout=120):
        calls.append(("run", argv))
        if argv[:2] == ["docker", "inspect"]:
            return 0, "healthy\n"
        return 0, ""

    def exec_in(container, argv, timeout=120):
        calls.append(("exec", container, argv)); return 0, "present\n"
    out = ff.step7_licence(facts, "inv-1", "tok", get=get, run_fn=run_fn, exec_in=exec_in, sleep=lambda s: None, clock=lambda: 0.0, log=logs.append)
    assert out["present"] is True and out["prefix"] == key[:12]
    text = env.read_text()
    assert f"FEDERATION_LICENSE_KEY={key}" in text and "old" not in text and text.count("FEDERATION_LICENSE_KEY=") == 1
    assert (env.stat().st_mode & 0o777) == 0o600
    recreate = [c for c in calls if c[0] == "run" and "up" in c[1]][0][1]
    assert "--no-deps" in recreate and "--force-recreate" in recreate and recreate[-1] == "hello-registry"
    assert key not in " ".join(" ".join(map(str, c[1] if c[0] == "run" else c[2])) for c in calls if c[0] in ("run", "exec"))
    assert key not in " ".join(logs) and "applied" in logs[-1]


def test_step7_names_finalize_retry_when_no_key_is_parked():
    facts = ff.Facts(stack_dir="/nonexistent", name="hello", trust_domain="hello.example", spire_container="s", registry_port=8500, refresh_sec=300, cert_dir="/certs")
    import pytest as _pt
    with _pt.raises(ff.StepFailed) as e:
        ff.step7_licence(facts, "inv-1", "tok", get=lambda *a, **k: (404, {"detail": "no licence key is parked ... finalize-retry"}), run_fn=lambda *a, **k: (0, ""), log=lambda m: None)
    assert "finalize-retry" in str(e.value)



def _row(i, status, notes, created):
    return {"id": i, "status": status, "review_notes": notes, "created_at": created}


def test_a_rerun_prefers_the_completed_row_whose_key_can_still_be_taken():
    T = "https://sandbox-a.example.org"
    rows = [_row("a", "pending", f"[outbound] target {T}; sent by x", "1"),
            _row("b", "completed", f"[outbound] target {T}; licence issued by approver, prefix tp_fed_abc", "2"),
            _row("c", "completed", f"[outbound] target {T}; sent by x", "3")]
    assert ff.pick_resumable(rows, T)["id"] == "b"


def test_a_rerun_resumes_the_newest_live_row_and_ignores_other_targets():
    T = "https://sandbox-a.example.org"
    rows = [_row("a", "pending", f"[outbound] target {T}; sent by x", "1"),
            _row("b", "approved", f"[outbound] target {T}; sent by x", "2"),
            _row("z", "pending", "[outbound] target https://other.example.org; sent by x", "9")]
    assert ff.pick_resumable(rows, T)["id"] == "b"


def test_a_rerun_invites_again_only_when_every_earlier_row_is_spent():
    T = "https://sandbox-a.example.org"
    rows = [_row("a", "completed", f"[outbound] target {T}; sent by x", "1"),   # completed, the callback carried no key:
            _row("b", "rejected", f"[outbound] target {T}; sent by x", "2"),    # a new handshake is the only way to one
            _row("c", "revoked", f"[outbound] target {T}; sent by x", "3")]
    assert ff.pick_resumable(rows, T) is None
    assert ff.pick_resumable([], T) is None


def test_an_untrusted_peer_certificate_is_named_in_the_refusal(monkeypatch):
    """§EXTTEST run 2: the card fetch said 'no connection' for a certificate the host did not trust (a peer on its edge's
    internal CA); the refusal now carries the reason and the SSL_CERT_FILE hint."""
    import pytest
    reason = "URLError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate"
    monkeypatch.setattr(ff, "http_json", lambda method, url, **kw: (0, reason))
    with pytest.raises(ff.Refused) as exc:
        ff.step2_peer("https://sandbox-b.devframe.example", None, "sandbox.devframe.example", log=lambda *a, **k: None)
    assert "CERTIFICATE_VERIFY_FAILED" in str(exc.value) and "SSL_CERT_FILE" in str(exc.value)
