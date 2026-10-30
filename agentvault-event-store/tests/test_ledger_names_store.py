"""W4 phase 1 (agentvault2-aa, 2026-10-25): the event store reads a ledger event under its old and its new name.

His words that day to agentvault2-69: "i want the illegal wording completly gone before opening" and, on the ledger, "just
use the new wording and make it accept both or something" (sessionlogs2026/PLAN_2026-10-25_COMPLIANT_OPENING.md, W4).
Phase 2 lets an emitter write UnitsTransferred for TokensTransferred (and the rest of src/ledger_names.py); before any
emitter does, every reader in the store reads both names the same. Measured that day: every running store projects
balances from LedgerBalanceChanged alone (projection_config.single_writer on EU, ASIA, both sandbox frames and Frame A),
so the typed events are audit-only there; these readers still serve history, forensics, Kafka, the websocket and a store
without single_writer. What these tests pin (no database; the trigger's half is tests/test_ledger_names_trigger.py, its
own runner):
- the map is the registry's (agentvault_registry/core/ledger_names.py), data for data;
- the projection's replay (one agent, one agent at a time up to a moment, every agent with the supply audit) gives the
  same balances and the same supply figures for a history written under the new names as under the old, and a legacy
  spelling (TokenTransferred) still moves nothing, as before;
- the skip policy skips LockPayoutsDistributed while the policy table names only RewardsDistributed, and a new name of a
  known event is known;
- UnitsIssued is mint-class: an operator of this frame is refused it as it is refused TokensIssued, through the real
  events router; this frame's registry appends it, and only with an idempotency key (it is balance-moving);
- the other sets (forensics', Kafka's financial topic, the consumer's pre-locks) carry the new names, the transfer
  recipient's read asks both names, and a transfer's recipient channel is published for UnitsTransferred;
- every comparison of an event type against an old name in src asks the map (an AST scan, as the registry's).
Run: python -m pytest tests/test_ledger_names_store.py -q   (needs pytest, httpx and cryptography)
"""
import ast
import asyncio
import datetime
import hashlib
import os
import sys
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@127.0.0.1:1/ci")

import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import ledger_names as L  # noqa: E402
from src.models.events import Event  # noqa: E402
from src.services import materialized_projections, projections  # noqa: E402

T0 = datetime.datetime(2026, 10, 25, 20, 0, tzinfo=datetime.timezone.utc)
A, B = "did:theprotocol:w4-a", "did:theprotocol:w4-b"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── the map ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_map_is_the_registrys():
    assert L.RENAMED == {
        "TokensTransferred": "UnitsTransferred", "TokensIssued": "UnitsIssued", "TokensStaked": "UnitsLocked",
        "TokensUnstaked": "UnitsUnlocked", "StakeForceUnstaked": "LockForceUnlocked",
        "RewardsDistributed": "LockPayoutsDistributed", "RewardsAutoCompounded": "LockPayoutsRelocked",
        "RewardsAutoCompoundSkipped": "LockPayoutRelockSkipped", "TokensBridgeLocked": "UnitsBridgeLocked",
        "TokensBridgeUnlocked": "UnitsBridgeUnlocked"}
    assert L.AGORA_RENAMED == {
        "ExchangeDividendDeclared": "ExchangeDistributionDeclared", "ExchangeDividendPaid": "ExchangeDistributionPaid",
        "ExchangeSharesIssued": "ExchangePointsIssued", "ExchangeSharesSplit": "ExchangePointsSplit",
        "ExchangeShareRefloated": "ExchangePointsRefloated"}
    assert L.LEGACY == {"TokenTransferred": "TokensTransferred", "RewardDistributed": "RewardsDistributed",
                        "StakeRewardDistributed": "RewardsDistributed"}
    # the registry's copy, where this checkout sits in the stack (the store's own image carries only itself)
    reg = ROOT.parent / "AgentVault" / "agentvault_registry" / "src" / "agentvault_registry" / "core" / "ledger_names.py"
    if reg.is_file():
        ns: dict = {}
        exec(compile(reg.read_text(), str(reg), "exec"), ns)
        assert (ns["RENAMED"], ns["AGORA_RENAMED"], ns["LEGACY"]) == (L.RENAMED, L.AGORA_RENAMED, L.LEGACY)


def test_the_store_reads_a_new_name_as_its_old_one_and_leaves_a_legacy_spelling_alone():
    assert L.live_old("UnitsTransferred") == "TokensTransferred" and L.live_old("TokensTransferred") == "TokensTransferred"
    assert L.live_old("TokenTransferred") == "TokenTransferred", "a legacy spelling is never applied by the store"
    assert L.live_names("UnitsLocked") == ("TokensStaked", "UnitsLocked")
    assert L.live_names("AgentCreated") == ("AgentCreated",)
    assert L.expand_live({"TokensIssued", "AgentCreated"}) == {"TokensIssued", "UnitsIssued", "AgentCreated"}
    assert L.old_name("StakeRewardDistributed") == "RewardsDistributed" and L.new_name("TokensIssued") == "UnitsIssued"


# ── the projection's replay ─────────────────────────────────────────────────────────────────────────────────────────

def _history(names: bool):
    """One frame's history, under the old names (names=False) or the new ones (names=True); the unrenamed events and
    the legacy spelling are the same in both."""
    n = (lambda t: L.RENAMED.get(t, t)) if names else (lambda t: t)
    rows = [
        (n("TokensIssued"), A, {"amount": "100"}),
        (n("TokensTransferred"), A, {"from": A, "to": B, "amount": "30"}),
        ("TransactionFeeCollected", A, {"fee_amount": "0.15"}),
        (n("TokensStaked"), A, {"amount": "20"}),
        (n("TokensUnstaked"), A, {"amount": "5"}),
        (n("TokensIssued"), A, {"amount": "1.25"}),
        (n("RewardsAutoCompounded"), A, {"amount": "1.25"}),
        (n("RewardsDistributed"), A, {"amount": "1.25", "recipients": 1}),
        (n("TokensBridgeLocked"), A, {"amount": "2"}),
        (n("TokensBridgeUnlocked"), A, {"amount": "0.5"}),
        ("TokenTransferred", A, {"from": A, "to": B, "amount": "7"}),     # legacy: never applied, before or after
        ("DisputeSlash", B, {"amount": "1"}),
    ]
    return [Event(id=f"w4-{i}", event_type=t, aggregate_id=agg, data=d, source_service="registry",
                  timestamp=T0 + datetime.timedelta(seconds=i)) for i, (t, agg, d) in enumerate(rows)]


class _Store:
    def __init__(self, events):
        self.events, self.db = events, None

    async def get_events_involving_agent(self, did):
        recipient = set(L.live_names("TokensTransferred")) | {"CrossRegistryTransferCompleted"}
        return [e for e in self.events
                if e.aggregate_id == did or (e.event_type in recipient and e.data.get("to") == did)]

    async def get_latest_snapshot(self):
        return None

    async def get_all_events(self, limit=200000):
        return list(self.events)


@pytest.fixture
def replay(monkeypatch):
    """The replay paths (no materialized table, no policy fetch), the policy table naming only the old skip."""
    monkeypatch.setattr(materialized_projections, "MATERIALIZED_ENABLED", False)

    async def _no_fetch():
        return None
    monkeypatch.setattr(projections, "_refresh_skip_policies", _no_fetch)
    monkeypatch.setattr(projections, "_skip_policy_cache_ts", float("inf"))
    monkeypatch.setattr(projections, "_skip_in_projection", {"RewardsDistributed", "CrossRegistryTransferCompleted"})
    projections.invalidate_balance_cache()
    yield
    projections.invalidate_balance_cache()


def _views(new_names: bool):
    projections.invalidate_balance_cache()
    svc = projections.ProjectionService(_Store(_history(new_names)))
    one = {d: _run(svc.calculate_balance(d)) for d in (A, B)}
    projections.invalidate_balance_cache()
    at = {d: _run(svc.get_balance_at_timestamp(d, T0 + datetime.timedelta(hours=1))) for d in (A, B)}
    every = {b.agent_did: (b.liquid_balance, b.staked_balance, b.event_count) for b in _run(svc.get_all_balances())}
    return ({d: (p.liquid_balance, p.staked_balance) for d, p in one.items()},
            {d: (p.liquid_balance, p.staked_balance) for d, p in at.items()},
            every, dict(svc._last_supply_audit))


def test_a_history_under_the_new_names_projects_as_under_the_old(replay):
    old, new = _views(False), _views(True)
    assert new == old
    one, at, every, supply = old
    # the old names' own figures, so an equal pair of wrong answers cannot pass
    assert one[A] == (Decimal("100") - 30 - Decimal("0.15") - 20 + 5 + Decimal("1.25") - Decimal("1.25"),
                      Decimal("20") - 5 + Decimal("1.25")) == at[A]
    assert one[B] == (Decimal("30") - 1, Decimal("0")) == at[B], "the legacy TokenTransferred moved nothing"
    assert supply["tokens_issued"] == str(Decimal("101.25")) and supply["tokens_destroyed"] == "1"
    assert supply["bridge_locked"] == "1.5"
    assert every[A][2] == 10, "every applied event of A counted once (the payout skipped, the legacy one counted as before)"


def test_the_payout_is_skipped_under_its_new_name_while_the_table_names_only_the_old(replay):
    assert projections._should_skip_in_projection("LockPayoutsDistributed") is True
    assert projections._should_skip_in_projection("RewardsDistributed") is True
    assert projections._should_skip_in_projection("UnitsTransferred") is False
    assert projections._should_skip_in_projection("RewardDistributed") is False, "a legacy spelling as before"


def test_a_new_name_of_a_known_event_is_known(monkeypatch):
    monkeypatch.setattr(projections, "_known_event_types", {"TokensIssued", "AgentCreated"})
    assert projections._is_known_event_type("UnitsIssued") and projections._is_known_event_type("TokensIssued")
    assert not projections._is_known_event_type("UnitsLocked") and not projections._is_known_event_type("Nonsense")


def test_the_transaction_history_finds_an_asked_event_under_either_name(replay):
    svc = projections.ProjectionService(_Store(_history(True)))
    got = [h.event_type for h in _run(svc.get_transaction_history(A, limit=100, event_types=["TokensStaked"]))]
    assert got == ["UnitsLocked"]
    every = {h.event_type for h in _run(svc.get_transaction_history(A, limit=100))}
    assert {"UnitsIssued", "UnitsTransferred", "UnitsLocked", "UnitsUnlocked", "LockPayoutsRelocked",
            "LockPayoutsDistributed"} <= every


def test_the_sets_carry_the_new_names():
    from src.routers import forensics
    from src.services import kafka_publisher
    for t in ("TokensIssued", "TokensTransferred", "TokensStaked", "TokensUnstaked", "RewardsAutoCompounded"):
        for name in L.live_names(t):
            assert name in projections.BALANCE_MOVING_EVENT_TYPES and name in forensics._BALANCE_MOVING, name
            assert kafka_publisher.get_kafka_topic(name) == "theprotocol.events.financial", name
    assert kafka_publisher.get_kafka_topic("LockPayoutsDistributed") == "theprotocol.events.financial"
    assert "TokenTransferred" not in projections.BALANCE_MOVING_EVENT_TYPES
    src = (ROOT / "src" / "services" / "kafka_consumer.py").read_text()
    assert "_single_agent = ledger_names.expand_live({" in src and 'ledger_names.live_old(et) == "TokensTransferred"' in src


def test_the_recipients_read_asks_both_transfer_names():
    from src.services.event_store import EventStore

    class _Db:
        stmt = None

        async def execute(self, stmt):
            _Db.stmt = stmt

            class _R:
                def scalars(self):
                    return self

                def all(self):
                    return []
            return _R()
    _run(EventStore(_Db()).get_events_involving_agent(B))
    sql = str(_Db.stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "'TokensTransferred'" in sql and "'UnitsTransferred'" in sql and "'TokenTransferred'" not in sql


@pytest.mark.parametrize("name, recipient_told", [("TokensTransferred", True), ("UnitsTransferred", True),
                                                   ("TokenTransferred", False), ("UnitsLocked", False)])
def test_a_transfer_under_either_name_reaches_its_recipients_channel(name, recipient_told):
    from src.services.websocket_publisher import EventPublisher
    sent = []

    class _Mgr:
        async def broadcast_to_channel(self, channel, message):
            sent.append(channel)
    ev = Event(event_type=name, aggregate_id=A, data={"from": A, "to": B, "amount": "1"}, source_service="registry")
    _run(EventPublisher(_Mgr()).publish_event(ev))
    assert sent[:3] == [f"agent:{A}", "events:all", f"events:{name}"]
    assert (f"agent:{B}" in sent) is recipient_told, "a legacy spelling as before: no recipient channel"


# ── the mint guard, through the real events router ──────────────────────────────────────────────────────────────────

MARKER = "w4-names-test-proxy-marker-not-a-secret-000000"
EU = "eu.theprotocol.cloud"
ORIGIN = f"spiffe://{EU}/service/eu-registry"
AMS_WRITER = f"spiffe://{EU}/operator/amsterdam/svid-writer"
AMS_LIC = "fa43d7b6-a25b-48fc-a7a5-5afc52357a67"
APPEND = "/api/v1/events/"
_CERTS: dict = {}


def _through_terminator(spiffe_id):
    if spiffe_id not in _CERTS:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "w4-names-test")])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(minutes=1)).not_valid_after(now + datetime.timedelta(hours=1))
                .add_extension(x509.SubjectAlternativeName([x509.UniformResourceIdentifier(spiffe_id)]), critical=False)
                .sign(key, hashes.SHA256()))
        _CERTS[spiffe_id] = quote(cert.public_bytes(serialization.Encoding.PEM).decode())
    return {"X-SSL-Client-Verify": "SUCCESS", "X-SSL-Client-Cert": _CERTS[spiffe_id], "X-ES-Proxy-Auth": MARKER}


@pytest.fixture
def router(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src import internal_key
    from src.database.connection import get_db
    from src.models.federation_operator import FederationOperator
    from src.routers import events

    class _Result:
        def __init__(self, one=None, tuples=()):
            self._one, self._tuples = one, list(tuples)

        def scalar_one_or_none(self):
            return self._one

        def fetchall(self):
            return list(self._tuples)

        def scalars(self):
            return self

        def all(self):
            return []

    ams = FederationOperator(id=AMS_LIC, operator_name="amsterdam", spiffe_id=AMS_WRITER, status="active",
                             max_events_per_minute=1000, bayesian_discount=1.0,
                             license_key_hash=hashlib.sha256(AMS_LIC.encode()).hexdigest())

    class _Db:
        async def execute(self, stmt, params=None):
            try:
                sql = " ".join(str(stmt.compile(compile_kwargs={"literal_binds": True})).split())
            except Exception:  # noqa: BLE001
                sql = str(stmt)
            if sql.startswith("SELECT federation_operators.spiffe_id, federation_operators.operator_name, "
                              "federation_operators.status, federation_operators.max_events_per_minute"):
                return _Result(tuples=[(ams.spiffe_id, ams.operator_name, ams.status, ams.max_events_per_minute)])
            if "federation_operators" in sql and (AMS_WRITER in sql or AMS_LIC in sql):
                return _Result(one=ams)
            return _Result()

        def add(self, obj):
            pass

        async def commit(self):
            pass

    class _Writer:
        stored: list = []

        def __init__(self, db):
            pass

        async def append_event(self, event, source_operator_id=None):
            _Writer.stored.append(event)
            return event

    monkeypatch.setattr(internal_key, "_CURRENT", "w4-names-test-internal-key-not-a-secret")
    monkeypatch.setattr(internal_key, "_PREVIOUS", "")
    monkeypatch.setattr(events, "MTLS_REQUIRED", True)
    monkeypatch.setattr(events, "PROXY_TRUST_SECRET", MARKER)
    monkeypatch.setattr(events, "EVENTSTORE_HTTP_VIA_KAFKA", False)
    monkeypatch.setattr(events, "EventStore", _Writer)
    monkeypatch.setenv("TRUSTED_SPIFFE_DOMAINS", EU)
    monkeypatch.setenv("KNOWN_INTERNAL_SERVICES", "eu-registry")
    monkeypatch.setenv("ES_OWN_TRUST_DOMAIN", EU)
    events._OPERATOR_STANDING.clear()
    monkeypatch.setattr(events, "_OPERATOR_WINDOW", events.MinuteWindow())
    _Writer.stored = []
    app = FastAPI()
    app.include_router(events.router)

    async def _db():
        yield _Db()
    app.dependency_overrides[get_db] = _db
    with TestClient(app) as client:
        yield client, _Writer


def _mint(client, name, caller, key="w4-mint-1"):
    body = {"event_type": name, "aggregate_id": "did:theprotocol:w4-agent", "data": {"amount": 1000},
            "source_service": "registry"}
    if key:
        body["idempotency_key"] = key
    return client.post(APPEND, json=body, headers=_through_terminator(caller))


@pytest.mark.parametrize("name", ["TokensIssued", "UnitsIssued"])
def test_an_operator_may_not_mint_under_either_name(router, name):
    client, writer = router
    r = _mint(client, name, AMS_WRITER)
    assert r.status_code == 403, r.text
    assert "may only be appended by this frame's own registry" in r.json()["detail"]
    assert writer.stored == []


def test_this_frames_registry_appends_units_issued_with_its_key_and_not_without(router):
    client, writer = router
    r = _mint(client, "UnitsIssued", ORIGIN, key=None)
    assert r.status_code == 400 and "requires a deterministic idempotency_key" in r.json()["detail"], r.text
    assert writer.stored == []
    r = _mint(client, "UnitsIssued", ORIGIN)
    assert r.status_code in (200, 201), r.text
    assert [e.event_type for e in writer.stored] == ["UnitsIssued"]


# ── the source: every comparison against an old name asks the map ──────────────────────────────────────────────────

OLD = set(L.RENAMED) | set(L.AGORA_RENAMED)


def _lits(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        out = set()
        for e in node.elts:
            out |= _lits(e)
        return out
    return set()


def test_every_comparison_against_an_old_name_asks_the_map():
    bad, seen = [], 0
    for p in sorted((ROOT / "src").rglob("*.py")):
        if p.name == "ledger_names.py" or "__pycache__" in p.parts:
            continue
        src = p.read_text(encoding="utf-8")
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.Compare):
                names = _lits(n.left)
                for c in n.comparators:
                    names |= _lits(c)
                if names & OLD:
                    seen += 1
                    if "ledger_names" not in src:
                        bad.append(f"{p.relative_to(ROOT)}:{n.lineno} {sorted(names & OLD)}")
    assert seen >= 22, f"the scan sees the store's comparisons (22 measured 2026-10-25, 19 in the projection; {seen})"
    assert bad == [], "read the event under every name it may be written under (src/ledger_names.py)"
