"""D6-560 (2026-10-16): a federation veto's written reason, and who vetoed, are served with the proposal.

A veto requires a reason (1 to 1000 characters, VetoRequest in routers/federation_governance.py) and the store keeps it
with the proposal (veto_reason, vetoed_by), but _proposal_to_dict, the one serializer behind the proposal list, the
single proposal and the veto's own answer, left both out, so the recorded reason could not be read through the API.
These tests run _proposal_to_dict from the service's own source (the module imports the database; no DB, no network,
like test_federal_ballots.py) and read which routes answer through it.

Run: python -m pytest tests/test_federation_veto_served.py -q   (needs pytest only)
"""
from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Dict

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if not (ROOT / "src").is_dir():
    ROOT = pathlib.Path("/app")
SERVICE = ROOT / "src" / "services" / "federation_governance.py"
ROUTER = ROOT / "src" / "routers" / "federation_governance.py"


@pytest.fixture(scope="module")
def to_dict():
    tree = ast.parse(SERVICE.read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_proposal_to_dict")
    ns: Dict = {"Dict": Dict, "FederationProposal": object}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(SERVICE), "exec"), ns)
    return ns["_proposal_to_dict"]


def _proposal(**over):
    now = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
    p = dict(
        id="3f6c1d2e-0000-4000-8000-000000000001", title="Raise the minimum bond", description="d",
        proposal_type="federation_policy_change", policy_diff={"min_bond": 300}, status="PASSED",
        origin_registry_id="spiffe://eu.example/service/registry", origin_proposal_id=7,
        origin_tally={"status": "PASSED", "quorum_met": True}, proposer_operator_name="origin",
        quorum_percent=20.0, pass_percent=66.0, min_registries=2, duration_seconds=604800,
        created_at=now - timedelta(days=8), end_timestamp=now - timedelta(days=1), tallied_at=now - timedelta(days=1),
        veto_deadline=now + timedelta(days=6), applied_at=None, votes_for=10, votes_against=2, total_voters=12,
        distinct_registries=3, pass_rate=83.3, quorum_met=True, ballot_mode=False, ballot_summary=None,
        vetoed_by=None, veto_reason=None,
    )
    p.update(over)
    return SimpleNamespace(**p)


def test_a_vetoed_proposal_is_served_with_its_reason_and_who_vetoed(to_dict):
    d = to_dict(_proposal(status="VETOED", vetoed_by="origin", veto_reason="It would weaken the supply audit."))
    assert d["status"] == "VETOED"
    assert d["veto_reason"] == "It would weaken the supply audit."
    assert d["vetoed_by"] == "origin"


def test_a_proposal_never_vetoed_carries_both_fields_empty(to_dict):
    d = to_dict(_proposal())
    assert d["veto_reason"] is None and d["vetoed_by"] is None


def test_the_list_the_proposal_and_the_veto_answer_through_the_serializer():
    service = ast.parse(SERVICE.read_text())
    for name in ("list_federation_proposals", "get_federation_proposal"):
        fn = next(n for n in service.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
        assert "_proposal_to_dict(" in ast.unparse(fn), f"{name} no longer answers through _proposal_to_dict"
    router = ast.parse(ROUTER.read_text())
    veto = next(n for n in router.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "veto_proposal")
    assert "_proposal_to_dict(proposal)" in ast.unparse(veto), "the veto's answer no longer carries the proposal"
