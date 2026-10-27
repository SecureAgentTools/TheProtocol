"""§FRAMESHOWCASE (his word 2026-09-14, "your recommendation. but not cap at 1m"): a genesis issuance larger than the
registry's per-call mint ceiling is minted in pieces, and the ceiling is the running registry's own answer.

hansa asked for 5,000,000. The registry's validator refused the single call (TEG_MINT_MAX_AVT is 1,000,000 in a
runner-built frame's network profile) and the driver logged the refusal and went on. Every call below is faked: nothing
is issued and no container is asked.

The control: the fake rail refuses a piece above its ceiling exactly as the validator did, so the old driver's single call
of the whole amount is refused here too (test_standup_progress.py drives the driver's admin step against the same shape).
"""
import importlib.machinery
import importlib.util
import pathlib
import subprocess
import types
from decimal import Decimal

import pytest

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]


def load():
    loader = importlib.machinery.SourceFileLoader("standup_extras_mint_under_test", str(HERE.parent / "standup_extras.py"))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


ex = load()


class Rail:
    """The mint rail: above the ceiling 422, the `refuse_at`-th call 503, otherwise 200 and the amount counted."""

    def __init__(self, ceiling="1000000", refuse_at=None):
        self.ceiling, self.refuse_at, self.calls, self.minted = Decimal(ceiling), refuse_at, [], Decimal("0")

    def __call__(self, amount, reason):
        self.calls.append((amount, reason))
        if Decimal(amount) > self.ceiling:
            return 422, {"detail": f"Amount exceeds maximum ({self.ceiling:,})"}
        if self.refuse_at == len(self.calls):
            return 503, {"detail": "TEG Layer unavailable for the issuance"}
        self.minted += Decimal(amount)
        return 200, {"transaction_id": f"tx-{len(self.calls)}"}


def test_five_million_at_a_one_million_ceiling_is_five_whole_pieces():
    rail, totals = Rail(), []
    assert ex.mint_in_pieces(rail, "5000000", "1000000", "Genesis", on_piece=totals.append) == (Decimal("5000000"), 5, None)
    assert [a for a, _ in rail.calls] == ["1000000"] * 5 and rail.minted == Decimal("5000000")
    assert totals == [Decimal(n * 1000000) for n in range(1, 6)] and rail.calls[0][1] == "Genesis (part 1 of 5)"


def test_the_control_the_old_single_call_is_refused_by_the_same_rail():
    rail = Rail()
    assert rail("5000000", "Genesis")[0] == 422 and rail.minted == 0


def test_a_remainder_is_its_own_last_piece_and_an_amount_under_the_ceiling_is_one_call():
    rail = Rail()
    assert ex.mint_in_pieces(rail, "2500000.5", "1000000", "G")[:2] == (Decimal("2500000.5"), 3)
    assert [a for a, _ in rail.calls] == ["1000000", "1000000", "500000.5"]
    one = Rail()
    assert ex.mint_in_pieces(one, "750000", "1000000", "G")[:2] == (Decimal("750000"), 1)
    assert one.calls[0][1] == "G (part 1 of 1)"


def test_a_refusal_stops_at_once_and_the_resume_mints_only_the_rest():
    rail, totals = Rail(refuse_at=3), []
    minted, made, err = ex.mint_in_pieces(rail, "5000000", "1000000", "G", on_piece=totals.append)
    assert (minted, made) == (Decimal("2000000"), 2) and err.startswith("HTTP 503") and len(rail.calls) == 3
    assert totals == [Decimal("1000000"), Decimal("2000000")]
    again = Rail()
    assert ex.mint_in_pieces(again, "5000000", "1000000", "G", minted_before=minted)[:2] == (Decimal("5000000"), 3)
    assert len(again.calls) == 3 and again.minted == Decimal("3000000")


def test_a_mint_that_already_landed_whole_calls_nothing_and_an_impossible_one_is_refused_before_any_call():
    rail = Rail()
    assert ex.mint_in_pieces(rail, "5000000", "1000000", "G", minted_before="5000000") == (Decimal("5000000"), 0, None)
    for amount, ceiling, before in (("0", "1000000", "0"), ("5000000", "0", "0"), ("5000000", "1000000", "6000000")):
        with pytest.raises(ValueError):
            ex.mint_in_pieces(rail, amount, ceiling, "G", minted_before=before)
    assert rail.calls == []


def test_the_ceiling_is_the_running_registrys_own_answer_and_a_failed_ask_falls_back_saying_so():
    asked = []

    def run(cmd, **kwargs):
        asked.append(cmd)
        return types.SimpleNamespace(returncode=0, stdout="1000000 profile\n", stderr="")

    assert ex.registry_mint_ceiling("hansa", run=run) == (Decimal("1000000"), "the registry (profile)")
    assert asked[0][:2] == ["docker", "exec"] and "hansa-registry" in asked[0]

    def refused(cmd, **kwargs):
        return types.SimpleNamespace(returncode=1, stdout="", stderr="Error: No such container: plum-registry")

    ceiling, source = ex.registry_mint_ceiling("plum", run=refused)
    assert ceiling == ex.MINT_CEILING_FALLBACK and source.startswith("not read (rc=1") and source.endswith("the fallback")

    def broken(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 60)

    assert ex.registry_mint_ceiling("plum", run=broken)[0] == ex.MINT_CEILING_FALLBACK


def test_the_ask_reads_the_knob_and_default_the_registry_validator_reads():
    rail_src = (REPO / "AgentVault/agentvault_registry/src/agentvault_registry/routers/teg_integration.py").read_text()
    assert 'money_knob("TEG_MINT_MAX_AVT", "100000000")' in rail_src
    assert "money_knob('TEG_MINT_MAX_AVT', '100000000')" in ex._CEILING_PY
