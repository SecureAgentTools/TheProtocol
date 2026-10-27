"""The registry's halves of the TEG partner rule (agentvault2-5b's ledgergate3 TEG, fix/teg-partner-quarantine a9cad595).

Under that rule a cross-TEG leg runs only with a peer the TEG holds as a current partner, and nothing adds one but
add-partner: the TEG no longer adds a peer from the target URL of a fund sent to it, and a partner a reactor removed (at
a quarantine, a licence suspension, a peer's deactivation) stays removed. What these tests pin, on the real code (only
the TEG's HTTP answers, the database and the peer lookup replaced):
- one helper registers an ACTIVE peer row as a partner on this frame's TEG, as the first fund used to (teg-<safe name>,
  the safe name as registry id, the row's base_url), and registers nothing for a row it cannot resolve;
- an operator's provisioning, on both paths (self-provision and the admin route), registers the new operator before its
  genesis funding and whatever the funding amount, and says so in its answer;
- a quarantine lift and a peer's reactivation register the peer again;
- the cross-registry transfer's per-worker partner cache no longer believes forever: the TEG's refusal of a peer that is
  no current partner drops the entry (the next transfer adds the partner again), and an entry older than
  TEG_PARTNER_CACHE_TTL_SEC is added again.
RED on 453cc8b8 (the base of V0622): no helper; the lift and the reactivation register nothing; the provisioning paths
register nothing; after the TEG's partner refusal the next transfer adds no partner; an entry of any age is believed.
"""
import ast
import asyncio
import inspect
import time
import types

import pytest
from fastapi import HTTPException  # noqa: F401  (the transfer harness raises it)

from agentvault_registry.routers import teg_integration as ti
from tests.test_kept_money_routes import _common, _nobody_in_quarantine, _xfer, redis  # noqa: F401  (fixtures)

LISBON_URL = "https://lisbon.op.example:31443"


class _TegClient:
    """The registry's pooled TEG client (_get_teg_client): records each admin POST and answers 200."""

    def __init__(self):
        self.posts = []

    async def post(self, url, headers=None, json=None):
        self.posts.append((url, json))
        return types.SimpleNamespace(status_code=200, text="{}", json=lambda: {"status": "added", "total_partners": 3})


@pytest.fixture
def teg(monkeypatch):
    client = _TegClient()
    monkeypatch.setenv("TEG_ADMIN_API_KEY", "partner-halves-test-key-not-a-secret")
    monkeypatch.setattr(ti, "_get_teg_client", lambda: client)

    async def _resolve(name, db):
        return (LISBON_URL, "crossteg-fund-cache:lisbon") if str(name).strip().lower() == "lisbon" else None
    monkeypatch.setattr(ti, "_resolve_peer_target_for_cross_teg_fund", _resolve)
    return client


def _adds(client):
    return [body for url, body in client.posts if url.endswith("/api/v1/cross-teg/config/add-partner")]


# ── the helper ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_an_active_peer_row_is_registered_as_the_first_fund_named_it(teg):
    from agentvault_registry.background_tasks.reactor_helpers import register_peer_partner_on_teg
    assert asyncio.run(register_peer_partner_on_teg(None, "Lisbon", source_label="test")) is not None
    assert _adds(teg) == [{"teg_id": "teg-lisbon", "registry_id": "lisbon", "url": LISBON_URL}]


def test_a_row_it_cannot_resolve_registers_nothing(teg):
    from agentvault_registry.background_tasks.reactor_helpers import register_peer_partner_on_teg
    assert asyncio.run(register_peer_partner_on_teg(None, "faro", source_label="test")) is None
    assert teg.posts == []


# ── a quarantine lift and a reactivation ─────────────────────────────────────────────────────────────────────────────

class _LiftDB:
    """The compliance row the lift reads, and the peer row the re-registration reads."""

    def __init__(self):
        self.compliance = types.SimpleNamespace(federation_status="quarantined", policy_hash="0" * 64,
                                                quarantine_reason="drift", quarantine_since=None,
                                                quarantine_grace_expires=None)
        self.peer = types.SimpleNamespace(id=42, name="lisbon")

    async def execute(self, stmt, *a, **k):
        sql = str(stmt)
        one = self.compliance if "federated_registry_compliance" in sql else (
            self.peer if "peer_registries" in sql else None)
        return types.SimpleNamespace(scalar_one_or_none=lambda: one)

    async def commit(self):
        pass


def test_a_quarantine_lift_registers_the_peer_again(teg, monkeypatch):
    from agentvault_registry.services import federation_compliance_monitor as fcm

    class _Emitter:
        def __init__(self):
            self.received = []

        async def emit(self, **kw):
            self.received.append(kw.get("event_type"))
    emitter = _Emitter()
    monkeypatch.setattr(fcm, "get_event_emitter", lambda: emitter)
    db = _LiftDB()
    asyncio.run(fcm.FederationComplianceMonitor().lift_quarantine(db, peer_id=42, new_policy_hash="a" * 64,
                                                                   admin_email="admin@example.test"))
    assert db.compliance.federation_status == "federated"
    assert emitter.received == ["RegistryQuarantineLifted"]
    assert _adds(teg) == [{"teg_id": "teg-lisbon", "registry_id": "lisbon", "url": LISBON_URL}]


def test_a_reactivated_peer_is_registered_again(teg, monkeypatch):
    from agentvault_registry import schemas
    from agentvault_registry.crud import crud_peer_registry
    from agentvault_registry.routers import admin_federation

    peer = types.SimpleNamespace(id=42, name="lisbon", status="INACTIVE")

    async def _get(db, peer_id):
        return peer

    async def _set(db, db_peer, status, admin_id=None, reason=None):
        db_peer.status = status
        return db_peer

    class _Read:
        @staticmethod
        def model_validate(obj):
            return obj
    monkeypatch.setattr(crud_peer_registry, "get_peer_registry_by_id", _get)
    monkeypatch.setattr(crud_peer_registry, "update_peer_registry_status", _set)
    monkeypatch.setattr(schemas, "PeerRegistryRead", _Read)
    route = inspect.unwrap(admin_federation.reactivate_peer_registry)
    out = asyncio.run(route(peer_id=42, db=None, current_admin=types.SimpleNamespace(id=1)))
    assert out.status == "ACTIVE"
    assert _adds(teg) == [{"teg_id": "teg-lisbon", "registry_id": "lisbon", "url": LISBON_URL}]


# ── provisioning, both paths ─────────────────────────────────────────────────────────────────────────────────────────
# The provisioning routes start a whole operator stack; what is pinned here is where they call the helper: in the
# route's own body (not under the funding amount's `if`), before the genesis funding, and named in the answer.

def _route_using(module, call):
    src = inspect.getsource(module)
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.AsyncFunctionDef) and call in ast.unparse(node) and "_fund_new_op_treasury(" in \
                ast.unparse(node) and node.name != "_fund_new_op_treasury":
            return node
    return None


@pytest.mark.parametrize("modname", ["operator_self_service", "cloud_operators"])
def test_provisioning_registers_the_new_operator_before_its_funding_whatever_the_amount(modname):
    import importlib
    module = importlib.import_module(f"agentvault_registry.routers.{modname}")
    fn = _route_using(module, "register_peer_partner_on_teg")
    assert fn is not None, f"{modname}: no provisioning route registers the new operator as a TEG partner"
    body = [ast.unparse(st) for st in fn.body]
    reg = next(i for i, s in enumerate(body) if "register_peer_partner_on_teg" in s)
    fund = next(i for i, s in enumerate(body) if s.startswith("genesis_funding_applied: bool = False"))
    assert reg < fund, "registered after the genesis funding"
    assert isinstance(fn.body[reg], ast.Try), "the registration is not a statement of the route's own body"
    assert any("'teg_partner_registered': teg_partner_registered" in s for s in body), "not named in the answer"


# ── the cross-registry transfer's partner cache ──────────────────────────────────────────────────────────────────────

def _refusing_twopc(monkeypatch, transfer_answers):
    """A same-currency receiver on a peer frame whose TEG answers add-partner 200 and each cross-teg/transfer with the
    next of `transfer_answers` ((status, detail)); the BFS names the receiver's registry with its address."""
    _common(monkeypatch)
    from agentvault_registry.routers import agent_locations
    from agentvault_registry.services import spiffe_canonical
    posts, answers = [], list(transfer_answers)

    async def _resolved(db, did):
        return "teg-layer-b", "registry-b"

    async def _bfs(db):
        return [{"name": "registry-b", "url": "https://registry-b.example:8443"}]

    async def _ccy(db, target_peer=None):
        return "SBXA"

    async def _td(*a, **k):
        return "other.example"

    async def _tok(*a, **k):
        return "tok"

    async def _url(*a, **k):
        return "https://teg-b.example:8443"

    class _Resp:
        def __init__(self, code, detail=None):
            self.status_code, self.headers, self._detail = code, {}, detail
            self.text = "{}" if detail is None else f'{{"detail": "{detail}"}}'

        def json(self):
            return {} if self._detail is None else {"detail": self._detail}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **k):
            posts.append(url)
            if url.endswith("/cross-teg/config/add-partner"):
                return _Resp(200)
            code, detail = answers.pop(0) if len(answers) > 1 else answers[0]   # the last answer repeats
            return _Resp(code, detail)

    async def _fast(*a, **k):
        return None
    monkeypatch.setattr(ti, "_resolve_receiver_registry", _resolved)
    monkeypatch.setattr(agent_locations, "_compute_trusted_registries", _bfs)
    monkeypatch.setattr(ti, "_local_frame_currency", lambda: "SBXA")
    monkeypatch.setattr(ti, "_resolve_peer_currency", _ccy)
    monkeypatch.setattr(spiffe_canonical, "resolve_target_trust_domain", _td)
    monkeypatch.setattr(ti, "get_teg_token_for_agent", _tok)
    monkeypatch.setattr(ti, "_resolve_target_teg_url", _url)
    monkeypatch.setattr(ti.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(asyncio, "sleep", _fast)
    monkeypatch.delenv("TEG_CROSS_FRAME_BACKEND", raising=False)
    return posts


REFUSED = ("This TEG (teg-layer-a) has no current partner teg-layer-b (cross_teg_partner_refused): its partner list "
           "names no such peer")


def _added_partner(posts):
    return any(p.endswith("/cross-teg/config/add-partner") for p in posts)


def test_after_the_tegs_partner_refusal_the_next_transfer_adds_the_partner_again(redis, monkeypatch):
    monkeypatch.setattr(ti, "_runtime_partner_cache", {"teg-layer-b"})
    monkeypatch.setattr(ti, "_runtime_partner_added_at", {"teg-layer-b": time.monotonic()}, raising=False)
    posts = _refusing_twopc(monkeypatch, [(400, REFUSED), (500, None)])
    first = _xfer("k1")
    assert first.status == "failed" and "cross_teg_partner_refused" in (first.error_message or "")
    assert not _added_partner(posts), "the first transfer believed its cache"
    assert "teg-layer-b" not in ti._runtime_partner_cache
    del posts[:]
    with pytest.raises(HTTPException):   # the second transfer's TEG answers 500: only the partner step is under test
        _xfer("k2")
    assert _added_partner(posts), "the next transfer did not add the partner again"
    assert "teg-layer-b" in ti._runtime_partner_cache


def test_a_cached_partner_older_than_the_ttl_is_added_again(redis, monkeypatch):
    monkeypatch.setattr(ti, "_runtime_partner_cache", {"teg-layer-b"})
    monkeypatch.setattr(ti, "_runtime_partner_added_at", {"teg-layer-b": time.monotonic() - 10_000}, raising=False)
    posts = _refusing_twopc(monkeypatch, [(500, None)])
    with pytest.raises(HTTPException):
        _xfer("k3")
    assert _added_partner(posts), "an entry of any age was believed"


def test_a_fresh_cached_partner_is_not_added_again(redis, monkeypatch):   # control: the hot path keeps its cache
    monkeypatch.setattr(ti, "_runtime_partner_cache", {"teg-layer-b"})
    monkeypatch.setattr(ti, "_runtime_partner_added_at", {"teg-layer-b": time.monotonic()}, raising=False)
    posts = _refusing_twopc(monkeypatch, [(500, None)])
    with pytest.raises(HTTPException):
        _xfer("k4")
    assert not _added_partner(posts)
