"""§CANARYONBOARD (2026-09-22, his words "onboard canaries but dark for discovery ... for eu-asia cluster and sandbox
cluster. intervall should be half an hour"): what the registry needed before canaries could run on the new clusters.

1. The rebalancer classified senders only by the LEGACY registries' names (registry-a, :8100, frame-c, the OP_CREDS
   ports), so on any other network a master's own senders read "unknown" and were skipped forever. A sender whose
   registry_url is this node now reads "self" and is funded from this node's treasury.
2. Its floor/top-up read os.environ only (5,000 / 1,000,000): on a low-supply frame (EU and ASIA hold 1,000,001 each)
   one top-up was the whole supply. They now read the network profile after the env.
3. The API tester's contracts fired path 1 (a real canary wherever canaries run) and switched off EVERY path (the
   maintenance body used the wrong key, so the endpoint read scope "all", enable false).
4. His words the same afternoon: "since we dont mint so much on eu-asia frame we have to rebalance them properly". The
   rebalancer only ever PAID canaries; what a canary received stayed there. A ceiling now closes the band: above it the
   excess beyond floor + top-up goes back to the node's own treasury (the escrow rail, one sweep per sender per day).
"""
import inspect

from agentvault_registry.background_tasks import canary_rebalancer as cr


def test_a_sender_on_this_node_is_self(monkeypatch):
    monkeypatch.delenv("REGISTRY_SELF_URL", raising=False)
    assert cr._home_kind("http://localhost:8000") == "self"
    assert cr._home_kind("http://127.0.0.1:8150") == "self"
    monkeypatch.setenv("REGISTRY_SELF_URL", "https://eu.theprotocol.cloud")
    assert cr._home_kind("https://eu.theprotocol.cloud/") == "self"


def test_the_legacy_kinds_are_unchanged(monkeypatch):
    monkeypatch.delenv("REGISTRY_SELF_URL", raising=False)
    monkeypatch.setattr(cr, "CANARY_REBALANCER_OP_CREDS", {}, raising=False)
    assert cr._home_kind("http://registry-a:8000") == "mainframe-a"
    assert cr._home_kind("http://frame-b-registry:8100") == "frame-b"
    assert cr._home_kind("http://frame-c-registry:8000") == "frame-c"
    assert cr._home_kind("https://sbx-beta.example") == "unknown"


def test_self_is_funded_from_this_nodes_treasury():
    src = inspect.getsource(cr._refund_agent)
    assert 'if home in ("mainframe-a", "frame-c", "self"):' in src
    assert "_fund_agent_from_treasury_internal" in src


def test_floor_and_topup_follow_the_network_profile():
    src = inspect.getsource(cr)
    assert '_np.knob("CANARY_REBALANCER_FLOOR_AVT", "5000")' in src
    assert '_np.knob("CANARY_REBALANCER_TOPUP_AVT", "1000000")' in src


def test_the_api_tester_can_no_longer_fire_or_switch_off_real_canaries():
    from agentvault_registry.api_tests.contracts import admin_canary_actions as aca
    fire = [v for v in vars(aca).values() if isinstance(v, type) and v.__name__ == "CanaryFire"][0]
    maint = [v for v in vars(aca).values() if isinstance(v, type) and v.__name__ == "CanaryMaintenance"][0]
    assert fire().body({}) == {"path_id": 99999}
    assert maint().body({}) == {"scope": [], "enable": False}


class _Canary:
    frame = "eu"
    agent_did = "did:theprotocol:eu.theprotocol.cloud:0000aaaa-0000-4000-8000-00000000abcd"
    registry_url = "http://localhost:8000"


def _band(monkeypatch, floor, topup, ceiling):
    from decimal import Decimal as D
    monkeypatch.setattr(cr, "CANARY_REBALANCER_FLOOR_AVT", D(floor))
    monkeypatch.setattr(cr, "CANARY_REBALANCER_TOPUP_AVT", D(topup))
    monkeypatch.setattr(cr, "CANARY_REBALANCER_CEILING_AVT", D(ceiling))


def test_the_sweep_returns_only_what_lies_beyond_floor_plus_topup(monkeypatch):
    from decimal import Decimal as D
    _band(monkeypatch, "25", "25", "0")
    assert cr.sweep_amount(_Canary, D("1000")) == 0            # the default: no sweep anywhere it is not set
    _band(monkeypatch, "25", "25", "150")
    assert cr.sweep_amount(_Canary, D("150")) == 0             # at the ceiling is inside the band
    assert cr.sweep_amount(_Canary, D("1000")) == D("950")     # back to floor + top-up, where a refill lands at most
    _band(monkeypatch, "25", "25", "50")
    assert cr.sweep_amount(_Canary, D("1000")) == 0            # a ceiling not above floor + top-up would loop: refused


def test_one_sweep_per_sender_per_day():
    import datetime
    t = datetime.datetime(2026, 9, 22, 23, 59, tzinfo=datetime.timezone.utc)
    assert cr.sweep_reference(_Canary.agent_did, t) == "canary-sweep:0000aaaa-0000-4000-8000-00000000abcd:20260922"
    assert cr.sweep_reference(_Canary.agent_did, t + datetime.timedelta(minutes=2)).endswith(":20260923")


def test_the_sweep_rides_the_escrow_rail_and_only_for_a_canary_homed_here():
    src = inspect.getsource(cr._sweep_to_treasury)
    assert "from ..services.escrow import escrow_deposit" in src
    assert 'escrow_deposit(canary.agent_did, amount, ref, reason="canary_sweep")' in src
    assert 'if excess > 0 and home == "self":' in inspect.getsource(cr._rebalance_cycle)


async def test_an_operator_asked_to_refill_sweeps_a_canary_above_the_ceiling(monkeypatch):
    from decimal import Decimal as D
    _band(monkeypatch, "25", "25", "150")
    monkeypatch.setattr(cr, "CANARY_REFILL_ENABLED", True)
    monkeypatch.setattr(cr, "CANARY_ENABLED", True)
    received = []

    async def _senders():
        return [_Canary]

    async def _balance(canary):
        return D("1000")

    async def _paused():
        return False

    async def _sweep(canary, amount, ref):
        received.append((canary.agent_did, amount, ref))
        return {"transaction_id": "tx-1"}

    monkeypatch.setattr(cr, "_load_local_senders", _senders)
    monkeypatch.setattr(cr, "_check_balance", _balance)
    monkeypatch.setattr(cr, "_fleet_paused", _paused)
    monkeypatch.setattr(cr, "_sweep_to_treasury", _sweep)
    cr._last_rebalance.pop(_Canary.agent_did, None)
    out = await cr.refill_local_senders(requested_by="spiffe://eu.theprotocol.cloud/service/eu-registry")
    assert out["swept"] == 1 and out["funded"] == 0 and out["errors"] == 0
    assert received == [(_Canary.agent_did, D("950"), received[0][2])] and received[0][2].startswith("canary-sweep:")
    assert out["senders"][0]["action"] == "swept"
    cr._last_rebalance.pop(_Canary.agent_did, None)
    dry = await cr.refill_local_senders(requested_by="x", dry_run=True)
    assert dry["would_sweep"] == 1 and len(received) == 1         # a dry run moves nothing
    cr._last_rebalance.pop(_Canary.agent_did, None)
