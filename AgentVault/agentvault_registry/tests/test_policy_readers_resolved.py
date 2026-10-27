"""Two enforcement readers that kept literals of their own after the rule moved (agentvault2-66, 2026-10-26).

Found by the operator read on V0641: sbx-alpha and both sandbox operators run an active policy row whose only key is
`phase6` (an API tester row of 2026-09-04..12, written before the validator refused unknown keys). Every reader that
resolves the row onto the factory default runs the factory default there; these two did not:

  * GET /fees/current-rate read the row with its own fallbacks, 1.5 and 7.5, while the charge path
    (TransactionFeeService._load_rates) falls back to 0.5 and 5.0: on such a row it reported three times the fee
    every transfer paid, and disagreed with the registry card. It now returns the service's own
    get_current_rate, the answer the card publishes.
  * GET /enforcement/my-status computed bond maturity from the retired `reputation_bond.*` keys with literals 10,
    30 and 0.1, so it showed every agent the absolute EigenTrust gate (0.1) §BONDFILL-3 retired as unreachable,
    and ignored a frame's own `enforcement.bond_maturity_*`. It now reads the one rule /agents/reputation-bond/status
    reads (maturity_thresholds over the resolved policy, progress_for), without stamping maturity.

Every test but the second fails on the V0643 tree (b1e6d5ca), each for its own defect; the second passes on both
and keeps the first honest (it proves the row reaches the charge path).
"""
import asyncio
import pathlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from agentvault_registry.crud import crud_enforcement
from agentvault_registry.routers import enforcement_agent as ea
from agentvault_registry.services import frame_policy as fp
from agentvault_registry.services import reputation_bond as rb
from agentvault_registry.services.transaction_fee_service import TransactionFeeService

JUNK_ROW = {"phase6": {"probe": True}}


def _row(doc):
    return SimpleNamespace(policy_json=doc, version=72, modified_at=None, modified_by="admin_override:developer_1")


def _patch_row(monkeypatch, doc):
    async def _active(db):
        return _row(doc)
    monkeypatch.setattr(crud_enforcement, "get_active_policy", _active)


def _fee_route():
    return asyncio.run(ea.get_current_fee_rate(db=None, current_developer=None))


def test_the_fee_rate_on_a_row_without_a_fee_section_is_what_a_transfer_pays(monkeypatch):
    """Control: the V0643 route answers 1.5 / 7.5 here, while the charge path (and the card) say 0.5 / 5.0."""
    _patch_row(monkeypatch, JUNK_ROW)
    got = _fee_route()
    assert asyncio.run(TransactionFeeService()._load_rates(None)) == (0.5, 5.0)
    assert (got["rate_percent"], got["base_rate_percent"], got["max_rate_percent"]) == (0.5, 0.5, 5.0)
    assert got == asyncio.run(TransactionFeeService().get_current_rate(None))


def test_the_fee_rate_follows_a_row_that_names_its_own_rates(monkeypatch):
    """A frame's own rates are reported as charged. This leg also proves the row patch reaches the charge
    path: with no row read at all, the defaults would pass the test above by accident."""
    _patch_row(monkeypatch, {"transaction_fees": {"base_rate_percent": 0.8, "max_rate_percent": 4.0}})
    got = _fee_route()
    assert asyncio.run(TransactionFeeService()._load_rates(None)) == (0.8, 4.0)
    assert (got["base_rate_percent"], got["max_rate_percent"]) == (0.8, 4.0)


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar(self):
        return self._value


class _DB:
    """Answers the route's two reads in order (its trust vector, then its bond) and refuses any third: the
    maturity numbers must come from the shared reader, not a query of the route's own."""
    def __init__(self, *values):
        self._values = list(values)

    async def execute(self, *_a, **_k):
        assert self._values, "the route ran a query of its own for the maturity numbers"
        return _Result(self._values.pop(0))


def _my_status(monkeypatch, doc, activity):
    did = "did:theprotocol:sbxalphaop.theprotocol.cloud:0b6f2c1e-policy-readers"
    bond = SimpleNamespace(status="locked", amount=50, locked_at=datetime.now(timezone.utc) - timedelta(days=13),
                           matured_at=None)
    agent = SimpleNamespace(did=did, enforcement_status="active", rewards_paused_until=None, offense_count=0,
                            enforcement_level=0, reputation_score=0.0)
    _patch_row(monkeypatch, doc)

    async def _policy(db):
        return fp.resolve(doc)

    async def _activity(db, dids):
        return {d: activity for d in dids}

    async def _no_stamp(*_a, **_k):
        raise AssertionError("my-status stamped maturity: that write is the bond route's")

    monkeypatch.setattr(rb, "policy_json", _policy)
    monkeypatch.setattr(rb, "activity_batch", _activity)
    monkeypatch.setattr(rb, "stamp_matured", _no_stamp)
    return asyncio.run(ea.get_my_enforcement_status(db=_DB(None, bond), current_agent=agent)), bond


def test_my_status_shows_the_frames_own_maturity_rule(monkeypatch):
    """A frame that sets `enforcement.bond_maturity_*` is shown its own numbers. Control: the V0643 route
    shows 10 and 30 from the retired `reputation_bond.*` keys, and runs a query of its own."""
    doc = {"enforcement": {"bond_maturity_min_transactions": 17, "bond_maturity_min_age_days": 12}}
    activity = {"transactions": 4, "eigentrust": 0.00028, "rated_peers": 1, "trust_percentile": 40.0,
                "trust_population": 25}
    got, bond = _my_status(monkeypatch, doc, activity)
    prog = got["reputation_bond"]["maturity_progress"]
    assert (prog["transactions_required"], prog["age_days_required"]) == (17, 12)
    assert (prog["transactions"], prog["age_days"]) == (4, 13)
    assert prog == rb.progress_for(activity, bond.locked_at, rb.maturity_thresholds(fp.resolve(doc)))


def test_my_status_names_no_retired_absolute_trust_gate(monkeypatch):
    """On the sandbox's `phase6` row the route used to show `eigentrust_required: 0.1`, a fixed threshold on a
    normalised vector that no agent can meet. It shows the relative gate the bond route applies instead."""
    prog = _my_status(monkeypatch, JUNK_ROW, None)[0]["reputation_bond"]["maturity_progress"]
    assert "eigentrust_required" not in prog
    assert prog["trust_percentile_required"] == 50 and prog["rated_peers_required"] == 3
    assert prog["matured"] is False


def test_the_bond_tutorial_teaches_the_live_rule():
    """The track's step 9 described the retired gate ("Minimum EigenTrust score"). Control: V0643's text."""
    track = (pathlib.Path(__file__).resolve().parents[1] / "src/agentvault_registry/static/new_registry_frontend"
             / "src/views/Tutorials/data/enforcementTrust.track.ts").read_text()
    step9 = track[track.index("id: 'et-bond-status'"):track.index("id: 'et-bond-status'") + 2500]
    assert "Minimum EigenTrust score" not in step9
    for live in ("bond_maturity_", "counterparties owned by other developers", "median of the frame's ranked agents"):
        assert live in step9
