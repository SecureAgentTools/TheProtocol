"""§MCPTEST30 (V0651, tester batch 3 item 2, agentvault2-d3, Guild order gwo_5b6bc38b2e17c317754d6e29; his words in
d3's session 2026-10-31 ~11:40Z, "2. approved very good"): the federation suite's 25 unclassified skips on a pair.

Read on the trial pair nt261031x5's whole federation run (551 passed, 0 failed, 40 skipped of 591; 25 of the 40 matched
no code). Four tests skipped on every tier for a fed-test-agent sidecar no tier has run since the sandbox tier retired,
though they only read ABOUT an agent: they now use one of the run's own (rig.fixture_agent_dids). The other 21 are
environment, each class now named with its pair count as its ceiling. RED on the code before: the helper does not
exist and every reason below classifies as unclassified.
"""
from __future__ import annotations

import asyncio
import inspect
from typing import Any, Dict, List

import pytest

from agentvault_registry.api_tests.federation_suite import rig as R
from agentvault_registry.api_tests.federation_suite import skip_codes as S
from agentvault_registry.api_tests.federation_suite import throwaways
from agentvault_registry.api_tests.federation_suite.tests import test_enforcement_propagation as enf
from agentvault_registry.api_tests.federation_suite.tests import test_flare_subsystem as flare
from agentvault_registry.api_tests.federation_suite.tests import test_reputation_and_trust as trust

# the reasons as nt261031x5's federation run recorded them (2026-10-31 10:13-10:20Z), one per class
SEEN = {
    "fixture_sidecar_retired": "fixture agent container 'sandbox-a-fed-test-agent' does not exist on this tier (set "
                               "API_TEST_FED_AGENT_A/B to name the ones that do)",
    "young_frame": ["no updated_at is shared by two cards in 14 rows — a walk here passes with or without a tiebreak",
                    "only 13 types have rows — too thin to assert on",
                    "EventStore is readable and holds NO events yet — no amounts exist to check",
                    "NOT MEASURED — a young ledger (23 events): this check is about a ledger that has run for a while",
                    "fixture propagation-subject absent: no agent on sandbox-A is older than one pull-sync cycle "
                    "(21600s) - 9 candidate(s) seen"],
    "population_moved": "the ranked population changed under the walk (1 → [1, 0, 0] across four concurrent reads)",
    "no_genesis": "no frame of the pair holds the network's genesis certificate (states {'sandbox-A-admin': "
                  "'unlicensed'}): the genesis ceremony has not run on this pair",
    "rail_never_failed": "no FxRouteRefunded or FxRouteStranded on this store — the rail has not failed here",
    "peer_sidecar_unknown": "the peer's sidecar address is unknown: TEG_SIDECAR_MAP names no teg-layer-sandbox-alpha",
    "no_guild_order": ["NOT MEASURED — no guild order posted on either frame",
                       "no guild order posted on this frame — nothing to compare list-vs-detail against",
                       "NOT MEASURED — no order carried a status on either frame"],
    "no_signing_key": "NOT MEASURED — no developer on this frame has published a signing key yet",
    "no_trading_listing": "no listing is TRADING on this venue (0 listed) — nothing to place against",
    # the trial pair nt261031x0 (2026-10-31 17:09-17:17Z): the sending operator did not know the receiver yet
    "operator_receiver_unresolved": "sandboxdelta->sandboxalpha: the send was refused before anything could be "
                                    "judged (unresolved, HTTP 400): Cannot resolve registry for receiver "
                                    "did:theprotocol:nt261031x0a.theprotocol.cloud:425b05a7-28f2-4895-9d0a-0815ad40fdfe. "
                                    "If this is a local agent, use the normal transfer endp",
    # the trial pair nt261031x9 (2026-10-31 16:36-16:43Z): production's posture on the pair, the members' ballot
    "ballot_cycle": ["cycle_started: the home's members' vote: 1c81f622-7319-47a5-b87d-15e4a2c0e76f at the home; "
                     "the members' vote 3 at sandbox-A closes 2026-10-31T17:40:15.322585+00:00 (a member voted: "
                     "HTTP 200); a later run casts the two ballots and tallies",
                     "cycle_pending: the members' vote at sandbox-B on 7 closes at 2026-10-31T17:40:15Z; a run "
                     "after that casts both ballots and tallies"],
}


@pytest.mark.parametrize("code", sorted(SEEN))
def test_each_recorded_reason_has_its_code(code):
    for reason in (SEEN[code] if isinstance(SEEN[code], list) else [SEEN[code]]):
        for text in (reason, "precondition unmet: " + reason):
            assert S.classify_skip(text) == code, (text, S.classify_skip(text))


def test_the_pairs_census_after_v0651_is_within_the_ceilings():
    # nt261031x5's 40 skips less the four tests that now read an agent of the run's own
    census = {"fixture_sidecar_retired": 7, "young_frame": 7, "population_moved": 1, "no_genesis": 2,
              "rail_never_failed": 1, "peer_sidecar_unknown": 1, "no_guild_order": 3, "no_signing_key": 1,
              "no_trading_listing": 1, "canary_unprovisioned": 8, "canary_no_firings": 1, "operator_fx_disabled": 2,
              "switched_off": 1}
    ok, complaints = S.skip_verdict(census)
    assert ok, complaints
    worse = dict(census, no_guild_order=4)
    assert not S.skip_verdict(worse)[0], "one more than its ceiling is a complaint"


def test_a_reason_nobody_read_stays_unread():
    assert S.classify_skip("precondition unmet: something nobody has seen before") == S.UNCLASSIFIED


# ── rig.fixture_agent_dids ───────────────────────────────────────────────────────────────────────────────────────────
class _Mcp:
    def __init__(self, label: str, calls: List[Any], refuse: bool):
        self.label, self.calls, self.refuse = label, calls, refuse

    async def call(self, tool: str, args: Dict[str, Any], **_k):
        self.calls.append((self.label, tool, dict(args)))
        assert tool == "createAgent" and args["name"].startswith("fedsuite-fixture-")
        if self.refuse:
            raise RuntimeError("HTTP 403: the scripted refusal")
        return {"did": f"did:theprotocol:{self.label}:fixture", "client_id": "c", "client_secret": "s"}


class _Rig:
    def __init__(self, refuse: bool = False):
        self.calls: List[Any] = []
        self.refuse = refuse

    def mcp(self, label: str) -> _Mcp:
        return _Mcp(label, self.calls, self.refuse)


def test_no_sidecar_makes_an_agent_of_the_runs_own_on_each_frame(monkeypatch):
    made: List[Any] = []
    monkeypatch.setattr(R, "container_exists_and_runs", lambda name: (False, False))
    monkeypatch.setattr(throwaways, "made", lambda label, did: made.append((label, did)))
    rig = _Rig()
    a, b = asyncio.run(R.fixture_agent_dids(rig, "flare-lookup"))
    assert (a, b) == ("did:theprotocol:sandbox-A:fixture", "did:theprotocol:sandbox-B:fixture")
    assert made == [("sandbox-A", a), ("sandbox-B", b)], "each is retired once the test's verdict is in"


def test_a_running_sidecar_is_read_as_before(monkeypatch):
    monkeypatch.setattr(R, "container_exists_and_runs", lambda name: (True, True))

    async def sidecar(container):
        return f"did:theprotocol:{container}"
    monkeypatch.setattr(R, "_did_from_sidecar", sidecar)
    rig = _Rig()
    (a,) = asyncio.run(R.fixture_agent_dids(rig, "flare-consistent", sides=("A",)))
    assert a == f"did:theprotocol:{R.FED_AGENT_A}" and rig.calls == []


def test_a_frame_that_makes_no_agent_is_a_named_precondition(monkeypatch):
    monkeypatch.setattr(R, "container_exists_and_runs", lambda name: (False, False))
    with pytest.raises(R.PreconditionUnmet) as e:
        asyncio.run(R.fixture_agent_dids(_Rig(refuse=True), "trust-graph"))
    assert "createAgent on sandbox-A failed" in str(e.value)


def test_the_four_tests_read_an_agent_of_the_runs_own():
    for fn in (flare.test_agent_flare_lookup, flare.test_agent_card_flare_consistent,
               enf.test_enforcement_agent_status_reachable, trust.test_dev_trust_graph_readable):
        src = inspect.getsource(fn)
        assert "fixture_agent_dids(rig" in src and "require_running_container(" not in src, fn.__name__


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


# ── the trial pair nt261031x9 (V0650's images, production's posture, the backstop off: tester batch 2 item 6) ────────
def test_the_trial_pairs_census_with_the_fixes_is_within_the_ceilings():
    # nt261031x9's 42 skips: 7 unclassified = six bond-gate tests on the refused backstop (they bond from the agent's own
    # funds now, so they run) and the elevation's ballot cycle (named now)
    census = {"fixture_sidecar_retired": 7, "canary_unprovisioned": 8, "canary_no_firings": 1, "young_frame": 6,
              "operator_fx_disabled": 2, "population_moved": 1, "switched_off": 1, "no_trading_listing": 1,
              "no_signing_key": 1, "no_genesis": 2, "rail_never_failed": 1, "no_guild_order": 3, "peer_sidecar_unknown": 1,
              "ballot_cycle": 1}
    ok, complaints = S.skip_verdict(census)
    assert ok, complaints
    assert not S.skip_verdict(dict(census, ballot_cycle=2))[0], "one test raises it, once per run"


def _bond_with(monkeypatch, cfg):
    from agentvault_registry.api_tests.federation_suite.tests import test_reputation_bond_gates as G
    calls = []

    async def config(rig, label):
        calls.append(("config", label))
        return cfg

    async def own(rig, label, did, c):
        calls.append(("own_funds", label, did, c.get("amount")))
        return "locked"

    async def rest(rig, method, path, label=None, body=None):
        calls.append(("rest", method, path, label))
        return 200, {"status": "matured"}
    monkeypatch.setattr(G, "bond_config", config)
    monkeypatch.setattr(G, "_bond_from_own_funds", own)
    monkeypatch.setattr(G, "_rest", rest)
    return asyncio.run(G._bond(object(), "did:theprotocol:t:x")), calls


def test_a_bond_gate_fixture_bonds_from_its_own_funds_where_the_tier_has_no_backstop(monkeypatch):
    st, calls = _bond_with(monkeypatch, {"mode": "enforce", "amount": "250", "treasury_backstop": False})
    assert st == "locked" and ("own_funds", "sandbox-A", "did:theprotocol:t:x", "250") in calls
    assert not any(c[0] == "rest" for c in calls), "no backstop call where the tier refuses it"


def test_a_bond_gate_fixture_takes_the_backstop_where_the_tier_offers_it(monkeypatch):
    st, calls = _bond_with(monkeypatch, {"mode": "enforce", "amount": "250", "treasury_backstop": True})
    assert st == "matured" and calls[-1][0] == "rest" and calls[-1][2].endswith("/reputation-bond/backstop")
    assert not any(c[0] == "own_funds" for c in calls)


def test_trial_six_census_is_within_the_ceilings_and_the_operator_rows_trade():
    # nt261031x0: 555 passed, 0 failed, 36 skipped; its one unread skip is named now
    census = {"fixture_sidecar_retired": 7, "canary_unprovisioned": 8, "canary_no_firings": 1, "young_frame": 7,
              "operator_fx_disabled": 1, "operator_receiver_unresolved": 1, "population_moved": 1, "switched_off": 1,
              "no_trading_listing": 1, "no_signing_key": 1, "ballot_cycle": 1, "no_genesis": 2, "rail_never_failed": 1,
              "no_guild_order": 2, "peer_sidecar_unknown": 1}
    ok, complaints = S.skip_verdict(census)
    assert ok, complaints
    worse = dict(census, operator_fx_disabled=2, operator_receiver_unresolved=2)
    assert not S.skip_verdict(worse)[0], "the two operator rows trade: four outcomes from two rows is a complaint"
