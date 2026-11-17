"""V0666 OPA phase 2 step 2, layer C: an independent verifier that reads what already exists and alerts, never blocks
(gwo_bec4b18190831482a6463d46; his "ok. approved.", room seq 4948, of sessionlogs2026/DESIGN_2026-11-15_OPA_BACKSTOP.md
sections 4, 5, 8 and 10).

This file is the verifier's plumbing, and it runs everywhere (no OPA binary, no database). The rules themselves, judged by the
real Rego, are tests/test_opa_verifier_rego_v0666.py (OPA_VERIFIER_BIN + OPA_VERIFIER_POLICY_DIR) and the readers on a real
Postgres are tests/test_opa_verifier_db_v0666.py (OPA_VERIFIER_TEST_DB).

What it pins:
  1. one shared builder per rule, and no input is a literal: every key of every builder's input moves when the fact it stands for
     moves (the lint of section 5: a rule fed `if x == y: True` is a tripwire, not a check);
  2. independence: the verifier imports no other registry code (a change cannot reach it through a helper it shares), reads
     only an allow-list of environment names, and has no write verb to any service (it detects; it never blocks);
  3. a violation raises an alert through the alert path (a metric a vmalert rule reads, severity critical, as the design says)
     and is recorded; a clean run raises nothing; a rule that cannot be read is UNMEASURED (never a pass, never a violation);
     a rule whose evaluation fails is an error, and the other rules still run;
  4. the alert rules parse and name only metrics the verifier exports.
RED on d689b3b68: there is no agentvault_registry.verifier.
"""
from __future__ import annotations

import ast
import asyncio
import datetime as dt
import json
import pathlib
import re

import pytest

from agentvault_registry.verifier import evaluator, facts, inputs, rules, runner
from tests._opa_verifier_facts import GOOD, NOW, deep as _deep

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "verifier"
ALERTS = PKG / "opa_verifier_alerts.yml"

EXPECTED_RULES = {"iron_pairing", "jurisdiction_coherent", "fiat_buy_only", "merge_needs_the_record", "deletion_on_schedule"}


def run(coro):
    return asyncio.run(coro)


# --- 1. one shared builder, no literal inputs -----------------------------------------------------------------------------

def test_the_five_rules_the_order_names_are_registered_with_one_builder_each():
    assert set(rules.RULES) == EXPECTED_RULES
    for name, r in rules.RULES.items():
        assert r.build is getattr(inputs, name), name          # ONE builder, in one module, per rule
        assert r.rego.startswith("agentvault/"), name
        assert r.severity == "critical", name                  # the design: a breach pages (critical)


def test_no_builder_returns_a_dict_with_a_literal_value():
    tree = ast.parse((PKG / "inputs.py").read_text())
    for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in EXPECTED_RULES]:
        for node in ast.walk(fn):
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    assert not isinstance(v, ast.Constant), f"{fn.name}: the input key {ast.unparse(k)} is the literal {ast.unparse(v)}"


# (rule, a change to the facts, the input key that must move because of it)
MOVES = [
    ("iron_pairing", lambda f: f["env"].update(AGENT_RBAC_MODE="shadow"), "rbac_mode"),
    ("iron_pairing", lambda f: f["env"].update(AGENT_DELEGATION_MODE="off"), "delegation_mode"),
    ("jurisdiction_coherent", lambda f: f["profile"]["features"].update(guild=False), "profile"),
    ("jurisdiction_coherent", lambda f: f["env"].update(EXCHANGE_ENABLED="true"), "live_flags"),
    ("fiat_buy_only", lambda f: f["paths"].append("/api/v1/fiat/payout"), "out_routes"),
    ("fiat_buy_only", lambda f: f.update(purchases_not_in=2), "not_in"),
    ("fiat_buy_only", lambda f: f.update(purchases_issued=3), "issued"),
    ("merge_needs_the_record", lambda f: f["change"]["acceptance"].update(ok=False), "acceptance_ok"),
    ("merge_needs_the_record", lambda f: f["change"]["acceptance"]["record"].update(commit="b" * 40), "accepted_commit"),
    ("merge_needs_the_record", lambda f: f["change"].update(veto={"by": 1}), "veto_present"),
    ("merge_needs_the_record", lambda f: f["change"].update(proposal_status="FAILED"), "ballot_passed"),
    ("merge_needs_the_record", lambda f: f["change"].update(go={"by": 9, "bootstrap": {"members": 2}}), "bootstrap_go"),
    ("merge_needs_the_record", lambda f: f["change"].update(go={"by": 9}), "go_present"),
    ("merge_needs_the_record", lambda f: f["change"].update(passed_at=NOW - dt.timedelta(hours=1)), "passed_at"),
    ("merge_needs_the_record", lambda f: f["env"].update(CODE_CHANGE_VETO_HOURS="72"), "window_seconds"),
    ("merge_needs_the_record", lambda f: f["reviews"].clear(), "approvals"),
    ("merge_needs_the_record", lambda f: f["reviews"].append({"reviewer_developer_id": 3, "verdict": "changes",
                                                              "commit": "a" * 40, "at": 2.0}), "blockers"),
    ("merge_needs_the_record", lambda f: f["change"].update(paths=["agentvault_registry/y.py"]), "paths_outside_scope"),
    ("merge_needs_the_record", lambda f: f["change"]["acceptance"]["record"].update(read_from="caller"), "read_from_checker"),
    ("merge_needs_the_record", lambda f: f["change"].update(commit="e" * 40), "voted_commit"),
    ("merge_needs_the_record", lambda f: f["change"]["merged"].update(commit="f" * 40), "merged_commit"),
    ("merge_needs_the_record", lambda f: f["change"]["merged"].update(at=(NOW + dt.timedelta(hours=5)).isoformat()), "merged_at"),
    ("merge_needs_the_record", lambda f: f["change"].update(sensitive=True), "approvals_needed"),
    ("deletion_on_schedule", lambda f: f["account"].update(deletion_status="active"), "pending"),
    ("deletion_on_schedule", lambda f: f["account"].update(deletion_requested_at=NOW - dt.timedelta(days=40)), "requested_at"),
    ("deletion_on_schedule", lambda f: f["env"].update(ACCOUNT_DELETION_COOLING_OFF_DAYS="30"), "cooling_off_seconds"),
    ("deletion_on_schedule", lambda f: f.update(now=NOW + dt.timedelta(days=2)), "now"),
    ("deletion_on_schedule", lambda f: f["env"].update(ACCOUNT_DELETION_INTERVAL_SECONDS="172800"), "grace_seconds"),
]


@pytest.mark.parametrize("rule,change,key", MOVES, ids=[f"{r}:{k}" for r, _, k in MOVES])
def test_every_input_key_moves_with_the_fact_it_stands_for(rule, change, key):
    base = _deep(GOOD[rule])
    moved = _deep(GOOD[rule])
    change(moved)
    a, b = inputs.BUILDERS[rule](base), inputs.BUILDERS[rule](moved)
    assert key in a, f"{rule} builds no {key}"
    assert a[key] != b[key], f"{rule}: {key} did not move when its fact did: a literal is hiding in the builder"


def test_every_key_of_every_input_is_covered_by_a_move():
    covered = {}
    for rule, _, key in MOVES:
        covered.setdefault(rule, set()).add(key)
    for rule in EXPECTED_RULES:
        assert set(inputs.BUILDERS[rule](_deep(GOOD[rule]))) == covered[rule], rule


def test_the_builders_are_pure_and_the_facts_are_not_changed():
    for rule in EXPECTED_RULES:
        f = _deep(GOOD[rule])
        before = repr(f)
        inputs.BUILDERS[rule](f)
        assert repr(f) == before, rule


# --- 2. independence, and nothing that writes -------------------------------------------------------------------------------

def test_the_verifier_imports_no_other_registry_code():
    for path in PKG.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    assert node.level == 1 and (node.module or "").split(".")[0] in {p.stem for p in PKG.glob("*.py")} | {""}, \
                        f"{path.name}: a relative import leaves the package: {ast.unparse(node)}"
                mods = [node.module or ""]
            for m in mods:
                if m.startswith("agentvault_registry"):
                    assert m.startswith("agentvault_registry.verifier"), f"{path.name} imports {m}"


def test_the_verifier_has_no_write_verb_and_no_web_framework():
    banned_calls = {"post", "put", "patch", "delete"}
    for path in PKG.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in banned_calls:
                raise AssertionError(f"{path.name}: .{node.func.attr}( is a write verb: layer C detects, it never acts")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mod = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
                assert (mod or "").split(".")[0] not in {"fastapi", "starlette"}, f"{path.name} imports a web framework"
    # no SQL write either
    for path in PKG.glob("*.py"):
        for m in re.finditer(r"\b(INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|DROP\s+|ALTER\s+TABLE)\b", path.read_text(), re.I):
            raise AssertionError(f"{path.name}: SQL write {m.group(0)!r}")


def test_only_an_allow_list_of_environment_names_is_ever_read():
    names = facts.ENV_ALLOW
    assert {"AGENT_RBAC_MODE", "AGENT_DELEGATION_MODE", "EXCHANGE_ENABLED", "FX_ENABLED", "GUILD_ENABLED", "FORGE_ENABLED",
            "FIAT_ONRAMP_ENABLED", "CODE_CHANGE_VETO_HOURS", "ACCOUNT_DELETION_COOLING_OFF_DAYS"} <= set(names)
    env = [f"{n}=x" for n in names] + ["DATABASE_URL=postgresql://u:SECRET@h/db", "API_KEY_SECRET=SECRET", "SOME_KEY=SECRET"]
    out = facts.pick_env(env)
    assert set(out) == set(names) and "SECRET" not in json.dumps(out)


def test_docker_env_reads_through_one_runner_and_keeps_only_the_allow_list():
    calls = []

    def fake(cmd):
        calls.append(cmd)
        return json.dumps(["AGENT_RBAC_MODE=enforce", "DATABASE_URL=postgresql://u:SECRET@h/db"])
    out = facts.docker_env("eu-registry", fake)
    assert out == {"AGENT_RBAC_MODE": "enforce"} and "SECRET" not in repr(out)
    assert calls and calls[0][:2] == ["docker", "inspect"] and "eu-registry" in calls[0]


# --- 3. alert, record, never block --------------------------------------------------------------------------------------------

class FakeSources(facts.Sources):
    def __init__(self, good=True, broken=()):
        self.good, self.broken = good, set(broken)

    def nodes(self):
        return ["eu-registry"]

    def now(self):
        return NOW

    def subjects(self, rule, node):
        if rule in self.broken:
            raise facts.Unmeasured(f"{rule}: the node's database does not answer")
        g = _deep(GOOD[rule])
        if not self.good and rule == "iron_pairing":
            g["env"]["AGENT_DELEGATION_MODE"] = "off"
        if rule == "merge_needs_the_record":
            return [("cc1", g)]
        if rule == "deletion_on_schedule":
            return [("developer:7", g)]
        return [(node, g)]


class FakeOpa:
    """Decides by the one fact the test breaks: iron_pairing with delegation off is a violation; everything else passes."""

    def __init__(self, fail=()):
        self.fail, self.seen = set(fail), []

    async def decide(self, rego, data):
        self.seen.append((rego, data))
        if rego in self.fail:
            raise evaluator.EvaluationError("opa did not answer")
        if rego.endswith("flag_pairing_ok"):
            return not (data["rbac_mode"] == "enforce" and data["delegation_mode"] == "off")
        return True


def test_a_broken_fact_raises_the_alert_and_is_recorded(tmp_path):
    rec = runner.Recorder(tmp_path / "findings.jsonl")
    res = run(runner.run_once(FakeSources(good=False), FakeOpa(), recorder=rec))
    assert res.violations["iron_pairing"] == 1 and sum(res.violations.values()) == 1
    text = res.metrics_text()
    assert 'opa_verifier_violations{rule="iron_pairing"} 1' in text
    assert 'opa_verifier_violations{rule="merge_needs_the_record"} 0' in text
    lines = [json.loads(l) for l in (tmp_path / "findings.jsonl").read_text().splitlines()]
    assert len(lines) == 1 and lines[0]["rule"] == "iron_pairing" and lines[0]["subject"] == "eu-registry"
    assert lines[0]["input"] == {"rbac_mode": "enforce", "delegation_mode": "off"} and lines[0]["severity"] == "critical"


def test_the_same_facts_unbroken_raise_nothing_and_record_nothing(tmp_path):
    rec = runner.Recorder(tmp_path / "findings.jsonl")
    res = run(runner.run_once(FakeSources(good=True), FakeOpa(), recorder=rec))
    assert sum(res.violations.values()) == 0
    assert not (tmp_path / "findings.jsonl").exists() or not (tmp_path / "findings.jsonl").read_text()
    assert all(f'opa_verifier_violations{{rule="{r}"}} 0' in res.metrics_text() for r in EXPECTED_RULES)
    assert res.subjects["iron_pairing"] == 1                       # it did look: 0 violations of 1, not 0 of nothing


def test_a_fact_that_cannot_be_read_is_unmeasured_never_a_pass_and_never_a_violation():
    res = run(runner.run_once(FakeSources(broken={"merge_needs_the_record"}), FakeOpa()))
    assert res.unmeasured["merge_needs_the_record"] == 1 and res.violations["merge_needs_the_record"] == 0
    assert res.subjects["merge_needs_the_record"] == 0             # nothing was judged, and the metric says so
    assert 'opa_verifier_unmeasured{rule="merge_needs_the_record"} 1' in res.metrics_text()
    assert res.violations["iron_pairing"] == 0 and res.subjects["iron_pairing"] == 1     # the others ran


def test_an_evaluation_error_is_an_error_not_a_violation_and_the_other_rules_still_run():
    res = run(runner.run_once(FakeSources(), FakeOpa(fail={"agentvault/jurisdiction/profile_coherent"})))
    assert res.errors["jurisdiction_coherent"] == 1 and res.violations["jurisdiction_coherent"] == 0
    assert res.subjects["iron_pairing"] == 1 and res.subjects["deletion_on_schedule"] == 1
    assert 'opa_verifier_rule_errors{rule="jurisdiction_coherent"} 1' in res.metrics_text()


def test_the_run_records_when_it_ran_and_how_long():
    res = run(runner.run_once(FakeSources(), FakeOpa()))
    text = res.metrics_text()
    assert f"opa_verifier_last_run_unixtime {int(NOW.timestamp())}" in text and "opa_verifier_run_seconds " in text


def test_a_source_that_raises_something_unexpected_is_an_error_for_that_rule_only():
    class Boom(FakeSources):
        def subjects(self, rule, node):
            if rule == "fiat_buy_only":
                raise RuntimeError("driver exploded")
            return super().subjects(rule, node)
    res = run(runner.run_once(Boom(), FakeOpa()))
    assert res.errors["fiat_buy_only"] == 1 and res.subjects["iron_pairing"] == 1


def test_the_evaluator_refuses_to_run_without_its_binary_and_policies(tmp_path):
    with pytest.raises(evaluator.EvaluationError):
        evaluator.OpaEvaluator(str(tmp_path / "nope"), [str(tmp_path)])
    binary = tmp_path / "opa"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    with pytest.raises(evaluator.EvaluationError):
        evaluator.OpaEvaluator(str(binary), [str(tmp_path / "no-policies")])


def _fake_opa(tmp_path, body, code=0):
    binary = tmp_path / "opa"
    binary.write_text(f"#!/bin/sh\ncat > /dev/null\nprintf '%s' '{body}'\nexit {code}\n")
    binary.chmod(0o755)
    return evaluator.OpaEvaluator(str(binary), [str(tmp_path)])


def test_the_evaluator_reads_only_a_boolean_and_every_other_answer_is_an_error(tmp_path):
    ok = _fake_opa(tmp_path, '{"result":[{"expressions":[{"value":true}]}]}')
    assert run(ok.decide("agentvault/x/y", {"a": 1})) is True
    for body in ('{"result":[{"expressions":[{"value":"yes"}]}]}',      # not a boolean
                 '{"result":[{"expressions":[{"value":1}]}]}',
                 '{}',                                                   # the rule is not defined
                 'not json'):
        with pytest.raises(evaluator.EvaluationError):
            run(_fake_opa(tmp_path, body).decide("agentvault/x/y", {}))
    with pytest.raises(evaluator.EvaluationError):                       # opa itself failed
        run(_fake_opa(tmp_path, '{}', code=2).decide("agentvault/x/y", {}))


def test_the_metrics_page_serves_the_last_run_on_get_and_nothing_else():
    import urllib.error
    import urllib.request
    from agentvault_registry.verifier import __main__ as entry
    state = {}
    srv = entry.serve_metrics(state, "127.0.0.1", 0)
    try:
        port = srv.server_address[1]
        body = urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5).read().decode()
        assert body == runner.RunResult.empty().metrics_text()           # before the first run: zeros, and last_run 0 (the stale alert)
        state["result"] = run(runner.run_once(FakeSources(good=False), FakeOpa()))
        body = urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5).read().decode()
        assert 'opa_verifier_violations{rule="iron_pairing"} 1' in body
        for method, path in (("GET", "/other"), ("POST", "/metrics"), ("PUT", "/metrics"), ("DELETE", "/metrics")):
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, data=b"x" if method in ("POST", "PUT") else None)
            with pytest.raises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(req, timeout=5)
            assert e.value.code in (404, 501), (method, path)
    finally:
        srv.shutdown()
        srv.server_close()


def test_the_entry_point_builds_from_names_only_and_a_missing_name_is_loud(tmp_path):
    from agentvault_registry.verifier import __main__ as entry
    cfg = tmp_path / "nodes.json"
    cfg.write_text(json.dumps({"nodes": [{"name": "n1", "container": "n1-registry", "db_env": "DB", "es_env": "ES",
                                          "base_url": "http://n1"}]}))
    binary = tmp_path / "opa"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    pol = tmp_path / "policies"
    pol.mkdir()
    env = {"OPA_VERIFIER_CONFIG": str(cfg), "OPA_VERIFIER_BIN": str(binary), "OPA_VERIFIER_POLICY_DIR": str(pol),
           "OPA_VERIFIER_FINDINGS": str(tmp_path / "f.jsonl")}
    sources, opa, rec = entry.build(env)
    assert sources.nodes() == ["n1"] and opa.dirs[0] == str(pol) and opa.dirs[1] == entry.OWN_POLICIES
    assert pathlib.Path(entry.OWN_POLICIES, "agentvault_verifier.rego").is_file()
    with pytest.raises(KeyError):
        entry.build({k: v for k, v in env.items() if k != "OPA_VERIFIER_BIN"})


# --- 4. the alert rules -------------------------------------------------------------------------------------------------------

def _rules():
    import yaml
    doc = yaml.safe_load(ALERTS.read_text())
    return [r for g in doc["groups"] for r in g["rules"]]


def test_the_alert_rules_parse_and_a_violation_pages_critical():
    rs = {r["alert"]: r for r in _rules()}
    v = rs["OpaVerifierViolation"]
    assert v["labels"]["severity"] == "critical" and "opa_verifier_violations" in v["expr"] and v["for"]
    assert "{{ $labels.rule }}" in v["annotations"]["summary"] + v["annotations"]["description"]
    assert {"OpaVerifierViolation", "OpaVerifierStale", "OpaVerifierRuleError", "OpaVerifierUnmeasured"} <= set(rs)
    assert rs["OpaVerifierStale"]["labels"]["severity"] == "warning"


def test_every_metric_an_alert_reads_is_one_the_verifier_exports():
    exported = set(re.findall(r"^# TYPE (opa_verifier_\w+) ", runner.RunResult.empty().metrics_text(), re.M))
    for r in _rules():
        for m in re.findall(r"opa_verifier_\w+", r["expr"]):
            assert m in exported, f"{r['alert']} reads {m}, which the verifier does not export"


def test_every_rule_has_a_clause_in_the_alerts_runbook_text():
    text = ALERTS.read_text()
    for name in EXPECTED_RULES:
        assert name in text, f"{name} is not named in the alert descriptions"
