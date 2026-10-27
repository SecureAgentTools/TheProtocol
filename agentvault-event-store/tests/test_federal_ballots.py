"""§MEMBERSHIP phase D2 (2026-10-02, agentvault2-33): federal ballots, one per registry, on federation proposals.

The store keeps the ballots and applies the rule; the host REGISTRY verifies each ballot (its signature, the caller's
identity, its eligibility) and alone may write one or tally a ballot proposal, because whoever passes the eligible
registries picks the electorate. These tests read the source (no DB, no network, like test_mint_origin_rule.py):

  1. the rule: two thirds of the for-and-against ballots, at least half the eligible registries cast (abstain counts as
     cast), at least min_registries counted, and only ballots from registries still eligible count;
  2. the ballot route is origin-only, structurally first;
  3. an agent's vote on a ballot proposal is refused, and a ballot tally without the eligible registries is refused;
  4. a peer that passes an eligible list to the tally is refused;
  5. the columns exist in the models and in the startup migration.
"""
from __future__ import annotations

import ast
import pathlib
from typing import Dict, List, Optional

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if not (ROOT / "src").is_dir():
    ROOT = pathlib.Path("/app")
SERVICE = ROOT / "src" / "services" / "federation_governance.py"
ROUTER = ROOT / "src" / "routers" / "federation_governance.py"
MODELS = ROOT / "src" / "models" / "federation_governance.py"
MAIN = ROOT / "src" / "main.py"


def _load_rule():
    """ballot_outcome and its constants, executed from the service's own source (the module imports the database)."""
    tree = ast.parse(SERVICE.read_text())

    def assigned(n):
        out = []
        for t in n.targets:
            out += [t.id] if isinstance(t, ast.Name) else [e.id for e in getattr(t, "elts", []) if isinstance(e, ast.Name)]
        return set(out)
    keep = [n for n in tree.body
            if (isinstance(n, ast.FunctionDef) and n.name == "ballot_outcome")
            or (isinstance(n, ast.Assign) and assigned(n) & {"BALLOT_PASS_NUM", "BALLOT_CHOICES"})]
    assert len(keep) == 3, [ast.dump(k)[:60] for k in keep]
    ns: Dict = {"Dict": Dict, "List": List, "Optional": Optional}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(SERVICE), "exec"), ns)
    return ns["ballot_outcome"]


@pytest.fixture(scope="module")
def outcome():
    return _load_rule()


def B(rid, choice):
    return {"registry_id": f"registry:{rid}", "choice": choice}


E3 = ["registry:a/A", "registry:b/B", "registry:c/C"]


def test_two_thirds_of_the_decided_ballots(outcome):
    assert outcome([B("a/A", "for"), B("b/B", "for"), B("c/C", "against")], E3, 2)["status"] == "PASSED"
    got = outcome([B("a/A", "for"), B("b/B", "against")], E3, 2)
    assert got["status"] == "FAILED" and got["two_thirds_met"] is False and got["pass_rate"] == 50.0


def test_half_the_eligible_must_cast_and_abstain_counts_as_cast(outcome):
    e4 = E3 + ["registry:d/D"]
    assert outcome([B("a/A", "for")], e4, 1)["participation_met"] is False
    got = outcome([B("a/A", "for"), B("b/B", "abstain")], e4, 2)
    assert got["status"] == "PASSED" and got["cast"] == 2 and got["abstain"] == 1


def test_min_registries_and_an_empty_electorate(outcome):
    assert outcome([B("a/A", "for"), B("b/B", "for")], E3, 3)["multi_registry_met"] is False
    assert outcome([B("a/A", "for")], [], 1)["status"] == "FAILED"


def test_a_ballot_from_a_registry_no_longer_eligible_is_listed_not_counted(outcome):
    got = outcome([B("a/A", "for"), B("b/B", "for"), B("x/X", "against")], E3, 2)
    assert got["status"] == "PASSED" and got["against"] == 0 and got["not_counted"] == ["registry:x/X"]


def _fn(path, name):
    return next(n for n in ast.walk(ast.parse(path.read_text()))
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def test_only_the_host_registry_writes_a_ballot():
    first = _fn(ROUTER, "cast_ballot").body[1]   # [0] is the docstring
    assert isinstance(first, ast.If) and "not is_origin(auth_context)" in ast.unparse(first.test)
    assert "403" in ast.unparse(first.body[0])


def test_an_agents_vote_and_a_blind_tally_are_refused_on_a_ballot_proposal():
    vote = ast.unparse(_fn(SERVICE, "cast_federation_vote"))
    assert "if getattr(proposal, 'ballot_mode', False):" in vote and "decided by registry ballots" in vote
    tally = ast.unparse(_fn(SERVICE, "tally_federation_proposal"))
    assert "if eligible_registries is None:" in tally and "raise ValueError" in tally


def test_a_peer_cannot_pass_the_electorate():
    route = ast.unparse(_fn(ROUTER, "tally_proposal"))
    assert "if eligible is not None and auth_context.get('auth_type') != 'internal' and (not is_origin(auth_context)):" in route


def test_the_columns_exist_in_the_models_and_the_startup_migration():
    models, main = MODELS.read_text(), MAIN.read_text()
    for col in ("ballot_mode = Column", "ballot_summary = Column", "choice = Column", "ballot_jws = Column",
                "ballot_basis = Column", "eligibility = Column"):
        assert col in models, col
    for ddl in ("federation_proposals ADD COLUMN IF NOT EXISTS ballot_mode", "federation_proposals ADD COLUMN IF NOT EXISTS ballot_summary",
                "federation_votes ADD COLUMN IF NOT EXISTS choice", "federation_votes ADD COLUMN IF NOT EXISTS ballot_jws",
                "federation_votes ADD COLUMN IF NOT EXISTS ballot_basis", "federation_votes ADD COLUMN IF NOT EXISTS eligibility"):
        assert ddl in main, ddl
