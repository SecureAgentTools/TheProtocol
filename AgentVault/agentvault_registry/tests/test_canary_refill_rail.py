"""§R5 (batch 2, 2026-09-05) — the mTLS canary-refill rail.
HOME side: refill_local_senders() funds only senders below the floor, one reference per sender
per hour, respects the cooldown and the cap, funds nothing on dry_run, says PAUSED/DISABLED.
MASTER side: _refill_home_via_federation() posts to the home's /api/v1/federation/canary-refill
over the canary-fire transport and returns None on 404 so the caller can name its fallback;
_rebalance_remote_senders() prefers it and never touches the password leg when it answers.
Doubles here ASSERT RECEIPT (what was funded, with which reference) — a fake that accepts
everything proves nothing.
"""
import json
import datetime
import os
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://t:t@localhost:5432/t")
os.environ.setdefault("API_KEY_SECRET", "test-only-secret-value-0123456789abcdef")

from agentvault_registry.background_tasks import canary_rebalancer as cr  # noqa: E402

NOW = datetime.datetime(2026, 9, 5, 4, 30, tzinfo=datetime.timezone.utc)


def _canary(did, frame="frame-a"):
    return SimpleNamespace(agent_did=did, frame=frame, registry_url="http://registry-x:8000", is_active=True)


@pytest.fixture
def home(monkeypatch):
    funded = []
    monkeypatch.setattr(cr, "CANARY_REFILL_ENABLED", True)
    monkeypatch.setattr(cr, "CANARY_ENABLED", True, raising=False)
    monkeypatch.setattr(cr, "CANARY_REBALANCER_FLOOR_AVT", Decimal("5000"))
    monkeypatch.setattr(cr, "CANARY_REBALANCER_TOPUP_AVT", Decimal("1000000"))
    monkeypatch.setattr(cr, "CANARY_REFILL_MAX_FUND", 10)
    cr._last_rebalance.clear(); cr._last_error.clear()

    async def _now(): return NOW
    async def _paused(): return False
    async def _senders(): return [_canary("did:a:low"), _canary("did:a:high"), _canary("did:a:dead")]
    async def _balance(c):
        return {"did:a:low": Decimal("12.5"), "did:a:high": Decimal("999999"), "did:a:dead": None}[c.agent_did]
    async def _fund(c, amount, ref, actor):
        funded.append((c.agent_did, amount, ref, actor)); return {"transaction_id": f"tx-{len(funded)}"}
    monkeypatch.setattr(cr, "_now_utc", _now); monkeypatch.setattr(cr, "_fleet_paused", _paused)
    monkeypatch.setattr(cr, "_load_local_senders", _senders); monkeypatch.setattr(cr, "_check_balance", _balance)
    monkeypatch.setattr(cr, "_fund_local_from_treasury", _fund)
    return funded


@pytest.mark.asyncio
async def test_home_funds_only_below_floor_with_a_per_attempt_reference(home):
    """§BATCH3 (2026-09-05): the reference was ONE per sender per HOUR and doubled as the treasury
    rail's idempotency key; the keeper gate (test_treasury_fund_idempotency) refused it — a floor-keeper
    dedups by the balance it reads, and an hour key left a drained sender under the floor for the rest
    of the hour. Now: unique per attempt, an audit reference only."""
    rep = await cr.refill_local_senders(requested_by="spiffe://agentvault.com/service/registry-a")
    assert rep["ok"] and rep["checked"] == 3 and rep["funded"] == 1 and rep["errors"] == 1
    assert len(home) == 1
    did, amount, ref, actor = home[0]
    assert (did, amount, actor) == ("did:a:low", Decimal("1000000"), "canary_refill:spiffe://agentvault.com/service/registry-a")
    assert ref.startswith("canary-refill-did:a:low-20260905")
    # a retried ask is deduped by the keeper's own means — the balance it re-reads and the per-agent
    # cooldown (CANARY_REBALANCER_MIN_INTERVAL_SEC) — never by an idempotency key
    rep2 = await cr.refill_local_senders(requested_by="spiffe://agentvault.com/service/registry-a")
    assert rep2["funded"] == 0 and {r["did"]: r for r in rep2["senders"]}["did:a:low"]["action"] == "cooldown"
    assert cr.refill_reference("did:a:low", NOW) != cr.refill_reference("did:a:low", NOW), "unique per attempt"
    by = {r["did"]: r for r in rep["senders"]}
    assert by["did:a:high"]["action"] == "above_floor" and by["did:a:dead"]["action"] == "balance_query_failed"
    assert by["did:a:low"]["action"] == "funded" and by["did:a:low"]["tx"] == "tx-1"


@pytest.mark.asyncio
async def test_home_dry_run_funds_nothing_but_names_what_it_would(home):
    rep = await cr.refill_local_senders(requested_by="peer", dry_run=True)
    assert rep["funded"] == 0 and rep["would_fund"] == 1 and home == []


@pytest.mark.asyncio
async def test_home_respects_cooldown_and_cap(home, monkeypatch):
    cr._last_rebalance["did:a:low"] = NOW - datetime.timedelta(minutes=5)
    rep = await cr.refill_local_senders(requested_by="peer")
    assert rep["skipped_cooldown"] == 1 and rep["funded"] == 0 and home == []
    cr._last_rebalance.clear()
    rep = await cr.refill_local_senders(requested_by="peer", max_fund=0)
    assert rep["funded"] == 0 and [r["action"] for r in rep["senders"] if r["did"] == "did:a:low"] == ["cap_reached"]


@pytest.mark.asyncio
async def test_home_says_paused_and_disabled(home, monkeypatch):
    async def _paused(): return True
    monkeypatch.setattr(cr, "_fleet_paused", _paused)
    rep = await cr.refill_local_senders(requested_by="peer")
    assert rep["paused"] is True and rep["funded"] == 0 and home == []
    monkeypatch.setattr(cr, "CANARY_REFILL_ENABLED", False)
    rep = await cr.refill_local_senders(requested_by="peer")
    assert rep["disabled"] is True


def _peer(monkeypatch, base_url="https://op-berlin.op.theprotocol.cloud:8443", status="ACTIVE"):  # the real peer-row shape (measured on registry-a)
    class _Res:
        def __init__(self, rows): self._rows = rows
        def scalars(self): return self
        def all(self): return self._rows
    class _DB:
        async def execute(self, *_a, **_k): return _Res([SimpleNamespace(name="op-berlin", status=status, base_url=base_url)])
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
    monkeypatch.setattr(cr, "get_db_context", lambda: _DB())


@pytest.mark.asyncio
async def test_master_posts_over_the_federation_channel_and_reads_the_report(monkeypatch):
    _peer(monkeypatch)
    seen = {}
    def handler(request: httpx.Request):
        seen["url"] = str(request.url); seen["json"] = request.read()
        return httpx.Response(200, json={"ok": True, "checked": 2, "funded": 1, "errors": 0, "skipped_cooldown": 0})
    monkeypatch.setattr(cr, "_remote_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    import agentvault_registry.identity.svid_client as sc
    monkeypatch.setattr(sc, "get_client_cert_config", lambda target_url=None: {"verify": False}, raising=False)
    rep = await cr._refill_home_via_federation("op-berlin")
    assert rep and rep["funded"] == 1
    assert seen["url"].endswith("/api/v1/federation/canary-refill") and seen["url"].startswith("https://")
    sent = json.loads(seen["json"])  # §DEPS: the values, not the bytes (httpx 0.28 sends compact JSON)
    assert sent["dry_run"] is False and "max_fund" in sent


@pytest.mark.asyncio
async def test_master_returns_none_on_404_so_the_caller_names_its_fallback(monkeypatch):
    _peer(monkeypatch)
    monkeypatch.setattr(cr, "_remote_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))))
    import agentvault_registry.identity.svid_client as sc
    monkeypatch.setattr(sc, "get_client_cert_config", lambda target_url=None: {"verify": False}, raising=False)
    assert await cr._refill_home_via_federation("op-berlin") is None


@pytest.mark.asyncio
async def test_master_prefers_federation_and_never_touches_the_password_leg(monkeypatch):
    async def homes(): return ["op-berlin"]
    # §CANARYONBOARD: a home also reports what it swept back to its treasury above the ceiling, and the master counts it
    async def fed(home, dry_run=False): return {"ok": True, "checked": 3, "funded": 2, "swept": 1, "errors": 0, "skipped_cooldown": 1}
    async def forbidden(*a, **k): raise AssertionError("the password leg must not run when the rail answered")
    monkeypatch.setattr(cr, "_REMOTE_SENDERS_ENABLED", True)
    monkeypatch.setattr(cr, "_load_remote_homes", homes)
    monkeypatch.setattr(cr, "_refill_home_via_federation", fed)
    monkeypatch.setattr(cr, "_get_admin_jwt", forbidden)
    out = await cr._rebalance_remote_senders(NOW)
    assert out == {"remote_homes": 1, "remote_checked": 3, "remote_funded": 2, "remote_swept": 1, "remote_errors": 0,
                   "remote_skipped_cooldown": 1}


def test_route_is_registered_under_federation():
    from agentvault_registry.routers import federation_sync
    paths = {getattr(r, "path", "") for r in federation_sync.router.routes}
    assert any(p.endswith("/canary-refill") for p in paths), sorted(paths)[:5]
