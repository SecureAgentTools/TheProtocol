"""V0663 (agent workflows): the pure rules (services/workflow_rules.py)."""
import pytest

from agentvault_registry.services import workflow_rules as wr


def test_unknown_and_later_rules_are_refused_not_ignored():
    with pytest.raises(wr.RulesetError, match="frame"):
        wr.normalize({"frame": "eu"})
    with pytest.raises(wr.RulesetError, match="not a rule"):
        wr.normalize({"cheap": True})
    with pytest.raises(wr.RulesetError, match="quantum"):
        wr.normalize({"quantum_rung": 2})


def test_normalize_checks_values_and_sorts_lists():
    out = wr.normalize({"bonded_only": True, "min_reputation": 3, "min_proven_orders": 2,
                        "max_price": 5.5, "org_ids": ["b", "a", "a"]})
    assert out == {"bonded_only": True, "min_reputation": 3.0, "min_proven_orders": 2, "max_price": 5.5, "org_ids": ["a", "b"]}
    assert wr.normalize({"bonded_only": False}) == {}
    for bad in ({"min_reputation": True}, {"max_price": -1}, {"min_proven_orders": 1.5}, {"org_ids": []},
                {"org_ids": [""]}, {"bonded_only": "yes"}, {"max_price": float("nan")}):
        with pytest.raises(wr.RulesetError):
            wr.normalize(bad)


def test_independent_of_names_a_real_other_step():
    assert wr.normalize({"independent_of": ["build"]}, step_keys=["build", "verify"], own_key="verify") == {"independent_of": ["build"]}
    with pytest.raises(wr.RulesetError, match="no such step"):
        wr.normalize({"independent_of": ["nope"]}, step_keys=["build", "verify"], own_key="verify")
    with pytest.raises(wr.RulesetError, match="itself|belongs"):
        wr.normalize({"independent_of": ["verify"]}, step_keys=["build", "verify"], own_key="verify")


def test_merge_takes_the_stricter_side():
    m = wr.merge({"min_reputation": 2.0, "max_price": 10.0, "org_ids": ["a", "b"], "independent_of": ["x"]},
                 {"min_reputation": 4.0, "max_price": 6.0, "org_ids": ["b", "c"], "independent_of": ["y"], "bonded_only": True})
    assert m == {"min_reputation": 4.0, "max_price": 6.0, "org_ids": ["b"], "independent_of": ["x", "y"], "bonded_only": True}


def _facts(**kw):
    base = {"bonded": True, "reputation": 5.0, "proven_orders": 3, "price": 4.0, "org_id": "a", "owner": 7,
            "owners_by_step": {"build": 9}}
    base.update(kw)
    return base


def test_evaluate_passes_a_good_bidder_and_names_each_failed_rule():
    rules = {"bonded_only": True, "min_reputation": 3.0, "min_proven_orders": 2, "max_price": 5.0, "org_ids": ["a"],
             "independent_of": ["build"]}
    assert wr.evaluate(rules, _facts()) == []
    names = {f["rule"] for f in wr.evaluate(rules, _facts(bonded=False, reputation=1.0, proven_orders=0, price=9.0,
                                                          org_id="z", owners_by_step={"build": 7}))}
    assert names == set(rules)


def test_a_fact_the_registry_cannot_read_is_a_refusal_that_says_so():
    fails = wr.evaluate({"bonded_only": True, "min_reputation": 1.0}, _facts(bonded=None, reputation=None))
    assert {f["rule"] for f in fails} == {"bonded_only", "min_reputation"}
    assert any("cannot see" in f["message"] for f in fails)
    unknown_owner = wr.evaluate({"independent_of": ["build"]}, _facts(owner=None))
    assert unknown_owner and "cannot see who owns" in unknown_owner[0]["message"]


def test_independence_ignores_a_step_with_no_worker_yet():
    assert wr.evaluate({"independent_of": ["build"]}, _facts(owners_by_step={"build": None})) == []


def test_refusal_sentence_names_the_rules():
    s = wr.refusal_sentence([{"rule": "max_price", "message": "too dear"}])
    assert "max_price" in s and "too dear" in s


def test_ruleset_hash_is_stable_across_key_order():
    assert wr.ruleset_hash({"a": 1, "b": 2}) == wr.ruleset_hash({"b": 2, "a": 1})
    assert wr.ruleset_hash({"a": 1}) != wr.ruleset_hash({"a": 2})


def test_chain_verifies_and_any_edit_breaks_it():
    chain = wr.build_chain([("build", "aa"), ("verify", "bb"), ("meter", "cc")])
    assert wr.verify_chain(chain) == (True, None)
    assert wr.verify_chain([]) == (True, None)
    forged = [dict(l) for l in chain]
    forged[1]["output_hash"] = "zz"
    ok, why = wr.verify_chain(forged)
    assert not ok and "verify" in why
    reordered = [chain[1], chain[0], chain[2]]
    assert wr.verify_chain(reordered)[0] is False
    dropped = [chain[0], chain[2]]
    assert wr.verify_chain(dropped)[0] is False


def test_output_hash_is_the_hash_of_the_delivered_output_never_the_workers_claim():
    assert wr.output_hash({"hash": " ABC "}) != "abc"           # (security read W3: tests/test_workflows_security_v0663.py)
    a = wr.output_hash({"text": "x"})
    assert a == wr.output_hash({"text": "x"}) and a != wr.output_hash({"text": "y"}) and len(a) == 64
