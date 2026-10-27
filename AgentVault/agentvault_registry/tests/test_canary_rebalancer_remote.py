"""§FEDSYNCTRUTH-2 — the master rebalancer refills the senders of REMOTE-homed canary paths from the
home node's own treasury (no network: MockTransport; no database: the home list is injected)."""
import asyncio
import datetime
import json
import os
import urllib.parse
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@localhost:5432/ci")
os.environ.setdefault("API_KEY_SECRET", "ci-dummy-secret-0123456789abcdef")

import httpx  # noqa: E402

from agentvault_registry.background_tasks import canary_rebalancer as rb  # noqa: E402

A, B, C = ("did:theprotocol:aaaa-1", "did:theprotocol:bbbb-2", "did:theprotocol:cccc-3")


def _wire(monkeypatch, balances, homes, fund_status=200, detail_status=200):
    calls = {"fund": [], "detail": [], "status": 0}
    creds = {"op-washington": {"port": 27200, "email": "a@x", "password": "p"},
             "op-doha": {"port": 28300, "email": "a@x", "password": "p"}}
    monkeypatch.setattr(rb, "CANARY_REBALANCER_OP_CREDS", creds)
    monkeypatch.setenv("CANARY_HOME_HOST", "203.0.113.8")   # §BATCH3 item 1: the dial host is a carrier, not a literal
    # §R5 (V0221) put the mTLS canary-refill ask FIRST in the remote leg; it reads the peer row from
    # the DB, which these tests never had. Stub it to "no answer" so the leg falls through to the
    # password path this file was written to exercise (§BATCH3: found red in the image, never in CI).
    async def _no_mtls_answer(home, *, dry_run=False):
        return None
    monkeypatch.setattr(rb, "_refill_home_via_federation", _no_mtls_answer)
    monkeypatch.setattr(rb, "FRAME_B_ADMIN_PASSWORD", "")
    monkeypatch.setattr(rb, "_REMOTE_SENDERS_ENABLED", True)

    async def jwt(**kw):
        return "tok"
    monkeypatch.setattr(rb, "_get_admin_jwt", jwt)

    async def homes_fn():
        return homes
    monkeypatch.setattr(rb, "_load_remote_homes", homes_fn)

    async def emit(*a, **k):
        return None
    monkeypatch.setattr(rb, "_emit_audit_event", emit)

    def handler(req):
        p = req.url.path
        assert req.headers.get("authorization") == "Bearer tok"
        if p == "/api/v1/admin/canary/status":
            calls["status"] += 1
            pair = "frame-c->frame-a" if req.url.port == 28300 else "frame-a->frame-c"
            return httpx.Response(200, json={"paths": [
                {"sender_did": A, "is_active": True, "frame_pair": pair},
                {"sender_did": A, "is_active": True, "frame_pair": pair},      # same sender twice → one check
                {"sender_did": B, "is_active": True, "frame_pair": pair},
                {"sender_did": C, "is_active": False, "frame_pair": pair},     # inactive path → ignored
                {"sender_did": None, "is_active": True},
            ]})
        if p.startswith("/api/v1/admin/agents/"):
            did = p.rsplit("/", 1)[1]
            calls["detail"].append(did)
            if detail_status != 200:
                return httpx.Response(detail_status, json={"detail": "boom"})
            return httpx.Response(200, json={"agent_did": did, "liquid_balance": balances.get(did, 0)})
        if p == "/api/v1/teg/treasury/fund-agent":
            calls["fund"].append((req.url.port, req.read()))
            return httpx.Response(fund_status, json={"status": "completed" if fund_status == 200 else "x"})
        return httpx.Response(404)
    monkeypatch.setattr(rb, "_remote_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    rb._last_rebalance.clear()
    rb._last_balance.clear()
    rb._last_error.clear()
    return calls


def _run():
    now = datetime.datetime.now(datetime.timezone.utc)
    return asyncio.run(rb._rebalance_remote_senders(now)), now


def test_under_floor_remote_sender_is_funded_once_and_then_cools_down(monkeypatch):
    calls = _wire(monkeypatch, {A: 5.44, B: 60000}, ["op-washington", "Frame-C", "op-nowhere"])
    out, now = _run()
    assert out["remote_homes"] == 1                       # Frame-C refills itself; op-nowhere has no login
    assert out["remote_checked"] == 2 and out["remote_funded"] == 1 and out["remote_errors"] == 0
    assert sorted(calls["detail"]) == [A, B]
    (port, body), = calls["fund"]
    sent = json.loads(body)  # §DEPS: the values, not the bytes (httpx 0.28 sends compact JSON)
    assert port == 27200 and sent["target_agent_did"] == A
    assert sent["amount"] == str(rb.CANARY_REBALANCER_TOPUP_AVT)     # frame-a sender → AVT topup
    assert rb._last_balance[A][0] == Decimal("5.44") and rb._last_rebalance[A] == now
    out2, _ = _run()
    assert out2["remote_skipped_cooldown"] == 1 and out2["remote_funded"] == 0 and len(calls["fund"]) == 1


def test_frame_c_op_sender_gets_the_bvt_topup(monkeypatch):
    calls = _wire(monkeypatch, {A: 1, B: 99999}, ["op-doha"])
    out, _ = _run()
    assert out["remote_funded"] == 1
    (port, body), = calls["fund"]
    assert port == 28300 and json.loads(body)["amount"] == str(rb.CANARY_REBALANCER_TOPUP_BVT)


def test_a_failed_balance_read_is_an_error_not_a_fund(monkeypatch):
    calls = _wire(monkeypatch, {A: 1}, ["op-washington"], detail_status=503)
    out, _ = _run()
    assert out["remote_errors"] == 2 and out["remote_funded"] == 0 and calls["fund"] == []
    assert rb._last_error[A] == "balance_query_failed"


def test_a_refused_fund_is_counted_and_not_cooled_down(monkeypatch):
    calls = _wire(monkeypatch, {A: 1, B: 99999}, ["op-washington"], fund_status=403)
    out, _ = _run()
    assert out["remote_errors"] == 1 and out["remote_funded"] == 0 and len(calls["fund"]) == 1
    assert A not in rb._last_rebalance and rb._last_error[A] == "fund_failed"


def test_home_login_collapses_labels_and_skips_frames(monkeypatch):
    monkeypatch.setattr(rb, "CANARY_REBALANCER_OP_CREDS",
                        {"op-losangeles": {"port": 27100, "email": "e", "password": "p"}})
    monkeypatch.setenv("CANARY_HOME_HOST", "203.0.113.8")
    assert rb._remote_home_creds("op-singapore")["home"] == "op-losangeles"    # label → identity
    assert rb._remote_home_creds("op-losangeles")["base"].endswith(":27100")
    assert rb._remote_home_creds("Frame-C") is None
    assert rb._remote_home_creds("op-unknown") is None
    assert rb._remote_home_creds("") is None


def test_admin_login_url_encodes_the_form_body(monkeypatch):
    """The login body is a FORM: a password with `+`, `%`, `=` or `&` must arrive intact — the old
    f-string sent `+` as a space and broke four operators' logins for weeks (measured 2026-09-03)."""
    seen = {}

    def handler(req):
        seen["body"] = req.read()
        form = urllib.parse.parse_qs(seen["body"].decode())
        return httpx.Response(200, json={"access_token": "tok"}) if form.get("password") == ["a+b%c=d&e"] else httpx.Response(401)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(rb.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    rb._admin_jwt_cache.clear()
    tok = asyncio.run(rb._get_admin_jwt(cache_key="t", login_url="http://op/api/v1/auth/login", email="a@x", password="a+b%c=d&e"))
    assert tok == "tok"
    assert b"password=a%2Bb%25c%3Dd%26e" in seen["body"]


def test_without_canary_home_host_the_password_leg_is_inert(monkeypatch):
    """§BATCH3 item 1: the box IP left the code. With no CANARY_HOME_HOST the retired password leg
    resolves no home at all (None), it does not guess a host — V0221 retired its credentials anyway."""
    monkeypatch.setattr(rb, "CANARY_REBALANCER_OP_CREDS", {"op-losangeles": {"port": 27100, "email": "a@b", "password": "x"}})
    monkeypatch.delenv("CANARY_HOME_HOST", raising=False)
    assert rb._remote_home_creds("op-losangeles") is None
    monkeypatch.setenv("CANARY_HOME_HOST", "203.0.113.8")
    assert rb._remote_home_creds("op-losangeles")["base"] == "http://203.0.113.8:27100"

