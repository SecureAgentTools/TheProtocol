"""§TRUSTCHAIN (2026-09-12) — the compliance baseline, and the one hash.

Measured on the live cluster before this change:
  * `federated_registry_compliance` held ZERO rows on EU and on ASIA. The only writer was the
    Phase 2 admission pipeline (`routers/federation_admission.py`), which the bilateral
    invitation rail never runs; the poller skipped every ACTIVE peer with `continue`, so the
    drift monitor journal 45 describes compared nothing.
  * BOTH policy-compliance endpoints (federation-namespaced `federation_sync.py` and the admin
    twin in `registry_health.py`) hashed the RAW policy row, while the signed card publishes the
    hash of the RESOLVED document (`frame_policy.ResolvedPolicy.hash`). On EU (amended, v2) the
    card said d2f2040f... and the endpoints said b82a5cad...: a peer would have read a drift that
    never happened, and a baseline would have stored a fact the card does not publish.

These tests pin: (1) the pure baseline builder; (2) that BOTH poll paths record a baseline
instead of skipping (AST: the `compliance is None` branch calls `_record_baseline`, never
`continue`s or returns "skipped"); (3) that BOTH compliance endpoints take their hash from
`frame_policy` and never from `hashlib`; (4) that the approve and finalize rails schedule the
baseline. Each is RED on the pre-change tree (`R51_SRC_DIR`-style: point `TRUSTCHAIN_SRC` at a
`git archive` of the old registry package and every test here fails).
"""
from __future__ import annotations

import ast
import os
import pathlib
from datetime import datetime, timezone

import pytest

HERE = pathlib.Path(__file__).resolve().parent
SRC = pathlib.Path(os.environ.get("TRUSTCHAIN_SRC", HERE.parent / "src" / "agentvault_registry"))


def _fn(path: pathlib.Path, name: str) -> ast.AST:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{path.name}: no function {name}")


def _calls(node: ast.AST, attr: str) -> list:
    return [
        n for n in ast.walk(node)
        if isinstance(n, ast.Call) and (
            (isinstance(n.func, ast.Attribute) and n.func.attr == attr)
            or (isinstance(n.func, ast.Name) and n.func.id == attr)
        )
    ]


def _none_branch(fn: ast.AST) -> ast.If:
    """The `if compliance is None:` branch of a poll path."""
    for n in ast.walk(fn):
        if isinstance(n, ast.If) and isinstance(n.test, ast.Compare):
            left = n.test.left
            if isinstance(left, ast.Name) and left.id == "compliance" and any(
                isinstance(op, ast.Is) for op in n.test.ops
            ) and any(isinstance(c, ast.Constant) and c.value is None for c in n.test.comparators):
                return n
    raise AssertionError("no `if compliance is None` branch")


# ── 1. the pure builder ─────────────────────────────────────────────────────────
def _builder():
    # import lazily: the module imports settings, which needs the CI dummies
    from agentvault_registry.background_tasks.compliance_poller import (
        baseline_from_payload, BASELINE_FIRST_SIGHT,
    )
    return baseline_from_payload, BASELINE_FIRST_SIGHT


def test_baseline_from_payload_records_first_sight_with_provenance():
    baseline_from_payload, FIRST_SIGHT = _builder()
    now = datetime(2026, 9, 12, 6, 0, tzinfo=timezone.utc)
    row = baseline_from_payload(7, {
        "policy_hash": "d2f2040fe0e791e6" * 4, "policy_version": 2,
        "policy_source": "amended", "registry_did": "did:theprotocol:eu",
    }, now=now)
    assert row is not None
    assert row.peer_registry_id == 7
    assert row.policy_hash == "d2f2040fe0e791e6" * 4
    assert row.policy_version == 2
    assert row.federation_status == "federated"
    assert row.admitted_at == now
    assert row.admitted_by == FIRST_SIGHT, "an observed baseline must be told apart from an admitted one"
    assert row.policy_json["baseline_source"] == FIRST_SIGHT
    assert row.policy_json["policy_source"] == "amended"
    assert row.drift_events_count == 0 and row.consecutive_poll_failures == 0


def test_baseline_from_payload_refuses_an_empty_hash():
    baseline_from_payload, _ = _builder()
    assert baseline_from_payload(7, {"policy_version": 1}) is None
    assert baseline_from_payload(7, {"policy_hash": ""}) is None
    assert baseline_from_payload(7, {"policy_hash": "   "}) is None
    assert baseline_from_payload(7, "not a dict") is None
    # a version the peer mangled degrades to 0, never to an exception
    row = baseline_from_payload(7, {"policy_hash": "abc", "policy_version": "two"})
    assert row is not None and row.policy_version == 0


# ── 2. both poll paths record instead of skipping ───────────────────────────────
@pytest.mark.parametrize("name", ["_poll_cycle", "force_single_peer_poll"])
def test_poll_paths_record_a_baseline_when_the_row_is_missing(name):
    fn = _fn(SRC / "background_tasks" / "compliance_poller.py", name)
    branch = _none_branch(fn)
    assert _calls(branch, "_record_baseline"), f"{name}: the missing-row branch does not record a baseline"
    for n in ast.walk(branch):
        if isinstance(n, ast.Return):
            for c in ast.walk(n):
                if isinstance(c, ast.Constant) and c.value == "skipped":
                    raise AssertionError(f"{name}: a missing row is still reported as 'skipped'")
    # the cycle's old shape was a bare `continue` as the branch's only statement
    assert not (len(branch.body) == 1 and isinstance(branch.body[0], ast.Continue)), (
        f"{name}: the missing-row branch is still a bare continue"
    )


def test_poll_and_baseline_read_the_peer_through_one_fetch():
    src = SRC / "background_tasks" / "compliance_poller.py"
    assert _calls(_fn(src, "_poll_peer"), "_fetch_policy_compliance"), "_poll_peer does not use the shared fetch"
    assert _calls(_fn(src, "_record_baseline"), "_fetch_policy_compliance"), "_record_baseline does not use the shared fetch"
    assert _calls(_fn(src, "_record_baseline"), "baseline_from_payload")


# ── 3. one hash: both compliance endpoints read the resolver, never hashlib ────
@pytest.mark.parametrize("rel,name", [
    ("routers/federation_sync.py", "get_federation_policy_compliance"),
    ("routers/registry_health.py", "get_own_policy_compliance"),
])
def test_compliance_endpoints_serve_the_resolved_policy_hash(rel, name):
    fn = _fn(SRC / rel, name)
    assert _calls(fn, "hash"), f"{name} does not call the resolved policy's hash()"
    assert _calls(fn, "load"), f"{name} does not load the resolved policy"
    for n in ast.walk(fn):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "hashlib":
            raise AssertionError(f"{name} still hashes a document itself ({rel})")
        if isinstance(n, ast.Name) and n.id == "DEFAULT_POLICY_JSON":
            raise AssertionError(f"{name} still falls back to the raw shipped default ({rel})")


def test_policy_compliance_response_declares_policy_source():
    """The wire, not the builder (§FRAMEPOLICY's lesson): a field the model does not declare is
    dropped silently while the endpoint still answers 200."""
    from agentvault_registry.routers.registry_health import PolicyComplianceResponse
    assert "policy_source" in PolicyComplianceResponse.model_fields


# ── 4. the approve rails schedule the baseline ─────────────────────────────────
@pytest.mark.parametrize("name", ["approve_frame_invitation", "finalize_frame_invitation"])
def test_invitation_rails_schedule_the_baseline(name):
    src = SRC / "routers" / "frame_invitations.py"
    try:
        fn = _fn(src, name)
    except AssertionError:
        pytest.skip(f"{name} not found by that name; the hook is asserted by the sibling test")
    assert _calls(fn, "_schedule_compliance_baseline"), f"{name} does not schedule the compliance baseline"


def test_invitation_module_schedules_the_baseline_twice():
    tree = ast.parse((SRC / "routers" / "frame_invitations.py").read_text(encoding="utf-8"))
    sites = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_schedule_compliance_baseline"
    ]
    assert len(sites) == 2, f"expected the approve and the finalize rail to schedule it, found {len(sites)} site(s)"


def test_consul_detail_models_declare_the_baseline_provenance():
    """The constructors pass baseline_source/baseline_hash; pydantic drops an undeclared kwarg
    without a word, so the MODEL is what must be pinned (the §FRAMEPOLICY lesson, again)."""
    from agentvault_registry.routers.consul_admin import PeerDetail, PeerDetailExtended, PeerComplianceRow
    for model in (PeerDetail, PeerDetailExtended, PeerComplianceRow):
        assert "baseline_source" in model.model_fields, model.__name__
        assert "baseline_hash" in model.model_fields, model.__name__
