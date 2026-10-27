#!/usr/bin/env python3
"""§BATCH10 — the pure parts of standup_extras, runner style (python3 test_standup_extras.py). Controls both ways."""
import json, os, sys, tempfile, pathlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import standup_extras as X

passed = 0; total = 0
def check(name, cond):
    global passed, total
    total += 1; passed += bool(cond); print(("PASS" if cond else "FAIL"), name)

ports = {"registry": 8350, "teg": 8362, "es": 8461, "spire_grpc": 8391, "spire_bundle": 8665, "nginx_fed": 30663, "push": 8399}
# vhosts: every placeholder rendered, the console routes ONLY its own sockets, the es vhost verifies the federated bundle
c = X.render_vhost("console", "eu", ports)
check("console: no placeholders left", "{{" not in c)
check("console: own socket + alias only", c.count("location /ws/events") == 2 and "/ws/events-eu " in c and "events-b" not in c)
check("console: proxies the registry and the ES ports", ":8350" in c and ":8461/ws/events" in c)
e = X.render_vhost("es", "eu", ports)
check("es: optional client cert against the federated bundle", "ssl_verify_client optional" in e and X.FEDERATED_BUNDLE_PEM in e)
check("acme: the four names", all(f"eu{s}.theprotocol.cloud" in X.render_vhost("acme", "eu", ports) for s in ("", "-es", "-spire", "-push")))
check("vhost_names: the runbook's five", X.vhost_names("eu") == {"console": "eu-theprotocol", "es": "eu-es.theprotocol.cloud", "spire": "eu-spire", "push": "eu-push", "acme": "eu-acme"})
try:
    X.render_vhost("push", "eu", {"registry": 1, "es": 2, "spire_bundle": 3})   # missing push port → must refuse, never render a hole
    check("render refuses a missing port", False)
except (KeyError, AssertionError):
    check("render refuses a missing port", True)
# card extras: github never rides
with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
    json.dump({"tags": ["eu"], "links": {"website": "https://x", "github_source": "https://github.com/x", "docs": ""}, "commitments": {"gdpr_compliant": True}, "spiffe_id": "locked"}, f); cj = f.name
ex = X.card_extras(cj)
check("card_extras: github_source dropped, empty links dropped, locked fields dropped", ex["links"] == {"website": "https://x"} and "spiffe_id" not in ex and ex["tags"] == ["eu"])
check("card_extras: none → {}", X.card_extras(None) == {})
# fresh-network upsert on a temp compose: upsert by slug, quoting intact, idempotent
with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
    f.write("services:\n  registry-a:\n    environment:\n      FRESH_NETWORK_JSON: '[{\"slug\":\"sbx-alpha\",\"name\":\"Sandbox Alpha\"}]'\n      OTHER: x\n"); cp = f.name
slugs = X.fresh_network_upsert({"slug": "eu", "name": "EU", "ws_path": "/ws/events-eu"}, compose_path=cp)
slugs2 = X.fresh_network_upsert({"slug": "eu", "name": "EU", "ws_path": "/ws/events-eu"}, compose_path=cp)
t = pathlib.Path(cp).read_text()
check("fresh_network_upsert: appended once, idempotent", slugs == ["sbx-alpha", "eu"] and slugs2 == ["sbx-alpha", "eu"] and t.count("FRESH_NETWORK_JSON") == 1)
check("fresh_network_upsert: the line still parses", json.loads(t.split("FRESH_NETWORK_JSON: '")[1].split("'\n")[0])[1]["ws_path"] == "/ws/events-eu")
# tester fixtures: the posture the testers assume, no OPA, no fiat secrets, no topology
tf = X.tester_fixture_env()
# §TESTBED (2026-09-19): the property is "no fiat SECRETS"; the fiat rails' two on/off flags (the tester's contracts expect
# the tiers, providers and purchases rails to answer, as on sbx-alpha) are flags, and nothing secret may ride with them
check("tester fixtures: the gates + bypass, no OPA/fiat secret/topology", tf["API_TEST_EXECUTION_ENABLED"] == "true" and tf["SANDBOX_BYPASS_RATE_LIMIT"] == "true"
      and not any(k.startswith(("OPA_", "MOLLIE", "TRUSTED_REGISTRIES")) for k in tf)
      and not any(k.startswith("FIAT_") and any(w in k for w in ("SECRET", "KEY", "TOKEN", "WEBHOOK", "STRIPE")) for k in tf)
      and {k: v for k, v in tf.items() if k.startswith("FIAT_")} == {"FIAT_ONRAMP_ENABLED": "true", "FIAT_GENESIS_REGISTRY": "true"})
# identity nets: append once
with tempfile.NamedTemporaryFile("w", delete=False) as f:
    f.write("fresh-identity\n"); nf = f.name
check("identity_nets_append: new appended, existing not", X.identity_nets_append("eu-identity", nf) and not X.identity_nets_append("fresh-identity", nf)
      and pathlib.Path(nf).read_text().splitlines() == ["fresh-identity", "eu-identity"])
# bundle_list_append — idempotent, ordered, mode 640
with tempfile.TemporaryDirectory() as _d:
    _lst = os.path.join(_d, "bundle.list")
    check("bundle_list_append: first add", X.bundle_list_append("/etc/nginx/eu-spire-bundle.pem", _lst) is True)
    check("bundle_list_append: idempotent", X.bundle_list_append("/etc/nginx/eu-spire-bundle.pem", _lst) is False)
    check("bundle_list_append: second frame appended in order", X.bundle_list_append("/etc/nginx/asia-spire-bundle.pem", _lst) is True and open(_lst).read().splitlines() == ["/etc/nginx/eu-spire-bundle.pem", "/etc/nginx/asia-spire-bundle.pem"])
    check("bundle_list_append: mode 640", oct(os.stat(_lst).st_mode & 0o777) == "0o640")
# sni_route — calls the product's script with the frame's public name and its federation port
_calls = []; _real = X.subprocess.run
class _R: returncode = 0; stdout = "[SNI] entry present"; stderr = ""
X.subprocess.run = lambda cmd, **kw: (_calls.append(cmd), _R())[1]
try:
    check("sni_route: rc 0 through the script", X.sni_route("eu", 30663) == 0)
finally:
    X.subprocess.run = _real
check("sni_route: bash <extend_stream_sni_map.sh> eu.theprotocol.cloud 30663", bool(_calls) and _calls[0][0] == "bash" and _calls[0][1].endswith("extend_stream_sni_map.sh") and _calls[0][2] == "eu.theprotocol.cloud" and _calls[0][3] == "30663")
print(f"{passed}/{total} passed"); sys.exit(0 if passed == total else 1)
