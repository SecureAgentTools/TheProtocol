"""§ONESHOT P2.1 (2026-09-12) — the `federate` step's pure halves, pinned.

The step writes the post-approve state of a federated pair on BOTH frames. Every merge here has an
APPEND semantics a third peer relies on (`FX_ROUTE_PEERS` / `TEG_SIDECAR_MAP` / `CROSS_FRAME_PEERS` must
never be overwritten by the next peer — Appendix A's own sentence), an idempotence a resumed run relies
on (a second pass changes nothing and says so), and a refusal a half peer relies on (no router DID ⇒ no
FX keys, said out loud). And the driver's own KNOWN_INTERNAL_SERVICES override (F2) is gone: pinned on
the AST, never on the text, because the comment that replaced it names the retired value.
"""
import ast
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER_DIR = os.path.dirname(HERE)


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(DRIVER_DIR, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fed = _load("standup_federate")

ENV = """# rendered by the provisioner
FRAME_CURRENCY=JUC
FT_ES_CROSS_FRAME_REPLICATION_ENABLED=false
FT_ES_CROSS_FRAME_PEERS=
FT_ES_KNOWN_INTERNAL_SERVICES=juice-registry,registry,teg-layer
FT_TRUSTED_SPIFFE_DOMAINS=juice.theprotocol.cloud
FT_REG_FRESH_NETWORK_JSON=[{"name":"JUICE","slug":"juice","currency":"JUC","role":"frame","group":"sandbox","console":"https://juice.theprotocol.cloud","status_url":"https://juice.theprotocol.cloud/#/status","registry_url":"http://juice-registry:8000","es_url":"http://juice-event-store:8200","ws_path":"/ws/events"}]
FT_REG_FX_ENABLED=false
FT_REG_FX_RATE_MODE=pool
FT_REG_FX_ROUTE_PEERS=[]
FT_REG_TEG_SIDECAR_MAP={}
FT_REG_FX_RESERVE_KEEPER_ENABLED=false
FT_REG_EVENT_STORE_B_URL=
"""

BRRR = {"name": "brrr", "frame_label": "Brrr", "env_label": "sandbox", "td": "brrr.theprotocol.cloud", "ticker": "BRR",
        "currency_name": "Brrr Unit", "public_url": "https://brrr.theprotocol.cloud",
        "es_public_url": "https://brrr-es.theprotocol.cloud", "router_did": "did:theprotocol:brrr.theprotocol.cloud:abc"}
THIRD = {"name": "fizz", "frame_label": "Fizz", "env_label": "sandbox", "td": "fizz.theprotocol.cloud", "ticker": "FZZ",
         "public_url": "https://fizz.theprotocol.cloud", "es_public_url": "https://fizz-es.theprotocol.cloud",
         "router_did": "did:theprotocol:fizz.theprotocol.cloud:def"}


def test_merges_append_and_dedupe():
    t, ch = fed.merge_csv("A=x,y\n", "A", ["y", "z"]); assert ch and fed.env_get(t, "A") == "x,y,z"
    t2, ch2 = fed.merge_csv(t, "A", ["z"]); assert not ch2 and t2 == t
    t, ch = fed.merge_pipe_list("P=a.td|https://a\n", "P", "b.td", "b.td|https://b"); assert fed.env_get(t, "P") == "a.td|https://a,b.td|https://b"
    t, ch = fed.merge_pipe_list(t, "P", "a.td", "a.td|https://a2"); assert ch and fed.env_get(t, "P") == "b.td|https://b,a.td|https://a2"
    t, ch = fed.merge_json_list("L=[]\n", "L", {"registry_id": "a", "v": 1}, "registry_id"); assert fed.env_get(t, "L") == '[{"registry_id":"a","v":1}]'
    t, ch = fed.merge_json_list(t, "L", {"registry_id": "a", "v": 2}, "registry_id"); assert ch and fed.env_get(t, "L") == '[{"registry_id":"a","v":2}]'
    t, ch = fed.merge_json_list(t, "L", {"registry_id": "b"}, "registry_id"); assert fed.env_get(t, "L").count("registry_id") == 2
    t, ch = fed.merge_json_dict("M={}\n", "M", {"k": "v"}); assert ch and fed.env_get(t, "M") == '{"k":"v"}'
    t2, ch2 = fed.merge_json_dict(t, "M", {"k": "v"}); assert not ch2
    t, ch = fed.upsert_env_line("X=1\n", "Y", "2"); assert ch and t.endswith("Y=2\n")
    t2, ch2 = fed.upsert_env_line(t, "Y", "2"); assert not ch2


def test_post_approve_env_first_pass_then_no_op_then_third_peer_appends():
    t, keys = fed.post_approve_env(ENV, BRRR)
    assert set(keys) >= {"FT_ES_CROSS_FRAME_REPLICATION_ENABLED", "FT_ES_CROSS_FRAME_PEERS", "FT_ES_KNOWN_INTERNAL_SERVICES",
                         "FT_TRUSTED_SPIFFE_DOMAINS", "FT_REG_FRESH_NETWORK_JSON", "FT_REG_FX_ENABLED", "FT_REG_FX_ROUTE_PEERS",
                         "FT_REG_TEG_SIDECAR_MAP", "FT_REG_FX_RESERVE_KEEPER_ENABLED", "FT_REG_EVENT_STORE_B_URL"}
    assert fed.env_get(t, "FT_ES_CROSS_FRAME_PEERS") == "brrr.theprotocol.cloud|https://brrr-es.theprotocol.cloud"
    assert fed.env_get(t, "FT_ES_KNOWN_INTERNAL_SERVICES") == "juice-registry,registry,teg-layer,brrr-registry"
    assert fed.env_get(t, "FT_TRUSTED_SPIFFE_DOMAINS") == "juice.theprotocol.cloud,brrr.theprotocol.cloud"
    peers = fed._json_load(fed.env_get(t, "FT_REG_FX_ROUTE_PEERS"), [])
    assert peers == [{"currency": "BRR", "registry_id": "brrr", "teg_id": "teg-layer-brrr", "router_did": BRRR["router_did"]}]
    assert "url" not in peers[0]          # §FXSTRAND: a hardcoded gateway url beats the authoritative peer row
    assert fed._json_load(fed.env_get(t, "FT_REG_TEG_SIDECAR_MAP"), {}) == {"teg-layer-brrr": "brrr-nginx-teg", "registry-brrr": "brrr-nginx-teg"}
    tiles = fed._json_load(fed.env_get(t, "FT_REG_FRESH_NETWORK_JSON"), [])
    assert [x["slug"] for x in tiles] == ["juice", "brrr"] and tiles[1]["ws_path"] == "/ws/events-brrr" and tiles[1]["currency"] == "BRR"
    # the second pass is a no-op and SAYS so (empty change list)
    t2, keys2 = fed.post_approve_env(t, BRRR); assert keys2 == [] and t2 == t
    # a third peer APPENDS to every list and map and loses nothing
    t3, keys3 = fed.post_approve_env(t, THIRD)
    assert [p["registry_id"] for p in fed._json_load(fed.env_get(t3, "FT_REG_FX_ROUTE_PEERS"), [])] == ["brrr", "fizz"]
    assert set(fed._json_load(fed.env_get(t3, "FT_REG_TEG_SIDECAR_MAP"), {})) == {"teg-layer-brrr", "registry-brrr", "teg-layer-fizz", "registry-fizz"}
    assert fed.env_get(t3, "FT_ES_CROSS_FRAME_PEERS").count("|") == 2
    assert fed.env_get(t3, "FT_TRUSTED_SPIFFE_DOMAINS").split(",") == ["juice.theprotocol.cloud", "brrr.theprotocol.cloud", "fizz.theprotocol.cloud"]
    assert "FT_REG_EVENT_STORE_B_URL" in keys3   # the B ledger follows the newest peer (a single-valued key)


def test_a_peer_without_a_router_did_gets_no_fx_keys():
    t, keys = fed.post_approve_env(ENV, {**BRRR, "router_did": ""})
    assert "FT_REG_FX_ENABLED" not in keys and fed.env_get(t, "FT_REG_FX_ENABLED") == "false"
    assert fed.env_get(t, "FT_REG_FX_ROUTE_PEERS") == "[]"
    assert fed.env_get(t, "FT_ES_CROSS_FRAME_PEERS").startswith("brrr.theprotocol.cloud|")   # replication still federates


def test_keeper_body_anchor_vs_pegged():
    a = fed.keeper_body("JUC", "JUC"); b = fed.keeper_body("BRR", "JUC")
    assert a["anchor_currency"] == "JUC" and "target_float" in a and a["enabled"] is True
    assert b["anchor_currency"] == "JUC" and "target_float" not in b and b["ratio_vs_anchor"] == "1"


def test_fresh_network_entry_names_public_addresses():
    e = fed.fresh_network_entry({"name": "x", "public_url": "https://x.theprotocol.cloud/", "es_public_url": "https://x-es.theprotocol.cloud/"})
    assert e["registry_url"] == "https://x.theprotocol.cloud" and e["es_url"] == "https://x-es.theprotocol.cloud"


def test_fresh_network_entry_never_guesses_a_currency():
    e = fed.fresh_network_entry({"name": "x", "public_url": "https://x.theprotocol.cloud/"})
    assert "currency" not in e and e["console"] == "https://x.theprotocol.cloud" and e["ws_path"] == "/ws/events-x"


def test_preconditions_name_the_fix_and_the_happy_path_is_empty():
    me = {"td": "juice.theprotocol.cloud", "identity_net": "oneshot-identity"}
    peer = {"td": "brrr.theprotocol.cloud", "es_public_url": "https://brrr-es.theprotocol.cloud", "admin_email": "a@b",
            "identity_net": "oneshot-identity", "registry_port": 8850, "stack_dir": "/x"}
    assert fed.classify_preconditions(me, peer, peer_health=200, my_svid_verifies=True, federated_pem_roots=4) == []
    p = fed.classify_preconditions(me, peer, peer_health=0, my_svid_verifies=True, federated_pem_roots=4); assert len(p) == 1 and "/health" in p[0]
    p = fed.classify_preconditions(me, {**peer, "identity_net": "other"}, peer_health=200, my_svid_verifies=True, federated_pem_roots=4); assert "identity" in p[0]
    p = fed.classify_preconditions(me, peer, peer_health=200, my_svid_verifies=True, federated_pem_roots=1); assert "frame-spire-bundles.list" in p[0]
    p = fed.classify_preconditions(me, peer, peer_health=200, my_svid_verifies=False, federated_pem_roots=4); assert "stale" in p[0]
    p = fed.classify_preconditions({**me, "td": peer["td"]}, peer, peer_health=200, my_svid_verifies=True, federated_pem_roots=4); assert "itself" in p[0]


def test_driver_has_the_step_and_not_the_known_internal_services_override():
    src = open(os.path.join(DRIVER_DIR, "standup_driver.py")).read()
    tree = ast.parse(src)
    steps = [n for n in ast.walk(tree) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_STEPS" for t in n.targets)]
    assert steps, "post_boot's _STEPS list"
    names = [c.value for c in steps[0].value.elts]
    assert names.index("federate") == names.index("jurisdiction") + 1 and names.index("federate") < names.index("operators")
    # F2: no tuple/constant anywhere in the driver names the ES allowlist (the template line is the one answer)
    consts = [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value == "KNOWN_INTERNAL_SERVICES"]
    assert consts == [], "the driver must not write KNOWN_INTERNAL_SERVICES (it overwrote the template's corrected value)"
    assert "federate.run(" in src and "federate.pre_issue_license(" in src


# ── §NIGHTPROV (2026-09-27): the TEG's health after a recreate is asked where the TEG listens ──────────────────────
SOCKET_HC = ["CMD", "curl", "-fs", "-o", "/dev/null", "--unix-socket", "/sock/teg/teg.sock", "http://localhost/health"]


def test_a_socket_only_teg_is_asked_on_its_socket_and_an_older_one_on_tcp():
    """nt260927x1b's TEG listens on /sock/teg/teg.sock only (§MTLSHOPS T2 S4); the step asked TCP 8080, was refused after
    every recreate and failed a frame docker called healthy. The socket comes from the container's own healthcheck."""
    p = fed.teg_health_probe(SOCKET_HC)
    assert "AF_UNIX" in p and "'/sock/teg/teg.sock'" in p and "8080" not in p
    compile(p, "<probe>", "exec")
    for older in (None, [], ["CMD", "curl", "-fs", "http://localhost:8080/health"], ["CMD-SHELL", "--unix-socket"]):
        q = fed.teg_health_probe(older)
        assert "127.0.0.1:8080" in q and "AF_UNIX" not in q, older


def test_the_socket_probe_reads_a_real_unix_socket_answer(tmp_path):
    """The probe as the step runs it (a separate python), against an HTTP server on a unix socket answering 200."""
    import socket
    import subprocess
    import threading
    path = str(tmp_path / "teg.sock")
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(path)
    srv.listen(1)

    def answer():
        conn, _ = srv.accept()
        conn.recv(1024)
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        conn.close()
    t = threading.Thread(target=answer, daemon=True)
    t.start()
    hc = SOCKET_HC[:SOCKET_HC.index("--unix-socket") + 1] + [path, "http://localhost/health"]
    r = subprocess.run([sys.executable, "-c", fed.teg_health_probe(hc)], capture_output=True, text=True, timeout=30)
    t.join(5)
    srv.close()
    assert r.returncode == 0 and r.stdout.strip() == "200", (r.stdout, r.stderr)


def test_proxies_are_reloaded_so_they_serve_the_peer_root_now(monkeypatch):
    """§F6 stage 5 (2026-09-27): a proxy loads its client CA at start and at each reload only (every 300 s), so once its
    file holds both roots the step reloads it rather than waiting a scheduled reload out (nt260927x4's FX wait did not)."""
    calls = []

    def fake_sh(cmd, timeout=120):
        calls.append(cmd)
        return 0, ""

    monkeypatch.setattr(fed, "sh", fake_sh)
    got = fed.reload_proxies({"name": "nt1a"})
    assert calls == [["docker", "exec", f"nt1a-{p}", "nginx", "-s", "reload"] for p in fed.PROXIES]
    assert got == {f"nt1a-{p}": 0 for p in fed.PROXIES}


def test_a_failed_reload_is_reported_and_never_raised(monkeypatch):
    """Control: the sidecar's own loop still takes the file, so a refused reload is a line, not a failed federation."""
    monkeypatch.setattr(fed, "sh", lambda cmd, timeout=120: (1, "nginx: [error] ...") if cmd[2].endswith("nginx-teg")
                        else (0, ""))
    got = fed.reload_proxies({"name": "nt1b"})
    assert got == {"nt1b-nginx-federation": 0, "nt1b-nginx-teg": 1}


def test_the_step_reloads_both_frames_proxies_right_after_the_roots_check():
    """Wired on the AST: in `run`, the branch that logs "proxies at ... roots" reloads the proxies of both frames."""
    src = open(os.path.join(DRIVER_DIR, "standup_federate.py")).read()
    run = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "run")
    for node in ast.walk(run):
        if isinstance(node, ast.If):
            seg = ast.get_source_segment(src, node) or ""
            if "proxies at {want}+ roots" in seg and "all(v >= want" in seg:
                body = "".join(ast.get_source_segment(src, s) or "" for s in node.body)
                assert "reload_proxies(me)" in body and "reload_proxies(peer)" in body
                assert body.index("reload_proxies(me)") > body.index("proxies at {want}+ roots")
                return
    raise AssertionError("the roots check's success branch was not found in run()")


def test_only_the_host_reach_grant_says_host_reach_granted():
    """§F6 stage 5 (2026-09-27): the socket-only --tester-self branch printed "HOST REACH GRANTED ... /host-stack +
    /host-nginx-sites" while its frame held the socket alone; --grant-host-reach printed nothing. The sentence belongs
    to the grant."""
    src = open(os.path.join(DRIVER_DIR, "standup_driver.py")).read()
    tree = ast.parse(src)
    grants, testers = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = ast.get_source_segment(src, node.test) or ""
            body = "".join(ast.get_source_segment(src, s) or "" for s in node.body)
            if test == "args.grant_host_reach":
                grants.append(body)
            elif test == 'getattr(args, "tester_self", False)':
                testers.append(body)
    assert grants and testers, "both kinds of branch found"
    assert any("HOST REACH GRANTED" in b for b in grants)
    assert any("nothing else of the host" in b for b in testers), "the socket-only branch is among them"
    assert not any("HOST REACH GRANTED" in b for b in testers)


def test_the_invitation_goes_in_as_the_approvers_admin(monkeypatch):
    """§FINDINGS-A4 3d (2026-09-27): the invitation route lets only a FEDERATION ADMIN name an internal bundle host, and a
    same-host pair's bundle URL is compose-internal, so the POST must carry the approver's token (an older registry
    ignores it). Driven through ensure_approved with a recording http."""
    calls = []

    def fake_http(method, url, body=None, headers=None, timeout=30, form=False):
        calls.append((method, url, dict(headers or {})))
        if url.endswith("/api/v1/federation/frame-invitations"):
            return 201, {"id": "inv-1"}
        if url.endswith("/approve"):
            return 200, {"status": "completed", "peer_registry_id": 3}
        return 200, {}

    monkeypatch.setattr(fed, "http", fake_http)
    monkeypatch.setattr(fed, "completed_invitation_for", lambda approver, tok, td: None)
    monkeypatch.setattr(fed, "base", lambda f: "http://127.0.0.1:9")
    peer = {"td": "b.invalid", "bundle_url": "https://ntb-spire-server:8443/", "fed_url": "https://ntb-registry:8443/",
            "es_public_url": "https://ntb-es.invalid", "name": "ntb", "admin_email": "admin@b.invalid"}
    fed.ensure_approved({"name": "nta"}, "TOKEN-A", peer, "notes")
    invite = [c for c in calls if c[1].endswith("/api/v1/federation/frame-invitations")]
    assert invite and invite[0][2].get("Authorization") == "Bearer TOKEN-A"


# §FEDLICENCE (2026-09-28): the network licence rides the invitation. Measured by the kit dry run: this step created each
# invitation on the approver with no licence facts, so under FEDERATION_LICENCE_MODE=enforce both approves answered 403.
KEY = {"kty": "OKP", "crv": "Ed25519", "x": "k" * 43, "kid": "not-sent"}


def test_an_invitation_presents_the_described_frames_licence_facts():
    assert fed.licence_invitation_fields({}) == {}
    # an unlicensed frame presents its key, so the genesis can issue to it, and nothing else
    assert fed.licence_invitation_fields({"state": "unlicensed", "key": KEY, "certificate": None}) == \
        {"licence_key": {"kty": "OKP", "crv": "Ed25519", "x": "k" * 43}}
    got = fed.licence_invitation_fields({"state": "licensed", "key": KEY, "certificate": "jws.a.b", "chain": ["root", 7, "x", "y"]})
    assert got["licence_certificate"] == "jws.a.b" and got["licence_chain"] == ["root", "x"]
    # control: a certificate the frame itself does not hold as licensed is never presented
    assert "licence_certificate" not in fed.licence_invitation_fields({"state": "revoked", "key": KEY, "certificate": "jws.a.b"})


def test_only_the_genesis_issues_and_only_to_a_frame_without_a_licence():
    genesis, plain = {"state": "genesis"}, {"state": "licensed"}
    assert fed.approve_licence_fields(genesis, {"state": "unlicensed"}, "research") == {"network_licence_plan": "research"}
    assert fed.approve_licence_fields(genesis, {}, "research") == {"network_licence_plan": "research"}
    assert fed.approve_licence_fields(genesis, plain, "research") == {}          # it holds one already
    assert fed.approve_licence_fields(plain, {"state": "unlicensed"}, "research") == {}   # not the genesis
    assert fed.approve_licence_fields(genesis, {"state": "unlicensed"}, "") == {}   # no plan asked for
    assert fed.genesis_first({"state": "unlicensed"}, genesis) and fed.genesis_first({}, genesis)
    assert not fed.genesis_first(plain, genesis) and not fed.genesis_first({"state": "unlicensed"}, plain)


def test_the_genesis_approve_asks_for_the_plan_and_the_invitation_carries_the_key(monkeypatch):
    calls = []

    def fake_http(method, url, body=None, headers=None, timeout=30, form=False):
        calls.append((method, url, body))
        if url.endswith("/api/v1/federation/frame-invitations"):
            return 201, {"id": "inv-9"}
        if url.endswith("/approve"):
            return 200, {"status": "completed", "peer_registry_id": 4,
                         "network_licence": {"issued_hash": "ab" * 32, "plan": "research", "error": None,
                                             "installed_by_peer": None}}
        return 200, {}

    monkeypatch.setattr(fed, "http", fake_http)
    monkeypatch.setattr(fed, "completed_invitation_for", lambda approver, tok, td: None)
    monkeypatch.setattr(fed, "base", lambda f: "http://127.0.0.1:9")
    peer = {"td": "kit.invalid", "bundle_url": "https://kit-spire-server:8443/", "fed_url": "https://kit-registry:8443/",
            "es_public_url": "https://kit-es.invalid", "name": "kit", "admin_email": "admin@kit.invalid"}
    out = fed.ensure_approved({"name": "sbxa"}, "TOKEN-G", peer, "notes", described_lic={"state": "unlicensed", "key": KEY},
                              approver_lic={"state": "genesis"}, plan="research")
    invite = next(c for c in calls if c[1].endswith("/frame-invitations"))
    approve = next(c for c in calls if c[1].endswith("/approve"))
    assert invite[2]["licence_key"]["x"] == "k" * 43 and "licence_certificate" not in invite[2]
    assert approve[2]["network_licence_plan"] == "research"
    assert out[0] == 4 and out[3]["issued_hash"] == "ab" * 32


def test_an_issued_licence_the_callback_did_not_deliver_is_installed(monkeypatch):
    calls = []

    def fake_http(method, url, body=None, headers=None, timeout=30, form=False):
        calls.append((method, url, body))
        if "/public/federation/licences/" in url:
            return 200, {"certificate": "frame.jws.sig"}
        if url.endswith("/federation/licence/own"):
            return 200, {"state": "genesis", "certificate": "root.jws.sig"}
        if url.endswith("/admin/federation/licence/install"):
            # the route's own answer (routers/federation_licence.py _install): {installed, verdict}
            return 200, {"installed": "cd" * 32, "verdict": {"state": "licensed", "reason": "chain verifies"}}
        return 404, {}

    monkeypatch.setattr(fed, "http", fake_http)
    monkeypatch.setattr(fed, "base", lambda f: f"http://{f['name']}:9")
    genesis, kit = {"name": "sbxa"}, {"name": "kit"}
    # nothing issued, or delivered by the callback: nothing to do
    assert fed.install_issued_licence(genesis, kit, "TOK", None) is None
    assert fed.install_issued_licence(genesis, kit, "TOK", {"issued_hash": "cd" * 32,
                                                            "installed_by_peer": {"installed": "cd" * 32, "state": "licensed"}}).startswith("installed by the callback")
    assert calls == []
    said = fed.install_issued_licence(genesis, kit, "TOK", {"issued_hash": "cd" * 32, "installed_by_peer": None})
    install = next(c for c in calls if c[1].endswith("/licence/install"))
    assert install[1].startswith("http://kit:9") and install[2] == {"certificate": "frame.jws.sig", "chain": ["root.jws.sig"]}
    assert "licensed" in said
