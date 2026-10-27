"""§MTLSHOPS V0378 (2026-09-15): the registry's in-frame clients build their TLS from es_ssl_helper, by scheme.

After T2 a frame's registry reaches its TEG through <f>-nginx-teg:8443, OPA at <f>-opa:8181, its kit Prometheus at
<f>-prometheus:9090 and ntfy through <f>-nginx-ntfy:8443, and each requires a client certificate the frame bundle chains. A
client built without es_ssl_helper presents no certificate and trusts the system roots only, so it reads nothing there, and in
this registry's habit it fails quietly: an empty admin status page, a push that never leaves, an OPA shadow that decides
nothing, a peer blocklist that never propagates. es_ssl_helper's context carries the SVID and trusts the bundle plus the system
roots, and httpx and aiohttp ignore it for an http URL, so one value serves a plain frame and a T2 frame alike.

  1. (structure) the pinned in-frame callers build their clients from the helper; parsed, never grepped;
  2. (structure, census) every client built in a module that reads an in-frame URL setting uses the helper, passes a TLS
     choice of its own, or is exempted by name with its reason; a new one must choose, and a stale exemption is refused;
  3. (behaviour) the OPA singleton and the reactor peer session rebuild when the SVID file changes (a loaded context keeps the
     certificate it read), and the push sender hands httpx exactly the helper's value.

Control: IN_FRAME_TLS_SRC=<a pre-V0378 copy of agentvault_registry> turns 1 and 2 RED; the behaviour tests go RED on the
pre-V0378 modules (they rebuild on no SVID change, and the push sender passes no verify). §SVIDRACE (V0639): the singletons
read es_ssl_helper.svid_stamp (the cert, the key and the bundle) and keep a client only when it holds a SPIRE context, so
the doubles here hand out real (empty) SSLContexts; tests/test_svid_reload_race.py measures the fallback half.
"""
from __future__ import annotations

import ast
import asyncio
import logging
import os
import pathlib
import re
import ssl

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@localhost:5432/ci")
os.environ.setdefault("API_KEY_SECRET", "ci-dummy-secret-0123456789abcdef")

_HERE = pathlib.Path(__file__).resolve()
_CANDIDATES = [
    pathlib.Path(os.environ["IN_FRAME_TLS_SRC"]) if os.environ.get("IN_FRAME_TLS_SRC") else None,
    _HERE.parents[1] / "src" / "agentvault_registry",
    pathlib.Path("/w/src/agentvault_registry"),
    pathlib.Path("/app/src/agentvault_registry"),
]
SRC = next(p for p in _CANDIDATES if p is not None and p.is_dir())

# FRESH_NETWORK_JSON joined in V0379: it names frame URLs, this frame's own and its peers'
IN_FRAME = re.compile(r"\b(TEG_API_BASE_URL|TEG_LAYER_URL|TEG_BASE_URL|TEG_INTERNAL_URL|PROMETHEUS_URL|PUSH_NTFY_URL|OPA_URL|FRESH_NETWORK_JSON)\b"
                      r"|\b(prometheus_url|opa_url)\(")

# (file, function) of every in-frame caller the V0378 census (2026-09-15) found building a client with no TLS choice
PINNED = {
    ("opa_client.py", "get_client"),
    ("routers/admin_opa.py", "_opa_get"),
    ("routers/admin_opa.py", "opa_simulate"),
    ("background_tasks/push_notify.py", "_send_ntfy"),
    ("routers/agent_health_admin.py", "_build_status"),
    ("routers/canary_ironhand_admin.py", "_build_status"),
    ("routers/canary_judge_admin.py", "_build_status"),
    ("routers/collusion_admin.py", "_build_status"),
    ("routers/federation_sync_admin.py", "_build_status"),
    ("routers/admin_health.py", "get_degradation_coverage"),
    ("routers/admin_health.py", "get_prometheus_metrics"),
    ("routers/public_status.py", "_prom_days"),
    ("routers/public_status.py", "_fresh_network_services"),
    # the cross-frame block/unblock propagation (_post_federation_admin) posts through this session to a peer's federation
    # terminator, which verifies client certificates
    ("background_tasks/reactor_helpers.py", "_get_session"),
    ("routers/federation_blocklist.py", "_get_session"),
    # already chose: per-request ssl from get_es_ssl_context (kept pinned so it cannot regress)
    ("background_tasks/eventstore_balance_sync.py", "_sync_agent_from_teg"),
}

# callers that must not build a client at all: they ride teg_integration's pooled, SVID-self-healing TEG client
SHARED_TEG_CLIENT = {("background_tasks/reactor_emission_policy_updated.py", "_refresh_teg_policy_cache")}

EXEMPT = {
    ("mcp/tools_admin.py", "admin_grafana_query"): "Grafana is not an in-frame mTLS hop: T2 keeps Grafana off the frame network",
    ("routers/admin_health.py", "test_endpoint"): "a diagnostic call to a caller-given base URL",
    ("routers/admin_health.py", "authenticated_health_check"): "this registry's own loopback, http://localhost:8000",
    ("routers/admin_health.py", "comprehensive_health_check"): "this registry's own loopback, http://localhost:8000",
    ("routers/admin_health.py", "health_check_with_agent_auth"): "this registry's own loopback, http://localhost:8000",
    ("routers/fiat_onramp.py", "_refund_stripe_payment_intent"): "Stripe's public API: the frame's SVID is never shown to a third party",
    ("routers/public_status.py", "_stack_health"): "this registry's own SELF_URL",
    ("routers/teg_integration.py", "fx_rate_public"): "a gateway frame's public host, verified with the system roots",
    ("routers/teg_integration.py", "fx_rates_public"): "a gateway frame's public host, verified with the system roots",
    ("services/agent_cicd_service.py", "_send_webhook"): "a developer's webhook URL: the frame's SVID is never shown to a third party",
    ("services/exchange_service.py", "run_peg_keeper"): "the retiring mainframes' plain venue list",
    ("services/exchange_service.py", "repatriate_gateway_credits"): "this registry's own loopback, http://localhost:8000",
    ("services/exchange_service.py", "repatriate_gateway_credits_aggregated"): "this registry's own loopback, http://localhost:8000",
    ("background_tasks/fiat_routed_local_reconciler.py", "_reconcile_one"): (
        "an operator's call to its parent registry (MAINFRAME_PROXY_URL), not an in-frame hop; its verify=False is tracked on its own"),
    ("routers/fiat_onramp.py", "_create_operator_routed_checkout"): (
        "an operator's call to its parent registry (MAINFRAME_PROXY_URL), not an in-frame hop; its verify=False is tracked on its own"),
    ("routers/teg_integration_jwt_svid.py", "get_mtls_client"): "unmounted: main.py leaves this router out, so no route reaches it",
    ("routers/teg_integration_oauth.py", "get_teg_access_token"): "unmounted: main.py leaves this router out, so no route reaches it",
    ("routers/teg_integration_oauth.py", "make_teg_request"): "unmounted: main.py leaves this router out, so no route reaches it",
    ("routers/teg_integration_oauth.py", "get_fee_configuration"): "unmounted: main.py leaves this router out, so no route reaches it",
    ("routers/public_fresh_network.py", "fresh_network"): (
        "a certless read of frames' public facts: a socket frame is read at its public vhosts (agentvault2-b5 measured 200 on "
        "lantern's es vhost), and an SVID shown to an ssl_verify_client optional vhost whose bundle does not chain it turns that "
        "200 into a 400"),
}


def _functions(tree):
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _called(node, name):
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    return (f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")) == name


def _client_calls(node):
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name):
            mod, attr = n.func.value.id, n.func.attr
            if (mod == "httpx" and attr in ("AsyncClient", "Client")) or (mod == "aiohttp" and attr == "ClientSession"):
                out.append((mod, n))
    return out


def _verify_assigned(fn, name):
    """The value `name` carries for "verify": `name = {..., "verify": X}` or `name["verify"] = X`, inside fn."""
    for node in ast.walk(fn):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name) and t.id == name and isinstance(node.value, ast.Dict):
                    for k, v in zip(node.value.keys, node.value.values):
                        if isinstance(k, ast.Constant) and k.value == "verify":
                            return v
                if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and t.value.id == name
                        and isinstance(t.slice, ast.Constant) and t.slice.value == "verify"):
                    return node.value
    return None


def _bound(fn, name):
    """§SVIDRACE (V0639): the value a plain `name = X` binds inside fn. A cached client that keeps or drops itself by what
    it was built with (es_ssl_helper.spire_trust_loaded) binds its verify first and passes the name."""
    for node in ast.walk(fn):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == name):
            return node.value
    return None


def _uses_helper(mod, call, fn):
    if mod == "aiohttp":
        return "get_es_ssl_context(" in ast.unparse(fn)
    for k in call.keywords:
        if k.arg == "verify":
            if isinstance(k.value, ast.Name):
                return _called(_bound(fn, k.value.id), "get_httpx_verify")
            return _called(k.value, "get_httpx_verify")
        if k.arg is None and isinstance(k.value, ast.Name):
            return _called(_verify_assigned(fn, k.value.id), "get_httpx_verify")
    return False


def _chose(mod, call):
    """A construction that passes a non-literal verify, a connector or **kwargs chose its TLS somewhere; a bare one, or a
    literal verify=True/False, did not."""
    if any(k.arg == "verify" and isinstance(k.value, ast.Constant) and isinstance(k.value.value, bool) for k in call.keywords):
        return False
    kws = {k.arg for k in call.keywords}
    wanted = {"verify"} if mod == "httpx" else {"connector"}
    return bool(kws & wanted) or None in kws


def _innermost(tree, lineno):
    best = None
    for fn in _functions(tree):
        if fn.lineno <= lineno <= (fn.end_lineno or fn.lineno) and (best is None or fn.lineno > best.lineno):
            best = fn
    return best


def census(text, rel, exempt=None):
    """None when the module reads no in-frame URL setting; else the constructions that made no TLS choice."""
    exempt = EXEMPT if exempt is None else exempt
    if not IN_FRAME.search(text):
        return None
    tree = ast.parse(text)
    offenders = []
    for mod, call in _client_calls(tree):
        fn = _innermost(tree, call.lineno)
        name = fn.name if fn is not None else "<module>"
        if (rel, name) in exempt:
            continue
        if fn is not None and _uses_helper(mod, call, fn):
            continue
        if _chose(mod, call):
            continue
        literal = [k.value.value for k in call.keywords if k.arg == "verify" and isinstance(k.value, ast.Constant)]
        what = f"verify={literal[0]!r} presents no SVID" if literal else "no TLS choice"
        offenders.append(f"{rel}:{call.lineno} {name}: {mod} client, {what}: {ast.unparse(call)[:90]}")
    return offenders


def test_the_in_frame_callers_build_their_clients_from_es_ssl_helper():
    problems = []
    for rel, name in sorted(PINNED):
        fns = [f for f in _functions(ast.parse((SRC / rel).read_text())) if f.name == name]
        assert len(fns) == 1, f"{rel}: expected one function {name}, found {len(fns)} (the test is not looking at the caller)"
        calls = _client_calls(fns[0])
        assert calls, f"{rel}:{name} builds no httpx/aiohttp client (the test is not looking at the caller)"
        for mod, call in calls:
            if not _uses_helper(mod, call, fns[0]):
                problems.append(f"{rel}:{call.lineno} {name}: {mod} client without es_ssl_helper: {ast.unparse(call)[:100]}")
    assert not problems, "\n".join(problems)


def test_the_teg_policy_refresh_rides_the_shared_teg_client():
    for rel, name in sorted(SHARED_TEG_CLIENT):
        fns = [f for f in _functions(ast.parse((SRC / rel).read_text())) if f.name == name]
        assert len(fns) == 1, f"{rel}: expected one function {name}, found {len(fns)}"
        assert not _client_calls(fns[0]), f"{rel}:{name} builds its own client (a bare one presents no certificate)"
        assert "_get_teg_client(" in ast.unparse(fns[0]), f"{rel}:{name} does not use teg_integration._get_teg_client"


def test_every_client_in_an_in_frame_module_chose_its_tls():
    offenders, modules = [], 0
    for path in sorted(SRC.rglob("*.py")):
        if "tests" in path.parts:
            continue
        rel = path.relative_to(SRC).as_posix()
        try:
            found = census(path.read_text(), rel)
        except SyntaxError:
            continue
        if found is None:
            continue
        modules += 1
        offenders += found
    assert modules >= 40, f"only {modules} modules read an in-frame URL setting: the census is not looking at the tree"
    assert not offenders, "\n".join(offenders)


def test_every_exemption_names_a_function_that_still_builds_a_client():
    stale = []
    for (rel, name), reason in sorted(EXEMPT.items()):
        assert reason.strip(), f"{rel}:{name} carries no reason"
        fns = [f for f in _functions(ast.parse((SRC / rel).read_text())) if f.name == name]
        if not fns or not any(_client_calls(f) for f in fns):
            stale.append(f"{rel}:{name}")
    assert not stale, f"exemptions whose function no longer builds a client (drop them): {stale}"


def test_the_census_refuses_a_bare_client_and_accepts_a_choice():
    bare = ("import httpx\nfrom x import prometheus_url\n\n\nasync def f():\n"
            "    async with httpx.AsyncClient(timeout=5.0) as c:\n        await c.get(prometheus_url())\n")
    assert len(census(bare, "synthetic.py", exempt={})) == 1
    assert census(bare.replace("timeout=5.0", "timeout=5.0, verify=get_httpx_verify()"), "synthetic.py", exempt={}) == []
    assert len(census(bare.replace("timeout=5.0", "timeout=5.0, verify=True"), "synthetic.py", exempt={})) == 1
    assert census(bare, "synthetic.py", exempt={("synthetic.py", "f"): "a reason"}) == []
    assert census(bare.replace("prometheus_url", "some_other_name"), "synthetic.py", exempt={}) is None


class _Client:
    built = []

    def __init__(self, **kwargs):
        self.kwargs, self.is_closed = kwargs, False
        type(self).built.append(self)

    async def aclose(self):
        self.is_closed = True


def test_the_opa_client_rebuilds_after_an_svid_rotation(monkeypatch):
    from agentvault_registry import opa_client

    mtime = {"v": ((100, 1), (100, 1), (100, 1))}
    values = iter([ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT) for _ in range(3)])
    monkeypatch.setattr(opa_client, "svid_stamp", lambda: mtime["v"], raising=False)
    monkeypatch.setattr(opa_client, "get_httpx_verify", lambda: next(values), raising=False)
    monkeypatch.setattr(opa_client.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(opa_client, "_client", None)
    monkeypatch.setattr(opa_client, "_client_stamp", (), raising=False)
    _Client.built = []

    async def run():
        first = await opa_client.get_client()
        again = await opa_client.get_client()
        mtime["v"] = ()
        missing = await opa_client.get_client()
        mtime["v"] = ((200, 1), (100, 1), (100, 1))
        second = await opa_client.get_client()
        return first, again, missing, second

    first, again, missing, second = asyncio.run(run())
    assert again is first, "an unchanged SVID must keep the pooled client"
    assert missing is first, "a momentarily absent SVID file (the cert-writer replaces it) must not churn the client"
    assert "verify" in first.kwargs, "the OPA client makes no TLS choice: a T2 frame's OPA requires the registry's SVID"
    assert second is not first and first.is_closed, "a rotated SVID must replace the client (a loaded context keeps the old certificate)"
    assert first.kwargs["verify"] is not second.kwargs["verify"] and len(_Client.built) == 2


class _Push:
    kwargs = None
    url = None

    def __init__(self, **kwargs):
        type(self).kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, content=None, headers=None):
        type(self).url = url
        return type("_R", (), {"status_code": 200})()


def test_the_push_sender_hands_httpx_the_helper_value(monkeypatch):
    from agentvault_registry.background_tasks import push_notify

    sentinel = object()
    monkeypatch.setattr(push_notify, "get_httpx_verify", lambda: sentinel, raising=False)
    monkeypatch.setattr(push_notify.httpx, "AsyncClient", _Push)
    monkeypatch.setattr(push_notify.settings, "PUSH_NTFY_URL", "https://sbx-beta-nginx-ntfy:8443")
    _Push.kwargs, _Push.url = None, None
    assert asyncio.run(push_notify._send_ntfy("topic-1", "Title", "message", "tag", "3")) is True
    assert _Push.kwargs is not None and _Push.kwargs.get("verify") is sentinel, (
        f"verify={(_Push.kwargs or {}).get('verify')!r}: a T2 frame's ntfy lane requires the registry's SVID")
    assert _Push.url == "https://sbx-beta-nginx-ntfy:8443/topic-1"


def test_a_refused_push_is_logged_with_a_hint_of_the_topic_never_the_topic(monkeypatch, caplog):
    # agentvault2-b5's V0378 lab: nginx-ntfy answers 400 to a registry without its certificate, and only exceptions were logged
    # here, so a refused publish left no trace. A device's topic is its read-and-publish capability on an anonymous ntfy, so the
    # log carries a hint of it, the way the webpush lines log the row id rather than the endpoint.
    from agentvault_registry.background_tasks import push_notify

    class _Refused(_Push):
        async def post(self, url, content=None, headers=None):
            return type("_R", (), {"status_code": 400})()

    class _Broken(_Push):
        async def post(self, url, content=None, headers=None):
            raise RuntimeError("handshake refused")

    topic = "tp-device-topic-0123456789"
    monkeypatch.setattr(push_notify.settings, "PUSH_NTFY_URL", "https://sbx-beta-nginx-ntfy:8443")
    for client, want in ((_Refused, "status=400"), (_Broken, "handshake refused")):
        monkeypatch.setattr(push_notify.httpx, "AsyncClient", client)
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger=push_notify.logger.name):
            assert asyncio.run(push_notify._send_ntfy(topic, "Title", "message", "tag", "3")) is False
        lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("[PUSH]")]
        assert any(want in line for line in lines), f"{client.__name__}: no [PUSH] line says {want!r}: {lines}"
        assert not any(topic in line for line in lines), f"{client.__name__}: a [PUSH] line carries the device topic: {lines}"


class _Session:
    built = []

    def __init__(self, **kwargs):
        self.kwargs, self.closed = kwargs, False
        type(self).built.append(self)

    async def close(self):
        self.closed = True


class _Connector:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_the_reactor_peer_session_presents_the_svid_and_rebuilds_after_a_rotation(monkeypatch):
    from agentvault_registry.background_tasks import reactor_helpers as rh

    sentinel = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    mtime = {"v": ((1, 1), (1, 1), (1, 1))}
    monkeypatch.setattr(rh, "svid_stamp", lambda: mtime["v"], raising=False)
    monkeypatch.setattr(rh, "get_es_ssl_context", lambda: sentinel, raising=False)
    monkeypatch.setattr(rh.aiohttp, "ClientSession", _Session)
    monkeypatch.setattr(rh.aiohttp, "TCPConnector", _Connector)
    monkeypatch.setattr(rh, "_shared_session", None)
    monkeypatch.setattr(rh, "_shared_session_stamp", (), raising=False)
    _Session.built = []

    async def run():
        a = rh._get_session()
        b = rh._get_session()
        mtime["v"] = ((2, 1), (1, 1), (1, 1))
        c = rh._get_session()
        await asyncio.sleep(0)
        return a, b, c

    a, b, c = asyncio.run(run())
    connector = a.kwargs.get("connector")
    assert connector is not None and connector.kwargs.get("ssl") is sentinel, (
        "the peer session must present the SVID (a peer's federation terminator refuses a bare session)")
    assert a is b and c is not a, "the session must be pooled while the SVID is unchanged and replaced after a rotation"
    assert a.closed, "the pre-rotation session must be closed"
