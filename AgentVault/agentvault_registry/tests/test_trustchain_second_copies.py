"""§TRUSTCHAIN P4.5 / P4.6 / P4.7 (2026-09-12) — the second copies, the dead literals, the readout.

Each test is RED on the pre-change tree (`TRUSTCHAIN_SRC=<git archive of the old package>`):
  P4.5  the staking rewards service reads the RESOLVED policy (frame_policy.load), not the raw row;
        the rated-peers clause says what it means (`ra.did IS NULL`); the treasury streak has a name
        that says what it carries, with the old key kept one release as an alias.
  P4.6  ONE rule derives a target's event store (core/es_url_for_target) and the torn-down tier's
        literal `event-store-test:8200` is gone from the tester, its verifier, the sandbox proxy's
        default and the diagnostics targets; the mcp tester delegates to that rule.
  P4.7  the eligibility readout tells `unmeasured` (no trust vector yet) from `below the floor`.
"""
from __future__ import annotations

import ast
import os
import pathlib
import re

import pytest

HERE = pathlib.Path(__file__).resolve().parent
SRC = pathlib.Path(os.environ.get("TRUSTCHAIN_SRC", HERE.parent / "src" / "agentvault_registry"))


def _read(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def _fn(rel: str, name: str):
    tree = ast.parse(_read(rel))
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{rel}: no function {name}")


# ── P4.5 ────────────────────────────────────────────────────────────────────────
def test_staking_rewards_read_the_resolved_policy_not_the_raw_row():
    src = _read("services/staking_rewards_service.py")
    assert "get_active_policy" not in src, "staking_rewards_service still reads the raw policy row"
    for name in ("get_apy_tier", "get_eligible_stakers"):
        fn = _fn("services/staking_rewards_service.py", name)
        assert any(
            isinstance(n, ast.ImportFrom) and n.module == "frame_policy" for n in ast.walk(fn)
        ), f"{name} does not import the resolver"


def test_rated_peers_clause_says_what_it_means():
    src = _read("services/reputation_bond.py")
    assert "ra.did IS NULL" in src
    assert "creator_developer_id IS NULL" not in src, "the old IS NULL tests (never true on agents) survive"


def test_treasury_streak_has_a_name_and_keeps_its_alias_one_release():
    src = _read("routers/registry_health.py")
    assert 'result["treasury_unfunded_streak_days"]' in src
    assert 'result["zero_distribution_events_30d"]' in src, "the alias must survive one release"


def test_sync_display_name_is_fed_from_the_db_backed_cache():
    fn = _fn("services/reputation_bond.py", "registry_display_name")
    assert any(
        isinstance(n, ast.Attribute) and n.attr == "_registry_display_name" for n in ast.walk(fn)
    ) or "_registry_display_name" in ast.unparse(fn), "the sync reader does not consult federation_sync's cache"


# ── P4.6 ────────────────────────────────────────────────────────────────────────
def test_one_rule_for_the_event_store_of_a_target():
    from agentvault_registry.core.es_url_for_target import es_url_for_target
    assert es_url_for_target("http://sbx-alpha-registry:8000") == "http://sbx-alpha-event-store:8200"
    assert es_url_for_target("http://eu-registry:8000/") == "http://eu-event-store:8200"
    assert es_url_for_target("http://registry-test:8000") == "http://event-store-test:8200"   # legacy pairing
    assert es_url_for_target("http://registry-test-b:8000") == "http://event-store-test-b:8200"
    assert es_url_for_target("https://api.example.invalid") == ""                            # undecidable, said so
    assert es_url_for_target("") == "" and es_url_for_target(None) == ""                     # type: ignore[arg-type]


@pytest.mark.parametrize("rel", [
    "routers/admin_api_test.py",
    "api_tests/es_event_verifier.py",
    "routers/sandbox_proxy.py",
    "sandbox_bootstrap.py",
    "main.py",
    "api_tests/categories/flow_reactor_batch_1/test_flow_reactor_batch_1.py",
])
def test_the_torn_down_tiers_event_store_literal_is_gone(rel):
    assert "event-store-test:8200" not in _read(rel), f"{rel} still dials the torn-down sandbox tier"


def test_mcp_tester_delegates_to_the_one_rule():
    fn = _fn("routers/mcp_tester.py", "_derive_es_url_from_target")
    assert "es_url_for_target" in ast.unparse(fn)
    assert "event-store-test" not in ast.unparse(fn)


def test_sandbox_proxy_has_no_dead_default_and_refuses_loudly():
    src = _read("routers/sandbox_proxy.py")
    m = re.search(r'SANDBOX_ES_URL = os\.getenv\("SANDBOX_ES_INTERNAL_URL", "(.*?)"\)', src)
    assert m and m.group(1) == "", "the sandbox ES default must be empty, not a hostname"
    assert "No sandbox event store is configured" in src


def test_flow_test_reads_the_key_from_the_environment():
    src = _read("api_tests/categories/flow_reactor_batch_1/test_flow_reactor_batch_1.py")
    assert "sandbox-event-store-api-key-2026" not in src, "a literal internal key sits in a tracked test"
    assert "API_TEST_EVENT_STORE_API_KEY" in src


# ── P4.7 ────────────────────────────────────────────────────────────────────────
def test_eligibility_readout_tells_unmeasured_from_below_floor():
    fn = _fn("services/staking_rewards_service.py", "get_eligible_stakers")
    body = ast.unparse(fn)
    for key in ("skipped_unmeasured", "skipped_below_floor", "skipped_paused", "skipped_distributed_today", "unmeasured_dids"):
        assert f"'{key}'" in body or f'"{key}"' in body, f"the eligibility report lacks {key}"
    assert "last_eligibility_report" in body
    # the record the operator reads carries the report
    fn2 = _fn("services/staking_rewards_service.py", "run_daily_distribution")
    assert "'eligibility'" in ast.unparse(fn2) or '"eligibility"' in ast.unparse(fn2)
