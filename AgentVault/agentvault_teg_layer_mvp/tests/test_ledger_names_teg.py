"""W4 phase 1 (agentvault2-aa, 2026-10-25): the TEG's copy of the ledger names map is the registry's, data for data.

His words that day to agentvault2-69: "i want the illegal wording completly gone before opening" and, on the ledger, "just
use the new wording and make it accept both or something" (sessionlogs2026/PLAN_2026-10-25_COMPLIANT_OPENING.md, W4). The
TEG's reader of a renamed event (the inbound reconciler, tests/test_inbound_reconciler.py) asks this map; the TEG's own
emission gate is fail-closed, so a new name no policy row allows is never emitted by a TEG.
"""
from __future__ import annotations

import ast
import pathlib

from teg_core_service import ledger_names as L

SRC = pathlib.Path(L.__file__).resolve().parent


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
    # the registry's copy, where this checkout holds it (an AgentVault checkout, as CI's)
    reg = SRC.parents[2] / "agentvault_registry" / "src" / "agentvault_registry" / "core" / "ledger_names.py"
    if reg.is_file():
        ns: dict = {}
        exec(compile(reg.read_text(), str(reg), "exec"), ns)
        assert (ns["RENAMED"], ns["AGORA_RENAMED"], ns["LEGACY"]) == (L.RENAMED, L.AGORA_RENAMED, L.LEGACY)


def test_a_new_name_reads_as_its_old_one_and_a_legacy_spelling_stays():
    assert L.live_old("UnitsTransferred") == "TokensTransferred" and L.live_old("TokenTransferred") == "TokenTransferred"
    assert L.live_names("TokensIssued") == ("TokensIssued", "UnitsIssued") and L.live_names("AgentCreated") == ("AgentCreated",)
    assert L.expand_live({"TokensStaked"}) == {"TokensStaked", "UnitsLocked"}


def test_a_new_name_without_a_policy_row_is_never_emitted_by_a_teg(monkeypatch):
    from teg_core_service import event_emitter as E
    monkeypatch.setattr(E, "_teg_policy_cache", {"TokensTransferred": False, "LedgerBalanceChanged": True})
    assert E._teg_should_emit("UnitsTransferred") is False and E._teg_should_emit("TokensTransferred") is False
    assert E._teg_should_emit("LedgerBalanceChanged") is True


def test_every_comparison_against_an_old_name_asks_the_map():
    old = set(L.RENAMED) | set(L.AGORA_RENAMED)
    bad, seen = [], 0

    def lits(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            return {n.value}
        if isinstance(n, (ast.Tuple, ast.List, ast.Set)):
            return set().union(*(lits(e) for e in n.elts)) if n.elts else set()
        return set()
    for p in sorted(SRC.rglob("*.py")):
        if p.name == "ledger_names.py" or "__pycache__" in p.parts:
            continue
        src = p.read_text(encoding="utf-8")
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.Compare):
                names = lits(n.left).union(*(lits(c) for c in n.comparators))
                if names & old:
                    seen += 1
                    if "ledger_names" not in src:
                        bad.append(f"{p.relative_to(SRC)}:{n.lineno} {sorted(names & old)}")
    assert seen >= 1, "the reconciler's comparison is seen"
    assert bad == [], "read the event under every name it may be written under (teg_core_service/ledger_names.py)"
