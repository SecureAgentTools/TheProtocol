"""§SOVKIT T5 (2026-09-14): every registry caller of its own event store builds its client from es_ssl_helper.

A frame's registry reaches its store through the frame's mTLS sidecar (`https://<frame>-nginx-event-store:8443`): the server
certificate is SPIRE-issued, the sidecar requires a client certificate and clears X-Internal-Key. A client that trusts the
system roots only (`verify=True`), turns verification off (`verify=False`) or presents no certificate reads nothing there,
and every one of them failed quietly: the saga pre-refund scan read "nothing settled" and refunded the batch; the forensic
scan, the developer activity list, the topology timelines and the supply-audit admin rails read empty. es_ssl_helper's
context trusts the SPIRE bundle AND the system roots and carries the SVID, so one value serves the sidecar and a public edge.

  1. (structure) the pinned store callers build their clients from the helper; parsed, never grepped;
  2. (structure, tree-wide) no function that reads EVENT_STORE_URL hands httpx a literal verify=True/False;
  3. (behaviour) the saga scan hands httpx exactly the helper's value, and says so when the store is unreadable;
  4. (behaviour, §SOVKIT-2, his decision 2026-09-14) a scan that could not read the store completely decides nothing: it
     answers None, and the sweep refunds nothing that cycle (control: a readable, empty scan still refunds).

Control: STORE_TLS_SRC=<a pre-T5 copy of agentvault_registry> turns 1 and 2 RED; the behaviour tests go RED on the pre-T5
module (PYTHONPATH at that copy): verify=True and a bare client both fail the identity check.
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
import logging
import os
import pathlib
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@localhost:5432/ci")
os.environ.setdefault("API_KEY_SECRET", "ci-dummy-secret-0123456789abcdef")

_HERE = pathlib.Path(__file__).resolve()
_CANDIDATES = [
    pathlib.Path(os.environ["STORE_TLS_SRC"]) if os.environ.get("STORE_TLS_SRC") else None,
    _HERE.parents[1] / "src" / "agentvault_registry",
    pathlib.Path("/w/src/agentvault_registry"),
    pathlib.Path("/app/src/agentvault_registry"),
]
SRC = next(p for p in _CANDIDATES if p is not None and p.is_dir())

# (file, function) of every caller the §SOVKIT T5 code read found building its OWN store client (2026-09-14)
PINNED = {
    ("background_tasks/saga_timeout_checker.py", "_find_settled_transfer_ids"),
    ("background_tasks/forensic_scanner.py", "_cycle_once"),
    ("routers/admin_developers.py", "get_developer_activity"),
    ("routers/federation_topology.py", "peer_events"),
    ("routers/federation_topology.py", "local_registry_events"),
    ("routers/supply_auditor_admin.py", "_build_status"),
    ("routers/supply_auditor_admin.py", "events_endpoint"),
    ("background_tasks/federation_sync.py", "_sync_trust_to_eventstore"),
    # the testers read the TARGET frame's store (§EMITDIAG): behind its sidecar they need the same context
    ("api_tests/es_event_verifier.py", "verify_events"),
    ("routers/mcp_tester.py", "_collect_emissions"),
    # §SOVKIT-2 R2: the LocalTrust backfill read the store with a bare client (the system roots, no certificate)
    ("services/local_trust_updater.py", "backfill_from_event_store"),
}


def _functions(tree):
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _called(node, name):
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    return (f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")) == name


def _client_calls(fn):
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            mod, attr = node.func.value.id, node.func.attr
            if (mod == "httpx" and attr in ("AsyncClient", "Client")) or (mod == "aiohttp" and attr == "ClientSession"):
                out.append((mod, node))
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


def _uses_helper(mod, call, fn):
    if mod == "aiohttp":
        has_connector = any(k.arg == "connector" for k in call.keywords)
        return has_connector and "get_es_ssl_context(" in ast.unparse(fn)
    for k in call.keywords:
        if k.arg == "verify":
            return _called(k.value, "get_httpx_verify")
        if k.arg is None and isinstance(k.value, ast.Name):
            return _called(_verify_assigned(fn, k.value.id), "get_httpx_verify")
    return False


def test_the_store_callers_build_their_clients_from_es_ssl_helper():
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


def _own_nodes(fn):
    """fn's nodes without descending into nested functions or classes: a literal belongs to its innermost function
    (create_app reads EVENT_STORE_URL and nests peer probes with verify=False that never touch the store)."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            stack.extend(ast.iter_child_nodes(node))


def _reads_store_url(fn):
    return any((isinstance(n, ast.Constant) and n.value == "EVENT_STORE_URL")
               or (isinstance(n, ast.Attribute) and n.attr == "EVENT_STORE_URL") for n in _own_nodes(fn))


def test_no_store_caller_hands_httpx_a_literal_verify():
    offenders, readers = [], 0
    for path in sorted(SRC.rglob("*.py")):
        if "tests" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for fn in _functions(tree):
            if not _reads_store_url(fn):
                continue
            readers += 1
            for node in _own_nodes(fn):
                if (isinstance(node, ast.keyword) and node.arg == "verify"
                        and isinstance(node.value, ast.Constant) and isinstance(node.value.value, bool)):
                    offenders.append(f"{path.relative_to(SRC)}:{node.value.lineno} {fn.name}: verify={node.value.value}")
                if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Subscript)
                        and isinstance(node.targets[0].slice, ast.Constant) and node.targets[0].slice.value == "verify"
                        and isinstance(node.value, ast.Constant) and isinstance(node.value.value, bool)):
                    offenders.append(f"{path.relative_to(SRC)}:{node.lineno} {fn.name}: [\"verify\"] = {node.value.value}")
    assert readers > 20, f"only {readers} functions read EVENT_STORE_URL: the scan is not looking at the tree"
    assert not offenders, "\n".join(sorted(set(offenders)))


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class _Recorder:
    """Stands in for httpx.AsyncClient: records the constructor's kwargs and answers the two tables."""
    kwargs = None
    mode = "ok"

    def __init__(self, **kwargs):
        type(self).kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None, headers=None):
        if type(self).mode == "fail" or (type(self).mode == "partial" and url.endswith("/foreign")):
            raise OSError("the store refused the handshake")
        return _Resp(200, [{"data": {"transfer_id": "t-settled"}}] if url.endswith("/foreign") else [])


def _scan(monkeypatch, tmp_path, mode, with_svid):
    from agentvault_registry.background_tasks import saga_timeout_checker as stc

    sentinel = object()
    monkeypatch.setattr(stc, "get_httpx_verify", lambda: sentinel, raising=False)
    monkeypatch.setattr(stc.httpx, "AsyncClient", _Recorder)
    monkeypatch.setenv("EVENT_STORE_URL", "https://orchard-nginx-event-store:8443")
    monkeypatch.setenv("EVENT_STORE_INTERNAL_API_KEY", "sovkit-test-key-not-a-secret")
    cert_dir = tmp_path / "certs"
    cert_dir.mkdir()
    if with_svid:   # the pre-T5 module set verify=True exactly when these exist: the fixture makes that branch run
        for name in ("svid.0.pem", "svid.0.key", "bundle.0.pem"):
            (cert_dir / name).write_text("fixture, not a certificate\n")
    monkeypatch.setenv("SVID_CERT_DIR", str(cert_dir))
    _Recorder.kwargs, _Recorder.mode = None, mode
    return sentinel, asyncio.run(stc._find_settled_transfer_ids(["t-settled", "t-open"]))


def _assert_helper_value(sentinel, settled):
    assert _Recorder.kwargs is not None, "the scan built no client"
    assert _Recorder.kwargs.get("verify") is sentinel, (
        f"verify={_Recorder.kwargs.get('verify')!r}: the pre-refund scan must use es_ssl_helper (verify=True trusts the system "
        "roots only and fails the frame's SPIRE-issued sidecar; a bare client presents no certificate)")
    assert settled == {"t-settled"}


def test_the_saga_scan_uses_the_helper_with_an_svid_mounted(monkeypatch, tmp_path):
    # control: the pre-T5 module answers verify=True here
    _assert_helper_value(*_scan(monkeypatch, tmp_path, "ok", with_svid=True))


def test_the_saga_scan_uses_the_helper_with_no_svid(monkeypatch, tmp_path):
    # control: the pre-T5 module builds a bare client here (no verify at all)
    _assert_helper_value(*_scan(monkeypatch, tmp_path, "ok", with_svid=False))


def test_an_unreadable_store_is_said_and_decides_nothing(monkeypatch, tmp_path, caplog):
    # §SOVKIT-2 (his decision 2026-09-14): None, not "nothing settled"; an empty set refunded the whole batch
    caplog.set_level(logging.WARNING)
    _, settled = _scan(monkeypatch, tmp_path, "fail", with_svid=True)
    assert settled is None, f"an unreadable scan answered {settled!r}, which the sweep reads as 'nothing settled'"
    lines = [r.getMessage() for r in caplog.records if "SagaPreRefund" in r.getMessage()]
    assert any("UNREADABLE" in line for line in lines), f"no warning named the unreadable store: {lines}"


def test_a_partial_scan_decides_nothing(monkeypatch, tmp_path, caplog):
    # the peer frame's Settled events live in the foreign table: with it unreadable, "not settled" is not known
    caplog.set_level(logging.WARNING)
    _, settled = _scan(monkeypatch, tmp_path, "partial", with_svid=True)
    assert settled is None
    assert any("partial" in r.getMessage() for r in caplog.records)


def test_a_scan_without_any_store_credential_decides_nothing(monkeypatch, tmp_path, caplog):
    from agentvault_registry.background_tasks import saga_timeout_checker as stc

    caplog.set_level(logging.WARNING)
    for name in ("EVENT_STORE_INTERNAL_API_KEY", "EVENT_STORE_API_KEY", "INTERNAL_API_KEY", "FEDERATION_LICENSE_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("EVENT_STORE_URL", "http://orchard-event-store:8200")
    monkeypatch.setenv("SVID_CERT_DIR", str(tmp_path))
    monkeypatch.setattr(stc.httpx, "AsyncClient", _Recorder)
    _Recorder.kwargs, _Recorder.mode = None, "ok"
    assert asyncio.run(stc._find_settled_transfer_ids(["t-open"])) is None
    assert _Recorder.kwargs is None, "with no credential the scan must not dial the store"
    assert any("No EventStore auth" in r.getMessage() for r in caplog.records)


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _Db:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, *args, **kwargs):
        return _Rows(self._rows)


def _sweep(monkeypatch, scan_answer):
    from agentvault_registry.background_tasks import saga_timeout_checker as stc

    rows = [SimpleNamespace(id="t-1"), SimpleNamespace(id="t-2")]

    @contextlib.asynccontextmanager
    async def _db_context():
        yield _Db(rows)

    async def _scan_stub(transfer_ids):
        return scan_answer

    refunded = []

    async def _refund_stub(row, *args, **kwargs):
        refunded.append(row.id)
        return row.id

    async def _concurrency_stub(local_frame):
        return 2

    monkeypatch.setattr(stc, "get_db_context", _db_context)
    monkeypatch.setattr(stc, "_find_settled_transfer_ids", _scan_stub)
    monkeypatch.setattr(stc, "_refund_one_cross_frame_row", _refund_stub)
    monkeypatch.setattr(stc, "_compute_adaptive_concurrency", _concurrency_stub)
    return asyncio.run(stc.check_cross_frame_timeouts()), refunded


def test_an_unreadable_scan_defers_every_refund(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    returned, refunded = _sweep(monkeypatch, None)
    assert returned == [] and refunded == [], f"refunded {refunded} on a scan that could not read the store"
    assert any("NOT refunded" in r.getMessage() for r in caplog.records)


def test_a_readable_scan_that_found_nothing_settled_still_refunds(monkeypatch):
    # control: the same sweep with a readable, empty scan refunds both rows, so the stubs do reach the refund path
    returned, refunded = _sweep(monkeypatch, set())
    assert sorted(returned) == ["t-1", "t-2"] and sorted(refunded) == ["t-1", "t-2"]
