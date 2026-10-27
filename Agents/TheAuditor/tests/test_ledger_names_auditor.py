"""W4 phase 1 (agentvault2-aa, 2026-10-25): the auditor counts a mint under its old and its new name.

His words that day to agentvault2-69: "i want the illegal wording completly gone before opening" and, on the ledger, "just
use the new wording and make it accept both or something" (sessionlogs2026/PLAN_2026-10-25_COMPLIANT_OPENING.md, W4).
Phase 2 lets the registry's emitter write UnitsIssued for TokensIssued. The auditor's native-supply reconciliation reads
the typed mint events of the immutable log (TRUE_SUPPLY_SQL) and asks whether a frame has any mint before the baseline
(the coverage probe): reading TokensIssued alone, every mint written as UnitsIssued would be missing from true_minted, and
on a frame with complete coverage the recon gap would read as a hidden mint. Both now name both, and nothing else changes:
the other kinds keep their clauses, and the old name stays first. The SQL is read from the source (no database, no
import of the service). Run 2026-10-25 against a throwaway Postgres 18.6 (two mints of 100 and 50, a dispute compensation
of 5, corrections of +3.25 and -1, a slash of 2, a transfer of 40): the history under the new names gave the same
true_minted and true_burned as under the old, 158.25 and 3; the SQL before this change gave 8.25 and 3 for the new names
(the two mints missing).
"""
import ast
import os
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TREE = os.getenv("AUDITOR_TREE") or HERE
MAIN = os.path.join(TREE, "src", "auditor", "main.py")


def _source():
    with open(MAIN, encoding="utf-8") as f:
        return f.read()


def _module_string(name):
    for node in ast.walk(ast.parse(_source())):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return node.value.value
    raise AssertionError(f"{name} is not where it was")


def _in_list(sql, head):
    m = re.search(re.escape(head) + r"\s+IN\s*\(([^)]*)\)", sql)
    assert m, f"no IN list after {head!r}"
    return [x.strip().strip("'") for x in m.group(1).split(",")]


def test_true_supply_counts_a_mint_under_either_name():
    sql = _module_string("TRUE_SUPPLY_SQL")
    assert _in_list(sql, "WHEN event_type") == ["TokensIssued", "UnitsIssued", "DisputeCompensationMinted"]
    assert _in_list(sql, "AND event_type") == ["TokensIssued", "UnitsIssued", "DisputeCompensationMinted", "DisputeSlash",
                                              "BalanceCorrected"]
    assert "WHEN event_type = 'DisputeSlash'" in sql and sql.count("WHEN event_type = 'BalanceCorrected'") == 2


def test_the_coverage_probe_asks_for_a_mint_under_either_name():
    src = _source()
    assert "WHERE event_type IN ('TokensIssued','UnitsIssued') AND timestamp < $1" in src
    assert "event_type = 'TokensIssued'" not in src, "a mint read under its old name alone"


def test_no_other_query_names_an_old_mint_or_transfer_name_alone():
    src = _source()
    for old, new in (("TokensIssued", "UnitsIssued"), ("TokensTransferred", "UnitsTransferred"),
                     ("TokensStaked", "UnitsLocked"), ("RewardsDistributed", "LockPayoutsDistributed")):
        assert src.count(f"'{old}'") == src.count(f"'{new}'"), f"{old} is read without {new}"
